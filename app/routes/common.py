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

bp = Blueprint("api", __name__, url_prefix="/api")

LOG_DIR = get_runtime_dir() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CST = timezone(timedelta(hours=8))

# /all 快照缓存有效期（30 分钟）
SNAPSHOT_TTL = 30 * 60

# 关系图搜索缓存（30 分钟）
SEARCH_CACHE_TTL = 30 * 60
_search_cache: dict[tuple, tuple[float, list]] = {}
_search_cache_lock = threading.Lock()

_AUTH_EXPIRED_KEYWORDS = (
    "登录态已失效",
    "登录已过期",
    "用户未登录",
    "凭证无效或已过期",
    "请更新 Cookie",
    "客户端未初始化",
)


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


def _is_auth_expired_error(msg: str) -> bool:
    """判定子模块错误是否为 Cookie / Token 登录凭证失效"""
    s = str(msg or "")
    return any(k in s for k in _AUTH_EXPIRED_KEYWORDS)


def _snapshot_age(snapshot: dict):
    """快照的年龄（秒）；无法解析时间返回 None"""
    ts = snapshot.get("_snapshot_time")
    if not ts:
        return None
    try:
        return max(0.0, time.time() - datetime.fromisoformat(str(ts)).timestamp())
    except (ValueError, TypeError, OSError):
        return None


def _is_marker(snapshot: dict) -> bool:
    """内容未变化的占位快照（save_snapshot 只存哈希标记，不含真实数据）"""
    return isinstance(snapshot, dict) and bool(snapshot.get("_marker"))


def clear_search_cache(platform: str) -> int:
    """清理关系图搜索缓存中指定平台的条目，返回清理条数"""
    with _search_cache_lock:
        stale = [k for k in _search_cache if k[0] == platform]
        for k in stale:
            del _search_cache[k]
    return len(stale)


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
