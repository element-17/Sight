"""
PyInstaller 独立可执行包冒烟测试脚本

在 CI（Windows / macOS / Linux）构建完 dist/Sight 后真实启动二进制，验证：
  1. `--version` 输出与预期发布版本号一致
  2. 服务可在随机空闲端口正常启动（禁用浏览器自动打开）
  3. `GET /` 正常返回前端 React HTML 页面
  4. `GET /api/platforms` 返回 HTTP 200 且全部 8 个平台适配器均可加载
  5. `GET /api/graph/saved` 正常初始化 SQLite 数据库，且可写数据落盘至 SIGHT_DATA_DIR（而非 _internal）
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

EXPECTED_PLATFORMS = {
    "netease",
    "bilibili",
    "douyin",
    "qqmusic",
    "weibo",
    "genshin",
    "xhs",
    "github",
}


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status), resp.read().decode("utf-8", errors="replace")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="冒烟测试 Sight 独立可执行包")
    parser.add_argument("--bundle-dir", default="dist/Sight", help="可执行包目录（默认 dist/Sight）")
    parser.add_argument("--expected-version", default="", help="预期版本号（例如 v0.2.0 或 0.2.0）")
    parser.add_argument("--timeout", type=float, default=30.0, help="等待服务启动超时秒数")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    bundle_dir = Path(args.bundle_dir).resolve()
    exe_name = "Sight.exe" if platform.system().lower().startswith("win") else "Sight"
    exe_path = bundle_dir / exe_name

    if not exe_path.is_file():
        print(f"[smoke] ERROR: 可执行文件不存在: {exe_path}", file=sys.stderr)
        return 1

    # 1. 验证 --version
    ver_proc = subprocess.run(
        [str(exe_path), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    ver_out = (ver_proc.stdout or ver_proc.stderr or "").strip()
    print(f"[smoke] --version exit={ver_proc.returncode}, output={ver_out!r}")
    if ver_proc.returncode != 0:
        return 1
    if args.expected_version:
        expected_clean = args.expected_version.strip().lstrip("vV")
        if expected_clean not in ver_out:
            print(
                f"[smoke] ERROR: 版本号不匹配，期望包含 {expected_clean!r}，实际为 {ver_out!r}",
                file=sys.stderr,
            )
            return 1

    # 2. 启动独立进程并隔离数据目录
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="sight-smoke-") as tmp_dir:
        data_root = Path(tmp_dir)
        env = os.environ.copy()
        env["SIGHT_DATA_DIR"] = str(data_root)
        env["SIGHT_NO_BROWSER"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        proc = subprocess.Popen(
            [str(exe_path), "--host", "127.0.0.1", "--port", str(port), "--no-browser"],
            cwd=str(bundle_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        try:
            deadline = time.monotonic() + args.timeout
            index_html = ""
            last_err = ""
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    output = proc.stdout.read() if proc.stdout else ""
                    print(
                        f"[smoke] ERROR: 服务提前退出 (code={proc.returncode})\n{output}",
                        file=sys.stderr,
                    )
                    return 1
                try:
                    status, body = http_get(f"{base_url}/", timeout=2.0)
                    if status == 200 and "<html" in body.lower():
                        index_html = body
                        break
                except (urllib.error.URLError, OSError, TimeoutError) as exc:
                    last_err = str(exc)
                time.sleep(0.4)

            if not index_html:
                print(f"[smoke] ERROR: 等待首页就绪超时 ({args.timeout}s): {last_err}", file=sys.stderr)
                return 1
            print(f"[smoke] ✓ GET / 返回 200 ({len(index_html)} bytes)")

            # 3. 验证 /api/platforms（会触发 8 个平台适配器加载）
            status, platforms_raw = http_get(f"{base_url}/api/platforms", timeout=15.0)
            if status != 200:
                print(f"[smoke] ERROR: /api/platforms 返回 HTTP {status}", file=sys.stderr)
                return 1
            platforms_payload = json.loads(platforms_raw)
            if platforms_payload.get("code") != 200:
                print(f"[smoke] ERROR: /api/platforms payload 异常: {platforms_payload}", file=sys.stderr)
                return 1
            returned_ids = {item["id"] for item in platforms_payload.get("data", [])}
            missing = EXPECTED_PLATFORMS - returned_ids
            if missing:
                print(f"[smoke] ERROR: 缺失平台: {sorted(missing)}", file=sys.stderr)
                return 1
            print(f"[smoke] ✓ GET /api/platforms 返回全部 {len(returned_ids)} 个平台")

            # 4. 验证 /api/graph/saved（触发 SQLite DataStore 初始化）
            status, saved_raw = http_get(f"{base_url}/api/graph/saved", timeout=10.0)
            if status != 200:
                print(f"[smoke] ERROR: /api/graph/saved 返回 HTTP {status}", file=sys.stderr)
                return 1
            saved_payload = json.loads(saved_raw)
            if saved_payload.get("code") != 200 or not isinstance(saved_payload.get("data"), list):
                print(f"[smoke] ERROR: /api/graph/saved payload 异常: {saved_payload}", file=sys.stderr)
                return 1
            print("[smoke] ✓ GET /api/graph/saved 返回 200")

            # 5. 验证可写目录落在 SIGHT_DATA_DIR 内
            if not (data_root / "logs").is_dir():
                print(f"[smoke] ERROR: 未在 SIGHT_DATA_DIR 下生成 logs/ 目录: {data_root}", file=sys.stderr)
                return 1
            if not (data_root / "data" / "snapshots.db").is_file():
                print(
                    f"[smoke] ERROR: 未在 SIGHT_DATA_DIR 下生成 data/snapshots.db: {data_root}",
                    file=sys.stderr,
                )
                return 1
            print(f"[smoke] ✓ 可写数据目录隔离验证通过: {data_root}")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            if proc.stdout:
                proc.stdout.close()

    print("[smoke] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
