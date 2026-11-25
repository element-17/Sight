"""
应用配置
"""
import os

from app.paths import is_frozen


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# ==================== 目标用户配置 ====================
# 默认监控的平台
DEFAULT_PLATFORM = "netease"

# 默认监控的用户 UID（空字符串 = 使用 cookie 对应的登录用户）
DEFAULT_TARGET_UID = ""

# ==================== 请求控制 ====================
REQUEST_INTERVAL = 0.8   # 请求间隔（秒），防反爬
REQUEST_TIMEOUT = 15      # 请求超时（秒）
MAX_RETRIES = 3           # 失败重试次数

# ==================== 服务器 ====================
FLASK_HOST = os.environ.get("SIGHT_HOST", "").strip() or "127.0.0.1"
FLASK_PORT = _env_int("SIGHT_PORT", 5001)
# 独立可执行包默认关闭 debug 与 reloader；源码开发运行默认开启
FLASK_DEBUG = _env_bool("SIGHT_DEBUG", default=not is_frozen())
