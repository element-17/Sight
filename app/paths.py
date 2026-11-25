"""
运行时路径解析

同时兼容源码直接运行（`python run.py`）与 PyInstaller 独立可执行包：
- 只读内置资源（前端静态目录 app/web、版本文件等）通过 `get_bundle_dir()` 定位
- 可写运行数据（credentials/、data/、logs/、tmp/）通过 `get_runtime_dir()` 定位
"""
import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """当前是否处于 PyInstaller 冻结打包后的独立可执行环境中。"""
    return bool(getattr(sys, "frozen", False))


def get_bundle_dir() -> Path:
    """返回只读内置资源根目录。

    - PyInstaller 打包运行：返回 `sys._MEIPASS`（onedir 模式下为 `_internal/`）
    - 源码直接运行：返回仓库根目录
    """
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent.parent


def get_runtime_dir() -> Path:
    """返回可写数据根目录（用于存放 credentials/、data/、logs/、tmp/）。

    解析优先级：
      1. 环境变量 `SIGHT_DATA_DIR`（便于自定义存储路径或隔离测试）
      2. PyInstaller 打包运行：可执行文件所在目录（便携式存储）
      3. 源码直接运行：仓库根目录
    """
    override = os.environ.get("SIGHT_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
