"""
LangGraph Agent 工具注册表与统一错误/证据边界。

所有工具直接调用 Sight Service 层（零 HTTP 回环），具备：
1. 严格输出压缩与截断，避免上下文爆炸；
2. 统一错误分类（auth_expired / rate_limit / privacy / not_found / unknown），
   向 LLM 暴露真实原因并写入信息盲区；
3. 自动抽取可编号的证据条目（E1, E2...），供侧写报告与追问直接引用。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.tools import tool

from app.agent.analyzers import analyze_social_network
from app.agent.llm_config import PROVIDER_GEMINI, load_effective_config
from app.agent.multimodal import analyze_images, analyze_video
from app.agent.state import next_evidence_id, wrap_untrusted_data
from app.credentials import CredentialManager, _PLATFORM_NAMES
from app.data.store import DataStore
from app.platforms import get_adapter, list_platforms
from app.services.bilibili_archives import archives as bilibili_archives_svc
from app.services.media_fetcher import MAX_VIDEO_BYTES, CachedMedia, download_media
from app.services.platform_fetcher import (
    AllModulesFailedError,
    AuthExpiredError,
    fetch_content_detail,
    fetch_platform_all,
    find_latest_real_snapshot,
    is_auth_expired_error,
)
from app.services.search_service import rank_identity_candidates, search_cross_platform
from app.services.social_expander import expand_social
from app.services.timeline import TimelineBuilder

PLATFORM_CAPABILITIES: dict[str, dict[str, bool]] = {
    "netease": {"content_detail": True, "history": True, "events": True, "social": True, "archives": False, "images": True, "video": False},
    "bilibili": {"content_detail": True, "history": False, "events": True, "social": True, "archives": True, "images": True, "video": True},
    "douyin": {"content_detail": True, "history": False, "events": True, "social": True, "archives": False, "images": True, "video": True},
    "qqmusic": {"content_detail": True, "history": False, "events": True, "social": True, "archives": False, "images": True, "video": False},
    "weibo": {"content_detail": False, "history": False, "events": True, "social": True, "archives": False, "images": True, "video": True},
    "genshin": {"content_detail": False, "history": False, "events": False, "social": False, "archives": False, "images": True, "video": False},
    "xhs": {"content_detail": True, "history": False, "events": True, "social": False, "archives": False, "images": True, "video": True},
    "github": {"content_detail": True, "history": False, "events": True, "social": True, "archives": False, "images": True, "video": False},
}


@dataclass
class ToolExecResult:
    ok: bool
    summary_text: str
    data: Any = None
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    media_catalog_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    error_kind: str = ""
    error: str = ""


def classify_error(msg: str) -> str:
    s = str(msg or "")
    if is_auth_expired_error(s) or "401" in s:
        return "auth_expired"
    if any(k in s for k in ("限流", "频率", "-799", "速率限制", "429", "风控")):
        return "rate_limit"
    if any(k in s for k in ("隐私", "受限", "2096", "无权限", "未公开")):
        return "privacy_restricted"
    if any(k in s for k in ("不存在", "404", "未知平台")):
        return "not_found"
    return "unknown"


def _compact_profile(profile: Optional[dict]) -> Optional[dict]:
    if not isinstance(profile, dict):
        return None
    extra = profile.get("extra") if isinstance(profile.get("extra"), dict) else {}
    keep_extra = {
        k: v
        for k, v in extra.items()
        if k
        in (
            "followeds",
            "follows",
            "listenSongs",
            "createdPlaylistCount",
            "official",
            "follower_count",
            "following_count",
            "video_count",
            "likes",
            "unique_id",
            "aweme_count",
            "total_favorited",
            "fan_count",
            "follow_count",
            "fans_count",
            "weibo_count",
            "server_name",
            "world_level",
            "achievements",
            "abyss_floor",
            "abyss_room",
            "red_id",
            "fans",
            "interaction",
            "notes_count",
            "login",
            "followers",
            "following",
            "public_repos",
            "company",
            "blog",
        )
        and v not in (None, "", 0)
    }
    return {
        "platform": profile.get("platform"),
        "uid": profile.get("uid"),
        "nickname": profile.get("nickname"),
        "signature": str(profile.get("signature") or "")[:240],
        "gender": profile.get("gender"),
        "birthday": profile.get("birthday") or "",
        "location": profile.get("location") or "",
        "join_time": profile.get("join_time") or "",
        "level": profile.get("level"),
        "vip_label": profile.get("vip_label") or "",
        "has_avatar": bool(profile.get("avatar_url")),
        "has_background": bool(profile.get("background_url")),
        "extra": keep_extra,
    }


def _dedupe_urls(urls: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, (list, tuple)):
        return out
    for u in urls:
        s = str(u or "").strip()
        if s.startswith("//"):
            s = "https:" + s
        if not s or not (s.startswith("http://") or s.startswith("https://")) or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def extract_media_catalog(
    platform: str,
    uid: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """从单平台原始抓取结果中提取供多模态工具消费的媒体索引（避免向 LLM 暴露冗长签名外链）。"""
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    avatar_list = _dedupe_urls(profile.get("avatar_url") or "")
    bg_list = _dedupe_urls(profile.get("background_url") or "")

    items_map: dict[str, dict[str, Any]] = {}
    for it in (payload.get("playlists") or [])[:40]:
        if not isinstance(it, dict):
            continue
        item_id = str(it.get("item_id") or "").strip()
        if not item_id:
            continue
        extra = it.get("extra") if isinstance(it.get("extra"), dict) else {}
        images = _dedupe_urls(extra.get("images") or extra.get("pics") or [])
        cover = _dedupe_urls(it.get("cover_url") or extra.get("cover_url") or "")
        video_urls = _dedupe_urls(extra.get("video_urls") or [])
        single_vid = _dedupe_urls(extra.get("video_url") or "")
        for v in single_vid:
            if v not in video_urls:
                video_urls.insert(0, v)
        bvid = str(extra.get("bvid") or "").strip()
        media_type = str(extra.get("media_type") or "").strip()
        if not media_type:
            if video_urls or platform == "bilibili":
                media_type = "video"
            elif images:
                media_type = "image"

        items_map[item_id] = {
            "item_id": item_id,
            "title": str(it.get("title") or "")[:120],
            "cover_url": cover[0] if cover else "",
            "images": images[:12],
            "video_url": video_urls[0] if video_urls else "",
            "video_urls": video_urls[:6],
            "media_type": media_type,
            "bvid": bvid,
            "xsec_token": str(extra.get("xsec_token") or ""),
            "url": str(it.get("url") or ""),
        }

    events_list: list[dict[str, Any]] = []
    for idx, ev in enumerate(payload.get("events") or []):
        if idx >= 30 or not isinstance(ev, dict):
            continue
        extra = ev.get("extra") if isinstance(ev.get("extra"), dict) else {}
        pics = _dedupe_urls(extra.get("pics") or extra.get("images") or [])
        cover = _dedupe_urls(extra.get("cover_url") or "")
        video_urls = _dedupe_urls(extra.get("video_urls") or [])
        for v in _dedupe_urls(extra.get("video_url") or ""):
            if v not in video_urls:
                video_urls.insert(0, v)
        bvid = str(extra.get("bvid") or "").strip()
        if not (pics or cover or video_urls or bvid):
            continue
        events_list.append(
            {
                "event_id": str(ev.get("event_id") or f"ev_{idx}"),
                "content": str(ev.get("content") or ev.get("media_title") or "")[:100],
                "pics": pics[:12],
                "cover_url": cover[0] if cover else "",
                "video_url": video_urls[0] if video_urls else "",
                "video_urls": video_urls[:6],
                "bvid": bvid,
                "media_type": str(extra.get("media_type") or ("video" if video_urls or bvid else "image")),
                "url": str(ev.get("url") or ""),
            }
        )

    return {
        "platform": platform,
        "uid": uid,
        "nickname": str(profile.get("nickname") or uid),
        "avatar_url": avatar_list[0] if avatar_list else "",
        "background_url": bg_list[0] if bg_list else "",
        "items": items_map,
        "events": events_list,
    }


def summarize_platform_payload(
    platform: str,
    uid: str,
    payload: dict[str, Any],
    errors: Optional[list[str]] = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    将单平台完整数据压缩为高信噪比摘要，并提取结构化证据条目列表（未编号）。
    """
    pname = _PLATFORM_NAMES.get(platform, platform)
    profile = _compact_profile(payload.get("profile"))

    playlists = payload.get("playlists") or []
    compact_items = []
    for it in playlists[:20]:
        if not isinstance(it, dict):
            continue
        extra = it.get("extra") if isinstance(it.get("extra"), dict) else {}
        images = _dedupe_urls(extra.get("images") or extra.get("pics") or [])
        has_video = bool(
            extra.get("video_url")
            or extra.get("video_urls")
            or str(extra.get("media_type") or "").lower() == "video"
            or platform == "bilibili"
        )
        media_type = str(extra.get("media_type") or ("video" if has_video else ("image" if images else "")))
        row: dict[str, Any] = {
            "item_id": str(it.get("item_id") or ""),
            "title": str(it.get("title") or "")[:120],
            "is_owner": bool(it.get("is_owner", True)),
            "count": it.get("count") or 0,
            "view_count": it.get("view_count") or 0,
            "description": str(it.get("description") or "")[:120],
            "create_time": it.get("create_time") or "",
            "url": it.get("url") or "",
            "language": extra.get("language") or "",
            "element": extra.get("element") or "",
            "level": extra.get("level") or "",
        }
        if media_type:
            row["media_type"] = media_type
        if images:
            row["image_count"] = len(images)
        elif it.get("cover_url") and platform in ("xhs", "douyin", "weibo", "bilibili"):
            row["has_cover"] = True
        if has_video:
            row["has_video"] = True
        if extra.get("bvid"):
            row["bvid"] = str(extra["bvid"])
        compact_items.append(row)

    events = payload.get("events") or []
    compact_events = []
    for ev in events[:20]:
        if not isinstance(ev, dict):
            continue
        extra = ev.get("extra") if isinstance(ev.get("extra"), dict) else {}
        pics = _dedupe_urls(extra.get("pics") or extra.get("images") or [])
        has_video = bool(
            extra.get("video_url")
            or extra.get("video_urls")
            or str(extra.get("media_type") or "").lower() == "video"
        )
        ev_row: dict[str, Any] = {
            "event_id": str(ev.get("event_id") or ""),
            "event_type": str(ev.get("event_type") or ""),
            "content": str(ev.get("content") or "")[:220],
            "media_title": str(ev.get("media_title") or "")[:100],
            "media_artist": str(ev.get("media_artist") or "")[:60],
            "timestamp": ev.get("timestamp") or 0,
            "url": ev.get("url") or "",
        }
        if pics:
            ev_row["pic_count"] = len(pics)
        if has_video:
            ev_row["has_video"] = True
        compact_events.append(ev_row)

    records = payload.get("records") or {}
    compact_records: dict[str, list[dict[str, Any]]] = {}
    if isinstance(records, dict):
        for bucket in ("weekly", "allTime"):
            rows = records.get(bucket) or []
            if rows:
                compact_records[bucket] = [
                    {
                        "title": str(r.get("title") or "")[:80],
                        "artist": str(r.get("artist_or_uploader") or "")[:60],
                        "play_count": r.get("play_count") or 0,
                    }
                    for r in rows[:15]
                    if isinstance(r, dict)
                ]

    follows = payload.get("follows") or []
    followers = payload.get("followers") or []

    compact = {
        "platform": platform,
        "platform_name": pname,
        "uid": uid,
        "profile": profile,
        "content_count": len(playlists),
        "content_samples": compact_items,
        "event_count": len(events),
        "event_samples": compact_events,
        "records": compact_records,
        "follows_sample_count": len(follows),
        "follows_top": [
            {
                "uid": str(u.get("uid") or ""),
                "nickname": str(u.get("nickname") or ""),
                "fans": u.get("fans") or 0,
                "verified": bool(u.get("is_verified") or u.get("verified")),
                "signature": str(u.get("signature") or "")[:80],
            }
            for u in follows[:15]
            if isinstance(u, dict)
        ],
        "followers_sample_count": len(followers),
        "partial_errors": errors or [],
    }

    evidence_items: list[dict[str, Any]] = []
    if profile:
        parts = [f"昵称「{profile.get('nickname') or uid}」"]
        if profile.get("location"):
            parts.append(f"地区: {profile['location']}")
        if profile.get("birthday"):
            parts.append(f"生日: {profile['birthday']}")
        if profile.get("level"):
            parts.append(f"等级 Lv.{profile['level']}")
        if profile.get("signature"):
            parts.append(f"签名: {profile['signature']}")
        if profile.get("extra"):
            extra_str = ", ".join(f"{k}={v}" for k, v in list(profile["extra"].items())[:6])
            parts.append(f"扩展: {extra_str}")
        evidence_items.append(
            {
                "platform": platform,
                "platform_name": pname,
                "uid": uid,
                "category": "profile",
                "title": f"{pname} 主页资料 ({profile.get('nickname') or uid})",
                "snippet": " | ".join(parts),
                "url": "",
                "timestamp": "",
            }
        )

    if compact_items:
        titles = "、".join(
            f"《{it['title']}》" + (f"({it['language']})" if it.get("language") else "")
            for it in compact_items[:8]
            if it.get("title")
        )
        evidence_items.append(
            {
                "platform": platform,
                "platform_name": pname,
                "uid": uid,
                "category": "content",
                "title": f"{pname} 内容列表（共 {len(playlists)} 项）",
                "snippet": titles or f"共 {len(playlists)} 项公开内容",
                "url": next((it["url"] for it in compact_items if it.get("url")), ""),
                "timestamp": str(compact_items[0].get("create_time") or ""),
            }
        )

    if compact_events:
        ev_preview = "；".join(
            f"[{ev['event_type'] or '动态'}] {(ev['content'] or ev['media_title'])[:60]}"
            for ev in compact_events[:6]
        )
        evidence_items.append(
            {
                "platform": platform,
                "platform_name": pname,
                "uid": uid,
                "category": "events",
                "title": f"{pname} 近期动态（共 {len(events)} 条）",
                "snippet": ev_preview,
                "url": next((ev["url"] for ev in compact_events if ev.get("url")), ""),
                "timestamp": str(compact_events[0].get("timestamp") or ""),
            }
        )

    if compact_records:
        top_songs = compact_records.get("weekly") or compact_records.get("allTime") or []
        songs_str = "、".join(
            f"《{s['title']}》-{s['artist']}({s['play_count']})" for s in top_songs[:8]
        )
        evidence_items.append(
            {
                "platform": platform,
                "platform_name": pname,
                "uid": uid,
                "category": "records",
                "title": f"{pname} 听歌排行",
                "snippet": songs_str,
                "url": "",
                "timestamp": "",
            }
        )

    return compact, evidence_items


# ==================== 工具底层实现函数 ====================


def exec_list_platform_status() -> ToolExecResult:
    try:
        items = list_platforms()
        enriched = []
        for p in items:
            pid = p["id"]
            enriched.append(
                {
                    **p,
                    "capabilities": PLATFORM_CAPABILITIES.get(pid, {}),
                }
            )
        return ToolExecResult(
            ok=True,
            summary_text=f"已获取 {len(enriched)} 个平台状态",
            data={"platforms": enriched},
        )
    except Exception as e:
        return ToolExecResult(ok=False, summary_text="获取平台状态失败", error_kind="unknown", error=str(e))


def exec_search_users(
    keyword: str,
    platforms: Optional[list[str]] = None,
    limit: int = 5,
) -> ToolExecResult:
    kw = (keyword or "").strip()
    if not kw:
        return ToolExecResult(ok=False, summary_text="缺少关键词", error_kind="invalid_arg", error="keyword 不能为空")
    limit = max(1, min(int(limit or 5), 10))
    try:
        res = search_cross_platform(kw, platform_ids=platforms, limit=limit)
        candidates = rank_identity_candidates(res, max_per_platform=limit)
        gaps = [
            {
                "platform": pid,
                "category": "search",
                "reason": str(err),
                "error_kind": classify_error(str(err)),
            }
            for pid, err in (res.get("errors") or {}).items()
        ]
        ev_items = []
        if candidates:
            top_desc = "；".join(
                f"{c['platform_name']}:{c['nickname']}(UID:{c['uid']}, 置信度{c['confidence']})"
                for c in candidates[:8]
            )
            ev_items.append(
                {
                    "platform": "multi",
                    "platform_name": "跨平台检索",
                    "uid": kw,
                    "category": "search",
                    "title": f"关键词「{kw}」跨平台搜索候选",
                    "snippet": top_desc,
                    "url": "",
                    "timestamp": "",
                }
            )
        return ToolExecResult(
            ok=True,
            summary_text=f"关键词「{kw}」命中 {len(candidates)} 个候选账号",
            data={
                "keyword": kw,
                "candidates": candidates[:20],
                "errors": res.get("errors") or {},
            },
            evidence_items=ev_items,
            gaps=gaps,
        )
    except Exception as e:
        return ToolExecResult(ok=False, summary_text=f"搜索「{kw}」失败", error_kind=classify_error(str(e)), error=str(e))


def exec_get_platform_summary(
    store: DataStore,
    platform: str,
    uid: str,
    refresh: bool = False,
) -> ToolExecResult:
    pid = (platform or "").strip()
    uid = (uid or "").strip()
    pname = _PLATFORM_NAMES.get(pid, pid)
    if not pid or not uid:
        return ToolExecResult(ok=False, summary_text="参数不足", error_kind="invalid_arg", error="platform 与 uid 均不能为空")
    try:
        payload, partial_errors = fetch_platform_all(
            pid,
            uid,
            store,
            refresh=bool(refresh),
            include_social=True,
            include_records=True,
        )
        compact, ev_items = summarize_platform_payload(pid, uid, payload, partial_errors)
        gaps = [
            {
                "platform": pid,
                "category": "platform_partial",
                "reason": err,
                "error_kind": classify_error(err),
            }
            for err in partial_errors
        ]
        return ToolExecResult(
            ok=True,
            summary_text=f"已获取 {pname} ({uid}) 资料与公开内容摘要",
            data=compact,
            evidence_items=ev_items,
            gaps=gaps,
            media_catalog_updates={pid: extract_media_catalog(pid, uid, payload)},
        )
    except AuthExpiredError as e:
        err = str(e)
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 登录凭证已失效",
            error_kind="auth_expired",
            error=err,
            gaps=[{"platform": pid, "category": "auth", "reason": err, "error_kind": "auth_expired"}],
        )
    except (AllModulesFailedError, Exception) as e:
        err = str(e)
        # 若实时拉取失败但本地有历史快照，可降级返回历史快照并标注为旧数据
        fallback_profile = find_latest_real_snapshot(store, pid, uid, "profile")
        if fallback_profile and not is_auth_expired_error(err):
            fallback_payload = {
                "platform": pid,
                "uid": uid,
                "profile": fallback_profile,
                "playlists": (find_latest_real_snapshot(store, pid, uid, "playlists") or {}).get("items", []),
                "events": (find_latest_real_snapshot(store, pid, uid, "events") or {}).get("items", []),
                "records": find_latest_real_snapshot(store, pid, uid, "records") or {"allTime": [], "weekly": []},
                "follows": (find_latest_real_snapshot(store, pid, uid, "follows") or {}).get("items", []),
                "followers": (find_latest_real_snapshot(store, pid, uid, "followers") or {}).get("items", []),
            }
            compact, ev_items = summarize_platform_payload(
                pid, uid, fallback_payload, [f"实时抓取失败，已回退历史快照: {err}"]
            )
            return ToolExecResult(
                ok=True,
                summary_text=f"{pname} 实时抓取失败，已复用本地历史快照",
                data=compact,
                evidence_items=ev_items,
                gaps=[{"platform": pid, "category": "stale_fallback", "reason": err, "error_kind": classify_error(err)}],
                media_catalog_updates={pid: extract_media_catalog(pid, uid, fallback_payload)},
            )
        return ToolExecResult(
            ok=False,
            summary_text=f"获取 {pname} ({uid}) 失败",
            error_kind=classify_error(err),
            error=err,
            gaps=[{"platform": pid, "category": "platform_fetch", "reason": err, "error_kind": classify_error(err)}],
        )


def exec_get_content_detail(
    platform: str,
    item_id: str,
    media_catalog: Optional[dict[str, Any]] = None,
) -> ToolExecResult:
    pid = (platform or "").strip()
    item_id = (item_id or "").strip()
    pname = _PLATFORM_NAMES.get(pid, pid)
    if not pid or not item_id:
        return ToolExecResult(ok=False, summary_text="参数不足", error_kind="invalid_arg", error="platform 与 item_id 均不能为空")
    try:
        detail = None
        if pid == "xhs":
            adapter = get_adapter(pid)
            if not adapter:
                raise KeyError(f"未知平台: {pid}")
            cat_item = ((media_catalog or {}).get(pid) or {}).get("items", {}).get(item_id) or {}
            xsec_token = str(cat_item.get("xsec_token") or "")
            detail = adapter.get_content_detail(item_id, xsec_token=xsec_token)
        else:
            detail = fetch_content_detail(pid, item_id)
        if not detail:
            return ToolExecResult(
                ok=False,
                summary_text=f"{pname} 内容 {item_id} 无详情或平台不支持",
                error_kind="not_found",
                error="未获取到内容详情（该平台可能不支持 get_content_detail）",
            )
        items = detail.get("items") or []
        compact_items = [
            {
                "title": str(it.get("title") or it.get("name") or "")[:100],
                "artist": str(it.get("artist") or it.get("singer") or it.get("author") or "")[:60],
                "album": str(it.get("album") or "")[:60],
            }
            for it in items[:30]
            if isinstance(it, dict)
        ]
        images = _dedupe_urls(detail.get("images") or [])
        video_urls = _dedupe_urls(detail.get("video_urls") or [])
        for v in _dedupe_urls(detail.get("video_url") or ""):
            if v not in video_urls:
                video_urls.insert(0, v)

        compact: dict[str, Any] = {
            "platform": pid,
            "item_id": item_id,
            "title": str(detail.get("title") or ""),
            "description": str(detail.get("description") or detail.get("desc") or "")[:400],
            "count": detail.get("count") or len(items),
            "items": compact_items,
        }
        if detail.get("media_type"):
            compact["media_type"] = str(detail["media_type"])
        if images:
            compact["image_count"] = len(images)
        if video_urls:
            compact["has_video"] = True
        if detail.get("tags"):
            compact["tags"] = [str(t) for t in (detail.get("tags") or [])[:12]]
        if detail.get("ip_location"):
            compact["ip_location"] = str(detail["ip_location"])
        if detail.get("bvid"):
            compact["bvid"] = str(detail["bvid"])
        if detail.get("duration"):
            compact["duration"] = detail["duration"]

        if compact_items:
            snippet = f"《{compact['title']}》（{compact['count']} 条）: " + "、".join(
                f"{x['title']}" + (f"-{x['artist']}" if x["artist"] else "") for x in compact_items[:10]
            )
        else:
            parts = [f"《{compact['title'] or item_id}》"]
            if compact.get("description"):
                parts.append(compact["description"][:220])
            if compact.get("tags"):
                parts.append("标签: " + "、".join(compact["tags"][:6]))
            if compact.get("ip_location"):
                parts.append(f"IP: {compact['ip_location']}")
            if images:
                parts.append(f"含 {len(images)} 张图片")
            if video_urls:
                parts.append("含可分析视频流")
            snippet = " | ".join(parts)

        catalog_updates: dict[str, dict[str, Any]] = {}
        detail_cover = detail.get("cover_url") or detail.get("coverUrl") or ""
        if images or video_urls or detail_cover or detail.get("bvid"):
            cover_list = _dedupe_urls(detail_cover)
            catalog_updates[pid] = {
                "platform": pid,
                "items": {
                    item_id: {
                        "item_id": item_id,
                        "title": compact["title"],
                        "cover_url": cover_list[0] if cover_list else (images[0] if images else ""),
                        "images": images[:12],
                        "video_url": video_urls[0] if video_urls else "",
                        "video_urls": video_urls[:6],
                        "media_type": str(detail.get("media_type") or ("video" if video_urls else ("image" if images else ""))),
                        "bvid": str(detail.get("bvid") or ""),
                        "url": str(detail.get("url") or ""),
                    }
                },
            }

        return ToolExecResult(
            ok=True,
            summary_text=f"已深挖 {pname} 内容详情《{compact['title'] or item_id}》",
            data=compact,
            evidence_items=[
                {
                    "platform": pid,
                    "platform_name": pname,
                    "uid": item_id,
                    "category": "content_detail",
                    "title": f"{pname} 内容详情: {compact['title'] or item_id}",
                    "snippet": snippet[:420],
                    "url": str(detail.get("url") or ""),
                    "timestamp": "",
                }
            ],
            media_catalog_updates=catalog_updates,
        )
    except Exception as e:
        err = str(e)
        return ToolExecResult(
            ok=False,
            summary_text=f"获取 {pname} 内容详情失败",
            error_kind=classify_error(err),
            error=err,
            gaps=[{"platform": pid, "category": "content_detail", "reason": err, "error_kind": classify_error(err)}],
        )


def exec_get_bilibili_archives(
    uid: str,
    source: str = "aicu_reply",
    page: int = 1,
    page_size: int = 20,
) -> ToolExecResult:
    uid = (uid or "").strip()
    source = (source or "aicu_reply").strip()
    page = max(1, min(int(page or 1), 3))
    page_size = max(5, min(int(page_size or 20), 30))
    try:
        data = bilibili_archives_svc.fetch(source, uid, page=page, page_size=page_size)
        events = data.get("events") or []
        compact_events = [
            {
                "event_type": ev.get("event_type") or "",
                "content": str(ev.get("content") or "")[:200],
                "timestamp": ev.get("timestamp") or 0,
                "media_title": str(ev.get("media_title") or "")[:80],
                "media_artist": str(ev.get("media_artist") or "")[:60],
                "url": ev.get("url") or "",
            }
            for ev in events[:25]
            if isinstance(ev, dict)
        ]
        ev_items = []
        if compact_events:
            preview = "；".join(
                (f"[{e['media_artist']}] " if e.get("media_artist") else "") + e["content"][:70]
                for e in compact_events[:6]
                if e.get("content")
            )
            ev_items.append(
                {
                    "platform": "bilibili",
                    "platform_name": "哔哩哔哩",
                    "uid": uid,
                    "category": f"archive:{source}",
                    "title": f"{data.get('source_name', source)}（共 {data.get('total', len(events))} 条，第 {page} 页）",
                    "snippet": preview[:420] or f"命中 {len(compact_events)} 条存档记录",
                    "url": str(data.get("source_url") or ""),
                    "timestamp": str(compact_events[0].get("timestamp") or ""),
                }
            )
        return ToolExecResult(
            ok=True,
            summary_text=f"查询 B 站 {data.get('source_name', source)}，返回 {len(compact_events)} 条记录",
            data={
                "source": source,
                "source_name": data.get("source_name"),
                "source_url": data.get("source_url"),
                "total": data.get("total"),
                "has_more": data.get("has_more"),
                "notice": data.get("notice"),
                "events": compact_events,
            },
            evidence_items=ev_items,
        )
    except Exception as e:
        err = str(e)
        return ToolExecResult(
            ok=False,
            summary_text=f"查询 B 站存档 ({source}) 失败",
            error_kind=classify_error(err),
            error=err,
            gaps=[{"platform": "bilibili", "category": f"archive:{source}", "reason": err, "error_kind": classify_error(err)}],
        )


def exec_get_timeline(
    store: DataStore,
    platform_uids: dict[str, str],
    source: str = "stored",
    limit: int = 40,
) -> ToolExecResult:
    clean_map = {str(k).strip(): str(v).strip() for k, v in (platform_uids or {}).items() if k and v}
    if not clean_map:
        return ToolExecResult(ok=False, summary_text="缺少 platform_uids", error_kind="invalid_arg", error="platform_uids 不能为空")
    limit = max(5, min(int(limit or 40), 80))
    source = "live" if str(source).strip() == "live" else "stored"
    try:
        rows: list[dict[str, Any]] = []
        if source == "stored":
            for pid, uid in clean_map.items():
                rows.extend(store.get_timeline_entries(platform=pid, uid=uid, limit=limit))
            rows.sort(key=lambda r: (r.get("created_at", ""), r.get("timestamp", 0)), reverse=True)
            rows = rows[:limit]
        else:
            entries = TimelineBuilder.build(clean_map, limit_per_platform=min(limit, 30), store=store)
            try:
                store.insert_timeline_entries(entries)
            except Exception:
                pass
            rows = [
                {
                    "platform": e.platform,
                    "platform_name": e.platform_name,
                    "uid": e.uid,
                    "event_type": e.event_type,
                    "time_str": e.time_str,
                    "time_suffix": e.time_suffix,
                    "summary": e.summary,
                    "detail": e.detail,
                    "timestamp": e.timestamp,
                }
                for e in entries[:limit]
            ]

        compact_rows = [
            {
                "platform": r.get("platform"),
                "time": r.get("time_str") or r.get("time_suffix") or r.get("created_at", "")[:16],
                "event_type": r.get("event_type"),
                "summary": str(r.get("summary") or "")[:160],
                "detail": str(r.get("detail") or "")[:120],
            }
            for r in rows
        ]
        ev_items = []
        if compact_rows:
            preview = "；".join(f"{r['time']} {r['summary']}" for r in compact_rows[:6])
            ev_items.append(
                {
                    "platform": "multi",
                    "platform_name": "统一时间线",
                    "uid": ",".join(f"{k}:{v}" for k, v in clean_map.items()),
                    "category": f"timeline:{source}",
                    "title": f"跨平台活动时间线（{source}，{len(compact_rows)} 条）",
                    "snippet": preview[:420],
                    "url": "",
                    "timestamp": "",
                }
            )
        return ToolExecResult(
            ok=True,
            summary_text=f"读取时间线 ({source}) 共 {len(compact_rows)} 条",
            data={"source": source, "count": len(compact_rows), "entries": compact_rows},
            evidence_items=ev_items,
        )
    except Exception as e:
        err = str(e)
        return ToolExecResult(
            ok=False,
            summary_text="读取时间线失败",
            error_kind=classify_error(err),
            error=err,
            gaps=[{"platform": "multi", "category": "timeline", "reason": err, "error_kind": classify_error(err)}],
        )


def exec_analyze_social_graph(
    store: DataStore,
    graph_id: Optional[int] = None,
    target_accounts: Optional[dict[str, str]] = None,
) -> ToolExecResult:
    try:
        if graph_id is None:
            saved = store.list_graphs()
            return ToolExecResult(
                ok=True,
                summary_text=f"当前有 {len(saved)} 张已保存图谱",
                data={"available_graphs": saved[:20]},
            )
        graph = store.get_graph(int(graph_id))
        if not graph:
            return ToolExecResult(
                ok=False,
                summary_text=f"图谱 #{graph_id} 不存在",
                error_kind="not_found",
                error=f"未找到 id={graph_id} 的已保存关系图谱",
            )
        analysis = analyze_social_network(
            graph_data=graph.get("data"),
            target_accounts=target_accounts,
        )
        core = analysis.get("mutual_core_contacts") or []
        ev_items = [
            {
                "platform": "multi",
                "platform_name": "关系图谱",
                "uid": str(graph_id),
                "category": "social_graph",
                "title": f"图谱「{graph.get('name')}」拓扑分析（{analysis['total_nodes']} 节点 / {analysis['total_follow_edges']} 关注边）",
                "snippet": (
                    "互关核心圈: "
                    + ("、".join(f"{c['nickname']}({c['platform_name']})" for c in core[:8]) or "暂无明显互关密友")
                ),
                "url": "",
                "timestamp": str(graph.get("updated_at") or ""),
            }
        ]
        return ToolExecResult(
            ok=True,
            summary_text=f"已分析图谱「{graph.get('name')}」({analysis['total_nodes']} 节点)",
            data={"graph_id": graph_id, "name": graph.get("name"), "analysis": analysis},
            evidence_items=ev_items,
        )
    except Exception as e:
        err = str(e)
        return ToolExecResult(ok=False, summary_text="图谱分析失败", error_kind="unknown", error=err)


def exec_fetch_social_sample(
    platform: str,
    uid: str,
    follows_limit: int = 30,
    followers_limit: int = 20,
) -> ToolExecResult:
    pid = (platform or "").strip()
    uid = (uid or "").strip()
    pname = _PLATFORM_NAMES.get(pid, pid)
    if not pid or not uid:
        return ToolExecResult(ok=False, summary_text="参数不足", error_kind="invalid_arg", error="platform 与 uid 不能为空")
    follows_limit = max(0, min(int(follows_limit or 0), 50))
    followers_limit = max(0, min(int(followers_limit or 0), 30))
    try:
        payload = expand_social(
            {
                "platform": pid,
                "uid": uid,
                "follows_limit": follows_limit,
                "followers_limit": followers_limit,
                "intercheck_limit": 0,  # Agent 工具禁止触发重型邻居互查
            }
        )
        analysis = analyze_social_network(
            graph_data={"nodes": payload.get("nodes") or [], "edges": payload.get("edges") or []},
            target_accounts={pid: uid},
        )
        gaps = [
            {
                "platform": pid,
                "category": f"social:{direction}",
                "reason": str(err),
                "error_kind": classify_error(str(err)),
            }
            for direction, err in (payload.get("errors") or {}).items()
        ]
        core = analysis.get("mutual_core_contacts") or []
        celebs = analysis.get("followed_public_accounts") or []
        ev_items = []
        if payload.get("nodes"):
            ev_items.append(
                {
                    "platform": pid,
                    "platform_name": pname,
                    "uid": uid,
                    "category": "social_sample",
                    "title": f"{pname} 社交关系采样（关注 {payload['counts']['follows']} / 粉丝 {payload['counts']['followers']}）",
                    "snippet": (
                        f"互关候选: {'、'.join(c['nickname'] for c in core[:6]) or '无'}；"
                        f"关注公众账号: {'、'.join(c['nickname'] for c in celebs[:6]) or '无'}"
                    ),
                    "url": "",
                    "timestamp": "",
                }
            )
        return ToolExecResult(
            ok=True,
            summary_text=f"{pname} 社交采样完成（节点 {len(payload.get('nodes') or [])}）",
            data={
                "counts": payload.get("counts"),
                "analysis": analysis,
                "errors": payload.get("errors") or {},
            },
            evidence_items=ev_items,
            gaps=gaps,
        )
    except Exception as e:
        err = str(e)
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 社交采样失败",
            error_kind=classify_error(err),
            error=err,
            gaps=[{"platform": pid, "category": "social_sample", "reason": err, "error_kind": classify_error(err)}],
        )


def _lookup_platform_catalog(
    store: DataStore,
    platform: str,
    media_catalog: Optional[dict[str, Any]],
    confirmed_accounts: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """优先从 LangGraph State 媒体索引读取；缺失时从 SQLite 最近快照恢复（兼容重启后追问）。"""
    entry = (media_catalog or {}).get(platform)
    if isinstance(entry, dict) and (
        entry.get("avatar_url") or entry.get("items") or entry.get("events")
    ):
        return entry

    uid = str((confirmed_accounts or {}).get(platform) or "").strip()
    if not uid:
        return {}
    payload = {
        "profile": find_latest_real_snapshot(store, platform, uid, "profile"),
        "playlists": (find_latest_real_snapshot(store, platform, uid, "playlists") or {}).get("items", []),
        "events": (find_latest_real_snapshot(store, platform, uid, "events") or {}).get("items", []),
    }
    return extract_media_catalog(platform, uid, payload)


def _find_catalog_item(catalog: dict[str, Any], target_id: str) -> Optional[dict[str, Any]]:
    tid = str(target_id or "").strip()
    if not tid:
        return None
    items = catalog.get("items") or {}
    if tid in items:
        return items[tid]
    for it in items.values():
        if isinstance(it, dict) and (
            str(it.get("bvid") or "") == tid or str(it.get("item_id") or "") == tid
        ):
            return it
    for ev in catalog.get("events") or []:
        if isinstance(ev, dict) and (
            str(ev.get("event_id") or "") == tid or str(ev.get("bvid") or "") == tid
        ):
            return ev
    return None


def exec_inspect_images(
    store: DataStore,
    platform: str,
    item_ids: Optional[list[str]] = None,
    image_urls: Optional[list[str]] = None,
    focus: str = "",
    media_catalog: Optional[dict[str, Any]] = None,
    confirmed_accounts: Optional[dict[str, str]] = None,
) -> ToolExecResult:
    """下载并调用多模态视觉模型分析指定平台图片（头像、背景、作品配图或动态配图，单次上限 6 张）。"""
    pid = (platform or "").strip()
    pname = _PLATFORM_NAMES.get(pid, pid or "多平台")
    cfg = load_effective_config()
    if not cfg["configured"] or not cfg["enable_multimodal"]:
        return ToolExecResult(
            ok=False,
            summary_text="多模态图片分析未启用",
            error_kind="capability_unsupported",
            error="当前模型配置未启用多模态视觉分析（可在右上角模型配置中开启）",
            gaps=[{"platform": pid or "multi", "category": "visual_images", "reason": "多模态分析未启用", "error_kind": "capability_unsupported"}],
        )

    catalog = _lookup_platform_catalog(store, pid, media_catalog, confirmed_accounts) if pid else {}
    candidates: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    page_url = ""
    catalog_updates: dict[str, dict[str, Any]] = {}

    def _add_candidate(label: str, url: str) -> None:
        for clean in _dedupe_urls(url):
            if clean not in seen_urls and len(candidates) < 6:
                seen_urls.add(clean)
                candidates.append((label, clean))

    for u in _dedupe_urls(image_urls or []):
        _add_candidate(f"{pname} 指定图片", u)

    req_ids = [str(x).strip() for x in (item_ids or []) if str(x).strip()]
    for tid in req_ids:
        if len(candidates) >= 6:
            break
        low = tid.lower()
        if low in ("avatar", "profile", "头像"):
            _add_candidate(f"{pname} 主页头像", catalog.get("avatar_url") or "")
            if low == "profile":
                _add_candidate(f"{pname} 主页背景", catalog.get("background_url") or "")
            continue
        if low in ("background", "bg", "背景"):
            _add_candidate(f"{pname} 主页背景", catalog.get("background_url") or "")
            continue

        entry = _find_catalog_item(catalog, tid)
        if entry:
            title = str(entry.get("title") or entry.get("content") or tid)[:40]
            if not page_url and entry.get("url"):
                page_url = str(entry["url"])
            pics = _dedupe_urls(entry.get("images") or entry.get("pics") or [])
            # 小红书列表仅带封面，深挖单条笔记时拉取完整图集
            if not pics and pid == "xhs":
                try:
                    adapter = get_adapter("xhs")
                    if adapter:
                        detail = adapter.get_content_detail(tid, xsec_token=str(entry.get("xsec_token") or ""))
                        if detail:
                            pics = _dedupe_urls(detail.get("images") or [])
                            if pics:
                                catalog_updates[pid] = {
                                    "platform": pid,
                                    "items": {tid: {**entry, "images": pics[:12]}},
                                }
                except Exception:
                    pass
            if pics:
                for idx, u in enumerate(pics[:6], start=1):
                    _add_candidate(f"{pname}《{title}》图{idx}", u)
            elif entry.get("cover_url"):
                _add_candidate(f"{pname}《{title}》封面", entry["cover_url"])
        elif pid in ("xhs", "douyin"):
            # 允许直接传未在列表缓存中的笔记/作品 ID
            try:
                adapter = get_adapter(pid)
                detail = adapter.get_content_detail(tid) if adapter else None
                if detail:
                    title = str(detail.get("title") or tid)[:40]
                    for idx, u in enumerate(_dedupe_urls(detail.get("images") or [])[:6], start=1):
                        _add_candidate(f"{pname}《{title}》图{idx}", u)
                    if not candidates and (detail.get("cover_url") or detail.get("coverUrl")):
                        _add_candidate(f"{pname}《{title}》封面", detail.get("cover_url") or detail.get("coverUrl"))
            except Exception:
                pass

    # 若未指定 item_ids 与 image_urls，则自动从该平台挑选最具代表性的配图（最多 6 张）
    if not req_ids and not image_urls and catalog:
        for ev in (catalog.get("events") or [])[:6]:
            for idx, u in enumerate(_dedupe_urls(ev.get("pics") or [])[:3], start=1):
                _add_candidate(f"{pname} 动态配图({ev.get('content', '')[:20]})#{idx}", u)
            if len(candidates) >= 6:
                break
        if len(candidates) < 6:
            for it in (catalog.get("items") or {}).values():
                title = str(it.get("title") or it.get("item_id") or "")[:30]
                imgs = _dedupe_urls(it.get("images") or [])
                if imgs:
                    for idx, u in enumerate(imgs[:2], start=1):
                        _add_candidate(f"{pname}《{title}》图{idx}", u)
                elif it.get("cover_url"):
                    _add_candidate(f"{pname}《{title}》封面", it["cover_url"])
                if len(candidates) >= 6:
                    break
        if len(candidates) < 6 and catalog.get("avatar_url"):
            _add_candidate(f"{pname} 主页头像", catalog["avatar_url"])

    if not candidates:
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 未找到可供分析的图片链接",
            error_kind="not_found",
            error=f"{pname} 未匹配到可用图片（请检查 item_id 或先拉取该平台基线资料）",
        )

    downloaded: list[tuple[str, CachedMedia]] = []
    dl_errors: list[str] = []

    def _dl(pair: tuple[str, str]):
        label, u = pair
        try:
            return label, download_media(u, platform=pid, kind="image"), None
        except Exception as exc:
            return label, None, str(exc)

    with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as ex:
        for label, media, err in ex.map(_dl, candidates):
            if media is not None:
                downloaded.append((label, media))
            elif err:
                dl_errors.append(f"{label}: {err}")

    if not downloaded:
        reason = "; ".join(dl_errors[:3]) or "图片下载全部失败"
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 图片下载失败",
            error_kind=classify_error(reason),
            error=reason,
            gaps=[{"platform": pid or "multi", "category": "visual_images", "reason": reason, "error_kind": classify_error(reason)}],
        )

    prompt = (
        f"请结合目标人物侧写视角，客观分析以下来自 {pname} 的 {len(downloaded)} 张图片：\n"
        + (f"重点观察方向：{focus.strip()}\n" if (focus or "").strip() else "")
        + "请提炼：1) 画面主体、环境场景、物品/设备/服饰与可见文字；2) 视觉审美、构图滤镜或生活氛围特征；3) 对人物画像有价值的高置信线索与不确定处。"
    )
    try:
        res = analyze_images(downloaded, prompt)
        analysis_text = res["analysis"]
        preview_urls = [m.preview_url for _, m in downloaded]
        return ToolExecResult(
            ok=True,
            summary_text=f"已完成 {pname} {len(downloaded)} 张图片的多模态视觉分析",
            data={
                "platform": pid,
                "analyzed_count": len(downloaded),
                "labels": [lbl for lbl, _ in downloaded],
                "provider": res["provider"],
                "model": res["model"],
                "analysis": analysis_text,
                "download_warnings": dl_errors[:3],
            },
            evidence_items=[
                {
                    "platform": pid or "multi",
                    "platform_name": pname,
                    "uid": ",".join(req_ids[:3]) or str(catalog.get("uid") or ""),
                    "category": "visual_images",
                    "title": f"{pname} 图片多模态分析（{len(downloaded)} 张）",
                    "snippet": analysis_text[:480],
                    "url": page_url,
                    "timestamp": "",
                    "media_urls": preview_urls,
                }
            ],
            media_catalog_updates=catalog_updates,
        )
    except Exception as e:
        err = str(e)
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 多模态图片分析失败",
            error_kind=classify_error(err),
            error=err,
            gaps=[{"platform": pid or "multi", "category": "visual_images", "reason": err, "error_kind": classify_error(err)}],
        )


def exec_inspect_video(
    store: DataStore,
    platform: str,
    item_id: str,
    focus: str = "",
    media_catalog: Optional[dict[str, Any]] = None,
    confirmed_accounts: Optional[dict[str, str]] = None,
) -> ToolExecResult:
    """下载指定平台单条代表性短视频（上限 25 MB）并用 Gemini 原生多模态理解画面、语音与字幕。"""
    pid = (platform or "").strip()
    tid = (item_id or "").strip()
    pname = _PLATFORM_NAMES.get(pid, pid)
    if not pid or not tid:
        return ToolExecResult(ok=False, summary_text="参数不足", error_kind="invalid_arg", error="platform 与 item_id 均不能为空")

    if pid not in ("douyin", "xhs", "bilibili", "weibo"):
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 暂不支持视频流解析",
            error_kind="capability_unsupported",
            error="目前仅支持 douyin、xhs、bilibili、weibo 平台的视频多模态分析",
        )

    cfg = load_effective_config()
    if not cfg["configured"] or not cfg["enable_multimodal"]:
        return ToolExecResult(
            ok=False,
            summary_text="多模态视频分析未启用",
            error_kind="capability_unsupported",
            error="当前模型配置未启用多模态分析",
            gaps=[{"platform": pid, "category": "visual_video", "reason": "多模态分析未启用", "error_kind": "capability_unsupported"}],
        )
    if cfg["provider"] != PROVIDER_GEMINI:
        err = "视频原生多模态分析需要切换至「Gemini 原生多模态」提供商（当前为 OpenAI 兼容模式，请改用 inspect_images 分析封面图）"
        return ToolExecResult(
            ok=False,
            summary_text="当前模型不支持原生视频理解",
            error_kind="capability_unsupported",
            error=err,
            gaps=[{"platform": pid, "category": "visual_video", "reason": err, "error_kind": "capability_unsupported"}],
        )

    catalog = _lookup_platform_catalog(store, pid, media_catalog, confirmed_accounts)
    entry = _find_catalog_item(catalog, tid) or {}
    title = str(entry.get("title") or entry.get("content") or tid)[:80]
    cover_url = str(entry.get("cover_url") or "")
    page_url = str(entry.get("url") or "")
    video_urls = _dedupe_urls(entry.get("video_urls") or [])
    for v in _dedupe_urls(entry.get("video_url") or ""):
        if v not in video_urls:
            video_urls.insert(0, v)

    # 按平台按需补拉直链（B 站 playurl / 小红书笔记详情 / 抖音作品详情）
    resolve_error = ""
    try:
        adapter = get_adapter(pid)
        if pid == "bilibili" and adapter and hasattr(adapter, "get_video_stream_url"):
            bvid_or_aid = str(entry.get("bvid") or tid)
            stream_info = adapter.get_video_stream_url(bvid_or_aid)
            if isinstance(stream_info, dict):
                video_urls = _dedupe_urls(stream_info.get("video_urls") or stream_info.get("video_url") or []) + video_urls
                if not title or title == tid:
                    title = str(stream_info.get("title") or title)[:80]
                if not cover_url and stream_info.get("cover_url"):
                    cover_url = str(stream_info["cover_url"])
        elif not video_urls and pid in ("xhs", "douyin") and adapter:
            if pid == "xhs":
                detail = adapter.get_content_detail(tid, xsec_token=str(entry.get("xsec_token") or ""))
            else:
                detail = adapter.get_content_detail(tid)
            if isinstance(detail, dict):
                video_urls = _dedupe_urls(detail.get("video_urls") or [])
                for v in _dedupe_urls(detail.get("video_url") or ""):
                    if v not in video_urls:
                        video_urls.insert(0, v)
                if not title or title == tid:
                    title = str(detail.get("title") or title)[:80]
                if not cover_url and (detail.get("cover_url") or detail.get("coverUrl")):
                    cover_url = str(detail.get("cover_url") or detail.get("coverUrl"))
                if not page_url and detail.get("url"):
                    page_url = str(detail["url"])
    except Exception as e:
        resolve_error = str(e)

    video_urls = _dedupe_urls(video_urls)
    cached_video: Optional[CachedMedia] = None
    dl_errors: list[str] = []
    for candidate_url in video_urls[:4]:
        try:
            cached_video = download_media(
                candidate_url,
                platform=pid,
                kind="video",
                max_bytes=MAX_VIDEO_BYTES,
                timeout=45,
            )
            break
        except Exception as exc:
            dl_errors.append(str(exc))

    # 若视频流解析或下载失败（如体积 > 25MB），优先降级分析封面图并记录盲区
    if cached_video is None:
        fail_reason = "; ".join(dl_errors[:2]) or resolve_error or "未找到可用视频直链"
        if cover_url:
            try:
                cover_media = download_media(cover_url, platform=pid, kind="image")
                fb = analyze_images(
                    [(f"{pname} 视频《{title}》封面（降级分析）", cover_media)],
                    f"原视频未能下载（{fail_reason}），请先基于封面图分析视频主题与风格。"
                    + (f"关注重点：{focus}" if focus else ""),
                )
                return ToolExecResult(
                    ok=True,
                    summary_text=f"{pname} 视频下载受限，已降级完成封面图分析",
                    data={
                        "platform": pid,
                        "item_id": tid,
                        "title": title,
                        "fallback_to_cover": True,
                        "video_error": fail_reason,
                        "analysis": fb["analysis"],
                    },
                    evidence_items=[
                        {
                            "platform": pid,
                            "platform_name": pname,
                            "uid": tid,
                            "category": "visual_cover_fallback",
                            "title": f"{pname} 视频封面降级分析: {title}",
                            "snippet": f"[原视频未下载: {fail_reason[:80]}] {fb['analysis'][:400]}",
                            "url": page_url,
                            "timestamp": "",
                            "media_urls": [cover_media.preview_url],
                        }
                    ],
                    gaps=[{"platform": pid, "category": "visual_video", "reason": fail_reason, "error_kind": classify_error(fail_reason)}],
                )
            except Exception:
                pass
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 视频《{title}》下载失败",
            error_kind=classify_error(fail_reason),
            error=fail_reason,
            gaps=[{"platform": pid, "category": "visual_video", "reason": fail_reason, "error_kind": classify_error(fail_reason)}],
        )

    prompt = (
        f"请结合人物画像侧写目标，全面分析这条来自 {pname} 的视频《{title}》：\n"
        + (f"重点观察方向：{focus.strip()}\n" if (focus or "").strip() else "")
        + "请提炼：1) 视频主题、拍摄/剪辑风格与内容领域；2) 画面中可见的人物状态、环境场景、设备或地域氛围线索；"
        "3) 语音口吻、用词习惯、背景音乐与字幕传递的性格和审美倾向。"
    )
    try:
        res = analyze_video(cached_video, prompt, label=f"{pname} - {title}")
        thumb_urls: list[str] = []
        if cover_url:
            try:
                cover_media = download_media(cover_url, platform=pid, kind="image")
                thumb_urls.append(cover_media.preview_url)
            except Exception:
                pass
        mb = round(cached_video.size_bytes / (1024 * 1024), 2)
        return ToolExecResult(
            ok=True,
            summary_text=f"已完成 {pname} 视频《{title}》原生多模态分析 ({mb} MB, {res['mode']})",
            data={
                "platform": pid,
                "item_id": tid,
                "title": title,
                "size_mb": mb,
                "transfer_mode": res["mode"],
                "provider": res["provider"],
                "model": res["model"],
                "analysis": res["analysis"],
            },
            evidence_items=[
                {
                    "platform": pid,
                    "platform_name": pname,
                    "uid": tid,
                    "category": "visual_video",
                    "title": f"{pname} 视频多模态分析: {title} ({mb} MB)",
                    "snippet": res["analysis"][:480],
                    "url": page_url,
                    "timestamp": "",
                    "media_urls": thumb_urls,
                    "video_url": cached_video.preview_url,
                }
            ],
        )
    except Exception as e:
        err = str(e)
        return ToolExecResult(
            ok=False,
            summary_text=f"{pname} 视频多模态分析失败",
            error_kind=classify_error(err),
            error=err,
            gaps=[{"platform": pid, "category": "visual_video", "reason": err, "error_kind": classify_error(err)}],
        )


# ==================== LangChain Tool Schema 绑定 + 统一调度 ====================


def build_tool_schemas(store: DataStore) -> list:
    """构建绑定给 ChatOpenAI.bind_tools() 的 LangChain 工具列表。"""

    @tool
    def list_platform_status() -> str:
        """查看 Sight 当前 8 个平台的凭证配置状态、存活状态及支持的能力矩阵（是否支持歌单详情、B站存档、社交关系等）。"""
        res = exec_list_platform_status()
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def search_users(
        keyword: str,
        platforms: Optional[list[str]] = None,
        limit: int = 5,
    ) -> str:
        """按昵称或 ID 跨平台搜索用户并返回排序后的候选账号。platforms 可选填如 ['bilibili', 'github']，不填则搜全部平台。"""
        res = exec_search_users(keyword=keyword, platforms=platforms, limit=limit)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def get_platform_profile_summary(
        platform: str,
        uid: str,
        refresh: bool = False,
    ) -> str:
        """获取指定平台目标用户的精简聚合资料（个人简介、内容列表 Top20、动态 Top20、听歌排行、关注样本）。优先复用 30 分钟本地快照。"""
        res = exec_get_platform_summary(store, platform=platform, uid=uid, refresh=refresh)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def get_content_detail(platform: str, item_id: str) -> str:
        """深挖单条内容详情：查看网易云/QQ音乐歌单曲目、GitHub 仓库（item_id 如 owner__repo）最近 Commit，或小红书/抖音/B站单条作品完整描述、标签与媒体列表。"""
        res = exec_get_content_detail(platform=platform, item_id=item_id)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def get_bilibili_archives(
        uid: str,
        source: str = "aicu_reply",
        page: int = 1,
        page_size: int = 20,
    ) -> str:
        """查询 B 站第三方公开存档，极具人物性格与作息分析价值。source 可选: aicu_reply(评论)、aicu_danmaku(视频弹幕)、danmakus(直播弹幕与互动)。uid 需为纯数字。"""
        res = exec_get_bilibili_archives(uid=uid, source=source, page=page, page_size=page_size)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def get_timeline(
        platform_uids: dict[str, str],
        source: str = "stored",
        limit: int = 40,
    ) -> str:
        """读取目标跨平台活动时间线，观察不同时间段的行为变化（听歌增长、新关注/取关、内容变动）。source='stored' 读历史持久化记录，'live' 实时比对。"""
        res = exec_get_timeline(store, platform_uids=platform_uids, source=source, limit=limit)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def analyze_social_graph(
        graph_id: Optional[int] = None,
        target_accounts: Optional[dict[str, str]] = None,
    ) -> str:
        """对已保存的跨平台关系图谱做拓扑分析（过滤大V后的互关核心圈、跨平台同人连边）。不传 graph_id 时返回已保存图谱列表。"""
        res = exec_analyze_social_graph(store, graph_id=graph_id, target_accounts=target_accounts)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def fetch_social_sample(
        platform: str,
        uid: str,
        follows_limit: int = 30,
        followers_limit: int = 20,
    ) -> str:
        """对指定平台用户做轻量社交关系采样（上限 50 关注 / 30 粉丝，不做全图互查），用于快速识别互关与关注领域。"""
        res = exec_fetch_social_sample(
            platform=platform,
            uid=uid,
            follows_limit=follows_limit,
            followers_limit=followers_limit,
        )
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def inspect_images(
        platform: str,
        item_ids: Optional[list[str]] = None,
        focus: str = "",
    ) -> str:
        """使用多模态视觉模型查看指定平台的图片内容（单次最多 6 张）。item_ids 可传作品 item_id、动态 event_id，或传 ['avatar', 'background'] 查看主页头像/背景；不传则自动选取该平台最具代表性的配图。"""
        res = exec_inspect_images(store, platform=platform, item_ids=item_ids, focus=focus)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    @tool
    def inspect_video(
        platform: str,
        item_id: str,
        focus: str = "",
    ) -> str:
        """使用 Gemini 原生多模态能力观看并听取单条短视频（画面、语音、口吻、字幕、环境线索），支持 douyin / xhs / bilibili / weibo。受限于体积上限 25MB，请仅挑选最具代表性的 1~2 条视频调用。"""
        res = exec_inspect_video(store, platform=platform, item_id=item_id, focus=focus)
        return json.dumps(res.data if res.ok else {"error": res.error}, ensure_ascii=False)

    return [
        list_platform_status,
        search_users,
        get_platform_profile_summary,
        get_content_detail,
        get_bilibili_archives,
        get_timeline,
        analyze_social_graph,
        fetch_social_sample,
        inspect_images,
        inspect_video,
    ]


def dispatch_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    store: DataStore,
    existing_evidence: dict[str, dict[str, Any]],
    *,
    media_catalog: Optional[dict[str, Any]] = None,
    confirmed_accounts: Optional[dict[str, str]] = None,
) -> tuple[str, dict[str, dict[str, Any]], list[dict[str, Any]], ToolExecResult]:
    """
    执行单次工具调用，自动分配新证据编号 [E#]，并将返回文本用 <untrusted_user_data> 隔离。
    返回: (tool_message_text, new_evidence_map, new_gaps, exec_result)
    """
    args = tool_args if isinstance(tool_args, dict) else {}
    try:
        if tool_name == "list_platform_status":
            res = exec_list_platform_status()
        elif tool_name == "search_users":
            res = exec_search_users(
                keyword=str(args.get("keyword") or ""),
                platforms=args.get("platforms"),
                limit=args.get("limit", 5),
            )
        elif tool_name == "get_platform_profile_summary":
            res = exec_get_platform_summary(
                store,
                platform=str(args.get("platform") or ""),
                uid=str(args.get("uid") or ""),
                refresh=bool(args.get("refresh", False)),
            )
        elif tool_name == "get_content_detail":
            res = exec_get_content_detail(
                platform=str(args.get("platform") or ""),
                item_id=str(args.get("item_id") or ""),
                media_catalog=media_catalog,
            )
        elif tool_name == "get_bilibili_archives":
            res = exec_get_bilibili_archives(
                uid=str(args.get("uid") or ""),
                source=str(args.get("source") or "aicu_reply"),
                page=args.get("page", 1),
                page_size=args.get("page_size", 20),
            )
        elif tool_name == "get_timeline":
            res = exec_get_timeline(
                store,
                platform_uids=args.get("platform_uids") or {},
                source=str(args.get("source") or "stored"),
                limit=args.get("limit", 40),
            )
        elif tool_name == "analyze_social_graph":
            gid = args.get("graph_id")
            res = exec_analyze_social_graph(
                store,
                graph_id=int(gid) if gid not in (None, "") else None,
                target_accounts=args.get("target_accounts"),
            )
        elif tool_name == "fetch_social_sample":
            res = exec_fetch_social_sample(
                platform=str(args.get("platform") or ""),
                uid=str(args.get("uid") or ""),
                follows_limit=args.get("follows_limit", 30),
                followers_limit=args.get("followers_limit", 20),
            )
        elif tool_name == "inspect_images":
            raw_ids = args.get("item_ids")
            if isinstance(raw_ids, str):
                raw_ids = [raw_ids]
            res = exec_inspect_images(
                store,
                platform=str(args.get("platform") or ""),
                item_ids=raw_ids if isinstance(raw_ids, list) else None,
                image_urls=args.get("image_urls") if isinstance(args.get("image_urls"), list) else None,
                focus=str(args.get("focus") or ""),
                media_catalog=media_catalog,
                confirmed_accounts=confirmed_accounts,
            )
        elif tool_name == "inspect_video":
            res = exec_inspect_video(
                store,
                platform=str(args.get("platform") or ""),
                item_id=str(args.get("item_id") or ""),
                focus=str(args.get("focus") or ""),
                media_catalog=media_catalog,
                confirmed_accounts=confirmed_accounts,
            )
        else:
            res = ToolExecResult(
                ok=False,
                summary_text=f"未知工具 {tool_name}",
                error_kind="unknown_tool",
                error=f"未注册的工具名: {tool_name}",
            )
    except Exception as e:
        res = ToolExecResult(
            ok=False,
            summary_text=f"工具 {tool_name} 执行异常",
            error_kind=classify_error(str(e)),
            error=str(e),
        )

    new_evidence: dict[str, dict[str, Any]] = {}
    assigned_ids: list[str] = []
    for idx, item in enumerate(res.evidence_items, start=1):
        eid = next_evidence_id(existing_evidence, offset=idx)
        entry = {"id": eid, **item}
        new_evidence[eid] = entry
        assigned_ids.append(eid)

    if not res.ok:
        msg_payload = {
            "ok": False,
            "error_kind": res.error_kind,
            "error": res.error,
            "hint": "已自动记录到信息盲区，无需重复重试同一失败请求。",
        }
        return json.dumps(msg_payload, ensure_ascii=False), new_evidence, res.gaps, res

    header = f"工具 {tool_name} 执行成功（新增证据编号: {', '.join(f'[{eid}]' for eid in assigned_ids) or '无'}）。\n"
    wrapped = wrap_untrusted_data(tool_name, res.data, max_chars=9000)
    return header + wrapped, new_evidence, res.gaps, res
