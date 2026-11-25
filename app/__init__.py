"""
多平台用户数据监控面板
Flask 应用工厂
"""
import os
import sys
import io

# 修复 Windows 终端 GBK 编码问题（兼容打包后无 buffer 或已是 UTF-8 的场景）
if sys.platform == "win32":
    if getattr(sys.stdout, "buffer", None) is not None and (getattr(sys.stdout, "encoding", "") or "").lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if getattr(sys.stderr, "buffer", None) is not None and (getattr(sys.stderr, "encoding", "") or "").lower() != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from flask import Flask

from app.paths import get_bundle_dir


def create_app() -> Flask:
    """创建并配置 Flask 应用"""
    web_dir = get_bundle_dir() / "app" / "web"
    app = Flask(
        __name__,
        static_folder=str(web_dir),  # Vite 构建产物目录（frontend/ 执行 npm run build 生成）
        static_url_path="",          # 静态资源挂根路径：/assets/...、/favicon.svg
    )
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

    # 镜像 stdout/stderr 到内存日志中枢（前端终端面板的数据源）
    from app.services.log_hub import install_tee
    install_tee()

    # 注册路由
    from app.routes.api import bp as api_bp
    from app.routes.views import bp as views_bp
    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)

    return app
