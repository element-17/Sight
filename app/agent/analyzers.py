"""
确定性特征提取与统计分析器

将“时间戳算术、词频分布、社交图谱拓扑中心度”交给本地 Python 确定性计算，
既大幅减少 LLM Token 消耗，又能直接驱动前端 ECharts 可视化图表。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.credentials import _PLATFORM_NAMES

CST = timezone(timedelta(hours=8))
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _parse_timestamp_cst(raw: Any) -> Optional[datetime]:
    """兼容毫秒/秒级时间戳与 ISO / 常见日期字符串，统一转为 CST datetime。"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts <= 0:
            return None
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, CST)
            if 2005 <= dt.year <= 2035:
                return dt
        except (OSError, OverflowError, ValueError):
            return None
        return None

    s = str(raw).strip()
    if not s:
        return None
    if s.isdigit():
        return _parse_timestamp_cst(int(s))

    # ISO 8601 / 常见格式
    try:
        iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CST)
        else:
            dt = dt.astimezone(CST)
        if 2005 <= dt.year <= 2035:
            return dt
    except ValueError:
        pass

    for fmt in ("%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=CST)
            if 2005 <= dt.year <= 2035:
                return dt
        except ValueError:
            continue
    return None


def _classify_chronotype(hourly: list[int], total: int) -> str:
    if total < 3:
        return "样本不足"
    late_night = sum(hourly[0:5]) + hourly[23]
    morning = sum(hourly[6:12])
    afternoon = sum(hourly[12:18])
    evening = sum(hourly[18:23])
    if late_night / total >= 0.3:
        return "深夜活跃型（夜猫子）"
    if evening / total >= 0.4:
        return "晚间活跃型"
    if morning / total >= 0.35:
        return "早间活跃型"
    if afternoon / total >= 0.4:
        return "午后活跃型"
    return "全天均衡型"


def compute_activity_stats(
    platform_payloads: dict[str, dict[str, Any]],
    timeline_entries: Optional[list[dict[str, Any]]] = None,
    archive_events: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    从多平台动态、内容发布时间、时间线、B 站存档中统计 24h 作息分布、星期分布、
    各平台活跃占比、高频歌手/语言/兴趣关键词。
    """
    hourly = [0] * 24
    weekday_counts = [0] * 7
    platform_counts: Counter[str] = Counter()
    artists: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    locations: list[str] = []
    signatures: list[dict[str, str]] = []
    timestamps: list[datetime] = []

    def _record_time(pid: str, raw_ts: Any):
        dt = _parse_timestamp_cst(raw_ts)
        if not dt:
            return
        hourly[dt.hour] += 1
        weekday_counts[dt.weekday()] += 1
        platform_counts[pid] += 1
        timestamps.append(dt)

    for pid, payload in (platform_payloads or {}).items():
        if not isinstance(payload, dict):
            continue
        profile = payload.get("profile") or {}
        if isinstance(profile, dict):
            loc = str(profile.get("location") or "").strip()
            if loc:
                locations.append(f"{_PLATFORM_NAMES.get(pid, pid)}: {loc}")
            sig = str(profile.get("signature") or "").strip()
            if sig:
                signatures.append(
                    {
                        "platform": pid,
                        "platform_name": _PLATFORM_NAMES.get(pid, pid),
                        "nickname": str(profile.get("nickname") or ""),
                        "signature": sig[:160],
                    }
                )

        for ev in payload.get("events") or []:
            if isinstance(ev, dict):
                _record_time(pid, ev.get("timestamp"))

        for item in payload.get("playlists") or []:
            if not isinstance(item, dict):
                continue
            _record_time(pid, item.get("create_time"))
            extra = item.get("extra") or {}
            if isinstance(extra, dict):
                lang = str(extra.get("language") or "").strip()
                if lang:
                    languages[lang] += 1

        records = payload.get("records") or {}
        if isinstance(records, dict):
            for bucket in ("weekly", "allTime"):
                for entry in records.get(bucket) or []:
                    if not isinstance(entry, dict):
                        continue
                    artist = str(entry.get("artist_or_uploader") or "").strip()
                    if artist:
                        weight = max(1, int(entry.get("play_count") or 1))
                        # 对不同曲目做柔和加权，避免单曲刷屏吞没整体分布
                        artists[artist] += min(weight, 20)

    for row in timeline_entries or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("platform") or "timeline")
        ts = row.get("timestamp") or row.get("time_range_until") or row.get("time_str")
        _record_time(pid, ts)

    for ev in archive_events or []:
        if isinstance(ev, dict):
            _record_time("bilibili", ev.get("timestamp"))

    total_timed = sum(hourly)
    peak_hours: list[int] = []
    if total_timed > 0:
        max_h = max(hourly)
        peak_hours = [h for h, c in enumerate(hourly) if c >= max(1, int(max_h * 0.7))][:4]

    late_night_count = sum(hourly[0:5]) + hourly[23]
    late_night_ratio = round(late_night_count / total_timed, 3) if total_timed else 0.0

    earliest = min(timestamps).strftime("%Y-%m-%d") if timestamps else ""
    latest = max(timestamps).strftime("%Y-%m-%d") if timestamps else ""

    return {
        "total_timed_events": total_timed,
        "hourly_distribution": hourly,
        "weekday_distribution": [
            {"day": WEEKDAY_LABELS[i], "count": weekday_counts[i]} for i in range(7)
        ],
        "peak_hours": peak_hours,
        "late_night_ratio": late_night_ratio,
        "chronotype": _classify_chronotype(hourly, total_timed),
        "timezone_hint": "CST (UTC+8)",
        "date_span": {"earliest": earliest, "latest": latest},
        "platform_activity": [
            {
                "platform": pid,
                "platform_name": _PLATFORM_NAMES.get(pid, pid),
                "count": cnt,
            }
            for pid, cnt in platform_counts.most_common()
        ],
        "top_artists": [{"name": name, "score": score} for name, score in artists.most_common(12)],
        "top_languages": [{"name": name, "count": cnt} for name, cnt in languages.most_common(10)],
        "locations": locations,
        "signatures": signatures,
    }


def analyze_social_network(
    graph_data: Optional[dict[str, Any]] = None,
    platform_payloads: Optional[dict[str, dict[str, Any]]] = None,
    target_accounts: Optional[dict[str, str]] = None,
    *,
    celebrity_fans_threshold: int = 50000,
    max_contacts: int = 20,
) -> dict[str, Any]:
    """
    对关系图谱（或各平台已拉取的 follows / followers）做确定性拓扑分析：
    - 识别互关关系（高亲密度密友候选）
    - 过滤认证大 V 与高粉公众账号，避免把明星/UP主误判为现实熟人
    - 提取跨平台 same/alike 同人边
    """
    nodes_by_id: dict[str, dict[str, Any]] = {}
    follow_edges: set[tuple[str, str]] = set()
    same_edges: list[dict[str, str]] = []

    if isinstance(graph_data, dict):
        for n in graph_data.get("nodes") or []:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id") or "")
            if not nid or n.get("platform") == "keyword":
                continue
            nodes_by_id[nid] = n
        for e in graph_data.get("edges") or []:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or "")
            dst = str(e.get("target") or "")
            rel = str(e.get("relation") or "")
            if rel == "follows" and src and dst:
                follow_edges.add((src, dst))
            elif rel in ("same", "alike") and src and dst:
                same_edges.append({"source": src, "target": dst, "relation": rel})

    # 补充来自单平台 payload 的关注/粉丝边
    for pid, payload in (platform_payloads or {}).items():
        if not isinstance(payload, dict):
            continue
        uid = str(payload.get("uid") or (target_accounts or {}).get(pid) or "").strip()
        if not uid:
            continue
        target_id = f"{pid}:{uid}"
        profile = payload.get("profile") or {}
        if target_id not in nodes_by_id:
            nodes_by_id[target_id] = {
                "id": target_id,
                "platform": pid,
                "uid": uid,
                "nickname": str(profile.get("nickname") or uid),
                "fans": 0,
            }
        for u in payload.get("follows") or []:
            if not isinstance(u, dict) or not u.get("uid"):
                continue
            nid = f"{pid}:{u['uid']}"
            nodes_by_id.setdefault(
                nid,
                {
                    "id": nid,
                    "platform": pid,
                    "uid": str(u["uid"]),
                    "nickname": str(u.get("nickname") or u["uid"]),
                    "fans": u.get("fans") or 0,
                    "verified": bool(u.get("is_verified") or u.get("verified")),
                    "signature": str(u.get("signature") or ""),
                },
            )
            follow_edges.add((target_id, nid))
        for u in payload.get("followers") or []:
            if not isinstance(u, dict) or not u.get("uid"):
                continue
            nid = f"{pid}:{u['uid']}"
            nodes_by_id.setdefault(
                nid,
                {
                    "id": nid,
                    "platform": pid,
                    "uid": str(u["uid"]),
                    "nickname": str(u.get("nickname") or u["uid"]),
                    "fans": u.get("fans") or 0,
                    "verified": bool(u.get("is_verified") or u.get("verified")),
                    "signature": str(u.get("signature") or ""),
                },
            )
            follow_edges.add((nid, target_id))

    target_ids = {
        f"{pid}:{uid}" for pid, uid in (target_accounts or {}).items() if pid and uid
    }

    in_deg: Counter[str] = Counter()
    out_deg: Counter[str] = Counter()
    for src, dst in follow_edges:
        out_deg[src] += 1
        in_deg[dst] += 1

    mutual_contacts: list[dict[str, Any]] = []
    followed_celebrities: list[dict[str, Any]] = []
    other_contacts: list[dict[str, Any]] = []

    def _safe_fans(node: dict[str, Any]) -> int:
        try:
            return int(node.get("fans") or 0)
        except (TypeError, ValueError):
            return 0

    for nid, node in nodes_by_id.items():
        if nid in target_ids:
            continue
        fans = _safe_fans(node)
        verified = bool(node.get("verified") or node.get("is_verified"))
        is_celeb = verified or fans >= celebrity_fans_threshold

        # 检查是否与任一目标账号互关或单向关注
        is_mutual = any(
            (tid, nid) in follow_edges and (nid, tid) in follow_edges for tid in target_ids
        )
        is_followed = any((tid, nid) in follow_edges for tid in target_ids)
        is_follower = any((nid, tid) in follow_edges for tid in target_ids)

        summary = {
            "id": nid,
            "platform": node.get("platform", ""),
            "platform_name": _PLATFORM_NAMES.get(str(node.get("platform", "")), str(node.get("platform", ""))),
            "uid": str(node.get("uid") or ""),
            "nickname": str(node.get("nickname") or ""),
            "fans": fans,
            "verified": verified,
            "signature": str(node.get("signature") or "")[:100],
            "degree": in_deg[nid] + out_deg[nid],
            "relation": (
                "mutual"
                if is_mutual
                else ("following" if is_followed else ("follower" if is_follower else "indirect"))
            ),
        }

        if is_mutual and not is_celeb:
            mutual_contacts.append(summary)
        elif is_followed and is_celeb:
            followed_celebrities.append(summary)
        elif is_followed or is_follower or summary["degree"] >= 2:
            other_contacts.append(summary)

    mutual_contacts.sort(key=lambda x: (x["degree"], -x["fans"]), reverse=True)
    followed_celebrities.sort(key=lambda x: x["fans"], reverse=True)
    other_contacts.sort(key=lambda x: (x["relation"] == "mutual", x["degree"]), reverse=True)

    cross_platform_links: list[dict[str, str]] = []
    for e in same_edges[:25]:
        a = nodes_by_id.get(e["source"], {})
        b = nodes_by_id.get(e["target"], {})
        cross_platform_links.append(
            {
                "relation": e["relation"],
                "a": f"{a.get('platform', '')}:{a.get('nickname', e['source'])}",
                "b": f"{b.get('platform', '')}:{b.get('nickname', e['target'])}",
            }
        )

    return {
        "total_nodes": len(nodes_by_id),
        "total_follow_edges": len(follow_edges),
        "mutual_core_contacts": mutual_contacts[:max_contacts],
        "followed_public_accounts": followed_celebrities[:15],
        "notable_neighbors": other_contacts[:15],
        "cross_platform_links": cross_platform_links,
    }


def extract_citation_ids(markdown: str) -> list[str]:
    """提取 Markdown 文本中所有形如 [E1] 或 [E1, E2] 的证据引用编号。"""
    found: list[str] = []
    seen: set[str] = set()
    for block in re.findall(r"\[([E\d,\s]+)\]", markdown or ""):
        for eid in re.findall(r"E\d+", block):
            if eid not in seen:
                seen.add(eid)
                found.append(eid)
    return found
