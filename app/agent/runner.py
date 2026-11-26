"""
LangGraph 后台执行管理器（AgentRunManager）与会话级 SSE 事件总线。

核心职责：
1. 管理独立 SQLite Checkpointer（`<runtime_dir>/data/agent_checkpoints.db`），支持中断恢复与多轮追问；
2. 在后台守护线程中消费 `graph.stream(..., stream_mode=["updates", "messages", "custom"])`，不阻塞 Flask 请求线程；
3. 为每个会话维护有序事件环形缓冲与条件变量，同时支持 SSE 实时流和轮询降级；
4. 同步把关键阶段与工具进度写入 `log_hub`，使前端底部终端面板可实时观察 Agent 执行。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.agent.graph import compile_profile_graph
from app.agent.graph_explorer import score_and_prune_candidates
from app.agent.llm_config import DEFAULT_MAX_STEPS, format_llm_error, load_effective_config
from app.agent.state import extract_text_content
from app.credentials import _PLATFORM_NAMES
from app.data.store import DataStore
from app.paths import get_runtime_dir
from app.services.log_hub import get_log_hub

CST = timezone(timedelta(hours=8))
MAX_SESSION_EVENTS = 600


def _now_ts() -> str:
    return datetime.now(CST).strftime("%H:%M:%S")


def _now_iso() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _extract_interrupt_payload(raw_interrupt: Any) -> Optional[dict[str, Any]]:
    """兼容不同版本 LangGraph 的 __interrupt__ 结构，提取 interrupt(value) 原始字典。"""
    if not raw_interrupt:
        return None
    first = raw_interrupt[0] if isinstance(raw_interrupt, (list, tuple)) else raw_interrupt
    val = getattr(first, "value", first)
    if isinstance(val, dict):
        return val
    return {"type": "confirm_identities", "raw": val}


class _SessionChannel:
    """单会话的内存事件总线与运行句柄。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.cond = threading.Condition()
        self.events: deque[dict[str, Any]] = deque(maxlen=MAX_SESSION_EVENTS)
        self.seq = 0
        self.running = False
        self.cancel_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        with self.cond:
            self.seq += 1
            ev = {
                "seq": self.seq,
                "ts": _now_ts(),
                "type": event_type,
                **payload,
            }
            self.events.append(ev)
            self.cond.notify_all()
            return ev

    def since(self, after: int = 0) -> list[dict[str, Any]]:
        with self.cond:
            return [e for e in self.events if e["seq"] > after]

    def wait_since(self, after: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        with self.cond:
            items = [e for e in self.events if e["seq"] > after]
            if items:
                return items
            self.cond.wait(timeout=timeout)
            return [e for e in self.events if e["seq"] > after]


class AgentRunManager:
    """全局（或测试隔离）LangGraph Agent 运行器。"""

    def __init__(
        self,
        store: Optional[DataStore] = None,
        checkpoint_db_path: Optional[Path] = None,
        llm_factory: Optional[Callable[[], Any]] = None,
    ):
        self._store = store
        self._checkpoint_db_path = checkpoint_db_path
        self._llm_factory = llm_factory
        self._lock = threading.RLock()
        self._channels: dict[str, _SessionChannel] = {}
        self._ckpt_conn: Optional[sqlite3.Connection] = None
        self._checkpointer: Optional[SqliteSaver] = None

    @property
    def store(self) -> DataStore:
        if self._store is None:
            from app.routes.common import get_store

            return get_store()
        return self._store

    def _get_checkpoint_path(self) -> Path:
        if self._checkpoint_db_path is not None:
            return self._checkpoint_db_path
        return get_runtime_dir() / "data" / "agent_checkpoints.db"

    def _get_checkpointer(self) -> SqliteSaver:
        with self._lock:
            if self._checkpointer is None:
                db_path = self._get_checkpoint_path()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10.0)
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA busy_timeout = 5000")
                saver = SqliteSaver(conn)
                saver.setup()
                self._ckpt_conn = conn
                self._checkpointer = saver
            return self._checkpointer

    def close(self) -> None:
        with self._lock:
            if self._ckpt_conn is not None:
                try:
                    self._ckpt_conn.close()
                except Exception:
                    pass
                self._ckpt_conn = None
                self._checkpointer = None

    def _channel(self, session_id: str) -> _SessionChannel:
        with self._lock:
            ch = self._channels.get(session_id)
            if ch is None:
                ch = _SessionChannel(session_id)
                self._channels[session_id] = ch
            return ch

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            ch = self._channels.get(session_id)
            return bool(ch and ch.running)

    def get_events(self, session_id: str, after: int = 0) -> dict[str, Any]:
        ch = self._channel(session_id)
        entries = ch.since(after)
        last_seq = entries[-1]["seq"] if entries else after
        return {
            "entries": entries,
            "last_seq": last_seq,
            "running": ch.running,
        }

    def wait_events(self, session_id: str, after: int = 0, timeout: float = 15.0) -> list[dict[str, Any]]:
        return self._channel(session_id).wait_since(after, timeout=timeout)

    def _log(self, msg: str, level: str = "info") -> None:
        try:
            get_log_hub().publish(f"[Agent] {msg}", level=level, source="agent")
        except Exception:
            pass

    @staticmethod
    def _derive_title(
        title: str,
        target_query: str,
        uids: dict[str, str],
    ) -> str:
        t = (title or "").strip()
        if t:
            return t[:60]
        q = (target_query or "").strip()
        if q:
            return f"{q[:40]} · 人物侧写"
        if uids:
            first_pid, first_uid = next(iter(uids.items()))
            pname = _PLATFORM_NAMES.get(first_pid, first_pid)
            suffix = f" 等 {len(uids)} 平台" if len(uids) > 1 else ""
            return f"{pname} {first_uid[:16]}{suffix}"
        return "新建人物侧写"

    def _ensure_llm_ready(self) -> str:
        if self._llm_factory is not None:
            return "custom"
        cfg = load_effective_config()
        if not cfg["configured"]:
            raise ValueError("尚未配置 LLM 模型，请先点击「模型配置」填写 Base URL、API Key 与 Model")
        return str(cfg["model"])

    # ==================== 会话 CRUD ====================

    def create_session(
        self,
        *,
        title: str = "",
        target_query: str = "",
        focus: str = "",
        uids: Optional[dict[str, str]] = None,
        graph_id: Optional[int] = None,
        auto_confirm: bool = False,
        refresh_data: bool = False,
        auto_start: bool = True,
    ) -> dict[str, Any]:
        clean_uids = {
            str(k).strip(): str(v).strip()
            for k, v in (uids or {}).items()
            if str(k).strip() and str(v).strip()
        }
        clean_query = (target_query or "").strip()
        if not clean_uids and not clean_query:
            raise ValueError("请至少提供已绑定的平台 UID 或输入搜索关键词/昵称")

        model_name = ""
        if auto_start:
            model_name = self._ensure_llm_ready()
        else:
            model_name = load_effective_config().get("model", "")

        session_id = uuid.uuid4().hex[:16]
        final_title = self._derive_title(title, clean_query, clean_uids)
        session = self.store.create_agent_profile(
            session_id,
            final_title,
            target_query=clean_query,
            focus=(focus or "").strip(),
            uids=clean_uids,
            graph_id=int(graph_id) if graph_id not in (None, "") else None,
            status="running" if auto_start else "idle",
            model=model_name,
        )

        if auto_start:
            self.start_profile_run(
                session_id,
                auto_confirm=auto_confirm,
                refresh_data=refresh_data,
            )
            session = self.get_session_detail(session_id) or session
        return session

    def _inspect_resumable_checkpoint(self, session_id: str) -> tuple[list[str], str]:
        """检查该 thread_id 的 SqliteSaver 是否存在可续跑的失败/未完成节点（排除人工确认 interrupt）。"""
        try:
            checkpointer = self._get_checkpointer()
            compiled = compile_profile_graph(
                self.store,
                checkpointer=checkpointer,
                llm_factory=self._llm_factory,
            )
            snap = compiled.get_state({"configurable": {"thread_id": session_id}})
            next_nodes = [str(n) for n in (getattr(snap, "next", ()) or ()) if n]
            if not next_nodes:
                return [], "profile"
            # 若挂在人工确认 interrupt() 上，应走 /resume 提交 confirmed_accounts 而非 /continue
            for task in getattr(snap, "tasks", ()) or ():
                if getattr(task, "interrupts", None):
                    return [], "profile"
            values = dict(getattr(snap, "values", {}) or {})
            mode = "followup" if values.get("mode") == "followup" else "profile"
            return next_nodes, mode
        except Exception:
            return [], "profile"

    def get_session_detail(self, session_id: str) -> Optional[dict[str, Any]]:
        profile = self.store.get_agent_profile(session_id)
        if not profile:
            return None
        ch = self._channel(session_id)
        profile["running"] = ch.running
        profile["last_seq"] = ch.seq
        if not ch.running and profile.get("status") in ("failed", "cancelled"):
            next_nodes, _ = self._inspect_resumable_checkpoint(session_id)
            profile["can_resume"] = bool(next_nodes)
            profile["resume_nodes"] = next_nodes
        else:
            profile["can_resume"] = False
            profile["resume_nodes"] = []
        return profile

    def list_sessions(self) -> list[dict[str, Any]]:
        items = self.store.list_agent_profiles()
        for item in items:
            item["running"] = self.is_running(item["id"])
        return items

    def delete_session(self, session_id: str) -> bool:
        self.cancel(session_id)
        deleted = self.store.delete_agent_profile(session_id)
        with self._lock:
            self._channels.pop(session_id, None)
            if self._ckpt_conn is not None:
                try:
                    for table in ("checkpoints", "writes"):
                        self._ckpt_conn.execute(
                            f"DELETE FROM {table} WHERE thread_id = ?",
                            (session_id,),
                        )
                    self._ckpt_conn.commit()
                except Exception:
                    pass
        return deleted

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            ch = self._channels.get(session_id)
            if not ch or not ch.running:
                return False
            ch.cancel_event.set()
            ch.publish("stage", stage="cancelling", label="已请求中止，正在安全收尾…")
            self._log(f"会话 {session_id} 请求中止", level="warn")
            return True

    # ==================== 启动 / 恢复 / 追问 ====================

    def start_profile_run(
        self,
        session_id: str,
        *,
        uids: Optional[dict[str, str]] = None,
        target_query: Optional[str] = None,
        focus: Optional[str] = None,
        graph_id: Any = ...,
        auto_confirm: bool = False,
        refresh_data: bool = False,
    ) -> dict[str, Any]:
        profile = self.store.get_agent_profile(session_id)
        if not profile:
            raise KeyError("侧写档案不存在")
        ch = self._channel(session_id)
        if ch.running:
            raise RuntimeError("该侧写档案正在运行中，请等待完成或先中止")

        model_name = self._ensure_llm_ready()
        cfg = load_effective_config()

        final_uids = (
            {str(k).strip(): str(v).strip() for k, v in uids.items() if str(k).strip() and str(v).strip()}
            if uids is not None
            else dict(profile.get("uids") or {})
        )
        final_query = (
            str(target_query).strip() if target_query is not None else str(profile.get("target_query") or "")
        )
        final_focus = str(focus).strip() if focus is not None else str(profile.get("focus") or "")
        final_gid = (
            profile.get("graph_id")
            if graph_id is ...
            else (int(graph_id) if graph_id not in (None, "") else None)
        )

        self.store.update_agent_profile(
            session_id,
            uids=final_uids,
            target_query=final_query,
            focus=final_focus,
            graph_id=final_gid,
            status="running",
            model=model_name,
            error="",
        )

        graph_input = {
            "mode": "profile",
            "target_query": final_query,
            "focus": final_focus,
            "confirmed_accounts": final_uids,
            "candidate_accounts": [],
            "graph_id": final_gid,
            "auto_confirm": bool(auto_confirm),
            "refresh_data": bool(refresh_data),
            "step_count": 0,
            "max_steps": int(cfg.get("max_steps") or DEFAULT_MAX_STEPS),
        }
        self._launch_worker(session_id, graph_input, kind="profile")
        return self.get_session_detail(session_id) or profile

    def resume_session(self, session_id: str, confirmed_accounts: dict[str, str]) -> dict[str, Any]:
        profile = self.store.get_agent_profile(session_id)
        if not profile:
            raise KeyError("侧写档案不存在")
        ch = self._channel(session_id)
        if ch.running:
            raise RuntimeError("该侧写档案正在运行中")

        self._ensure_llm_ready()
        clean_uids = {
            str(k).strip(): str(v).strip()
            for k, v in (confirmed_accounts or {}).items()
            if str(k).strip() and str(v).strip()
        }
        if not clean_uids:
            raise ValueError("请至少勾选确认一个平台账号")

        structured = dict(profile.get("structured") or {})
        structured.pop("pending_interrupt", None)
        self.store.update_agent_profile(
            session_id,
            uids=clean_uids,
            structured=structured,
            status="running",
            error="",
        )
        self._launch_worker(
            session_id,
            Command(resume={"confirmed_accounts": clean_uids}),
            kind="profile",
        )
        return self.get_session_detail(session_id) or profile

    def continue_session(self, session_id: str) -> dict[str, Any]:
        """
        使用 LangGraph 原生断点续跑（`graph.stream(None, config)`）：
        跳过已完成的基线采集/工具节点，直接从上次失败的节点原地重试。
        """
        profile = self.store.get_agent_profile(session_id)
        if not profile:
            raise KeyError("侧写档案不存在")
        ch = self._channel(session_id)
        if ch.running:
            raise RuntimeError("该侧写档案正在运行中")

        next_nodes, mode = self._inspect_resumable_checkpoint(session_id)
        if not next_nodes:
            raise ValueError("当前档案没有可续跑的 LangGraph 失败断点，请点击「重新生成」从头执行")

        model_name = self._ensure_llm_ready()
        self.store.update_agent_profile(
            session_id,
            status="running",
            model=model_name,
            error="",
        )
        self._log(f"会话 {session_id} 从 LangGraph 断点继续执行（待续跑节点: {', '.join(next_nodes)}）")
        self._launch_worker(session_id, None, kind=mode)
        return self.get_session_detail(session_id) or profile

    def send_followup(self, session_id: str, message: str) -> dict[str, Any]:
        profile = self.store.get_agent_profile(session_id)
        if not profile:
            raise KeyError("侧写档案不存在")
        ch = self._channel(session_id)
        if ch.running:
            raise RuntimeError("当前有正在执行的推理任务，请稍后再追问")
        text = (message or "").strip()
        if not text:
            raise ValueError("追问内容不能为空")

        self._ensure_llm_ready()

        chat_history = list(profile.get("chat_history") or [])
        chat_history.append({"role": "user", "content": text, "ts": _now_iso()})
        self.store.update_agent_profile(
            session_id,
            chat_history=chat_history,
            status="running",
            error="",
        )

        graph_input = {
            "mode": "followup",
            "step_count": 0,
            "max_steps": 4,
            "messages": [HumanMessage(content=text)],
            # 确保即使在重启或无历史 checkpoint 时，追问也能拥有档案里持久化的上下文
            "confirmed_accounts": profile.get("uids") or {},
            "report_markdown": profile.get("report_markdown") or "",
            "evidence": profile.get("evidence") or {},
            "gaps": profile.get("gaps") or [],
            "baseline_stats": (profile.get("structured") or {}).get("baseline_stats") or {},
        }
        self._launch_worker(session_id, graph_input, kind="followup")
        return self.get_session_detail(session_id) or profile

    # ==================== 后台流式消费线程 ====================

    def _launch_worker(self, session_id: str, graph_input: Any, *, kind: str) -> None:
        ch = self._channel(session_id)
        ch.cancel_event.clear()
        ch.running = True
        start_label = (
            "正在从 LangGraph 失败断点继续执行（跳过已完成阶段）…"
            if graph_input is None
            else ("开始执行人物侧写工作流…" if kind == "profile" else "正在处理追问…")
        )
        ch.publish("run_start", kind=kind, label=start_label)
        self._log(f"会话 {session_id} 启动 ({kind}{', resume' if graph_input is None else ''})")

        def _worker():
            try:
                self._execute_stream(session_id, ch, graph_input, kind=kind)
            except Exception as e:
                err_msg = format_llm_error(e)
                self._log(f"会话 {session_id} 失败: {err_msg}", level="error")
                updated = self._persist_failure_state(session_id, err_msg)
                ch.publish("error", message=err_msg, session=updated)
            finally:
                ch.running = False

        t = threading.Thread(target=_worker, daemon=True, name=f"agent-{session_id[:8]}")
        ch.thread = t
        t.start()

    def _persist_failure_state(self, session_id: str, err_msg: str) -> Optional[dict[str, Any]]:
        """
        工作流中途失败时，尽量从 LangGraph Checkpoint 回捞已采集的基线统计、证据账本、盲区与轨迹，
        避免前面已完成的平台采集数据丢失，并附加一条明确的失败轨迹。
        """
        existing = self.store.get_agent_profile(session_id) or {}
        structured = dict(existing.get("structured") or {})
        evidence = existing.get("evidence") or {}
        gaps = existing.get("gaps") or []
        trace = list(existing.get("trace") or [])

        next_nodes: list[str] = []
        try:
            checkpointer = self._get_checkpointer()
            compiled = compile_profile_graph(
                self.store,
                checkpointer=checkpointer,
                llm_factory=self._llm_factory,
            )
            snap = compiled.get_state({"configurable": {"thread_id": session_id}})
            next_nodes = [str(n) for n in (getattr(snap, "next", ()) or ()) if n]
            values = dict(getattr(snap, "values", {}) or {})
            if values.get("baseline_stats"):
                structured["baseline_stats"] = values["baseline_stats"]
            if values.get("candidate_accounts"):
                structured["candidate_accounts"] = values["candidate_accounts"]
            if values.get("evidence"):
                evidence = values["evidence"]
            if values.get("gaps"):
                gaps = values["gaps"]
            if values.get("trace"):
                trace = list(values["trace"])
        except Exception:
            pass

        trace.append(
            {
                "ts": _now_ts(),
                "stage": "error",
                "title": "推理过程异常中断",
                "detail": err_msg,
                "status": "error",
            }
        )
        updated = self.store.update_agent_profile(
            session_id,
            status="failed",
            error=err_msg,
            structured=structured,
            evidence=evidence,
            gaps=gaps,
            trace=trace[-200:],
        )
        if updated is not None:
            updated["running"] = False
            updated["can_resume"] = bool(next_nodes)
            updated["resume_nodes"] = next_nodes
        return updated

    def _execute_stream(
        self,
        session_id: str,
        ch: _SessionChannel,
        graph_input: Any,
        *,
        kind: str,
    ) -> None:
        checkpointer = self._get_checkpointer()
        compiled = compile_profile_graph(
            self.store,
            checkpointer=checkpointer,
            llm_factory=self._llm_factory,
            cancel_check=ch.cancel_event.is_set,
        )
        config = {"configurable": {"thread_id": session_id}}

        interrupted_payload: Optional[dict[str, Any]] = None
        report_stream_buf = ""
        suppress_meta_fence = False

        for mode, chunk in compiled.stream(
            graph_input,
            config=config,
            stream_mode=["updates", "messages", "custom"],
        ):
            if mode == "custom" and isinstance(chunk, dict):
                ev_type = str(chunk.get("type") or "custom")
                body = {k: v for k, v in chunk.items() if k != "type"}
                ch.publish(ev_type, **body)
                if ev_type == "stage" and body.get("label"):
                    self._log(f"[{session_id[:6]}] {body['label']}")
                elif ev_type == "tool_end" and isinstance(body.get("item"), dict):
                    it = body["item"]
                    lvl = "error" if it.get("status") == "error" else "info"
                    self._log(f"[{session_id[:6]}] {it.get('title')}: {it.get('detail')}", level=lvl)

            elif mode == "messages":
                if not isinstance(chunk, tuple) or len(chunk) != 2:
                    continue
                msg_chunk, metadata = chunk
                node_name = str((metadata or {}).get("langgraph_node") or "")
                if not isinstance(msg_chunk, AIMessageChunk):
                    continue
                if getattr(msg_chunk, "tool_call_chunks", None):
                    continue
                delta = extract_text_content(msg_chunk.content)
                if not delta:
                    continue

                if node_name == "synthesize_profile":
                    if suppress_meta_fence:
                        continue
                    report_stream_buf += delta
                    fence_idx = report_stream_buf.find("```json:profile_meta")
                    if fence_idx >= 0:
                        suppress_meta_fence = True
                        # 若当前 chunk 在 fence 之前还有正文，推送剩余正文部分
                        already_sent = len(report_stream_buf) - len(delta)
                        if fence_idx > already_sent:
                            ch.publish("report_delta", delta=report_stream_buf[already_sent:fence_idx])
                    else:
                        ch.publish("report_delta", delta=delta)
                elif node_name == "followup_agent":
                    ch.publish("chat_delta", delta=delta)

            elif mode == "updates" and isinstance(chunk, dict):
                if "__interrupt__" in chunk:
                    interrupted_payload = _extract_interrupt_payload(chunk["__interrupt__"])

        # 读取 Checkpoint 最新状态并落盘到 agent_profiles
        snap = compiled.get_state(config)
        values = dict(getattr(snap, "values", {}) or {})

        # 双保险：检查 snap.tasks 中是否仍有未决 interrupt
        if interrupted_payload is None:
            for task in getattr(snap, "tasks", ()) or ():
                task_interrupts = getattr(task, "interrupts", None)
                if task_interrupts:
                    interrupted_payload = _extract_interrupt_payload(task_interrupts)
                    break

        existing = self.store.get_agent_profile(session_id) or {}
        structured = dict(existing.get("structured") or {})
        if values.get("profile_structured") is not None:
            structured["profile_meta"] = values["profile_structured"]
        if values.get("baseline_stats"):
            structured["baseline_stats"] = values["baseline_stats"]
        if values.get("citation_report"):
            structured["citation_report"] = values["citation_report"]
        if values.get("candidate_accounts"):
            structured["candidate_accounts"] = values["candidate_accounts"]
        social_ws = values.get("social_workspace")
        if isinstance(social_ws, dict) and (social_ws.get("nodes") or social_ws.get("saved_graph_id")):
            try:
                scored_ws = score_and_prune_candidates(social_ws, top_k=15)
                structured["pruned_graph"] = {
                    "total_nodes": scored_ws["total_nodes"],
                    "total_edges": scored_ws["total_edges"],
                    "triangle_edges_count": scored_ws["triangle_edges_count"],
                    "pruned_summary": scored_ws["pruned_summary"],
                    "core_circle": scored_ws["core_circle"][:12],
                    "saved_graph_id": social_ws.get("saved_graph_id"),
                    "saved_graph_name": social_ws.get("saved_graph_name") or "",
                }
            except Exception:
                pass

        if interrupted_payload is not None:
            structured["pending_interrupt"] = interrupted_payload
            updated = self.store.update_agent_profile(
                session_id,
                status="waiting_confirm",
                structured=structured,
                evidence=values.get("evidence") or existing.get("evidence") or {},
                gaps=values.get("gaps") or existing.get("gaps") or [],
                trace=values.get("trace") or existing.get("trace") or [],
                error="",
            )
            self._log(f"会话 {session_id} 暂停等待人工确认候选账号", level="warn")
            ch.publish("interrupt", payload=interrupted_payload, session=updated)
            return

        structured.pop("pending_interrupt", None)
        final_status = "cancelled" if ch.cancel_event.is_set() else "done"

        if kind == "followup":
            answer = str(values.get("followup_answer") or "").strip()
            chat_history = list(existing.get("chat_history") or [])
            if answer:
                chat_history.append({"role": "assistant", "content": answer, "ts": _now_iso()})
            updated = self.store.update_agent_profile(
                session_id,
                status=final_status,
                structured=structured,
                evidence=values.get("evidence") or existing.get("evidence") or {},
                gaps=values.get("gaps") or existing.get("gaps") or [],
                trace=values.get("trace") or existing.get("trace") or [],
                chat_history=chat_history,
                error="",
            )
            self._log(f"会话 {session_id} 追问回复完成", level="success")
            ch.publish("chat_done", answer=answer, session=updated)
            return

        # 完整侧写收尾
        final_uids = values.get("confirmed_accounts") or existing.get("uids") or {}
        final_md = values.get("report_markdown") or existing.get("report_markdown") or ""
        updated = self.store.update_agent_profile(
            session_id,
            uids=final_uids,
            status=final_status,
            report_markdown=final_md,
            structured=structured,
            evidence=values.get("evidence") or existing.get("evidence") or {},
            gaps=values.get("gaps") or existing.get("gaps") or [],
            trace=values.get("trace") or existing.get("trace") or [],
            error="",
        )
        self._log(f"会话 {session_id} 人物侧写完成 ({final_status})", level="success")
        ch.publish("done", status=final_status, session=updated)


# 全局单例
_runner: Optional[AgentRunManager] = None
_runner_lock = threading.Lock()


def get_agent_runner() -> AgentRunManager:
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = AgentRunManager()
        return _runner
