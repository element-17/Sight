"""
Sight 跨平台独立可执行包构建脚本（Windows / macOS / Linux）

流程：
  1. （可选）构建 frontend 生产产物至 app/web/
  2. 写入临时构建版本文件 app/VERSION（构建结束后自动清理，不污染工作区）
  3. 调用 PyInstaller 按 packaging/sight.spec 生成独立目录包 dist/Sight/
  4. 写入配套说明文档与启动脚本，并按当前平台打包为 .zip（Windows）或 .tar.gz（macOS/Linux）

用法：
    python scripts/build_release.py --version v0.2.0
    python scripts/build_release.py --version v0.2.0 --skip-frontend
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = REPO_ROOT / "packaging" / "sight.spec"
VERSION_FILE = REPO_ROOT / "app" / "VERSION"
WEB_INDEX = REPO_ROOT / "app" / "web" / "index.html"


def detect_target() -> tuple[str, str]:
    """返回标准化的 (os_name, arch_name)，例如 ('windows', 'x64') / ('macos', 'arm64')。"""
    raw_os = platform.system().lower()
    if raw_os.startswith("win"):
        os_name = "windows"
    elif raw_os == "darwin":
        os_name = "macos"
    else:
        os_name = "linux"

    raw_arch = platform.machine().lower()
    arch_map = {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
        "i386": "x86",
        "i686": "x86",
        "x86": "x86",
    }
    arch_name = arch_map.get(raw_arch, raw_arch or "unknown")
    return os_name, arch_name


def normalize_version(raw: str) -> tuple[str, str]:
    """返回 (clean_version, tag_version)，例如 ('0.2.0', 'v0.2.0')。"""
    clean = raw.strip().lstrip("vV")
    if not clean:
        raise ValueError("版本号不能为空")
    return clean, f"v{clean}"


def build_frontend_if_needed(skip_frontend: bool):
    """确保 app/web/index.html 已构建就绪。"""
    if not skip_frontend:
        frontend_dir = REPO_ROOT / "frontend"
        npm_cmd = shutil.which("npm")
        if not npm_cmd:
            raise RuntimeError("未找到 npm，请先安装 Node.js 或提前构建前端后使用 --skip-frontend")
        print("[build_release] 正在构建前端产物 (frontend -> app/web)...")
        subprocess.run([npm_cmd, "run", "build"], cwd=str(frontend_dir), check=True)

    if not WEB_INDEX.is_file():
        raise FileNotFoundError(
            f"未找到前端构建产物 {WEB_INDEX}，请先在 frontend/ 执行 `npm run build`"
        )


def write_bundle_companion_files(bundle_dir: Path, tag_version: str, os_name: str):
    """向打包目录写入使用说明与一键启动脚本。"""
    if os_name == "windows":
        launch_hint = "双击 `Sight.exe`（或 `start.bat`），或在终端执行 `.\\Sight.exe`"
        platform_tip = ""
    elif os_name == "macos":
        launch_hint = "双击 `start.command`，或在终端执行 `./Sight`"
        platform_tip = (
            "\nmacOS 首次运行提示：\n"
            "  若系统提示「无法验证开发者 / 已损坏」，可在解压目录打开终端执行：\n"
            "    xattr -dr com.apple.quarantine .\n"
            "  然后再运行 `./Sight`。\n"
        )
    else:
        launch_hint = "在终端执行 `./Sight` 或 `./start.sh`"
        platform_tip = ""

    readme_text = (
        f"Sight {tag_version} · 独立可执行包\n"
        f"{'=' * 48}\n\n"
        f"快速启动：\n"
        f"  1. {launch_hint}\n"
        f"  2. 启动后将自动打开浏览器，默认访问地址：http://127.0.0.1:5001\n\n"
        f"常用启动参数：\n"
        f"  --port 8080         自定义监听端口（默认 5001）\n"
        f"  --host 0.0.0.0      允许局域网设备访问（默认 127.0.0.1）\n"
        f"  --no-browser        启动时不自动打开浏览器\n"
        f"  --version           输出当前版本号\n\n"
        f"数据持久化目录：\n"
        f"  凭证 (credentials/)、SQLite 快照库 (data/) 与日志 (logs/) 默认保存在\n"
        f"  可执行文件同级目录，也可通过环境变量 SIGHT_DATA_DIR 自定义位置。\n\n"
        f"可选运行依赖说明：\n"
        f"  - 无需安装 Python 或前端依赖，解压即可运行。\n"
        f"  - 小红书 / 抖音部分 JS 签名接口依赖本机 Node.js 22+（未安装时其余平台不受影响）。\n"
        f"{platform_tip}"
    )
    (bundle_dir / "README.txt").write_text(readme_text, encoding="utf-8")

    if os_name == "windows":
        bat = bundle_dir / "start.bat"
        bat.write_text(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "cd /d \"%~dp0\"\r\n"
            "Sight.exe %*\r\n"
            "if errorlevel 1 pause\r\n",
            encoding="utf-8",
        )
    elif os_name == "macos":
        cmd_file = bundle_dir / "start.command"
        cmd_file.write_text(
            "#!/bin/bash\n"
            "set -e\n"
            "cd \"$(dirname \"$0\")\"\n"
            "exec ./Sight \"$@\"\n",
            encoding="utf-8",
            newline="\n",
        )
        _make_executable(cmd_file)
    else:
        sh_file = bundle_dir / "start.sh"
        sh_file.write_text(
            "#!/usr/bin/env bash\n"
            "set -e\n"
            "cd \"$(dirname \"$0\")\"\n"
            "exec ./Sight \"$@\"\n",
            encoding="utf-8",
            newline="\n",
        )
        _make_executable(sh_file)


def _make_executable(path: Path):
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def package_archive(bundle_dir: Path, output_dir: Path, tag_version: str, os_name: str, arch_name: str) -> Path:
    """将 dist/Sight 目录打包为对应平台归档文件（保留顶层 Sight/ 目录）。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"Sight-{tag_version}-{os_name}-{arch_name}"

    if os_name == "windows":
        archive_path = output_dir / f"{stem}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for item in sorted(bundle_dir.rglob("*")):
                if item.is_file():
                    arcname = Path(bundle_dir.name) / item.relative_to(bundle_dir)
                    zf.write(item, arcname.as_posix())
    else:
        archive_path = output_dir / f"{stem}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tf:
            tf.add(bundle_dir, arcname=bundle_dir.name)

    return archive_path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建 Sight 独立可执行发行包")
    parser.add_argument("--version", required=True, help="发布版本号，例如 v0.2.0 或 0.2.0")
    parser.add_argument("--output-dir", default="release", help="最终归档输出目录（默认 release）")
    parser.add_argument("--dist-dir", default="dist", help="PyInstaller 输出目录（默认 dist）")
    parser.add_argument("--work-dir", default="build/pyinstaller", help="PyInstaller 临时构建目录")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="跳过 npm run build（需已存在 app/web/index.html）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    clean_version, tag_version = normalize_version(args.version)
    os_name, arch_name = detect_target()

    build_frontend_if_needed(args.skip_frontend)

    dist_dir = (REPO_ROOT / args.dist_dir).resolve()
    work_dir = (REPO_ROOT / args.work_dir).resolve()
    output_dir = (REPO_ROOT / args.output_dir).resolve()

    print(f"[build_release] Target: {os_name}-{arch_name}, Version: {tag_version}")
    VERSION_FILE.write_text(f"{clean_version}\n", encoding="utf-8")
    try:
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir),
            str(SPEC_FILE),
        ]
        print(f"[build_release] Running: {' '.join(cmd)}")
        subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)
    finally:
        VERSION_FILE.unlink(missing_ok=True)

    bundle_dir = dist_dir / "Sight"
    exe_name = "Sight.exe" if os_name == "windows" else "Sight"
    exe_path = bundle_dir / exe_name
    if not exe_path.is_file():
        raise FileNotFoundError(f"PyInstaller 未生成预期可执行文件: {exe_path}")

    write_bundle_companion_files(bundle_dir, tag_version, os_name)
    archive_path = package_archive(bundle_dir, output_dir, tag_version, os_name, arch_name)
    digest = sha256_file(archive_path)
    size_mb = archive_path.stat().st_size / (1024 * 1024)

    print(f"[build_release] ✓ 归档已生成: {archive_path} ({size_mb:.2f} MB)")
    print(f"[build_release] ✓ SHA-256: {digest}")

    github_output = os.environ.get("GITHUB_OUTPUT", "").strip()
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"archive_path={archive_path}\n")
            f.write(f"archive_name={archive_path.name}\n")
            f.write(f"sha256={digest}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
