"""
Agent 驱动的智能剪枝社交图谱探索与拓扑评分引擎

解决传统图谱「按接口顺序盲目展开、大 V/公众账号噪音淹没真实关联圈」的痛点：
1. 规则剪枝（Pruning）：在 2-hop 展开前先过滤认证大 V、高粉公众账号与机构/资讯号，并记录可解释的剪枝理由；
2. 多信号评分（Prioritization）：结合双向互关、三角闭合（邻居互连）、公开动态 @ 提及、
   LLM 推理线索词（同城/高校/兴趣/社群）与跨平台相似网名，排出最值得深挖的候选节点；
3. 受控 2-hop 定向互查：只对剪枝后的 Top-K 高价值候选执行 `expand_social` 互查，以极低配额发现共同关联圈；
4. 图谱沉淀：直接导出兼容 Sight 前端 ECharts 关系图谱的精简子图并可一键保存到 SQLite `saved_graphs`。
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Optional

from app.credentials import _PLATFORM_NAMES

_INSTITUTIONAL_KEYWORDS = (
    "官方",
    "官博",
    "官微",
    "旗舰店",
    "客服",
    "后援会",
    "资讯",
    "新闻",
    "日报",
    "晚报",
    "电视台",
    "出版社",
    "工作室",
    "官方号",
    "电台",
    "频道",
    "bot",
)

_MENTION_RE = re.compile(r"@([\w\u4e00-\u9fff\-_.]{2,24})")


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return default


def _norm_handle(name: str) -> str:
    return re.sub(r"[\s_\-.·]+", "", str(name or "").strip().lower())


def _is_institutional_name(nickname: str, signature: str = "") -> bool:
    n = str(nickname or "").strip().lower()
    if not n:
        return False
    for kw in _INSTITUTIONAL_KEYWORDS:
        if kw in n:
            return True
    s = str(signature or "").strip().lower()
    if any(k in s for k in ("官方账号", "官方微博", "唯一官方", "商务合作请联系官方")):
        return True
    return False


def extract_public_mentions(platform_payloads: dict[str, dict[str, Any]]) -> list[str]:
    """从目标自己的公开动态文本中提取高频 @ 提及昵称（纯公开交互信号）。"""
    counter: Counter[str] = Counter()
    for payload in (platform_payloads or {}).values():
        if not isinstance(payload, dict):
            continue
        for ev in payload.get("events") or []:
            if not isinstance(ev, dict):
                continue
            text = str(ev.get("content") or "")
            for m in _MENTION_RE.findall(text):
                clean = m.strip()
                if len(clean) >= 2:
                    counter[clean] += 1
    return [name for name, _ in counter.most_common(30)]


def empty_social_workspace() -> dict[str, Any]:
    return {
        "nodes": {},
        "edges": [],
        "target_ids": [],
        "mentions": [],
        "pruned": {},
        "probed_ids": [],
        "saved_graph_id": None,
        "saved_graph_name": "",
    }


def merge_social_workspace(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    """LangGraph State reducer：幂等增量合并 Agent 探索过程中的剪枝子图工作区。"""
    base = empty_social_workspace()
    nodes: dict[str, dict[str, Any]] = {}
    edge_map: dict[tuple[str, str, str], dict[str, str]] = {}
    target_ids: list[str] = []
    target_seen: set[str] = set()
    mentions: list[str] = []
    mention_seen: set[str] = set()
    pruned: dict[str, str] = {}
    probed: list[str] = []
    probed_seen: set[str] = set()
    saved_gid = None
    saved_gname = ""

    for ws in (left, right):
        if not isinstance(ws, dict):
            continue
        raw_nodes = ws.get("nodes") or {}
        if isinstance(raw_nodes, list):
            raw_nodes = {str(n.get("id") or ""): n for n in raw_nodes if isinstance(n, dict) and n.get("id")}
        for nid, n in raw_nodes.items():
            if not nid or not isinstance(n, dict) or n.get("platform") == "keyword":
                continue
            prev = dict(nodes.get(nid) or {})
            merged_n = {**prev, **{k: v for k, v in n.items() if v not in (None, "")}}
            # 保留较大粉丝数与已确认的认证标记
            merged_n["fans"] = max(_safe_int(prev.get("fans")), _safe_int(n.get("fans")))
            merged_n["verified"] = bool(prev.get("verified") or n.get("verified") or n.get("is_verified"))
            merged_n["id"] = nid
            nodes[nid] = merged_n

        for e in ws.get("edges") or []:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or "").strip()
            dst = str(e.get("target") or "").strip()
            rel = str(e.get("relation") or "follows").strip()
            if src and dst and src != dst:
                edge_map[(src, dst, rel)] = {"source": src, "target": dst, "relation": rel}

        for tid in ws.get("target_ids") or []:
            s = str(tid).strip()
            if s and s not in target_seen:
                target_seen.add(s)
                target_ids.append(s)

        for m in ws.get("mentions") or []:
            s = str(m).strip()
            if s and s not in mention_seen:
                mention_seen.add(s)
                mentions.append(s)

        for nid, reason in (ws.get("pruned") or {}).items():
            if nid and reason:
                pruned[str(nid)] = str(reason)

        for pid_uid in ws.get("probed_ids") or []:
            s = str(pid_uid).strip()
            if s and s not in probed_seen:
                probed_seen.add(s)
                probed.append(s)

        if ws.get("saved_graph_id") is not None:
            saved_gid = ws["saved_graph_id"]
        if ws.get("saved_graph_name"):
            saved_gname = str(ws["saved_graph_name"])

    base["nodes"] = nodes
    base["edges"] = list(edge_map.values())
    base["target_ids"] = target_ids
    base["mentions"] = mentions[:40]
    base["pruned"] = pruned
    base["probed_ids"] = probed
    base["saved_graph_id"] = saved_gid
    base["saved_graph_name"] = saved_gname
    return base


def seed_social_workspace(
    target_accounts: dict[str, str],
    raw_payloads: dict[str, dict[str, Any]],
    graph_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """从基线采集结果与可选关联图谱初始化 Agent 社交图谱工作区。"""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    target_ids: list[str] = []

    if isinstance(graph_data, dict):
        for n in graph_data.get("nodes") or []:
            if not isinstance(n, dict) or n.get("platform") == "keyword":
                continue
            nid = str(n.get("id") or "").strip()
            if nid:
                nodes[nid] = {
                    "id": nid,
                    "platform": str(n.get("platform") or ""),
                    "uid": str(n.get("uid") or ""),
                    "nickname": str(n.get("nickname") or n.get("uid") or ""),
                    "avatarUrl": str(n.get("avatarUrl") or ""),
                    "fans": _safe_int(n.get("fans")),
                    "verified": bool(n.get("verified") or n.get("is_verified")),
                    "signature": str(n.get("signature") or "")[:160],
                }
        for e in graph_data.get("edges") or []:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or "")
            dst = str(e.get("target") or "")
            rel = str(e.get("relation") or "")
            if src and dst and rel in ("follows", "same", "alike") and src != "keyword" and dst != "keyword":
                edges.append({"source": src, "target": dst, "relation": rel})

    for pid, uid in (target_accounts or {}).items():
        if not pid or not uid:
            continue
        tid = f"{pid}:{uid}"
        target_ids.append(tid)
        payload = (raw_payloads or {}).get(pid) or {}
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        nodes[tid] = {
            "id": tid,
            "platform": pid,
            "uid": uid,
            "nickname": str(profile.get("nickname") or uid),
            "avatarUrl": str(profile.get("avatar_url") or ""),
            "fans": _safe_int(
                (profile.get("extra") or {}).get("follower_count")
                or (profile.get("extra") or {}).get("followeds")
                or (profile.get("extra") or {}).get("fans_count")
                or (profile.get("extra") or {}).get("followers")
                or 0
            ),
            "verified": False,
            "signature": str(profile.get("signature") or "")[:160],
            "is_target": True,
        }
        for u in payload.get("follows") or []:
            if not isinstance(u, dict) or not u.get("uid"):
                continue
            nid = f"{pid}:{u['uid']}"
            nodes.setdefault(
                nid,
                {
                    "id": nid,
                    "platform": pid,
                    "uid": str(u["uid"]),
                    "nickname": str(u.get("nickname") or u["uid"]),
                    "avatarUrl": str(u.get("avatarUrl") or u.get("avatar_url") or ""),
                    "fans": _safe_int(u.get("fans")),
                    "verified": bool(u.get("is_verified") or u.get("verified")),
                    "signature": str(u.get("signature") or "")[:160],
                },
            )
            edges.append({"source": tid, "target": nid, "relation": "follows"})
        for u in payload.get("followers") or []:
            if not isinstance(u, dict) or not u.get("uid"):
                continue
            nid = f"{pid}:{u['uid']}"
            nodes.setdefault(
                nid,
                {
                    "id": nid,
                    "platform": pid,
                    "uid": str(u["uid"]),
                    "nickname": str(u.get("nickname") or u["uid"]),
                    "avatarUrl": str(u.get("avatarUrl") or u.get("avatar_url") or ""),
                    "fans": _safe_int(u.get("fans")),
                    "verified": bool(u.get("is_verified") or u.get("verified")),
                    "signature": str(u.get("signature") or "")[:160],
                },
            )
            edges.append({"source": nid, "target": tid, "relation": "follows"})

    # 跨平台目标节点之间补上 same 边，便于在图谱中一眼看清跨平台同一实体
    for i in range(len(target_ids)):
        for j in range(i + 1, len(target_ids)):
            edges.append({"source": target_ids[i], "target": target_ids[j], "relation": "same"})

    return merge_social_workspace(
        None,
        {
            "nodes": nodes,
            "edges": edges,
            "target_ids": target_ids,
            "mentions": extract_public_mentions(raw_payloads),
        },
    )


def score_and_prune_candidates(
    workspace: dict[str, Any],
    *,
    platform_filter: str = "",
    focus_keywords: Optional[list[str]] = None,
    celebrity_fans_threshold: int = 20000,
    include_verified: bool = False,
    top_k: int = 25,
) -> dict[str, Any]:
    """
    对当前社交图谱工作区执行确定性剪枝与多信号关联度打分。

    返回:
      - core_circle: 高置信关联圈（互关 / 三角闭合 / 高分候选）
      - priority_candidates: 剪枝后 Top-K 候选（含分数与可解释理由）
      - recommended_intercheck_uids: 推荐进行 2-hop 邻居互查的未探测 UID 列表
      - pruned_map: {node_id: prune_reason}
      - pruned_summary: 剪枝统计摘要
      - triangle_edges_count: 邻居之间的三角闭合互连边数量
    """
    nodes: dict[str, dict[str, Any]] = workspace.get("nodes") or {}
    edges: list[dict[str, str]] = workspace.get("edges") or []
    target_ids = set(workspace.get("target_ids") or [])
    probed_ids = set(workspace.get("probed_ids") or [])
    mentions_norm = {_norm_handle(m) for m in (workspace.get("mentions") or []) if _norm_handle(m)}
    kw_list = [str(k).strip().lower() for k in (focus_keywords or []) if str(k).strip()]

    follow_edges: set[tuple[str, str]] = set()
    same_neighbors: Counter[str] = Counter()
    for e in edges:
        src = str(e.get("source") or "")
        dst = str(e.get("target") or "")
        rel = str(e.get("relation") or "")
        if rel == "follows":
            follow_edges.add((src, dst))
        elif rel in ("same", "alike"):
            same_neighbors[src] += 1
            same_neighbors[dst] += 1

    # 识别目标 1-hop 邻居集合与邻居间三角闭合边
    direct_neighbors: set[str] = set()
    for src, dst in follow_edges:
        if src in target_ids and dst not in target_ids:
            direct_neighbors.add(dst)
        elif dst in target_ids and src not in target_ids:
            direct_neighbors.add(src)

    triangle_links: Counter[str] = Counter()
    triangle_edge_pairs: set[tuple[str, str]] = set()
    for src, dst in follow_edges:
        if src in target_ids or dst in target_ids:
            continue
        if src in direct_neighbors or dst in direct_neighbors:
            pair = (min(src, dst), max(src, dst))
            if pair not in triangle_edge_pairs:
                triangle_edge_pairs.add(pair)
                triangle_links[src] += 1
                triangle_links[dst] += 1

    # 跨平台相似网名索引（排除目标自身）
    norm_to_platforms: dict[str, set[str]] = {}
    for nid, n in nodes.items():
        if nid in target_ids:
            continue
        nh = _norm_handle(n.get("nickname") or "")
        if len(nh) >= 3:
            norm_to_platforms.setdefault(nh, set()).add(str(n.get("platform") or ""))

    pruned_map: dict[str, str] = {}
    pruned_by_reason: Counter[str] = Counter()
    pruned_samples: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for nid, node in nodes.items():
        if nid in target_ids:
            continue
        pid = str(node.get("platform") or "")
        if platform_filter and pid != platform_filter:
            continue

        uid = str(node.get("uid") or "")
        nickname = str(node.get("nickname") or uid)
        signature = str(node.get("signature") or "")
        fans = _safe_int(node.get("fans"))
        verified = bool(node.get("verified") or node.get("is_verified"))

        is_mutual = any((tid, nid) in follow_edges and (nid, tid) in follow_edges for tid in target_ids)
        is_following = any((tid, nid) in follow_edges for tid in target_ids)
        is_follower = any((nid, tid) in follow_edges for tid in target_ids)
        tri = triangle_links[nid]

        # ---- 剪枝规则（先剔除明显大 V 与机构号，但保留被目标公开互关且非超大号的例外） ----
        prune_reason = ""
        if verified and not include_verified and not (is_mutual and fans < celebrity_fans_threshold):
            prune_reason = "官方认证/公众账号"
        elif fans >= celebrity_fans_threshold:
            prune_reason = f"高粉公众账号 (≥{celebrity_fans_threshold} 粉)"
        elif not is_mutual and tri == 0 and _is_institutional_name(nickname, signature):
            prune_reason = "机构/资讯/官方号"

        if prune_reason:
            pruned_map[nid] = prune_reason
            pruned_by_reason[prune_reason] += 1
            if len(pruned_samples) < 10:
                pruned_samples.append(
                    {
                        "id": nid,
                        "platform": pid,
                        "nickname": nickname,
                        "fans": fans,
                        "reason": prune_reason,
                    }
                )
            continue

        # ---- 多信号可解释评分 ----
        score = 0.10
        reasons: list[str] = []

        if is_mutual:
            score += 0.42
            reasons.append("与目标双向互关")
        elif is_follower:
            score += 0.14
            reasons.append("主动关注目标")
        elif is_following:
            score += 0.08
            reasons.append("目标单向关注")

        if tri > 0:
            score += min(0.30, 0.12 * tri)
            reasons.append(f"圈内三角闭合 ×{tri}")

        nh = _norm_handle(nickname)
        if nh and nh in mentions_norm:
            score += 0.22
            reasons.append("目标公开动态 @ 互动提及")

        if nh and len(norm_to_platforms.get(nh, set())) >= 2:
            score += 0.15
            reasons.append("跨平台同名节点重合")
        elif same_neighbors[nid] > 0:
            score += 0.12
            reasons.append("存在跨平台关联边")

        if kw_list:
            haystack = f"{nickname} {signature}".lower()
            matched_kws = [k for k in kw_list if k in haystack][:3]
            if matched_kws:
                score += 0.16
                reasons.append("命中线索词: " + "/".join(matched_kws))

        if 0 < fans <= 2000:
            score += 0.12
            reasons.append(f"普通用户粉丝量级 ({fans})")
        elif 2000 < fans < celebrity_fans_threshold:
            score += 0.05

        score = round(min(score, 0.99), 2)
        relation = (
            "mutual"
            if is_mutual
            else ("follower" if is_follower else ("following" if is_following else "2hop"))
        )

        candidates.append(
            {
                "id": nid,
                "platform": pid,
                "platform_name": _PLATFORM_NAMES.get(pid, pid),
                "uid": uid,
                "nickname": nickname,
                "fans": fans,
                "verified": verified,
                "signature": signature[:100],
                "relation": relation,
                "triangle_links": tri,
                "probed": nid in probed_ids,
                "score": score,
                "reasons": reasons,
            }
        )

    candidates.sort(
        key=lambda x: (x["score"], x["relation"] == "mutual", x["triangle_links"], -x["fans"]),
        reverse=True,
    )

    core_circle = [
        c
        for c in candidates
        if c["score"] >= 0.45 or c["relation"] == "mutual" or c["triangle_links"] >= 1
    ][:15]

    recommended_intercheck_uids = [
        c["uid"]
        for c in candidates
        if not c["probed"] and c["uid"]
    ][:12]

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "triangle_edges_count": len(triangle_edge_pairs),
        "core_circle": core_circle,
        "priority_candidates": candidates[:top_k],
        "recommended_intercheck_uids": recommended_intercheck_uids,
        "pruned_map": pruned_map,
        "pruned_summary": {
            "total_pruned": len(pruned_map),
            "by_reason": dict(pruned_by_reason),
            "samples": pruned_samples,
        },
    }


def build_exportable_graph_data(
    workspace: dict[str, Any],
    *,
    keyword: str = "",
    scored: Optional[dict[str, Any]] = None,
    max_nodes: int = 120,
) -> dict[str, Any]:
    """
    将剪枝后的 Agent 关系子图导出为兼容 Sight 前端 ECharts 关系图谱的 SavedGraph data 结构。
    保留所有目标节点 + Top 非剪枝高分节点 + 它们之间的全部关系边。
    """
    nodes_map: dict[str, dict[str, Any]] = workspace.get("nodes") or {}
    edges: list[dict[str, str]] = workspace.get("edges") or []
    target_ids = list(workspace.get("target_ids") or [])

    if scored is None:
        scored = score_and_prune_candidates(workspace, top_k=max_nodes)

    keep_ids: list[str] = []
    keep_set: set[str] = set()
    for tid in target_ids:
        if tid in nodes_map and tid not in keep_set:
            keep_set.add(tid)
            keep_ids.append(tid)

    for cand in scored.get("priority_candidates") or []:
        nid = cand["id"]
        if nid in nodes_map and nid not in keep_set and len(keep_ids) < max_nodes:
            keep_set.add(nid)
            keep_ids.append(nid)

    export_nodes: list[dict[str, Any]] = []
    platforms_seen: list[str] = []
    for nid in keep_ids:
        n = dict(nodes_map[nid])
        pid = str(n.get("platform") or "")
        if pid and pid not in platforms_seen:
            platforms_seen.append(pid)
        export_nodes.append(n)

    export_edges = [
        e
        for e in edges
        if str(e.get("source") or "") in keep_set and str(e.get("target") or "") in keep_set
    ]

    return {
        "keyword": keyword or "AI剪枝关系子图",
        "platforms": platforms_seen,
        "searched": platforms_seen,
        "nodes": export_nodes,
        "edges": export_edges,
        "errors": {},
        "cached": [],
        "pruned_summary": scored.get("pruned_summary") or {},
    }


def similar_nickname_ratio(a: str, b: str) -> float:
    na = _norm_handle(a)
    nb = _norm_handle(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return round(SequenceMatcher(None, na, nb).ratio(), 2)
