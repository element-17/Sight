"""
Sight 版本信息

打包构建时由 `scripts/build_release.py` 将发布版本号写入 `app/VERSION` 并随包分发；
本地源码直接运行时若不存在该文件，则回退为 `dev`。
"""
from app.paths import get_bundle_dir


def get_version() -> str:
    """读取当前 Sight 版本号（不含前导 v，例如 `0.2.0` 或 `dev`）。"""
    version_file = get_bundle_dir() / "app" / "VERSION"
    if version_file.is_file():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            return text.lstrip("vV")
    return "dev"


__version__ = get_version()
