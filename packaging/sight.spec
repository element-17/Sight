# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（跨平台 Windows / macOS / Linux）

构建方式（推荐使用封装脚本）:
    python scripts/build_release.py --version v0.2.0
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

REPO_ROOT = Path(SPECPATH).resolve().parent
XHS_REF_ROOT = REPO_ROOT / "app" / "platforms" / "xhs"

for path_entry in (str(REPO_ROOT), str(XHS_REF_ROOT)):
    if path_entry not in sys.path:
        sys.path.insert(0, path_entry)

# 收集第三方原生依赖（curl_cffi 含 libcurl 动态库与证书，certifi 含 CA 证书）
curl_datas, curl_binaries, curl_hidden = collect_all("curl_cffi")
certifi_datas = collect_data_files("certifi")
tiktoken_datas = collect_data_files("tiktoken_ext")

metadata_datas = []
for pkg_name in (
    "langgraph",
    "langgraph-checkpoint",
    "langgraph-checkpoint-sqlite",
    "langchain-core",
    "langchain-openai",
    "langchain-anthropic",
    "anthropic",
    "langchain-google-genai",
    "google-genai",
):
    try:
        metadata_datas.extend(copy_metadata(pkg_name))
    except Exception:
        pass

datas = [
    (str(REPO_ROOT / "app" / "web"), "app/web"),
    (str(REPO_ROOT / "app" / "platforms" / "douyin" / "data"), "app/platforms/douyin/data"),
    (str(XHS_REF_ROOT / "ref_xhs_core" / "js"), "ref_xhs_core/js"),
    (str(XHS_REF_ROOT / "ref_xhs_pc" / "js"), "ref_xhs_pc/js"),
    *curl_datas,
    *certifi_datas,
    *tiktoken_datas,
    *metadata_datas,
]

version_file = REPO_ROOT / "app" / "VERSION"
if version_file.is_file():
    datas.append((str(version_file), "app"))

binaries = [
    *curl_binaries,
]

hiddenimports = sorted(
    set(
        collect_submodules("app")
        + collect_submodules("ref_xhs_core")
        + collect_submodules("ref_xhs_pc")
        + collect_submodules("ref_apis")
        + collect_submodules("ref_utils")
        + collect_submodules("langgraph")
        + collect_submodules("langgraph.checkpoint.sqlite")
        + collect_submodules("langchain_core")
        + collect_submodules("langchain_openai")
        + collect_submodules("langchain_anthropic")
        + collect_submodules("anthropic")
        + collect_submodules("langchain_google_genai")
        + collect_submodules("google.genai")
        + collect_submodules("tiktoken_ext")
        + list(curl_hidden)
        + [
            "cffi",
            "_cffi_backend",
            "cryptography",
            "Crypto",
            "Crypto.Cipher",
            "Crypto.Cipher.AES",
            "Crypto.Util.Padding",
            "google.protobuf",
            "google.auth",
            "ecdsa",
            "bs4",
            "loguru",
            "dotenv",
            "flask",
            "werkzeug",
            "jinja2",
            "sqlite3",
            "httpx",
            "openai",
            "pydantic",
            "ormsgpack",
            "xxhash",
            "tenacity",
        ]
    )
)

excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "pytest",
    "playwright",
    "PIL",
    "PyQt5",
    "PyQt6",
    "PySide6",
    "IPython",
    "notebook",
]

a = Analysis(
    [str(REPO_ROOT / "run.py")],
    pathex=[str(REPO_ROOT), str(XHS_REF_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Sight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Sight",
)
