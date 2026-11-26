"""
微博平台适配器

基于 weibo.com PC 端 Ajax API 与 s.weibo.com 搜索页的数据采集实现。

API 说明:
  - weibo.com/                              登录态校验与当前登录用户提取（window.$CONFIG）
  - weibo.com/ajax/profile/info             用户资料
  - weibo.com/ajax/statuses/mymblog         用户微博列表 / 动态
  - weibo.com/ajax/friendships/friends      关注 / 粉丝列表
  - s.weibo.com/user                        微博网页搜索

认证方式:
  - 需要 PC 网页版 weibo.com 的有效登录 Cookie（包含 SUB、SUBP、WBPSESS 等字段）
  - 统一使用 weibo.com / s.weibo.com 同域接口，避免 m.weibo.cn wapsso 跨域校验拦截
"""
import json
import re
import time
from typing import Optional

import requests

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    EventItem,
)
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


class WeiboAdapter(BasePlatformAdapter):
    """微博平台适配器"""

    platform_id = "weibo"
    platform_name = "微博"

    # API 基础地址
    WEB_BASE = "https://weibo.com"
    SEARCH_BASE = "https://s.weibo.com"

    # 登录态探测缓存有效期（秒）：避免 check_alive + get_login_user 连续调用重复请求首页
    _LOGIN_CACHE_TTL = 10.0

    _CONFIG_START_RE = re.compile(r"window\.\$CONFIG\s*=\s*")
    _AUTH_REDIRECT_HINTS = ("passport.weibo.com", "login.php", "signin", "visitor")

    def __init__(self, credentials: dict = None, account_id: str = None):
        super().__init__(credentials, account_id)
        self._session: requests.Session | None = None
        self._last_request_at = 0.0
        self._login_user_cache: Optional[dict] = None
        self._login_user_cache_at: float = 0.0
        self.last_api_error: str | None = None  # 最近一次业务错误，供上层透传真实原因

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        """构建请求会话（带 weibo.com Cookie 和请求头）"""
        s = requests.Session()
        cookies = self._load_cookies()
        for key, value in cookies.items():
            s.cookies.set(key, value)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"{self.WEB_BASE}/",
            "Origin": self.WEB_BASE,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
        }
        if cookies.get("XSRF-TOKEN"):
            headers["X-XSRF-TOKEN"] = cookies["XSRF-TOKEN"]
        s.headers.update(headers)
        return s

    def clear_cache(self) -> dict:
        had_login = 1 if self._login_user_cache_at > 0 else 0
        self._login_user_cache = None
        self._login_user_cache_at = 0.0
        return {"login_user": had_login} if had_login else {}

    def _rate_limit(self):
        """请求间隔控制"""
        if self._last_request_at <= 0:
            self._last_request_at = time.time()
            return
        now = time.time()
        min_interval = 1.5  # 微博请求间隔（秒）
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_at = time.time()

    def _pc_ajax_get(self, path: str, params: dict = None) -> dict:
        """
        weibo.com PC 端 ajax 接口（需有效 weibo.com 登录 Cookie）。
        使用 allow_redirects=False 快速识别 302 跳转 passport/login 登录页，
        登录失效、风控或接口异常一律抛 RuntimeError，不返回空值伪装成功。
        """
        headers = {"Referer": f"{self.WEB_BASE}/", "X-Requested-With": "XMLHttpRequest"}
        last_error = "未知错误"
        max_attempts = min(MAX_RETRIES, 2)
        for attempt in range(max_attempts):
            try:
                self._rate_limit()
                resp = self.session.get(
                    f"{self.WEB_BASE}{path}",
                    params=params or {},
                    headers=headers,
                    timeout=(5, REQUEST_TIMEOUT),
                    allow_redirects=False,
                )
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = str(resp.headers.get("Location", "") or "")
                    if any(h in loc for h in self._AUTH_REDIRECT_HINTS) or not loc:
                        raise RuntimeError("[微博] 登录态已失效，请更新 Cookie")
                    last_error = f"HTTP {resp.status_code} ({loc})"
                    print(f"[微博] 非预期重定向 HTTP {resp.status_code} -> {loc}, path={path}")
                elif resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        # 非 JSON（多为被重定向到 passport/login 的 HTML）
                        raise RuntimeError("[微博] 登录态已失效，请更新 Cookie（PC 接口返回非 JSON）")
                    if isinstance(data, dict) and data.get("ok") == 1:
                        self.last_api_error = None
                        return data
                    if isinstance(data, dict) and (data.get("ok") == -100 or data.get("url")):
                        raise RuntimeError("[微博] 登录态已失效，请更新 Cookie (ok=-100)")
                    msg = ""
                    if isinstance(data, dict):
                        msg = str(data.get("message") or data.get("msg") or "")
                    ok_val = data.get("ok") if isinstance(data, dict) else None
                    self.last_api_error = msg or f"接口返回异常 (ok={ok_val})"
                    print(f"[微博] PC 接口返回异常: {self.last_api_error}, path={path}")
                    raise RuntimeError(f"[微博] {self.last_api_error}")
                elif resp.status_code in (401, 403, 418, 432):
                    raise RuntimeError(
                        f"[微博] 登录态已失效或触发风控 (HTTP {resp.status_code})，请更新 Cookie"
                    )
                else:
                    last_error = f"HTTP {resp.status_code}"
                    print(f"[微博] HTTP {resp.status_code} (attempt {attempt+1}), path={path}")

                if attempt < max_attempts - 1:
                    time.sleep(1.5 + attempt * 0.5)
                    self._last_request_at = time.time()
            except RuntimeError:
                raise
            except (requests.RequestException, ValueError) as e:
                last_error = str(e)
                print(f"[微博] 请求失败 (attempt {attempt+1}): {e}")
                if attempt < max_attempts - 1:
                    time.sleep(1.5 + attempt)
                    self._last_request_at = time.time()
        self.last_api_error = last_error
        raise RuntimeError(f"[微博] 请求失败: {last_error}")

    def _web_get(self, url: str, params: dict = None, headers: dict = None) -> Optional[str]:
        """获取网页内容（s.weibo.com 搜索页等）"""
        max_attempts = min(MAX_RETRIES, 2)
        for attempt in range(max_attempts):
            try:
                self._rate_limit()
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=(5, REQUEST_TIMEOUT),
                )
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (401, 403, 418, 432):
                    raise RuntimeError(f"[微博] 网页访问受限或登录态已失效 (HTTP {resp.status_code})，请更新 Cookie")
                print(f"[微博] 网页 HTTP {resp.status_code} (attempt {attempt+1}), url={url}")
                if attempt < max_attempts - 1:
                    time.sleep(1.5 + attempt * 0.5)
                    self._last_request_at = time.time()
            except RuntimeError:
                raise
            except requests.RequestException as e:
                print(f"[微博] 网页请求失败 (attempt {attempt+1}): {e}")
                if attempt < max_attempts - 1:
                    time.sleep(1.5 + attempt)
                    self._last_request_at = time.time()
        return None

    # ==================== 状态检查 ====================

    @classmethod
    def _parse_config_user(cls, html: str) -> Optional[dict]:
        """从 weibo.com 首页 window.$CONFIG JSON 中解析当前登录用户信息"""
        if not html:
            return None
        match = cls._CONFIG_START_RE.search(html)
        if not match:
            return None
        try:
            cfg, _ = json.JSONDecoder().raw_decode(html, match.end())
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(cfg, dict):
            return None
        user = cfg.get("user")
        if not isinstance(user, dict):
            return None
        uid = str(user.get("idstr") or user.get("id") or "").strip()
        if not uid:
            return None
        return {
            "uid": uid,
            "nickname": str(user.get("screen_name") or "").strip(),
            "avatarUrl": str(
                user.get("avatar_large") or user.get("profile_image_url") or ""
            ).strip(),
        }

    def _fetch_login_user(self, force: bool = False) -> Optional[dict]:
        """通过访问 weibo.com 首页验证 PC Cookie 并解析登录用户（未登录/过期会 302 到 passport/login）"""
        cookies = self._load_cookies()
        if not cookies:
            self._login_user_cache = None
            self._login_user_cache_at = 0.0
            return None

        now = time.time()
        if not force and self._login_user_cache_at > 0 and (now - self._login_user_cache_at) < self._LOGIN_CACHE_TTL:
            return self._login_user_cache

        try:
            self._rate_limit()
            resp = self.session.get(
                f"{self.WEB_BASE}/",
                headers={
                    "Referer": f"{self.WEB_BASE}/",
                    "X-Requested-With": None,
                    "Accept": "text/html,application/xhtml+xml,*/*",
                },
                timeout=(5, REQUEST_TIMEOUT),
                allow_redirects=False,
            )
            user = self._parse_config_user(resp.text) if resp.status_code == 200 else None
        except requests.RequestException:
            user = None

        self._login_user_cache = user
        self._login_user_cache_at = time.time()
        return user

    def check_alive(self) -> bool:
        """检查 PC Cookie 是否有效"""
        try:
            return bool(self._fetch_login_user(force=True))
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        """获取当前登录用户信息"""
        try:
            return self._fetch_login_user(force=False)
        except Exception:
            return None

    def test_account(self) -> dict:
        """测试当前微博账号 Cookie 可用性：同时验证 weibo.com 登录态与 PC Ajax 接口"""
        cookies = self._load_cookies()
        if not cookies:
            return {"ok": False, "error": "未配置 Cookie，请从网页版 weibo.com 复制完整 Cookie"}
        try:
            user = self._fetch_login_user(force=True)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not user:
            return {
                "ok": False,
                "error": "登录态已失效或 Cookie 无效，请从 PC 网页版 weibo.com 复制完整 Cookie",
            }
        try:
            self._pc_ajax_get("/ajax/profile/info", {"uid": user["uid"]})
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "login_user": user}

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """按昵称搜索用户（s.weibo.com 用户搜索页，需有效登录 Cookie）

        错误直接抛 RuntimeError，由 API 层透传给前端展示真实原因。
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        return self._search_via_web(keyword, limit)

    # 用户卡片块（s.weibo.com SSR 页面）：<div class="card card-user-b ...">
    _USER_CARD_SPLIT = '<div class="card card-user-b'
    _USER_LINK_RE = re.compile(
        r'href="//weibo\.com/u/(\d+)"[^>]*?class="name"[^>]*?>(.*?)</a>', re.S
    )
    _USER_AVATAR_RE = re.compile(r'<img\s+src="(https://\w+\.sinaimg\.cn/[^"]+)"')
    _USER_FANS_RE = re.compile(r'粉丝[：:]\s*([\d.]+)(万)?')
    _ISLOGIN_RE = re.compile(r"\$CONFIG\['islogin'\]\s*=\s*'(\d)'")

    def _search_via_web(self, keyword: str, limit: int = 20) -> list[dict]:
        """通过 s.weibo.com 网页搜索用户"""
        html = self._web_get(
            f"{self.SEARCH_BASE}/user",
            params={"q": keyword, "page": 1, "Refer": "weibo_user"},
            # s.weibo.com 对 XHR 请求会返回"404错误"页，必须去掉会话里全局的
            # X-Requested-With 头
            headers={"X-Requested-With": None},
        )
        if not html:
            raise RuntimeError("微博搜索失败：搜索页请求无响应，请稍后重试")

        # 被 302 到 passport 访客页 / islogin=0 = 登录态失效
        if "passport.weibo.com" in html or (
            (m := self._ISLOGIN_RE.search(html)) and m.group(1) != "1"
        ):
            raise RuntimeError("微博搜索失败：登录态已失效，请更新 Cookie")

        # 过期/无效 Cookie 下 s.weibo.com 返回整页"404错误"
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        if title and "404" in title.group(1):
            raise RuntimeError(
                "微博搜索失败：搜索页返回 404，Cookie 可能已失效，请更新 Cookie 后重试"
            )

        users = []
        for block in html.split(self._USER_CARD_SPLIT)[1:]:
            link = self._USER_LINK_RE.search(block)
            if not link:
                continue
            uid, nickname = link.group(1), re.sub(r"<[^>]+>", "", link.group(2)).strip()
            if not uid or not nickname:
                continue

            fans = 0
            fans_m = self._USER_FANS_RE.search(block)
            if fans_m:
                fans = float(fans_m.group(1))
                if fans_m.group(2):
                    fans *= 10000
                fans = int(fans)

            avatar_m = self._USER_AVATAR_RE.search(block)
            users.append({
                "uid": uid,
                "nickname": nickname,
                "avatarUrl": avatar_m.group(1) if avatar_m else "",
                "signature": "",
                "fans": fans,
            })
            if len(users) >= limit:
                break

        return users

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """获取用户资料（weibo.com PC ajax；接口错误上抛，用户不存在返回 None）"""
        uid = str(uid).strip()
        if not uid:
            return None

        resp = self._pc_ajax_get("/ajax/profile/info", {"uid": uid})
        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        user_info = data.get("user") if isinstance(data.get("user"), dict) else {}
        if not user_info:
            return None

        # 解析性别
        gender = 0
        if user_info.get("gender") == "m":
            gender = 1
        elif user_info.get("gender") == "f":
            gender = 2

        verified_reason = str(user_info.get("verified_reason") or "").strip()
        return PlatformProfile(
            platform="weibo",
            uid=str(user_info.get("idstr") or user_info.get("id") or uid),
            nickname=user_info.get("screen_name", ""),
            avatar_url=user_info.get("avatar_large") or user_info.get("profile_image_url") or "",
            background_url=user_info.get("cover_image_phone") or "",
            signature=user_info.get("description") or "",
            gender=gender,
            birthday="",
            location=user_info.get("location") or "",
            join_time="",
            level=0,
            is_vip=bool(user_info.get("verified", False)),
            vip_label=verified_reason,
            extra={
                "follow_count": user_info.get("friends_count", 0) or 0,
                "fans_count": user_info.get("followers_count", 0) or 0,
                "weibo_count": user_info.get("statuses_count", 0) or 0,
                "favourite_count": user_info.get("favourites_count", 0) or 0,
                "verified_reason": verified_reason,
                "verified_type": user_info.get("verified_type", -1),
                "mbtype": user_info.get("mbtype", 0),
                "mbrank": user_info.get("mbrank", 0),
                "follow_status": bool(user_info.get("follow_me", False)),
                "avatar_hd": user_info.get("avatar_hd") or "",
            },
        )

    @staticmethod
    def _extract_mblog_media(mblog: dict) -> dict:
        """从微博 mblog 提取九宫格原图列表与视频流 URL（优先标清/流畅 MP4）。

        兼容 PC ajax（pic_infos / pic_ids / playback_list）与旧版移动端（pics）结构。
        """
        pics: list[str] = []
        for p in mblog.get("pics") or []:
            if not isinstance(p, dict):
                continue
            large = p.get("large") if isinstance(p.get("large"), dict) else {}
            u = str(large.get("url") or p.get("url") or "").strip()
            if u and u not in pics:
                pics.append(u)

        pic_infos = mblog.get("pic_infos")
        if isinstance(pic_infos, dict) and pic_infos:
            pic_ids = mblog.get("pic_ids") if isinstance(mblog.get("pic_ids"), list) else []
            ordered_ids = [pid for pid in pic_ids if pid in pic_infos]
            for pid in pic_infos:
                if pid not in ordered_ids:
                    ordered_ids.append(pid)
            for pid in ordered_ids:
                info = pic_infos.get(pid)
                if not isinstance(info, dict):
                    continue
                chosen = ""
                for size_key in ("original", "large", "largest", "mw2000", "bmiddle", "thumbnail"):
                    variant = info.get(size_key)
                    if isinstance(variant, dict) and variant.get("url"):
                        chosen = str(variant["url"]).strip()
                        break
                if chosen and chosen not in pics:
                    pics.append(chosen)

        video_urls: list[str] = []
        cover_url = pics[0] if pics else ""
        page_info = mblog.get("page_info") if isinstance(mblog.get("page_info"), dict) else {}
        if page_info:
            page_pic = page_info.get("page_pic")
            if not cover_url:
                if isinstance(page_pic, dict) and page_pic.get("url"):
                    cover_url = str(page_pic["url"])
                elif isinstance(page_pic, str):
                    cover_url = page_pic
            media_info = page_info.get("media_info") if isinstance(page_info.get("media_info"), dict) else {}
            urls_dict = page_info.get("urls") if isinstance(page_info.get("urls"), dict) else {}
            # 优先流畅/标清 mp4，再回退高清
            for candidate in (
                media_info.get("mp4_ld_mp4"),
                media_info.get("mp4_sd_url"),
                media_info.get("stream_url"),
                urls_dict.get("mp4_ld_mp4"),
                media_info.get("mp4_720p_mp4"),
                media_info.get("mp4_hd_url"),
                media_info.get("stream_url_hd"),
                urls_dict.get("mp4_720p_mp4"),
                urls_dict.get("mp4_hd_mp4"),
            ):
                if candidate and str(candidate).startswith(("http://", "https://")) and str(candidate) not in video_urls:
                    video_urls.append(str(candidate))

            # PC ajax playback_list 兜底（按清晰度从低到高排序，优先轻量 MP4）
            playback = media_info.get("playback_list")
            if isinstance(playback, list):
                pb_candidates: list[tuple[int, str]] = []
                for entry in playback:
                    if not isinstance(entry, dict):
                        continue
                    play_info = entry.get("play_info") if isinstance(entry.get("play_info"), dict) else {}
                    meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
                    url = str(play_info.get("url") or "").strip()
                    mime = str(play_info.get("mime") or "").lower()
                    if not url.startswith(("http://", "https://")):
                        continue
                    if mime and "mp4" not in mime:
                        continue
                    try:
                        q_idx = int(meta.get("quality_index") or 9999)
                    except (TypeError, ValueError):
                        q_idx = 9999
                    pb_candidates.append((q_idx, url))
                for _q, url in sorted(pb_candidates, key=lambda x: x[0]):
                    if url not in video_urls:
                        video_urls.append(url)

        video_url = video_urls[0] if video_urls else ""
        media_type = "video" if video_url else ("images" if pics else "text")
        return {
            "pics": pics,
            "cover_url": cover_url,
            "video_url": video_url,
            "video_urls": video_urls[:4],
            "media_type": media_type,
        }

    # ==================== 内容列表（微博列表） ====================

    def _fetch_user_mblogs(self, uid: str, max_pages: int = 3) -> list[dict]:
        """分页拉取用户微博列表（weibo.com/ajax/statuses/mymblog）"""
        mblogs: list[dict] = []
        seen_ids: set[str] = set()
        since_id = ""

        for page in range(1, max_pages + 1):
            params: dict = {"uid": uid, "page": page, "feature": 0}
            if since_id:
                params["since_id"] = since_id
            resp = self._pc_ajax_get("/ajax/statuses/mymblog", params)
            data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
            page_list = data.get("list") or []
            if not page_list:
                break

            for mblog in page_list:
                if not isinstance(mblog, dict):
                    continue
                item_id = str(mblog.get("idstr") or mblog.get("id") or mblog.get("mid") or "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                mblogs.append(mblog)

            since_id = str(data.get("since_id") or "").strip()
            if not since_id:
                break

        return mblogs

    @staticmethod
    def _clean_mblog_text(mblog: dict) -> tuple[str, str]:
        """返回 (原始 HTML/富文本, 纯文本)"""
        text_html = str(mblog.get("text") or "")
        text_raw = str(mblog.get("text_raw") or "").strip()
        text_plain = text_raw or re.sub(r"<[^>]+>", "", text_html).strip()
        return text_html or text_plain, text_plain

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取用户的微博列表"""
        uid = str(uid).strip()
        if not uid:
            return []

        mblogs = self._fetch_user_mblogs(uid, max_pages=3)
        items: list[ContentItem] = []

        for mblog in mblogs:
            created_at = self._parse_weibo_time(mblog.get("created_at", ""))
            text_raw, text_plain = self._clean_mblog_text(mblog)
            title = text_plain[:200]

            item_id = str(mblog.get("idstr") or mblog.get("id") or mblog.get("mid") or "")
            mblogid = str(mblog.get("mblogid") or "").strip()
            user = mblog.get("user") if isinstance(mblog.get("user"), dict) else {}
            author_uid = str(user.get("idstr") or user.get("id") or uid)
            source = re.sub(r"<[^>]+>", "", str(mblog.get("source") or "")).strip()
            media = self._extract_mblog_media(mblog)

            items.append(ContentItem(
                item_id=item_id,
                title=title,
                cover_url=media["cover_url"],
                count=len(media["pics"]) if media["pics"] else 1,
                view_count=0,
                creator=user.get("screen_name", ""),
                description=text_plain[:500],
                is_owner=(author_uid == uid),
                create_time=str(created_at),
                url=f"{self.WEB_BASE}/{uid}/{mblogid}" if mblogid else "",
                extra={
                    "reposts_count": mblog.get("reposts_count", 0) or 0,
                    "comments_count": mblog.get("comments_count", 0) or 0,
                    "attitudes_count": mblog.get("attitudes_count", 0) or 0,
                    "text": text_raw,
                    "pic_num": len(media["pics"]),
                    "pics": media["pics"],
                    "video_url": media["video_url"],
                    "video_urls": media["video_urls"],
                    "media_type": media["media_type"],
                    "is_retweet": bool(mblog.get("retweeted_status")),
                    "source": source,
                },
            ))

        return items

    def _parse_weibo_time(self, time_str: str) -> int:
        """解析微博时间字符串为 Unix 时间戳（毫秒）

        微博时间格式: "Tue May 19 12:00:00 +0800 2020"
        """
        if not time_str:
            return 0
        try:
            # 标准微博格式
            dt = time.strptime(time_str, "%a %b %d %H:%M:%S %z %Y")
            return int(time.mktime(dt) * 1000) if dt else 0
        except (ValueError, TypeError):
            try:
                # 尝试 ISO 格式
                from datetime import datetime
                dt = datetime.fromisoformat(time_str)
                return int(dt.timestamp() * 1000)
            except (ValueError, TypeError):
                return 0

    # ==================== 动态 ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户动态（微博发布/转发/赞）"""
        uid = str(uid).strip()
        if not uid:
            return []

        max_pages = min(3, max(1, (limit + 19) // 20))
        mblogs = self._fetch_user_mblogs(uid, max_pages=max_pages)
        events: list[EventItem] = []

        for mblog in mblogs:
            if len(events) >= limit:
                break

            user = mblog.get("user") if isinstance(mblog.get("user"), dict) else {}
            author_uid = str(user.get("idstr") or user.get("id") or uid)
            title_obj = mblog.get("title") if isinstance(mblog.get("title"), dict) else {}

            # 判断动态类型
            if mblog.get("retweeted_status"):
                event_type = "转发微博"
            elif author_uid != uid and "赞" in str(title_obj.get("text") or ""):
                event_type = "赞了微博"
            else:
                event_type = "发布微博"

            _text_raw, text_plain = self._clean_mblog_text(mblog)
            created_at = self._parse_weibo_time(mblog.get("created_at", ""))

            # 图片/视频媒体标题
            media_title = ""
            if isinstance(mblog.get("page_info"), dict):
                page_info = mblog["page_info"]
                media_title = page_info.get("page_title", "") or page_info.get("content2", "")

            if not media_title and isinstance(mblog.get("retweeted_status"), dict):
                orig = mblog["retweeted_status"]
                _orig_raw, orig_text = self._clean_mblog_text(orig)
                media_title = orig_text[:100]

            mblogid = str(mblog.get("mblogid") or "").strip()
            media = self._extract_mblog_media(mblog)
            events.append(EventItem(
                event_id=str(mblog.get("idstr") or mblog.get("id") or ""),
                event_type=event_type,
                content=text_plain[:500],
                timestamp=created_at,
                media_title=media_title[:200],
                media_artist=user.get("screen_name", ""),
                url=f"{self.WEB_BASE}/{uid}/{mblogid}" if mblogid else "",
                extra={
                    "reposts_count": mblog.get("reposts_count", 0) or 0,
                    "comments_count": mblog.get("comments_count", 0) or 0,
                    "attitudes_count": mblog.get("attitudes_count", 0) or 0,
                    "pic_count": len(media["pics"]),
                    "pics": media["pics"],
                    "video_url": media["video_url"],
                    "media_type": media["media_type"],
                    "is_retweet": bool(mblog.get("retweeted_status")),
                },
            ))

        return events

    # ==================== 关注/粉丝 ====================

    def _social_page(
        self, uid: str, relate: str, limit: int, skip: int
    ) -> tuple[list[dict], bool, int]:
        """
        增量拉取一页关注/粉丝。relate: "" 关注列表 | "fans" 粉丝列表（WeiboSpider 同款参数）。
        单页 20 条。返回 (条目, 还有更多, 真实总数或 -1)。
        """
        per_page = 20
        first_page = skip // per_page + 1
        items: list[dict] = []
        total = -1
        page = first_page
        max_pages = 20
        pages_fetched = 0
        skip_in_page = skip % per_page
        while len(items) < limit and pages_fetched < max_pages:
            pages_fetched += 1
            params = {"page": page, "uid": uid}
            if relate:
                params["relate"] = relate
                params["type"] = relate
            data = self._pc_ajax_get("/ajax/friendships/friends", params)
            if not data:
                # 第一页就取不到任何响应 = 接口失败（登录态失效/被风控/参数错误）；
                # 真正的空列表会返回 ok=1 且 users=[]。不吞错，让上层把真实原因展示给用户。
                if page == first_page:
                    detail = f"，平台返回：{self.last_api_error}" if self.last_api_error else ""
                    raise RuntimeError(
                        f"[微博] 获取关注/粉丝列表失败：接口无响应（Cookie 可能失效，或触发风控）{detail}"
                    )
                break
            if total < 0:
                try:
                    total = int(data.get("total_number", -1))
                except (TypeError, ValueError):
                    total = -1
            users = data.get("users") or []
            if not users:
                break
            for user in users:
                if skip_in_page:
                    skip_in_page -= 1  # 首页跳掉已拉取的条目
                    continue
                items.append({
                    "uid": str(user.get("id", "")),
                    "nickname": user.get("screen_name", ""),
                    "avatarUrl": user.get("profile_image_url", "") or user.get("avatar_hd", ""),
                    "signature": user.get("description", ""),
                    "gender": {"m": 1, "f": 2}.get(user.get("gender", ""), 0),
                    "is_vip": bool(user.get("verified", False)),
                    "is_verified": bool(user.get("verified", False)),
                    "fans": user.get("followers_count", 0) or 0,
                })
                if len(items) >= limit:
                    break
            if len(items) >= limit or len(users) < per_page:
                break
            page += 1
        if total >= 0:
            more = skip + len(items) < total
        else:
            more = len(items) >= limit  # 无总数时按取满推断还有更多
        return items, more, total

    def get_follows(self, uid: str, limit: int = 200, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取关注列表（增量：skip 已拉条数；返回 条目/还有更多/总数或-1）"""
        uid = str(uid).strip()
        if not uid:
            return [], False, -1
        return self._social_page(uid, "", limit, skip)

    def get_followers(self, uid: str, limit: int = 200, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取粉丝列表（增量：skip 已拉条数；返回 条目/还有更多/总数或-1）"""
        uid = str(uid).strip()
        if not uid:
            return [], False, -1
        return self._social_page(uid, "fans", limit, skip)

    def refresh_user_info(self, uid: str) -> Optional[dict]:
        """重新拉取用户最新粉丝数/认证（图谱"重新标记"用）"""
        profile = self.get_profile(uid)
        if not profile:
            return None
        # 微博 get_profile 把 verified 存在 is_vip 上（vip_label=认证原因）
        return {
            "nickname": profile.nickname,
            "fans": profile.extra.get("fans_count") or 0,
            "is_verified": bool(profile.is_vip),
        }
