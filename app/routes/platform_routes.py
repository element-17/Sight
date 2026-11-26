"""单平台数据抓取、聚合快照 (/all)、B 站存档与 QQ 音乐扫码登录路由"""
import time

from flask import request

from app.platforms import get_adapter
from app.routes.common import (
    _error,
    _get_uid,
    _log_fetch,
    _result,
    bp,
    get_store,
)
from app.services.platform_fetcher import (
    AllModulesFailedError,
    AuthExpiredError,
    fetch_content_detail,
    fetch_platform_all,
)


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
    try:
        detail = fetch_content_detail(platform, item_id)
        if detail is None:
            return _error("获取详情失败")
        return _result(detail)
    except KeyError as e:
        return _error(str(e).strip("'"), http_status=404)
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

    if not get_adapter(platform):
        return _error(f"未知平台: {platform}", http_status=404)

    refresh = request.args.get("refresh", "").strip() in ("1", "true")
    t0 = time.perf_counter()

    try:
        result, errors = fetch_platform_all(
            platform,
            uid,
            get_store(),
            refresh=refresh,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        detail = ""
        if errors:
            detail = "partial: " + "; ".join(errors)
            result["_errors"] = errors
            print(f"[{platform}] /all 部分数据加载失败: {'; '.join(errors)}")

        _log_fetch("GET /all", platform, uid, True, elapsed_ms, detail)
        return _result(result)
    except AuthExpiredError as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _log_fetch("GET /all", platform, uid, False, elapsed_ms, f"auth_expired: {e}")
        return _error("登录凭证已失效，请更新 Cookie 后重试: " + str(e))
    except AllModulesFailedError as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _log_fetch("GET /all", platform, uid, False, elapsed_ms, f"all_failed: {e}")
        return _error("所有数据模块均加载失败: " + str(e))
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
