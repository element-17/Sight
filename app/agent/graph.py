"""
LangGraph 人物侧写 StateGraph 定义与编译

图拓扑：
  START
    ├─ (mode == "followup") ──► followup_agent ◄──► followup_tools ──► END
    └─ (mode == "profile")
         ├─ (已有 confirmed_accounts) ──────────────────────────────► collect_baseline
         └─ (仅有 target_query) ──► discover_identities
                                       ├─ (需确认) ──► confirm_identities [interrupt()] ──► collect_baseline
                                       └─ (无候选) ───────────────────────────────────────► synthesize_profile
  collect_baseline ──► investigator ◄──► execute_tools
                             │
                             ▼ (证据充分或达步数上限)
                       synthesize_profile ──► verify_citations ──► END
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent.analyzers import (
    analyze_social_network,
    compute_activity_stats,
    extract_citation_ids,
)
from app.agent.llm_config import DEFAULT_MAX_STEPS, build_chat_model, format_llm_error, load_effective_config
from app.agent.multimodal import VISUAL_BASELINE_PROMPT, analyze_images
from app.agent.prompts import (
    FOLLOWUP_SYSTEM_PROMPT,
    INVESTIGATOR_SYSTEM_PROMPT,
    SYNTHESIZER_SYSTEM_PROMPT,
)
from app.agent.state import (
    ProfileAgentState,
    extract_text_content,
    next_evidence_id,
    wrap_untrusted_data,
)
from app.agent.tools import (
    build_tool_schemas,
    classify_error,
    dispatch_tool_call,
    extract_media_catalog,
    summarize_platform_payload,
)
from app.credentials import _PLATFORM_NAMES
from app.data.store import DataStore
from app.services.media_fetcher import CachedMedia, download_media
from app.services.platform_fetcher import (
    AllModulesFailedError,
    AuthExpiredError,
    fetch_platform_all,
    find_latest_real_snapshot,
    is_auth_expired_error,
)
from app.services.search_service import rank_identity_candidates, search_cross_platform

CST = timezone(timedelta(hours=8))


def _now_ts() -> str:
    return datetime.now(CST).strftime("%H:%M:%S")


def _emit_custom(payload: dict[str, Any]) -> None:
    """向 LangGraph custom 流推送进度事件；非流式调用下静默降级。"""
    try:
        writer = get_stream_writer()
        if writer:
            writer(payload)
    except Exception:
        pass


def _parse_profile_meta(raw_text: str) -> tuple[str, dict[str, Any]]:
    """
    从 Synthesizer 输出中剥离尾部的 ```json:profile_meta ... ``` 块，
    返回 (clean_markdown, structured_meta)。
    """
    text = (raw_text or "").strip()
    pattern = re.compile(r"```json:profile_meta\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    meta: dict[str, Any] = {}
    if match:
        raw_json = match.group(1).strip()
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                meta = parsed
        except json.JSONDecodeError:
            meta = {}
        clean_md = (text[: match.start()] + text[match.end() :]).strip()
    else:
        clean_md = text

    meta.setdefault("headline", "")
    meta.setdefault("tags", [])
    meta.setdefault("confidence_overall", "medium")
    meta.setdefault("dimensions", [])
    meta.setdefault("blind_spots", [])
    return clean_md, meta


def _format_evidence_catalog(evidence: dict[str, dict[str, Any]]) -> str:
    if not evidence:
        return "（暂无证据条目）"
    lines = []
    for eid, item in evidence.items():
        pname = item.get("platform_name") or item.get("platform") or ""
        title = item.get("title") or ""
        snippet = str(item.get("snippet") or "")[:360]
        lines.append(f"[{eid}] ({pname}) {title}: {snippet}")
    return "\n".join(lines)


def _trim_messages(messages: list, max_keep: int = 18) -> list:
    """保留最近若干轮消息并保证不从孤立的 ToolMessage 开始截断。"""
    if len(messages) <= max_keep:
        return list(messages)
    sliced = list(messages[-max_keep:])
    while sliced and isinstance(sliced[0], ToolMessage):
        sliced.pop(0)
    return sliced


def compile_profile_graph(
    store: DataStore,
    checkpointer: Any = None,
    *,
    llm_factory: Optional[Callable[[], Any]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    enable_visual_baseline: Optional[bool] = None,
):
    """
    组装并编译 Sight 人物侧写 LangGraph StateGraph。

    Args:
        store: Sight 共享 DataStore
        checkpointer: LangGraph Checkpointer（生产用 SqliteSaver，单测可用 MemorySaver/SqliteSaver）
        llm_factory: 可选自定义 LLM 工厂（测试注入 FakeChatModel 用）
        cancel_check: 可选协作式取消探针，返回 True 时提前收敛/退出
        enable_visual_baseline: 是否自动对跨平台头像/背景执行 Level 1 视觉基线（默认：非 Fake 模式下跟随 llm_config.enable_multimodal）
    """
    tools = build_tool_schemas(store)

    def _get_llm(streaming: bool = True):
        if llm_factory is not None:
            return llm_factory()
        return build_chat_model(streaming=streaming)

    def _is_cancelled() -> bool:
        try:
            return bool(cancel_check and cancel_check())
        except Exception:
            return False

    # ==================== 路由函数 ====================

    def route_entry(state: ProfileAgentState) -> str:
        if state.get("mode") == "followup":
            return "followup_agent"
        accounts = {k: v for k, v in (state.get("confirmed_accounts") or {}).items() if k and v}
        if accounts:
            return "collect_baseline"
        if (state.get("target_query") or "").strip():
            return "discover_identities"
        return "collect_baseline"

    # ==================== Node 1: 跨平台搜人 ====================

    def discover_identities(state: ProfileAgentState) -> dict[str, Any]:
        query = (state.get("target_query") or "").strip()
        _emit_custom(
            {
                "type": "stage",
                "stage": "discover_identities",
                "label": f"正在跨平台检索「{query}」的候选账号…",
            }
        )
        t0 = time.perf_counter()
        search_res = search_cross_platform(query, limit=6, refresh=bool(state.get("refresh_data")))
        candidates = rank_identity_candidates(search_res, max_per_platform=5)
        elapsed_ms = round((time.perf_counter() - t0) * 1000)

        gaps = [
            {
                "platform": pid,
                "category": "discover_search",
                "reason": str(err),
                "error_kind": classify_error(str(err)),
            }
            for pid, err in (search_res.get("errors") or {}).items()
        ]
        trace_item = {
            "ts": _now_ts(),
            "stage": "discover_identities",
            "title": f"跨平台检索「{query}」",
            "detail": f"命中 {len(candidates)} 个候选账号，覆盖 {len(search_res.get('platforms') or [])} 个平台",
            "status": "done",
            "elapsed_ms": elapsed_ms,
        }
        _emit_custom({"type": "trace", "item": trace_item})
        return {
            "candidate_accounts": candidates,
            "gaps": gaps,
            "trace": [trace_item],
        }

    def route_after_discover(state: ProfileAgentState) -> str:
        candidates = state.get("candidate_accounts") or []
        if not candidates:
            return "synthesize_profile"
        return "confirm_identities"

    # ==================== Node 2: 候选账号确认（原生 interrupt） ====================

    def confirm_identities(state: ProfileAgentState) -> dict[str, Any]:
        candidates = state.get("candidate_accounts") or []
        query = (state.get("target_query") or "").strip()

        if state.get("auto_confirm"):
            selected: dict[str, str] = {}
            for c in candidates:
                pid = str(c.get("platform") or "")
                uid = str(c.get("uid") or "")
                if pid and uid and c.get("recommended") and pid not in selected:
                    selected[pid] = uid
            # 若没有达到推荐阈值的，回退取每个平台置信度最高的前 3 个平台
            if not selected:
                for c in candidates:
                    pid = str(c.get("platform") or "")
                    uid = str(c.get("uid") or "")
                    if pid and uid and pid not in selected:
                        selected[pid] = uid
                    if len(selected) >= 3:
                        break
            trace_item = {
                "ts": _now_ts(),
                "stage": "confirm_identities",
                "title": "自动归并候选账号",
                "detail": "已选定: " + (", ".join(f"{_PLATFORM_NAMES.get(k, k)}:{v}" for k, v in selected.items()) or "无"),
                "status": "done",
            }
            _emit_custom({"type": "trace", "item": trace_item})
            return {"confirmed_accounts": selected, "trace": [trace_item]}

        # 触发 LangGraph 原生中断：Checkpoint 自动持久化，前端展示勾选卡片后用 Command(resume=...) 恢复
        interrupt_payload = {
            "type": "confirm_identities",
            "query": query,
            "candidates": candidates,
            "message": f"跨平台检索到 {len(candidates)} 个候选账号，请勾选确认属于同一目标的账号后继续侧写。",
        }
        decision = interrupt(interrupt_payload)

        selected = {}
        if isinstance(decision, dict):
            raw_accounts = decision.get("confirmed_accounts", decision)
            if isinstance(raw_accounts, dict):
                selected = {
                    str(k).strip(): str(v).strip()
                    for k, v in raw_accounts.items()
                    if str(k).strip() and str(v).strip()
                }
        elif isinstance(decision, list):
            for item in decision:
                if isinstance(item, dict) and item.get("platform") and item.get("uid"):
                    selected[str(item["platform"]).strip()] = str(item["uid"]).strip()

        trace_item = {
            "ts": _now_ts(),
            "stage": "confirm_identities",
            "title": "用户已确认跨平台账号",
            "detail": ", ".join(f"{_PLATFORM_NAMES.get(k, k)}:{v}" for k, v in selected.items()) or "未勾选任何账号",
            "status": "done",
        }
        _emit_custom({"type": "trace", "item": trace_item})
        return {"confirmed_accounts": selected, "trace": [trace_item]}

    # ==================== Node 3: 确定性基线采集 + 统计 ====================

    def collect_baseline(state: ProfileAgentState) -> dict[str, Any]:
        accounts = {
            str(k).strip(): str(v).strip()
            for k, v in (state.get("confirmed_accounts") or {}).items()
            if str(k).strip() and str(v).strip()
        }
        refresh = bool(state.get("refresh_data"))
        graph_id = state.get("graph_id")
        existing_evidence = dict(state.get("evidence") or {})

        _emit_custom(
            {
                "type": "stage",
                "stage": "collect_baseline",
                "label": f"正在并行采集 {len(accounts)} 个平台基线数据并计算作息/社交特征…",
            }
        )
        t0 = time.perf_counter()

        raw_payloads: dict[str, dict[str, Any]] = {}
        summaries: dict[str, dict[str, Any]] = {}
        media_catalog: dict[str, dict[str, Any]] = {}
        new_evidence: dict[str, dict[str, Any]] = {}
        new_gaps: list[dict[str, Any]] = []
        baseline_traces: list[dict[str, Any]] = []
        ev_offset = 0

        def _alloc_evidence(item: dict[str, Any]) -> str:
            nonlocal ev_offset
            ev_offset += 1
            eid = next_evidence_id(existing_evidence, offset=ev_offset)
            new_evidence[eid] = {"id": eid, **item}
            return eid

        def _fetch_one(pair: tuple[str, str]):
            pid, uid = pair
            try:
                payload, partial_errors = fetch_platform_all(
                    pid,
                    uid,
                    store,
                    refresh=refresh,
                    include_social=True,
                    include_records=True,
                )
                return pid, uid, payload, partial_errors, None
            except AuthExpiredError as e:
                return pid, uid, None, [], ("auth_expired", str(e))
            except (AllModulesFailedError, Exception) as e:
                err_str = str(e)
                # 离线/瞬时失败时回退最近一条本地快照
                if not is_auth_expired_error(err_str):
                    fb_profile = find_latest_real_snapshot(store, pid, uid, "profile")
                    if fb_profile:
                        fb = {
                            "platform": pid,
                            "uid": uid,
                            "profile": fb_profile,
                            "playlists": (find_latest_real_snapshot(store, pid, uid, "playlists") or {}).get("items", []),
                            "events": (find_latest_real_snapshot(store, pid, uid, "events") or {}).get("items", []),
                            "records": find_latest_real_snapshot(store, pid, uid, "records") or {"allTime": [], "weekly": []},
                            "follows": (find_latest_real_snapshot(store, pid, uid, "follows") or {}).get("items", []),
                            "followers": (find_latest_real_snapshot(store, pid, uid, "followers") or {}).get("items", []),
                        }
                        return pid, uid, fb, [f"实时拉取失败，使用本地历史快照: {err_str}"], None
                return pid, uid, None, [], (classify_error(err_str), err_str)

        if accounts:
            with ThreadPoolExecutor(max_workers=min(4, len(accounts))) as ex:
                for pid, uid, payload, partial_errors, fatal in ex.map(_fetch_one, accounts.items()):
                    if fatal is not None:
                        kind, err_msg = fatal
                        new_gaps.append(
                            {
                                "platform": pid,
                                "category": "baseline_fetch",
                                "reason": err_msg,
                                "error_kind": kind,
                            }
                        )
                        continue
                    raw_payloads[pid] = payload
                    media_catalog[pid] = extract_media_catalog(pid, uid, payload)
                    compact, ev_list = summarize_platform_payload(pid, uid, payload, partial_errors)
                    assigned_ids = [_alloc_evidence(ev) for ev in ev_list]
                    compact["evidence_ids"] = assigned_ids
                    summaries[pid] = compact
                    for perr in partial_errors:
                        new_gaps.append(
                            {
                                "platform": pid,
                                "category": "baseline_partial",
                                "reason": perr,
                                "error_kind": classify_error(perr),
                            }
                        )

        # 读取持久化历史时间线
        timeline_rows: list[dict[str, Any]] = []
        for pid, uid in accounts.items():
            try:
                timeline_rows.extend(store.get_timeline_entries(platform=pid, uid=uid, limit=30))
            except Exception:
                pass
        timeline_rows.sort(key=lambda r: (r.get("created_at", ""), r.get("timestamp", 0)), reverse=True)
        timeline_rows = timeline_rows[:50]
        if timeline_rows:
            tl_preview = "；".join(
                f"{r.get('time_str') or r.get('time_suffix') or ''} {r.get('summary', '')}"
                for r in timeline_rows[:6]
            )
            _alloc_evidence(
                {
                    "platform": "multi",
                    "platform_name": "活动时间线",
                    "uid": ",".join(f"{k}:{v}" for k, v in accounts.items()),
                    "category": "timeline",
                    "title": f"历史活动时间线（共 {len(timeline_rows)} 条）",
                    "snippet": tl_preview[:400],
                    "url": "",
                    "timestamp": "",
                }
            )

        # 读取可选关联图谱
        graph_data = None
        graph_name = ""
        if graph_id is not None:
            try:
                saved = store.get_graph(int(graph_id))
                if saved:
                    graph_data = saved.get("data")
                    graph_name = str(saved.get("name") or "")
            except Exception as e:
                new_gaps.append({"platform": "multi", "category": "graph", "reason": str(e), "error_kind": "unknown"})

        # 确定性统计计算（作息热力 + 社交网络核心圈）
        activity_stats = compute_activity_stats(raw_payloads, timeline_entries=timeline_rows)
        social_stats = analyze_social_network(
            graph_data=graph_data,
            platform_payloads=raw_payloads,
            target_accounts=accounts,
        )
        if activity_stats["total_timed_events"] > 0:
            peak_str = ", ".join(f"{h:02d}:00" for h in activity_stats["peak_hours"]) or "分散"
            _alloc_evidence(
                {
                    "platform": "multi",
                    "platform_name": "作息统计",
                    "uid": "stats",
                    "category": "activity_stats",
                    "title": f"确定性作息统计（{activity_stats['total_timed_events']} 条带时间记录）",
                    "snippet": (
                        f"作息类型: {activity_stats['chronotype']} | "
                        f"高峰时段: {peak_str} | 深夜活跃占比: {round(activity_stats['late_night_ratio'] * 100, 1)}% | "
                        f"跨度: {activity_stats['date_span'].get('earliest', '-')} ~ {activity_stats['date_span'].get('latest', '-')}"
                    ),
                    "url": "",
                    "timestamp": "",
                }
            )
        if social_stats["total_nodes"] > 1:
            mutuals = social_stats["mutual_core_contacts"][:6]
            _alloc_evidence(
                {
                    "platform": "multi",
                    "platform_name": "社交网络",
                    "uid": str(graph_id or "social"),
                    "category": "social_stats",
                    "title": f"社交网络拓扑分析（{graph_name or '基线关系'}，{social_stats['total_nodes']} 节点）",
                    "snippet": (
                        f"互关核心候选({len(social_stats['mutual_core_contacts'])}): "
                        + ("、".join(f"{c['nickname']}({c['platform_name']})" for c in mutuals) or "暂无")
                        + f" | 关注大V/公众账号: {len(social_stats['followed_public_accounts'])} 个"
                    ),
                    "url": "",
                    "timestamp": "",
                }
            )

        # Level 1 视觉基线：自动下载跨平台头像/背景图（最多 6 张），一次性分析身份一致性与审美风格
        eff_cfg = load_effective_config()
        should_run_visual = (
            bool(enable_visual_baseline)
            if enable_visual_baseline is not None
            else (llm_factory is None and bool(eff_cfg.get("configured")) and bool(eff_cfg.get("enable_multimodal")))
        )
        visual_baseline_summary: Optional[dict[str, Any]] = None
        if should_run_visual and media_catalog and not _is_cancelled():
            visual_candidates: list[tuple[str, str, str]] = []  # (label, platform, url)
            seen_visual_urls: set[str] = set()
            for pid, cat in media_catalog.items():
                pname = _PLATFORM_NAMES.get(pid, pid)
                nick = cat.get("nickname") or cat.get("uid") or ""
                av = str(cat.get("avatar_url") or "").strip()
                if av and av not in seen_visual_urls and len(visual_candidates) < 6:
                    seen_visual_urls.add(av)
                    visual_candidates.append((f"{pname} 头像 ({nick})", pid, av))
            for pid, cat in media_catalog.items():
                if len(visual_candidates) >= 6:
                    break
                pname = _PLATFORM_NAMES.get(pid, pid)
                bg = str(cat.get("background_url") or "").strip()
                if bg and bg not in seen_visual_urls:
                    seen_visual_urls.add(bg)
                    visual_candidates.append((f"{pname} 主页背景", pid, bg))

            if visual_candidates:
                _emit_custom(
                    {
                        "type": "stage",
                        "stage": "visual_baseline",
                        "label": f"正在执行多模态视觉基线分析（{len(visual_candidates)} 张跨平台头像/背景图）…",
                    }
                )
                vt0 = time.perf_counter()
                downloaded_visuals: list[tuple[str, CachedMedia]] = []

                def _dl_vis(item: tuple[str, str, str]):
                    lbl, pid_v, url_v = item
                    try:
                        return lbl, download_media(url_v, platform=pid_v, kind="image")
                    except Exception:
                        return lbl, None

                with ThreadPoolExecutor(max_workers=min(4, len(visual_candidates))) as ex:
                    for lbl, media in ex.map(_dl_vis, visual_candidates):
                        if media is not None:
                            downloaded_visuals.append((lbl, media))

                if downloaded_visuals:
                    try:
                        vres = analyze_images(downloaded_visuals, VISUAL_BASELINE_PROMPT)
                        v_eid = _alloc_evidence(
                            {
                                "platform": "multi",
                                "platform_name": "多模态视觉基线",
                                "uid": "visual_baseline",
                                "category": "visual_baseline",
                                "title": f"跨平台头像与背景视觉基线（{len(downloaded_visuals)} 张）",
                                "snippet": vres["analysis"][:480],
                                "url": "",
                                "timestamp": "",
                                "media_urls": [m.preview_url for _, m in downloaded_visuals],
                            }
                        )
                        visual_baseline_summary = {
                            "evidence_id": v_eid,
                            "image_count": len(downloaded_visuals),
                            "provider": vres["provider"],
                            "model": vres["model"],
                            "analysis": vres["analysis"][:1200],
                        }
                        v_trace = {
                            "ts": _now_ts(),
                            "stage": "visual_baseline",
                            "title": "多模态视觉基线完成",
                            "detail": f"已分析 {len(downloaded_visuals)} 张跨平台头像/背景图 ({vres['model']})",
                            "status": "done",
                            "elapsed_ms": round((time.perf_counter() - vt0) * 1000),
                            "evidence_ids": [v_eid],
                        }
                        baseline_traces.append(v_trace)
                        _emit_custom({"type": "trace", "item": v_trace})
                    except Exception as ve:
                        verr = format_llm_error(ve)
                        new_gaps.append(
                            {
                                "platform": "multi",
                                "category": "visual_baseline",
                                "reason": f"视觉基线未完成（已自动降级为纯文本侧写）: {verr}",
                                "error_kind": classify_error(verr),
                            }
                        )

        baseline_stats = {
            "activity": activity_stats,
            "social": social_stats,
            "graph_id": graph_id,
            "graph_name": graph_name,
            "timeline_count": len(timeline_rows),
        }

        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        trace_item = {
            "ts": _now_ts(),
            "stage": "collect_baseline",
            "title": "基线采集与确定性统计完成",
            "detail": (
                f"成功采集 {len(summaries)}/{len(accounts)} 个平台，"
                f"建立 {len(new_evidence)} 条初始证据，识别 {len(new_gaps)} 项盲区"
            ),
            "status": "done",
            "elapsed_ms": elapsed_ms,
        }
        baseline_traces.insert(0, trace_item)
        _emit_custom({"type": "trace", "item": trace_item})
        _emit_custom({"type": "baseline_stats", "stats": baseline_stats})

        # 构造给 Investigator 的首条结构化简报
        brief_payload: dict[str, Any] = {
            "target_query": state.get("target_query") or "",
            "focus": state.get("focus") or "全面人物形象侧写",
            "confirmed_accounts": accounts,
            "multimodal_capabilities": {
                "provider": eff_cfg["provider"],
                "supports_vision": eff_cfg["supports_vision"],
                "supports_video": eff_cfg["supports_video"],
            },
            "platform_summaries": summaries,
            "deterministic_stats": {
                "chronotype": activity_stats["chronotype"],
                "peak_hours": activity_stats["peak_hours"],
                "late_night_ratio": activity_stats["late_night_ratio"],
                "total_timed_events": activity_stats["total_timed_events"],
                "top_artists": activity_stats["top_artists"][:8],
                "top_languages": activity_stats["top_languages"][:6],
                "locations": activity_stats["locations"],
                "mutual_core_contacts": social_stats["mutual_core_contacts"][:10],
                "followed_public_accounts": social_stats["followed_public_accounts"][:8],
                "cross_platform_links": social_stats["cross_platform_links"][:10],
            },
            "known_gaps": new_gaps,
        }
        if visual_baseline_summary:
            brief_payload["visual_baseline"] = visual_baseline_summary

        all_ev = {**existing_evidence, **new_evidence}
        prompt_text = (
            "以下是目标的跨平台基线摘要、视觉基线（若有）与确定性统计特征，请你审视是否存在值得深挖的线索"
            "（如 B 站评论/弹幕存档、代表性歌单/仓库/笔记详情、图文多模态 inspect_images、短视频多模态 inspect_video、历史时间线、跨平台线索或社交采样）：\n\n"
            f"## 现有证据编号索引\n{_format_evidence_catalog(all_ev)}\n\n"
            f"## 基线数据\n{wrap_untrusted_data('baseline_bundle', brief_payload, max_chars=14000)}"
        )

        return {
            "confirmed_accounts": accounts,
            "baseline_summaries": summaries,
            "baseline_stats": baseline_stats,
            "media_catalog": media_catalog,
            "evidence": new_evidence,
            "gaps": new_gaps,
            "step_count": 0,
            "messages": [HumanMessage(content=prompt_text)],
            "trace": baseline_traces,
        }

    # ==================== Node 4: 侦查员 LLM ====================

    def investigator(state: ProfileAgentState) -> dict[str, Any]:
        step = int(state.get("step_count") or 0)
        max_steps = int(state.get("max_steps") or DEFAULT_MAX_STEPS)
        if _is_cancelled():
            return {"step_count": max_steps}

        _emit_custom(
            {
                "type": "stage",
                "stage": "investigator",
                "label": f"侦查推理中（第 {step + 1}/{max_steps} 步）…",
            }
        )

        remaining = max_steps - step
        budget_note = (
            f"\n\n[当前预算提醒] 这是第 {step + 1}/{max_steps} 步。"
            + (
                "已达步数上限，请勿再调用工具，直接输出简洁的侦查小结。"
                if remaining <= 1
                else f"最多还可调用工具 {remaining - 1} 轮；如证据已充分可直接结束侦查。"
            )
        )
        llm = _get_llm(streaming=True)
        bound = llm.bind_tools(tools) if remaining > 1 else llm
        history = _trim_messages(state.get("messages") or [], max_keep=16)
        response = bound.invoke([SystemMessage(content=INVESTIGATOR_SYSTEM_PROMPT + budget_note), *history])

        tool_calls = getattr(response, "tool_calls", None) or []
        trace_item = {
            "ts": _now_ts(),
            "stage": "investigator",
            "title": f"侦查推理第 {step + 1} 步",
            "detail": (
                "计划调用工具: " + ", ".join(tc.get("name", "?") for tc in tool_calls)
                if tool_calls
                else "证据采集充分，转入人物侧写报告合成"
            ),
            "status": "done",
        }
        _emit_custom({"type": "trace", "item": trace_item})
        return {
            "messages": [response],
            "step_count": step + 1,
            "trace": [trace_item],
        }

    def route_after_investigator(state: ProfileAgentState) -> str:
        if _is_cancelled():
            return "synthesize_profile"
        step = int(state.get("step_count") or 0)
        max_steps = int(state.get("max_steps") or DEFAULT_MAX_STEPS)
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        tool_calls = getattr(last, "tool_calls", None) or []
        if tool_calls and step < max_steps:
            return "execute_tools"
        return "synthesize_profile"

    # ==================== Node 5: 工具执行节点（带证据账本与错误边界） ====================

    def _run_tool_calls(state: ProfileAgentState, stage_name: str) -> dict[str, Any]:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        tool_calls = getattr(last, "tool_calls", None) or []

        existing_ev = dict(state.get("evidence") or {})
        existing_catalog = dict(state.get("media_catalog") or {})
        confirmed_accounts = dict(state.get("confirmed_accounts") or {})
        added_ev: dict[str, dict[str, Any]] = {}
        added_catalog: dict[str, dict[str, Any]] = {}
        added_gaps: list[dict[str, Any]] = []
        tool_messages: list[ToolMessage] = []
        traces: list[dict[str, Any]] = []

        for tc in tool_calls:
            if _is_cancelled():
                break
            tname = str(tc.get("name") or "")
            targs = tc.get("args") or {}
            tc_id = str(tc.get("id") or f"call_{int(time.time() * 1000)}")

            _emit_custom(
                {
                    "type": "tool_start",
                    "tool": tname,
                    "args": targs,
                    "label": f"正在执行工具 {tname}…",
                }
            )
            t0 = time.perf_counter()
            merged_now = {**existing_ev, **added_ev}
            merged_catalog = {**existing_catalog, **added_catalog}
            content_text, ev_map, gaps, exec_res = dispatch_tool_call(
                tname,
                targs,
                store,
                merged_now,
                media_catalog=merged_catalog,
                confirmed_accounts=confirmed_accounts,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000)

            added_ev.update(ev_map)
            if exec_res.media_catalog_updates:
                added_catalog.update(exec_res.media_catalog_updates)
            added_gaps.extend(gaps)
            tool_messages.append(ToolMessage(content=content_text, tool_call_id=tc_id, name=tname))

            trace_item = {
                "ts": _now_ts(),
                "stage": stage_name,
                "tool": tname,
                "title": f"工具 {tname}",
                "detail": exec_res.summary_text + (f" ({exec_res.error})" if not exec_res.ok else ""),
                "status": "done" if exec_res.ok else "error",
                "elapsed_ms": elapsed_ms,
                "evidence_ids": list(ev_map.keys()),
            }
            traces.append(trace_item)
            _emit_custom({"type": "tool_end", "item": trace_item, "new_evidence": ev_map})

        out_update: dict[str, Any] = {
            "messages": tool_messages,
            "evidence": added_ev,
            "gaps": added_gaps,
            "trace": traces,
        }
        if added_catalog:
            out_update["media_catalog"] = added_catalog
        return out_update

    def execute_tools(state: ProfileAgentState) -> dict[str, Any]:
        return _run_tool_calls(state, "execute_tools")

    # ==================== Node 6: 综合侧写报告生成 ====================

    def synthesize_profile(state: ProfileAgentState) -> dict[str, Any]:
        _emit_custom(
            {
                "type": "stage",
                "stage": "synthesize_profile",
                "label": "正在综合全部证据生成结构化人物侧写报告…",
            }
        )
        t0 = time.perf_counter()
        accounts = state.get("confirmed_accounts") or {}
        evidence = state.get("evidence") or {}
        gaps = state.get("gaps") or []
        baseline_stats = state.get("baseline_stats") or {}

        # 提取侦查员的最后总结（若有）
        investigator_notes = ""
        for msg in reversed(state.get("messages") or []):
            if isinstance(msg, AIMessage) and not (getattr(msg, "tool_calls", None) or []):
                investigator_notes = extract_text_content(msg.content).strip()
                break

        synth_context = {
            "target_query": state.get("target_query") or "",
            "focus": state.get("focus") or "全面人物形象侧写",
            "confirmed_accounts": {
                k: {"platform_name": _PLATFORM_NAMES.get(k, k), "uid": v}
                for k, v in accounts.items()
            },
            "activity_stats": baseline_stats.get("activity") or {},
            "social_stats": baseline_stats.get("social") or {},
            "gaps": gaps,
            "investigator_notes": investigator_notes[:3500],
        }

        user_prompt = (
            "请严格依据下面的证据账本与统计特征，撰写完整的人物形象侧写 Markdown 报告，并在末尾附上 `json:profile_meta` 代码块。\n\n"
            f"## 证据账本（仅允许引用下列真实存在的 E# 编号）\n"
            f"{wrap_untrusted_data('evidence_ledger', _format_evidence_catalog(evidence), max_chars=16000)}\n\n"
            f"## 结构化统计与盲区\n"
            f"{wrap_untrusted_data('synthesis_context', synth_context, max_chars=12000)}"
        )

        llm = _get_llm(streaming=True)
        resp = llm.invoke(
            [
                SystemMessage(content=SYNTHESIZER_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
        raw_text = extract_text_content(resp.content)
        clean_md, meta = _parse_profile_meta(raw_text)
        elapsed_ms = round((time.perf_counter() - t0) * 1000)

        trace_item = {
            "ts": _now_ts(),
            "stage": "synthesize_profile",
            "title": "人物侧写报告生成完成",
            "detail": f"共 {len(clean_md)} 字，标签 {len(meta.get('tags') or [])} 个",
            "status": "done",
            "elapsed_ms": elapsed_ms,
        }
        _emit_custom({"type": "trace", "item": trace_item})
        return {
            "report_markdown": clean_md,
            "profile_structured": meta,
            "messages": [AIMessage(content=f"[已生成人物侧写报告]\n\n{clean_md[:4000]}")],
            "trace": [trace_item],
        }

    # ==================== Node 7: 确定性引用校验 ====================

    def verify_citations(state: ProfileAgentState) -> dict[str, Any]:
        md = state.get("report_markdown") or ""
        evidence = state.get("evidence") or {}
        structured = dict(state.get("profile_structured") or {})

        cited = extract_citation_ids(md)
        valid_ids = [eid for eid in cited if eid in evidence]
        invalid_ids = [eid for eid in cited if eid not in evidence]

        cleaned_md = md
        for bad_id in invalid_ids:
            cleaned_md = re.sub(rf"\[{re.escape(bad_id)}\]", "", cleaned_md)

        # 同步清理 structured.dimensions 中的无效引用
        dims = structured.get("dimensions")
        if isinstance(dims, list):
            for d in dims:
                if isinstance(d, dict) and isinstance(d.get("evidence_ids"), list):
                    d["evidence_ids"] = [eid for eid in d["evidence_ids"] if eid in evidence]

        citation_report = {
            "total_evidence": len(evidence),
            "cited_valid": valid_ids,
            "removed_invalid": invalid_ids,
        }
        trace_item = {
            "ts": _now_ts(),
            "stage": "verify_citations",
            "title": "证据引用校验完成",
            "detail": (
                f"有效引用 {len(valid_ids)}/{len(evidence)} 条"
                + (f"，已剔除 {len(invalid_ids)} 条无效编号" if invalid_ids else "，零幻觉引用")
            ),
            "status": "done",
        }
        _emit_custom({"type": "trace", "item": trace_item})
        return {
            "report_markdown": cleaned_md,
            "profile_structured": structured,
            "citation_report": citation_report,
            "trace": [trace_item],
        }

    # ==================== Follow-up 多轮追问子路径 ====================

    def followup_agent(state: ProfileAgentState) -> dict[str, Any]:
        step = int(state.get("step_count") or 0)
        max_steps = int(state.get("max_steps") or 4)
        _emit_custom(
            {
                "type": "stage",
                "stage": "followup_agent",
                "label": f"正在分析追问并检索证据（第 {step + 1}/{max_steps} 步）…",
            }
        )
        accounts = state.get("confirmed_accounts") or {}
        evidence = state.get("evidence") or {}
        report_excerpt = (state.get("report_markdown") or "")[:3000]
        context_block = (
            f"\n\n## 当前档案上下文\n"
            f"- 已绑定账号: {json.dumps(accounts, ensure_ascii=False)}\n"
            f"- 现有证据索引:\n{wrap_untrusted_data('evidence_ledger', _format_evidence_catalog(evidence), max_chars=8000)}\n"
            f"- 现有侧写报告摘要:\n{wrap_untrusted_data('existing_report', report_excerpt, max_chars=3200)}"
        )

        llm = _get_llm(streaming=True)
        can_use_tools = (step + 1) < max_steps and not _is_cancelled()
        bound = llm.bind_tools(tools) if can_use_tools else llm
        history = _trim_messages(state.get("messages") or [], max_keep=16)
        resp = bound.invoke([SystemMessage(content=FOLLOWUP_SYSTEM_PROMPT + context_block), *history])

        tool_calls = getattr(resp, "tool_calls", None) or []
        answer = "" if tool_calls else extract_text_content(resp.content).strip()
        trace_item = {
            "ts": _now_ts(),
            "stage": "followup_agent",
            "title": "追问分析",
            "detail": (
                "补充调用工具: " + ", ".join(tc.get("name", "?") for tc in tool_calls)
                if tool_calls
                else "已生成追问回复"
            ),
            "status": "done",
        }
        _emit_custom({"type": "trace", "item": trace_item})
        return {
            "messages": [resp],
            "step_count": step + 1,
            "followup_answer": answer,
            "trace": [trace_item],
        }

    def route_after_followup(state: ProfileAgentState) -> str:
        if _is_cancelled():
            return END
        step = int(state.get("step_count") or 0)
        max_steps = int(state.get("max_steps") or 4)
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        tool_calls = getattr(last, "tool_calls", None) or []
        if tool_calls and step < max_steps:
            return "followup_tools"
        return END

    def followup_tools(state: ProfileAgentState) -> dict[str, Any]:
        return _run_tool_calls(state, "followup_tools")

    # ==================== 组装 StateGraph ====================

    builder = StateGraph(ProfileAgentState)
    builder.add_node("discover_identities", discover_identities)
    builder.add_node("confirm_identities", confirm_identities)
    builder.add_node("collect_baseline", collect_baseline)
    builder.add_node("investigator", investigator)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("synthesize_profile", synthesize_profile)
    builder.add_node("verify_citations", verify_citations)
    builder.add_node("followup_agent", followup_agent)
    builder.add_node("followup_tools", followup_tools)

    builder.add_conditional_edges(
        START,
        route_entry,
        {
            "discover_identities": "discover_identities",
            "collect_baseline": "collect_baseline",
            "followup_agent": "followup_agent",
        },
    )
    builder.add_conditional_edges(
        "discover_identities",
        route_after_discover,
        {
            "confirm_identities": "confirm_identities",
            "synthesize_profile": "synthesize_profile",
        },
    )
    builder.add_edge("confirm_identities", "collect_baseline")
    builder.add_edge("collect_baseline", "investigator")
    builder.add_conditional_edges(
        "investigator",
        route_after_investigator,
        {
            "execute_tools": "execute_tools",
            "synthesize_profile": "synthesize_profile",
        },
    )
    builder.add_edge("execute_tools", "investigator")
    builder.add_edge("synthesize_profile", "verify_citations")
    builder.add_edge("verify_citations", END)

    builder.add_conditional_edges(
        "followup_agent",
        route_after_followup,
        {
            "followup_tools": "followup_tools",
            END: END,
        },
    )
    builder.add_edge("followup_tools", "followup_agent")

    return builder.compile(checkpointer=checkpointer)
