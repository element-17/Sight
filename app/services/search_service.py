"""
跨平台用户检索与候选账号归一化服务

抽离自 routes/graph_routes.py，供关系图谱与 LangGraph Agent 的跨平台搜人节点复用。
"""
from __future__ import annotations

import difflib
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.credentials import CredentialManager
from app.platforms import get_adapter
from app.services.social_expander import graph_user_node

# 关系图 / Agent 搜索缓存（30 分钟）
SEARCH_CACHE_TTL = 30 * 60
_search_cache: dict[tuple, tuple[float, list]] = {}
_search_cache_lock = threading.Lock()


def clear_search_cache(platform: str) -> int:
    """清理搜索缓存中指定平台的条目，返回清理条数。"""
    with _search_cache_lock:
        stale = [k for k in _search_cache if k[0] == platform]
        for k in stale:
            del _search_cache[k]
    return len(stale)


def norm_nickname(name: str) -> str:
    """昵称归一化：全角转半角、去空白、转小写，用于跨平台同人判定。"""
    s = unicodedata.normalize("NFKC", str(name or ""))
    return "".join(s.split()).lower()


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def search_user_cached(
    pid: str,
    keyword: str,
    limit: int = 10,
    force: bool = False,
) -> tuple[list, bool]:
    """带 30 分钟缓存的平台用户搜索（仅缓存成功且非空结果）。"""
    key = (pid, keyword, limit)
    now = time.time()
    if not force:
        with _search_cache_lock:
            hit = _search_cache.get(key)
            if hit and now - hit[0] < SEARCH_CACHE_TTL:
                return list(hit[1]), True

    adapter = get_adapter(pid)
    if not adapter:
        return [], False
    users = adapter.search_user(keyword, limit) or []
    if users:
        with _search_cache_lock:
            _search_cache[key] = (now, list(users))
    return users, False


def search_cross_platform(
    keyword: str,
    platform_ids: Optional[list[str]] = None,
    *,
    limit: int = 10,
    refresh: bool = False,
    keyword_overrides: Optional[dict[str, str]] = None,
) -> dict:
    """按关键词并行搜索各平台用户，返回标准化图谱节点/边与候选信息。"""
    keyword = (keyword or "").strip()
    if not keyword:
        raise ValueError("请输入搜索关键词")

    pids = (
        [p for p in platform_ids if p]
        if platform_ids
        else [p["id"] for p in CredentialManager.get_available_platforms()]
    )
    overrides = {
        str(k).strip(): str(v).strip()
        for k, v in (keyword_overrides or {}).items()
        if str(k).strip() in pids and str(v).strip()
    }

    def _search_one(pid: str):
        try:
            if not get_adapter(pid):
                return pid, [], None, False
            users, from_cache = search_user_cached(
                pid, overrides.get(pid) or keyword, limit, force=refresh
            )
            return pid, users, None, from_cache
        except Exception as e:
            return pid, [], f"[账号：主账号] {e}", False

    results: dict[str, list] = {}
    errors: dict[str, str] = {}
    cached_pids: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(pids)))) as pool:
        for pid, users, err, from_cache in pool.map(_search_one, pids):
            results[pid] = users
            if err:
                errors[pid] = err
            if from_cache:
                cached_pids.append(pid)

    nodes = [
        {
            "id": "keyword",
            "platform": "keyword",
            "uid": "",
            "nickname": keyword,
            "avatarUrl": "",
            "fans": 0,
            "signature": "搜索关键词",
        }
    ]
    edges: list[dict] = []
    norm_index: list[dict] = []

    for pid, users in results.items():
        for u in users:
            node = graph_user_node(pid, u)
            if node is None:
                continue
            nodes.append(node)
            edges.append({"source": "keyword", "target": node["id"], "relation": "hit"})
            norm_index.append(
                {"id": node["id"], "platform": pid, "norm": norm_nickname(node["nickname"])}
            )

    for i in range(len(norm_index)):
        for j in range(i + 1, len(norm_index)):
            a, b = norm_index[i], norm_index[j]
            if a["platform"] == b["platform"] or not a["norm"] or not b["norm"]:
                continue
            if a["norm"] == b["norm"]:
                edges.append({"source": a["id"], "target": b["id"], "relation": "same"})
            elif name_similarity(a["norm"], b["norm"]) >= 0.9:
                edges.append({"source": a["id"], "target": b["id"], "relation": "alike"})

    return {
        "keyword": keyword,
        "keywords": overrides,
        "searched": sorted(pids),
        "platforms": sorted(pid for pid, users in results.items() if users),
        "nodes": nodes,
        "edges": edges,
        "errors": errors,
        "cached": sorted(cached_pids),
    }


def rank_identity_candidates(search_result: dict, max_per_platform: int = 5) -> list[dict]:
    """
    从跨平台搜索结果中提炼排序后的候选账号列表，供 Agent 消歧与前端勾选确认使用。
    """
    keyword_norm = norm_nickname(search_result.get("keyword", ""))
    same_peers: dict[str, int] = {}
    for edge in search_result.get("edges", []):
        rel = edge.get("relation")
        if rel in ("same", "alike"):
            weight = 2 if rel == "same" else 1
            same_peers[edge["source"]] = same_peers.get(edge["source"], 0) + weight
            same_peers[edge["target"]] = same_peers.get(edge["target"], 0) + weight

    by_platform: dict[str, list[dict]] = {}
    for node in search_result.get("nodes", []):
        pid = node.get("platform")
        if not pid or pid == "keyword":
            continue
        nick = str(node.get("nickname") or "")
        n_norm = norm_nickname(nick)
        sim = 1.0 if (keyword_norm and n_norm == keyword_norm) else name_similarity(keyword_norm, n_norm)
        peer_score = same_peers.get(node.get("id", ""), 0)
        confidence = round(min(1.0, sim * 0.75 + min(peer_score, 4) * 0.0625), 3)
        by_platform.setdefault(pid, []).append(
            {
                "id": node.get("id", f"{pid}:{node.get('uid', '')}"),
                "platform": pid,
                "platform_name": CredentialManager._get_platform_name(pid),
                "uid": str(node.get("uid") or ""),
                "nickname": nick,
                "avatarUrl": node.get("avatarUrl") or "",
                "signature": str(node.get("signature") or "")[:160],
                "fans": node.get("fans") or 0,
                "verified": bool(node.get("verified")),
                "similarity": round(sim, 3),
                "cross_platform_hits": peer_score,
                "confidence": confidence,
                "recommended": confidence >= 0.75,
            }
        )

    candidates: list[dict] = []
    for pid, items in by_platform.items():
        items.sort(key=lambda x: (x["confidence"], x["similarity"], int(x["fans"] or 0)), reverse=True)
        for idx, item in enumerate(items[:max_per_platform]):
            # 每个平台默认只对最高分且达阈值的那一条自动打勾推荐
            item["recommended"] = idx == 0 and item["confidence"] >= 0.72
            candidates.append(item)

    candidates.sort(key=lambda x: (x["recommended"], x["confidence"]), reverse=True)
    return candidates
