"""
防盗链多平台媒体下载与本地缓存服务

将受 Referer 防盗链或短效签名保护的图片/视频，在 Sight 本机携带平台请求头拉取至
`<runtime_dir>/data/media_cache/`，供：
1. Gemini 原生多模态模型读取字节流或 Files API 上传；
2. 前端证据账本通过 `/api/agent/media/<media_id>` 安全预览缩略图（零 SSRF）。
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from app.credentials import CredentialManager
from app.paths import get_runtime_dir

MAX_IMAGE_BYTES = 8 * 1024 * 1024       # 单张图片上限 8 MB
MAX_VIDEO_BYTES = 25 * 1024 * 1024      # 单条视频上限 25 MB
CACHE_TTL_SECONDS = 24 * 3600           # 本地缓存保留 24 小时
CACHE_MAX_TOTAL_BYTES = 500 * 1024 * 1024

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

PLATFORM_HEADERS: dict[str, dict[str, str]] = {
    "bilibili": {
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    },
    "douyin": {
        "Referer": "https://www.douyin.com/",
        "Origin": "https://www.douyin.com",
    },
    "xhs": {
        "Referer": "https://www.xiaohongshu.com/",
        "Origin": "https://www.xiaohongshu.com",
    },
    "weibo": {
        "Referer": "https://weibo.com/",
    },
    "netease": {
        "Referer": "https://music.163.com/",
    },
    "qqmusic": {
        "Referer": "https://y.qq.com/",
    },
    "github": {
        "Referer": "https://github.com/",
    },
    "genshin": {
        "Referer": "https://enka.network/",
    },
}

_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


@dataclass
class CachedMedia:
    media_id: str
    url: str
    path: Path
    mime_type: str
    size_bytes: int
    kind: str  # "image" | "video"
    platform: str

    @property
    def preview_url(self) -> str:
        return f"/api/agent/media/{self.media_id}"

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


def get_media_cache_dir() -> Path:
    cache_dir = get_runtime_dir() / "data" / "media_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _normalize_url(url: str) -> str:
    u = str(url or "").strip()
    if u.startswith("//"):
        u = "https:" + u
    return u


def _infer_mime(url: str, header_ct: str, kind: str) -> str:
    ct = (header_ct or "").split(";", 1)[0].strip().lower()
    if ct == "image/jpg":
        ct = "image/jpeg"
    if kind == "image" and ct.startswith("image/"):
        return ct
    if kind == "video" and ct.startswith("video/"):
        return ct
    guessed, _ = mimetypes.guess_type(urlparse(url).path)
    if guessed:
        if kind == "image" and guessed.startswith("image/"):
            return guessed
        if kind == "video" and guessed.startswith("video/"):
            return guessed
    return "image/jpeg" if kind == "image" else "video/mp4"


def _cache_key(url: str, kind: str) -> str:
    return hashlib.sha256(f"{kind}:{url}".encode("utf-8")).hexdigest()[:24]


def _purge_stale_cache(cache_dir: Path) -> None:
    """按 TTL 与总容量上限轻量清理过期媒体文件。"""
    now = time.time()
    entries: list[tuple[float, int, Path]] = []
    total_size = 0
    for p in cache_dir.iterdir():
        if not p.is_file() or p.name.endswith(".meta.json"):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if now - st.st_mtime > CACHE_TTL_SECONDS:
            p.unlink(missing_ok=True)
            cache_dir.joinpath(f"{p.stem}.meta.json").unlink(missing_ok=True)
            continue
        total_size += st.st_size
        entries.append((st.st_mtime, st.st_size, p))

    if total_size > CACHE_MAX_TOTAL_BYTES:
        entries.sort(key=lambda x: x[0])
        for _mtime, sz, p in entries:
            if total_size <= int(CACHE_MAX_TOTAL_BYTES * 0.75):
                break
            p.unlink(missing_ok=True)
            cache_dir.joinpath(f"{p.stem}.meta.json").unlink(missing_ok=True)
            total_size -= sz


def _build_request_headers(platform: str) -> dict[str, str]:
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    headers.update(PLATFORM_HEADERS.get(platform, {}))
    return headers


def lookup_cached_media(media_id: str) -> Optional[CachedMedia]:
    """根据严格校验后的十六进制 media_id 查找本地缓存文件（防止路径穿越）。"""
    mid = str(media_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{24}", mid):
        return None
    cache_dir = get_media_cache_dir()
    meta_path = cache_dir / f"{mid}.meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        file_path = cache_dir / str(meta["filename"])
        if not file_path.is_file():
            return None
        # 确保仍在 media_cache 目录内
        if file_path.resolve().parent != cache_dir.resolve():
            return None
        return CachedMedia(
            media_id=mid,
            url=str(meta.get("url") or ""),
            path=file_path,
            mime_type=str(meta.get("mime_type") or "application/octet-stream"),
            size_bytes=file_path.stat().st_size,
            kind=str(meta.get("kind") or "image"),
            platform=str(meta.get("platform") or ""),
        )
    except Exception:
        return None


def download_media(
    url: str,
    platform: str = "",
    *,
    kind: str = "image",
    max_bytes: Optional[int] = None,
    timeout: int = 25,
    use_cookies: bool = False,
) -> CachedMedia:
    """
    携带防盗链请求头下载单张图片或单条视频至本地 media_cache。
    命中 24 小时缓存时直接复用。
    """
    clean_url = _normalize_url(url)
    parsed = urlparse(clean_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"无效的媒体 URL: {url}")

    kind = "video" if kind == "video" else "image"
    cap = max_bytes if max_bytes is not None else (MAX_VIDEO_BYTES if kind == "video" else MAX_IMAGE_BYTES)
    mid = _cache_key(clean_url, kind)

    cached = lookup_cached_media(mid)
    if cached is not None and (time.time() - cached.path.stat().st_mtime) < CACHE_TTL_SECONDS:
        return cached

    cache_dir = get_media_cache_dir()
    headers = _build_request_headers(platform)
    cookies = CredentialManager.load_cookies(platform) if (use_cookies and platform) else None

    with requests.get(
        clean_url,
        headers=headers,
        cookies=cookies or None,
        stream=True,
        timeout=(8, timeout),
        allow_redirects=True,
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"媒体下载失败 (HTTP {resp.status_code}): {clean_url[:100]}")

        content_len = resp.headers.get("Content-Length")
        if content_len and content_len.isdigit() and int(content_len) > cap:
            mb = int(content_len) / (1024 * 1024)
            raise RuntimeError(
                f"媒体体积过大 ({mb:.1f} MB，超过上限 {cap / (1024 * 1024):.0f} MB)，已跳过下载"
            )

        mime = _infer_mime(clean_url, resp.headers.get("Content-Type", ""), kind)
        ext = _EXT_BY_MIME.get(mime, ".jpg" if kind == "image" else ".mp4")
        filename = f"{mid}{ext}"
        target_path = cache_dir / filename
        tmp_path = cache_dir / f"{filename}.part"

        downloaded = 0
        try:
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > cap:
                        raise RuntimeError(
                            f"媒体下载超过体积上限 ({cap / (1024 * 1024):.0f} MB)，已中止"
                        )
                    f.write(chunk)
            if downloaded == 0:
                raise RuntimeError("媒体响应为空")
            tmp_path.replace(target_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    meta = {
        "media_id": mid,
        "url": clean_url,
        "filename": filename,
        "mime_type": mime,
        "size_bytes": downloaded,
        "kind": kind,
        "platform": platform,
        "created_at": time.time(),
    }
    (cache_dir / f"{mid}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    try:
        _purge_stale_cache(cache_dir)
    except Exception:
        pass

    return CachedMedia(
        media_id=mid,
        url=clean_url,
        path=target_path,
        mime_type=mime,
        size_bytes=downloaded,
        kind=kind,
        platform=platform,
    )
