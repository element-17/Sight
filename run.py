"""
Sight 多源公开实体画像与社交关系图谱分析平台 - 启动入口

用法:
    python run.py                         # 默认监听 http://127.0.0.1:5001
    python run.py --port 8080             # 自定义端口
    python run.py --host 0.0.0.0          # 允许局域网访问
    python run.py --no-browser            # 独立打包运行时不自动打开浏览器
    python run.py --version               # 输出当前版本并退出
"""
import argparse
import multiprocessing
import os
import shutil
import threading
import webbrowser

from app import create_app
from app.config import (
    DEFAULT_PLATFORM,
    DEFAULT_TARGET_UID,
    FLASK_DEBUG,
    FLASK_HOST,
    FLASK_PORT,
)
from app.credentials import CredentialManager
from app.paths import get_runtime_dir, is_frozen
from app.platforms import get_adapter
from app.version import get_version


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="Sight",
        description="Sight 多源公开实体画像与社交关系图谱分析平台",
    )
    parser.add_argument("--host", default=FLASK_HOST, help=f"监听地址（默认 {FLASK_HOST}）")
    parser.add_argument("--port", type=int, default=FLASK_PORT, help=f"监听端口（默认 {FLASK_PORT}）")
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=FLASK_DEBUG,
        help="开启 Flask 调试模式",
    )
    parser.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="关闭 Flask 调试模式",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=os.environ.get("SIGHT_NO_BROWSER", "").strip().lower() in ("1", "true", "yes"),
        help="启动后不自动打开浏览器",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Sight {get_version()}",
    )
    return parser.parse_args(argv)


def _startup_check(host: str, port: int):
    """启动前检查各平台连接与运行环境"""
    version = get_version()
    print("=" * 58)
    print(f"  📊  Sight ({version}) · 多源实体画像与关系图谱平台")
    print("=" * 58)

    # ---- 检查各平台连接 ----
    platforms = CredentialManager.get_available_platforms()
    for p in platforms:
        pid = p["id"]
        if p["has_credential"]:
            try:
                adapter = get_adapter(pid)
                if adapter and adapter.check_alive():
                    login = adapter.get_login_user()
                    if login:
                        print(f"  ✓ {p['name']}: {login.get('nickname', login.get('uid', '?'))} (UID: {login.get('uid', '?')})")
                    else:
                        print(f"  ✓ {p['name']}: 已连接")
                else:
                    reason = getattr(adapter, "_init_error", "") if adapter else ""
                    suffix = f"（{reason}）" if reason else ""
                    print(f"  ⚠ {p['name']}: 凭证已配置但未通过验证{suffix}")
            except Exception as e:
                print(f"  ⚠ {p['name']}: {e}")
        else:
            print(f"  ○ {p['name']}: 未配置凭证（在面板中配置 Cookie 即可启用）")

    # 默认监控用户
    if DEFAULT_TARGET_UID:
        try:
            adapter = get_adapter(DEFAULT_PLATFORM)
            if adapter:
                profile = adapter.get_profile(DEFAULT_TARGET_UID)
                if profile:
                    print(f"  ✓ 默认监控: {profile.nickname} ({DEFAULT_PLATFORM}, UID: {DEFAULT_TARGET_UID})")
        except Exception:
            pass

    if not shutil.which("node"):
        print("  ℹ 未检测到 Node.js：小红书/抖音部分 JS 签名接口需本机安装 Node.js 22+，其余平台不受影响")

    if is_frozen():
        print(f"  ✓ 数据目录: {get_runtime_dir()}")

    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"  ✓ 面板地址: http://{display_host}:{port}")
    print("=" * 58)


def _schedule_open_browser(host: str, port: int):
    """打包独立运行时延迟 1.2 秒自动拉起默认浏览器"""
    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{browser_host}:{port}"

    def _open():
        try:
            webbrowser.open(url)
        except Exception:
            pass

    timer = threading.Timer(1.2, _open)
    timer.daemon = True
    timer.start()


def main(argv: list[str] | None = None):
    """启动前检查 + 启动服务器"""
    args = _parse_args(argv)
    debug = bool(args.debug) and not is_frozen()

    # Flask debug 模式下 reloader 会启动父子两个进程，仅在实际服务进程执行一次启动探测
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _startup_check(args.host, args.port)
        if is_frozen() and not args.no_browser:
            _schedule_open_browser(args.host, args.port)

    app = create_app()
    app.run(
        host=args.host,
        port=args.port,
        debug=debug,
        use_reloader=debug and not is_frozen(),
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
