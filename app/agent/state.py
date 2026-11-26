"""
LangGraph 人物侧写智能体的核心 State、数据结构与安全辅助函数。
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def merge_evidence(
    left: dict[str, dict[str, Any]] | None,
    right: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """合并证据账本（按证据 ID 幂等覆盖/增量合并，保持插入顺序）。"""
    merged: dict[str, dict[str, Any]] = dict(left or {})
    if right:
        for eid, item in right.items():
            if eid and isinstance(item, dict):
                merged[str(eid)] = item
    return merged


def merge_media_catalog(
    left: dict[str, dict[str, Any]] | None,
    right: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """按平台合并媒体索引（头像、背景、作品图文与视频流元数据），避免重复抓取。"""
    merged: dict[str, dict[str, Any]] = {
        k: dict(v) for k, v in (left or {}).items() if isinstance(v, dict)
    }
    if right:
        for pid, entry in right.items():
            if not pid or not isinstance(entry, dict):
                continue
            prev = dict(merged.get(pid) or {})
            prev_items = dict(prev.get("items") or {})
            new_items = entry.get("items") or {}
            if isinstance(new_items, dict):
                prev_items.update(new_items)
            updated = {**prev, **entry, "items": prev_items}
            if not entry.get("events") and prev.get("events"):
                updated["events"] = prev["events"]
            merged[str(pid)] = updated
    return merged


def merge_gaps(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """合并信息盲区（按 platform + category + reason 去重）。"""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for bucket in (left or [], right or []):
        for item in bucket:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("platform") or ""),
                str(item.get("category") or ""),
                str(item.get("reason") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def append_trace(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """追加执行轨迹事件（上限保留最近 200 条）。"""
    merged = list(left or [])
    if right:
        merged.extend(item for item in right if isinstance(item, dict))
    return merged[-200:]


def next_evidence_id(existing: dict[str, dict[str, Any]] | None, offset: int = 1) -> str:
    """基于现有证据账本分配下一个 E# 编号（E1, E2, ...）。"""
    max_num = 0
    for eid in (existing or {}).keys():
        m = re.fullmatch(r"E(\d+)", str(eid).strip())
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"E{max_num + offset}"


def wrap_untrusted_data(source_label: str, payload: Any, max_chars: int = 12000) -> str:
    """
    将外部抓取数据用显式隔离标签封装并截断，降低间接提示词注入风险。
    """
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    # 防止外部文本闭合隔离标签
    text = text.replace("</untrusted_user_data>", "<\\/untrusted_user_data>")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [内容已截断，原始长度 {len(text)} 字符]"
    return f'<untrusted_user_data source="{source_label}">\n{text}\n</untrusted_user_data>'


def extract_text_content(content: Any) -> str:
    """兼容 LangChain 字符串或 content blocks 列表，提取纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(str(item["content"]))
        return "".join(parts)
    return str(content)


class ProfileAgentState(TypedDict, total=False):
    """LangGraph StateGraph 的核心状态结构。"""

    # 对话与工具调用轨迹（压缩后的摘要，不放原始大 JSON）
    messages: Annotated[list[AnyMessage], add_messages]

    # 执行模式: "profile"（完整侧写） | "followup"（多轮追问）
    mode: str

    # 调查输入与账号定界
    target_query: str
    focus: str
    confirmed_accounts: dict[str, str]          # {platform: uid}
    candidate_accounts: list[dict[str, Any]]    # 待消歧候选列表
    graph_id: Optional[int]                     # 可选关联已保存的关系图谱 ID
    auto_confirm: bool                          # 是否跳过人工确认直接采纳推荐候选
    refresh_data: bool                          # 是否强制绕过 30 分钟快照缓存

    # 基线数据摘要与确定性统计（供 ECharts 与侧写节点消费）
    baseline_summaries: dict[str, dict[str, Any]]
    baseline_stats: dict[str, Any]
    media_catalog: Annotated[dict[str, dict[str, Any]], merge_media_catalog]

    # 证据账本 & 信息盲区
    evidence: Annotated[dict[str, dict[str, Any]], merge_evidence]
    gaps: Annotated[list[dict[str, Any]], merge_gaps]

    # 预算与轨迹
    step_count: int
    max_steps: int
    trace: Annotated[list[dict[str, Any]], append_trace]

    # 最终产物
    profile_structured: Optional[dict[str, Any]]
    report_markdown: str
    citation_report: dict[str, Any]
    followup_answer: str
