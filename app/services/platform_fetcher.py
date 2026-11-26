"""
单平台聚合抓取与快照复用服务

抽离自 routes/platform_routes.py，供 REST API 与 LangGraph Agent 工具共用，
避免 Agent 通过 HTTP 回环调用本机 Flask。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from app.data.store import DataStore
from app.platforms import get_adapter
from app.platforms.base import dataclass_to_dict

# /all 快照缓存有效期（30 分钟）
SNAPSHOT_TTL = 30 * 60

AUTH_EXPIRED_KEYWORDS = (
    "登录态已失效",
    "登录已过期",
    "用户未登录",
    "凭证无效或已过期",
    "请更新 Cookie",
    "客户端未初始化",
)


class AuthExpiredError(RuntimeError):
    """子模块检测到 Cookie / Token 登录凭证失效时立即中断抓取。"""


class AllModulesFailedError(RuntimeError):
    """平台下所有数据模块均加载失败时抛出。"""


def is_auth_expired_error(msg: str) -> bool:
    """判定子模块错误是否为 Cookie / Token 登录凭证失效。"""
    s = str(msg or "")
    return any(k in s for k in AUTH_EXPIRED_KEYWORDS)


def snapshot_age(snapshot: dict) -> Optional[float]:
    """快照的年龄（秒）；无法解析时间返回 None。"""
    ts = snapshot.get("_snapshot_time")
    if not ts:
        return None
    try:
        return max(0.0, time.time() - datetime.fromisoformat(str(ts)).timestamp())
    except (ValueError, TypeError, OSError):
        return None


def is_marker(snapshot: dict) -> bool:
    """内容未变化的占位快照（save_snapshot 只存哈希标记，不含真实数据）。"""
    return isinstance(snapshot, dict) and bool(snapshot.get("_marker"))


def snapshot_is_usable(platform: str, data_type: str, snapshot: dict) -> bool:
    """过滤历史上字段映射修复前落库的无效 xhs 快照。"""
    if platform != "xhs":
        return True
    if not isinstance(snapshot, dict):
        return False
    if data_type == "profile":
        nickname = str(snapshot.get("nickname") or "")
        return bool(nickname) and "\ufffd" not in nickname

    items = snapshot.get("items")
    if not isinstance(items, list) or not items:
        return False
    first = next((item for item in items if isinstance(item, dict)), None)
    if not first:
        return False
    if data_type == "playlists":
        title = str(first.get("title") or "")
        return (
            bool(title)
            and title != "无标题"
            and "\ufffd" not in title
            and ("create_time" in first or "url" in first)
        )
    if data_type == "events":
        content = str(first.get("content") or "")
        return (
            bool(content)
            and content != "无标题"
            and "\ufffd" not in content
            and str(first.get("event_type") or "") == "发布笔记"
            and bool(first.get("timestamp") or first.get("url"))
        )
    return True


def find_fresh_snapshot(
    store: DataStore,
    platform: str,
    uid: str,
    data_type: str,
    *,
    require_items: bool = False,
    ttl: int = SNAPSHOT_TTL,
) -> Optional[dict]:
    """查找指定 TTL 内可用的非标记快照；未命中返回 None。"""
    snaps = [
        s
        for s in store.get_snapshots(platform, uid, data_type, limit=5)
        if not is_marker(s)
    ]
    for s in snaps:
        age = snapshot_age(s)
        if age is None or age >= ttl:
            continue
        if require_items and not s.get("items"):
            continue
        if snapshot_is_usable(platform, data_type, s):
            return s
    return None


def find_latest_real_snapshot(
    store: DataStore,
    platform: str,
    uid: str,
    data_type: str,
    *,
    require_items: bool = False,
) -> Optional[dict]:
    """查找最近一条可用的非标记快照（不限 TTL），供 Agent 在限流/离线时兜底读取历史数据。"""
    snaps = [
        s
        for s in store.get_snapshots(platform, uid, data_type, limit=10)
        if not is_marker(s)
    ]
    for s in snaps:
        if require_items and not s.get("items"):
            continue
        if snapshot_is_usable(platform, data_type, s):
            return s
    return None


def fetch_platform_all(
    platform: str,
    uid: str,
    store: DataStore,
    *,
    refresh: bool = False,
    include_social: bool = True,
    include_records: bool = True,
    ttl: int = SNAPSHOT_TTL,
) -> tuple[dict, list[str]]:
    """
    聚合获取平台全量数据（资料 / 内容 / 历史 / 动态 / 关注 / 粉丝）。

    - profile / playlists / events 优先命中 TTL 内的新鲜快照（refresh=True 强制实时）。
    - 任一子模块检测到 Cookie/登录态失效时立即抛出 AuthExpiredError（Fail-Fast）。
    - 所有模块全部失败且无任何数据时抛出 AllModulesFailedError。
    """
    adapter = get_adapter(platform)
    if not adapter:
        raise KeyError(f"未知平台: {platform}")

    result = {
        "platform": platform,
        "uid": uid,
        "profile": None,
        "playlists": [],
        "records": {"allTime": [], "weekly": []},
        "events": [],
        "follows": [],
        "followers": [],
    }
    errors: list[str] = []
    pending_snapshots: list[tuple[str, dict]] = []

    def _record_error(module_name: str, exc: Exception):
        err_text = f"{module_name}: {exc}"
        errors.append(err_text)
        if is_auth_expired_error(err_text):
            raise AuthExpiredError(err_text) from exc

    # 1. 用户资料
    try:
        fresh = None if refresh else find_fresh_snapshot(store, platform, uid, "profile", ttl=ttl)
        if fresh:
            result["profile"] = fresh
        else:
            profile = adapter.get_profile(uid)
            if profile:
                profile_dict = dataclass_to_dict(profile)
                result["profile"] = profile_dict
                pending_snapshots.append(("profile", profile_dict))
    except AuthExpiredError:
        raise
    except Exception as e:
        _record_error("profile", e)

    # 2. 内容列表（歌单 / 视频 / 作品 / 笔记 / 仓库）
    try:
        snap_pl = (
            None
            if refresh
            else find_fresh_snapshot(store, platform, uid, "playlists", require_items=True, ttl=ttl)
        )
        if snap_pl:
            result["playlists"] = snap_pl["items"]
            print(
                f"[{platform}] /all playlists 命中新鲜快照({int(snapshot_age(snap_pl) or 0)}s): "
                f"{len(result['playlists'])} 项"
            )
        else:
            item_dicts = [dataclass_to_dict(i) for i in adapter.get_content_lists(uid)]
            result["playlists"] = item_dicts
            if item_dicts:
                pending_snapshots.append(("playlists", {"count": len(item_dicts), "items": item_dicts}))
                print(f"[{platform}] /all playlists 实时拉取: {len(item_dicts)} 项")
            else:
                print(f"[{platform}] /all playlists 实时拉取为空")
    except AuthExpiredError:
        raise
    except Exception as e:
        print(f"[{platform}] /all playlists 异常: {e}")
        _record_error("playlists", e)

    # 3. 历史 / 听歌排行（网易云专有）
    if include_records:
        try:
            if platform == "netease":
                all_data = [dataclass_to_dict(e) for e in adapter.get_history(uid, "all")]
                week_data = [dataclass_to_dict(e) for e in adapter.get_history(uid, "week")]
                result["records"] = {"allTime": all_data, "weekly": week_data}
                if all_data or week_data:
                    pending_snapshots.append(("records", {"allTime": all_data, "weekly": week_data}))
        except AuthExpiredError:
            raise
        except Exception as e:
            _record_error("records", e)

    # 4. 动态
    try:
        snap_ev = (
            None
            if refresh
            else find_fresh_snapshot(store, platform, uid, "events", require_items=True, ttl=ttl)
        )
        if snap_ev:
            result["events"] = snap_ev["items"]
            print(
                f"[{platform}] /all events 命中新鲜快照({int(snapshot_age(snap_ev) or 0)}s): "
                f"{len(result['events'])} 条"
            )
        else:
            event_dicts = [dataclass_to_dict(e) for e in adapter.get_events(uid)]
            result["events"] = event_dicts
            if event_dicts:
                pending_snapshots.append(("events", {"count": len(event_dicts), "items": event_dicts}))
                print(f"[{platform}] /all events 实时拉取: {len(event_dicts)} 条")
            else:
                print(f"[{platform}] /all events 实时拉取为空")
    except AuthExpiredError:
        raise
    except Exception as e:
        print(f"[{platform}] /all events 异常: {e}")
        _record_error("events", e)

    # 5. 关注 / 粉丝
    if include_social:
        for field_name, method_name in (("follows", "get_follows"), ("followers", "get_followers")):
            try:
                items_list, _more, _total = getattr(adapter, method_name)(uid)
                result[field_name] = items_list
                if items_list:
                    pending_snapshots.append((field_name, {"count": len(items_list), "items": items_list}))
            except AuthExpiredError:
                raise
            except Exception as e:
                _record_error(field_name, e)

    for snap_type, snap_payload in pending_snapshots:
        store.save_snapshot(platform, uid, snap_type, snap_payload)

    has_any_data = any(
        (
            result["profile"] is not None,
            result["playlists"],
            result["events"],
            result["follows"],
            result["followers"],
            result["records"].get("allTime"),
            result["records"].get("weekly"),
        )
    )
    if not has_any_data:
        raise AllModulesFailedError("; ".join(errors))

    return result, errors


def fetch_content_detail(platform: str, item_id: str) -> Optional[dict]:
    """获取单条内容详情（歌单曲目 / GitHub 仓库提交等）。"""
    adapter = get_adapter(platform)
    if not adapter:
        raise KeyError(f"未知平台: {platform}")
    return adapter.get_content_detail(item_id)
