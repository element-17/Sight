"""
多平台 REST API 路由聚合入口

按业务域拆分至同目录子模块，避免单文件膨胀：
  - common.py          共享 Blueprint、响应封装、日志与缓存工具
  - logs_routes.py     /logs/recent, /logs/stream (SSE)
  - account_routes.py  /platforms, /credentials/*, /accounts/*, /<platform>/status|cache/clear
  - platform_routes.py /<platform>/search|playlist|all, /bilibili/archives, /qqmusic/qr-login/*
  - graph_routes.py    /graph/search|expand/*|refresh_nodes|save|saved*
  - timeline_routes.py /timeline, /timeline/<id>
  - agent_routes.py    /agent/config*, /agent/sessions*
"""
from app.routes.common import (
    SNAPSHOT_TTL,
    _error,
    _is_auth_expired_error,
    _result,
    _search_cache,
    _search_cache_lock,
    bp,
    get_store,
)

# 保留模块级 _store 引用（common.get_store() 读取此变量，兼容测试 patch）
_store = None

# 导入各领域子模块，将其路由注册到共享 Blueprint `bp`
from app.routes import (  # noqa: E402, F401
    account_routes,
    agent_routes,
    graph_routes,
    logs_routes,
    platform_routes,
    timeline_routes,
)

__all__ = [
    "bp",
    "_store",
    "get_store",
    "SNAPSHOT_TTL",
    "_result",
    "_error",
    "_is_auth_expired_error",
    "_search_cache",
    "_search_cache_lock",
]
