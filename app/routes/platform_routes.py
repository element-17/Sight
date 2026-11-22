"""单平台数据抓取、聚合快照 (/all)、B 站存档与 QQ 音乐扫码登录路由"""
import time

from flask import request

from app.platforms import get_adapter
from app.platforms.base import dataclass_to_dict
from app.routes.common import (
    SNAPSHOT_TTL,
    _error,
    _get_uid,
    _is_auth_expired_error,
    _is_marker,
    _log_fetch,
    _result,
    _snapshot_age,
    bp,
    get_store,
)


def _snapshot_is_usable(platform: str, data_type: str, snapshot: dict) -> bool:
    """过滤历史上字段映射修复前落库的无效 xhs 快照"""
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
        return bool(title) and title != "无标题" and "\ufffd" not in title and ("create_time" in first or "url" in first)
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


def _find_fresh_snapshot(platform: str, uid: str, data_type: str, require_items: bool = False):
    """查找 30 分钟内可用的非标记快照；未命中返回 None"""
    snaps = [
        s for s in get_store().get_snapshots(platform, uid, data_type, limit=5)
        if not _is_marker(s)
    ]
    for s in snaps:
        age = _snapshot_age(s)
        if age is None or age >= SNAPSHOT_TTL:
            continue
        if require_items and not s.get("items"):
            continue
        if _snapshot_is_usable(platform, data_type, s):
            return s
    return None


@bp.route("/bilibili/archives")
def bilibili_archives():
    """按需查询一页第三方评论/弹幕存档，不向第三方传递 B 站凭证"""
    from app.services.bilibili_archives import archives

    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "20"))
        data = archives.fetch(
            request.args.get("source", "aicu_reply"),
            request.args.get("uid", "").strip(),
            page,
            page_size,
        )
        return _result(data)
    except ValueError as e:
        return _error(str(e), http_status=400)
    except Exception as e:
        return _error(str(e), http_status=502)


@bp.route("/<platform>/search")
def search_user(platform):
    """单平台用户搜索"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return _error("请输入搜索关键词", http_status=400)

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        return _result(adapter.search_user(keyword))
    except Exception as e:
        return _error(str(e))


@bp.route("/<platform>/playlist/<item_id>")
def content_detail(platform, item_id):
    """获取内容详情（歌单曲目 / GitHub 仓库提交等）"""
    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        detail = adapter.get_content_detail(item_id)
        if detail is None:
            return _error("获取详情失败")
        return _result(detail)
    except Exception as e:
        return _error(str(e))


@bp.route("/<platform>/all")
def platform_all(platform):
    """
    聚合获取平台全量数据（资料/内容/历史/动态/关注/粉丝）。
    - profile/playlists/events 优先命中 30 分钟内的新鲜快照（refresh=1 强制实时）。
    - 任一子模块检测到 Cookie/登录态失效时立即快速失败（Fail-Fast），拒绝返回旧快照或未登录残缺数据。
    """
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID")

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    refresh = request.args.get("refresh", "").strip() in ("1", "true")
    t0 = time.perf_counter()

    try:
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

        def _handle_error(module_name: str, exc: Exception):
            err_text = f"{module_name}: {exc}"
            errors.append(err_text)
            if _is_auth_expired_error(err_text):
                elapsed_ms = (time.perf_counter() - t0) * 1000
                _log_fetch("GET /all", platform, uid, False, elapsed_ms, f"auth_expired: {err_text}")
                return _error("登录凭证已失效，请更新 Cookie 后重试: " + err_text)
            return None

        # 1. 用户资料
        try:
            fresh = None if refresh else _find_fresh_snapshot(platform, uid, "profile")
            if fresh:
                result["profile"] = fresh
            else:
                profile = adapter.get_profile(uid)
                if profile:
                    profile_dict = dataclass_to_dict(profile)
                    result["profile"] = profile_dict
                    pending_snapshots.append(("profile", profile_dict))
        except Exception as e:
            early = _handle_error("profile", e)
            if early is not None:
                return early

        # 2. 内容列表（歌单/视频/作品/笔记/仓库）
        try:
            snap_pl = None if refresh else _find_fresh_snapshot(platform, uid, "playlists", require_items=True)
            if snap_pl:
                result["playlists"] = snap_pl["items"]
                print(f"[{platform}] /all playlists 命中新鲜快照({int(_snapshot_age(snap_pl) or 0)}s): {len(result['playlists'])} 项")
            else:
                item_dicts = [dataclass_to_dict(i) for i in adapter.get_content_lists(uid)]
                result["playlists"] = item_dicts
                if item_dicts:
                    pending_snapshots.append(("playlists", {"count": len(item_dicts), "items": item_dicts}))
                    print(f"[{platform}] /all playlists 实时拉取: {len(item_dicts)} 项")
                else:
                    print(f"[{platform}] /all playlists 实时拉取为空")
        except Exception as e:
            print(f"[{platform}] /all playlists 异常: {e}")
            early = _handle_error("playlists", e)
            if early is not None:
                return early

        # 3. 历史/听歌排行（网易云专有）
        try:
            if platform == "netease":
                all_data = [dataclass_to_dict(e) for e in adapter.get_history(uid, "all")]
                week_data = [dataclass_to_dict(e) for e in adapter.get_history(uid, "week")]
                result["records"] = {"allTime": all_data, "weekly": week_data}
                if all_data or week_data:
                    pending_snapshots.append(("records", {"allTime": all_data, "weekly": week_data}))
        except Exception as e:
            early = _handle_error("records", e)
            if early is not None:
                return early

        # 4. 动态
        try:
            snap_ev = None if refresh else _find_fresh_snapshot(platform, uid, "events", require_items=True)
            if snap_ev:
                result["events"] = snap_ev["items"]
                print(f"[{platform}] /all events 命中新鲜快照({int(_snapshot_age(snap_ev) or 0)}s): {len(result['events'])} 条")
            else:
                event_dicts = [dataclass_to_dict(e) for e in adapter.get_events(uid)]
                result["events"] = event_dicts
                if event_dicts:
                    pending_snapshots.append(("events", {"count": len(event_dicts), "items": event_dicts}))
                    print(f"[{platform}] /all events 实时拉取: {len(event_dicts)} 条")
                else:
                    print(f"[{platform}] /all events 实时拉取为空")
        except Exception as e:
            print(f"[{platform}] /all events 异常: {e}")
            early = _handle_error("events", e)
            if early is not None:
                return early

        # 5. 关注 / 粉丝
        for field_name, method_name in (("follows", "get_follows"), ("followers", "get_followers")):
            try:
                items_list, _more, _total = getattr(adapter, method_name)(uid)
                result[field_name] = items_list
                if items_list:
                    pending_snapshots.append((field_name, {"count": len(items_list), "items": items_list}))
            except Exception as e:
                early = _handle_error(field_name, e)
                if early is not None:
                    return early

        elapsed_ms = (time.perf_counter() - t0) * 1000
        for snap_type, snap_payload in pending_snapshots:
            get_store().save_snapshot(platform, uid, snap_type, snap_payload)

        has_any_data = any(
            (
                result["profile"] is not None,
                result["playlists"],
                result["events"],
                result["follows"],
                result["followers"],
            )
        )
        if not has_any_data:
            detail = "all_failed: " + "; ".join(errors)
            _log_fetch("GET /all", platform, uid, False, elapsed_ms, detail)
            return _error("所有数据模块均加载失败: " + "; ".join(errors))

        detail = ""
        if errors:
            detail = "partial: " + "; ".join(errors)
            result["_errors"] = errors
            print(f"[{platform}] /all 部分数据加载失败: {'; '.join(errors)}")

        _log_fetch("GET /all", platform, uid, True, elapsed_ms, detail)
        return _result(result)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _log_fetch("GET /all", platform, uid, False, elapsed_ms, str(e))
        return _error(str(e))


# ==================== QQ音乐 QR 扫码登录 ====================

@bp.route("/qqmusic/qr-login/start", methods=["POST"])
def qr_login_start():
    """启动 QQ 音乐 QR 扫码登录"""
    from app.services.qqmusic_qr_login import get_session

    body = request.get_json(force=True, silent=True) or {}
    target_uid = body.get("uid", "oK6kowEAoK4z7Knioivl7evl7n**")
    return _result(get_session().start(target_uid))


@bp.route("/qqmusic/qr-login/status")
def qr_login_status():
    """轮询 QR 登录状态"""
    from app.services.qqmusic_qr_login import get_session

    return _result(get_session().get_status_dict())


@bp.route("/qqmusic/qr-login/stop", methods=["POST"])
def qr_login_stop():
    """停止 QR 登录会话"""
    from app.services.qqmusic_qr_login import get_session

    get_session().stop()
    return _result({"status": "stopped"})
