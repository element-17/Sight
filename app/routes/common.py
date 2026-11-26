"""
REST API 路由公共基础设施

集中管理 Blueprint 实例、统一响应封装、请求日志、搜索缓存与认证失效判定，
供各领域路由子模块复用，避免单一 api.py 无限膨胀。
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from app.config import DEFAULT_PLATFORM, DEFAULT_TARGET_UID
from app.data.store import DataStore
from app.paths import get_runtime_dir
from app.platforms import get_adapter
from app.services.log_hub import get_log_hub
from app.services.platform_fetcher import (
    AUTH_EXPIRED_KEYWORDS as _AUTH_EXPIRED_KEYWORDS,
    SNAPSHOT_TTL,
    is_auth_expired_error as _is_auth_expired_error,
    is_marker as _is_marker,
    snapshot_age as _snapshot_age,
)
from app.services.search_service import (
    SEARCH_CACHE_TTL,
    _search_cache,
    _search_cache_lock,
    clear_search_cache,
)

bp = Blueprint("api", __name__, url_prefix="/api")

LOG_DIR = get_runtime_dir() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CST = timezone(timedelta(hours=8))


def get_store() -> DataStore:
    """获取共享 DataStore 单例（通过 api._store 暴露，便于测试无缝打桩）"""
    from app.routes import api as api_module

    if api_module._store is None:
        api_module._store = DataStore()
    return api_module._store


def _result(data, code: int = 200):
    """统一成功响应格式"""
    return jsonify({"code": code, "data": data})


def _error(msg: str, code: int = -1, http_status: int = 500):
    """统一错误响应格式"""
    return jsonify({"code": code, "message": msg}), http_status


def _log_fetch(
    method: str,
    platform: str,
    uid: str,
    success: bool,
    elapsed_ms: float,
    detail: str = "",
):
    """记录每次数据拉取请求到日志文件并同步推送到前端终端 SSE"""
    try:
        now = datetime.now(CST)
        log_file = LOG_DIR / f"fetch_{now.strftime('%Y%m%d')}.log"
        status = "OK" if success else "FAIL"
        line = (
            f"{now.strftime('%Y-%m-%d %H:%M:%S')} | {method:6s} | {platform:8s} | "
            f"uid={uid:15s} | {status:4s} | {elapsed_ms:7.1f}ms"
        )
        if detail:
            line += f" | {detail}"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        get_log_hub().publish(
            line,
            level="success" if success else "error",
            source=f"fetch:{platform}",
        )
    except Exception:
        pass  # 日志写入失败不影响主流程


def _get_platform() -> str:
    """获取请求中的平台参数，默认 netease"""
    return request.args.get("platform", DEFAULT_PLATFORM).strip()


def _get_uid(platform: str = None) -> str:
    """获取目标 UID（优先级: 请求参数 > 配置默认 > 登录用户）"""
    uid = request.args.get("uid", "").strip()
    if uid:
        return uid
    if DEFAULT_TARGET_UID and (platform is None or platform == DEFAULT_PLATFORM):
        return DEFAULT_TARGET_UID
    adapter = get_adapter(platform or _get_platform())
    if adapter:
        login_user = adapter.get_login_user()
        if login_user:
            return str(login_user.get("uid", ""))
    return ""
