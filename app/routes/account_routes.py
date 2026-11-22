"""平台管理、凭证配置、多账号池与缓存清理路由"""
import time

from flask import jsonify, request

from app.credentials import CredentialManager, PRIMARY_ACCOUNT_ID
from app.platforms import get_adapter, get_pool, list_platforms, reset_adapter, reset_pool
from app.routes.common import _error, _result, bp, clear_search_cache


@bp.route("/platforms")
def list_platforms_api():
    """列出所有可用平台及其状态"""
    try:
        return jsonify({"code": 200, "data": list_platforms()})
    except Exception as e:
        return _error(str(e))


@bp.route("/credentials/<platform>")
def get_credentials(platform):
    """查看平台凭证状态（掩码显示，不暴露完整 Cookie）"""
    try:
        cookies = CredentialManager.load_cookies(platform)
        masked = {k: (v[:10] + "..." if len(v) > 10 else v) for k, v in cookies.items()}
        return _result({
            "platform": platform,
            "has_credential": bool(cookies),
            "cookie_keys": list(cookies.keys()),
            "cookie_preview": masked,
        })
    except Exception as e:
        return _error(str(e))


@bp.route("/credentials/<platform>", methods=["POST"])
def update_credentials(platform):
    """更新平台主账号 Cookie/Token，保存后重建适配器立即生效"""
    body = request.get_json(silent=True) or {}
    cookie_str = str(body.get("cookie", "")).strip()
    if not cookie_str:
        return _error("cookie 内容为空", http_status=400)
    if platform not in CredentialManager.PLATFORMS:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        CredentialManager.save_cookies(platform, cookie_str)
        reset_adapter(platform)
        cookies = CredentialManager.load_cookies(platform)
        return _result({
            "platform": platform,
            "has_credential": bool(cookies),
            "cookie_keys": list(cookies.keys()),
        })
    except Exception as e:
        return _error(str(e))


@bp.route("/<platform>/cache/clear", methods=["POST"])
def platform_cache_clear(platform):
    """清空平台运行期内存缓存（适配器实例缓存、模块级缓存、关系图搜索缓存）"""
    pool = get_pool(platform)
    if not pool:
        return _error(f"未知平台: {platform}", http_status=404)

    search_cleared = clear_search_cache(platform)
    dropped, cleared = pool.clear_caches()
    return _result({
        "platform": platform,
        "adapters_dropped": dropped,
        "cleared": cleared,
        "search_cache_cleared": search_cleared,
    })


@bp.route("/<platform>/status")
def platform_status(platform):
    """检查指定平台连接状态"""
    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)
    try:
        alive = adapter.check_alive()
        login_user = adapter.get_login_user()
        return _result({
            "platform": platform,
            "alive": alive,
            "login_user": login_user,
        })
    except Exception as e:
        return _error(str(e))


# ==================== 多账号管理 ====================

@bp.route("/accounts/<platform>")
def accounts_list(platform):
    """列出平台的所有账号（主账号 + 附加账号）"""
    if platform not in CredentialManager.PLATFORMS:
        return _error(f"未知平台: {platform}", http_status=404)

    primary = CredentialManager.get_account(platform, PRIMARY_ACCOUNT_ID) or {}
    primary_keys = list(CredentialManager.parse_cookie_str(primary.get("cookie", "")).keys())
    accounts = [{
        "id": PRIMARY_ACCOUNT_ID,
        "name": primary.get("name") or "主账号",
        "primary": True,
        "enabled": bool(primary.get("enabled", True)),
        "has_credential": bool(primary_keys),
        "cookie_keys": primary_keys,
    }]
    for a in CredentialManager.get_accounts(platform):
        if a["id"] == PRIMARY_ACCOUNT_ID:
            continue
        keys = list(CredentialManager.parse_cookie_str(a.get("cookie", "")).keys())
        accounts.append({
            "id": a["id"],
            "name": a.get("name") or a["id"],
            "primary": False,
            "enabled": bool(a.get("enabled", True)),
            "has_credential": bool(a.get("cookie")),
            "cookie_keys": keys,
        })

    return _result({
        "platform": platform,
        "accounts": accounts,
        "pool_size": len([a for a in accounts if a["enabled"] and a["has_credential"]]),
    })


@bp.route("/accounts/<platform>", methods=["POST"])
def accounts_add(platform):
    """添加附加账号（body: {cookie, name?}）"""
    if platform not in CredentialManager.PLATFORMS:
        return _error(f"未知平台: {platform}", http_status=404)
    body = request.get_json(silent=True) or {}
    try:
        account = CredentialManager.add_account(
            platform, str(body.get("cookie", "")), str(body.get("name") or "")
        )
    except ValueError as e:
        return _error(str(e), http_status=400)
    reset_pool(platform)
    return _result({"id": account["id"], "name": account["name"]})


@bp.route("/accounts/<platform>/<account_id>", methods=["POST"])
def accounts_update(platform, account_id):
    """更新账号（body: {name?, cookie?, enabled?}，主账号与附加账号通用）"""
    body = request.get_json(silent=True) or {}
    account = CredentialManager.update_account(
        platform,
        account_id,
        name=body.get("name"),
        cookie=body.get("cookie"),
        enabled=body.get("enabled"),
    )
    if not account:
        return _error("账号不存在", http_status=404)
    reset_pool(platform)
    return _result({"id": account["id"], "name": account["name"]})


@bp.route("/accounts/<platform>/<account_id>", methods=["DELETE"])
def accounts_delete(platform, account_id):
    """删除附加账号（主账号不可删除）"""
    if account_id == PRIMARY_ACCOUNT_ID:
        return _error("主账号不可删除，可停用或通过 /credentials/<platform> 覆盖", http_status=400)
    if not CredentialManager.remove_account(platform, account_id):
        return _error("账号不存在", http_status=404)
    reset_pool(platform)
    return _result({"deleted": account_id})


@bp.route("/accounts/<platform>/<account_id>/test", methods=["POST"])
def accounts_test(platform, account_id):
    """测试单个账号凭证可用性（真实调用平台接口探测）"""
    pool = get_pool(platform)
    if not pool:
        return _error(f"未知平台: {platform}", http_status=404)

    adapter = pool.adapter_for_account(account_id)
    if adapter is None:
        if any(a["id"] == account_id for a in CredentialManager.get_accounts(platform)):
            return _result({"ok": False, "error": "账号已停用，启用后才能测试"})
        return _error("账号不存在", http_status=404)

    t0 = time.perf_counter()
    try:
        result = adapter.test_account()
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    result["account_id"] = account_id
    return _result(result)
