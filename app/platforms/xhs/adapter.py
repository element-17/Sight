"""
小红书平台适配器 — 基于 cv-cat/Spider_XHS（PC 签名栈）

参考项目: https://github.com/cv-cat/Spider_XHS
上游同步说明: docs/MANUAL.md

架构说明:
  - ref_xhs_core/*, ref_xhs_pc/* 是 Spider_XHS 的移植模块
  - adapter.py 将这些基础 API 封装为 BasePlatformAdapter 的统一接口

用法:
    from app.platforms.xhs.adapter import XhsAdapter
    adapter = XhsAdapter()
    profile = adapter.get_profile("user_id")
"""
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# 添加 ref 模块到 sys.path
_xhs_ref_root = Path(__file__).parent
if str(_xhs_ref_root) not in sys.path:
    sys.path.insert(0, str(_xhs_ref_root))

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    EventItem,
)
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


class XhsAdapter(BasePlatformAdapter):
    """小红书平台适配器"""

    platform_id = "xhs"
    platform_name = "小红书"

    def __init__(self, credentials: dict = None, account_id: str = None):
        """
        Args:
            credentials: 凭证字典
            account_id: 多账号池绑定的账号 ID（None = 主账号）
        """
        super().__init__(credentials, account_id)
        self._auth_pc = None
        self._api_pc = None
        self._init_error: str = ""
        self._failed_cookie_str: Optional[str] = None
        self._last_request_at = 0.0
        # /graph 接口会从多个线程并发调用本适配器，限流必须串行化
        self._rl_lock = threading.Lock()
        # 缓存 note_id -> xsec_token，供 get_content_detail 调用笔记详情接口时携带
        self._note_tokens: dict[str, str] = {}

    # ==================== 凭证加载 ====================

    def _load_cookie_str(self) -> str:
        """加载本账号的小红书 Cookie 字符串（统一走 CredentialManager / accounts.json）"""
        cookies = self._load_cookies()
        if cookies:
            return "; ".join([f"{k}={v}" for k, v in cookies.items()])
        return ""

    # ==================== Auth 初始化 ====================

    @property
    def auth_pc(self):
        """获取 PC Auth 实例（延迟初始化；同一失效 Cookie 不重复触发网络 bootstrap）"""
        if self._auth_pc is None:
            cookie_str = self._load_cookie_str()
            if not cookie_str:
                self._init_error = "未配置 Cookie"
                return None
            if self._failed_cookie_str == cookie_str:
                return None
            try:
                from ref_xhs_pc.auth import XHSPcAuth
                print(f"[小红书] 加载 Cookie（account_id={self.account_id or 'primary'}）")
                self._auth_pc = XHSPcAuth.from_cookie(cookie_str)
                self._init_error = ""
                self._failed_cookie_str = None
                print("[小红书] PC Auth 已加载")
            except Exception as e:
                self._init_error = str(e)
                self._failed_cookie_str = cookie_str
                print(f"[小红书] PC Auth 初始化失败: {e}")
                return None
        return self._auth_pc

    @property
    def api_pc(self):
        """获取 PC API 实例"""
        if self._api_pc is None and self.auth_pc:
            try:
                from ref_apis.xhs_pc_apis import XHS_Apis
                api = XHS_Apis(self.auth_pc)
                # XHSPcAuth.from_cookie 内部已执行过一次 bootstrap()，仅在未就绪时补调
                if not getattr(self.auth_pc, "_user_id_ready", False):
                    api.bootstrap()
                self._api_pc = api
                self._init_error = ""
                print("[小红书] PC API 已初始化")
            except Exception as e:
                self._init_error = str(e)
                print(f"[小红书] PC API 初始化失败: {e}")
                return None
        return self._api_pc

    def _uninit_error_msg(self) -> str:
        detail = f"：{self._init_error}" if self._init_error else "（请检查 Cookie 是否已配置/有效）"
        return f"小红书客户端未初始化{detail}"

    # ==================== 限速 ====================

    def _rate_limit(self):
        """请求间隔，防止触发反爬。持锁 sleep：并发线程排队通过，保证请求间隔成立"""
        with self._rl_lock:
            now = time.time()
            elapsed = now - self._last_request_at
            if elapsed < 1.5:
                time.sleep(1.5 - elapsed)
            self._last_request_at = time.time()

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        """检查凭证是否有效"""
        cookies = self._load_cookies()
        if not cookies:
            return False
        try:
            if self.api_pc:
                success, msg, res = self.api_pc.get_user_me()
                return success
            return False
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        """获取当前登录用户信息"""
        try:
            if self.api_pc:
                self._rate_limit()
                success, msg, res = self.api_pc.get_user_me()
                if success and res:
                    data = res.get("data", {})
                    basic = data.get("basic_info") or data
                    return {
                        "uid": basic.get("user_id", ""),
                        "nickname": basic.get("nickname", ""),
                        "avatarUrl": basic.get("images") or basic.get("image", ""),
                    }
            return None
        except Exception as e:
            print(f"[小红书] get_login_user 失败: {e}")
            return None

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜索用户（失败时抛出带原因的异常，由调用方展示）"""
        try:
            if not self.api_pc:
                raise RuntimeError(self._uninit_error_msg())
            self._rate_limit()
            success, msg, res = self.api_pc.search_some_user(keyword, limit)
            if not success:
                raise RuntimeError(f"小红书搜索失败: {msg}")
            if not res:
                return []

            results = []
            # XHS_Apis.search_some_user returns the accumulated list directly.
            # Keep support for the raw response shape for compatibility.
            items = res if isinstance(res, list) else res.get("items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                user = item.get("user") or item
                results.append({
                    "uid": user.get("user_id") or user.get("id", ""),
                    "nickname": user.get("nickname") or user.get("nick_name") or user.get("name", ""),
                    "avatarUrl": user.get("avatar") or user.get("images") or user.get("image", ""),
                    "signature": user.get("desc") or user.get("description") or user.get("sub_title", ""),
                    # 搜索卡片可能带粉丝数与认证标记（official_verified / red_official_verify_type）
                    "fans": user.get("fans") or 0,
                    "is_verified": bool(user.get("official_verified")) or bool(user.get("red_official_verify_type")),
                })
            return results
        except Exception as e:
            print(f"[小红书] search_user 失败: {e}")
            raise

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """获取用户资料（接口失败上抛真实原因）"""
        if not self.api_pc:
            raise RuntimeError(self._uninit_error_msg())
        try:
            self._rate_limit()
            success, msg, res = self.api_pc.get_user_info(uid)
            if not success or not res:
                raise RuntimeError(f"[小红书] 获取资料失败: {msg or '接口返回失败'}")

            data = res.get("data", {})
            basic = data.get("basic_info") or data
            interactions = data.get("interactions") or []
            interaction_counts = {}
            for index, interaction in enumerate(interactions):
                if not isinstance(interaction, dict):
                    continue
                key = interaction.get("type") or interaction.get("name")
                count = interaction.get("count", 0)
                if key:
                    interaction_counts[str(key)] = count
                # Older responses do not include a type; preserve their order.
                if index == 0:
                    interaction_counts.setdefault("follows", count)
                elif index == 1:
                    interaction_counts.setdefault("fans", count)
                elif index == 2:
                    interaction_counts.setdefault("interaction", count)

            # XHS 编码 0=男 1=女；字段缺失（未公开）时用 -1 兜底，归为未知而非男
            gender_value = basic.get("gender", -1)
            if isinstance(gender_value, str):
                gender_key = gender_value.lower()
                gender = 1 if gender_key in {"male", "man", "男"} else 2 if gender_key in {"female", "woman", "女"} else 0
            elif gender_value == 0:
                gender = 1
            elif gender_value == 1:
                gender = 2
            else:
                gender = 0
            return PlatformProfile(
                platform="xhs",
                uid=uid,
                nickname=basic.get("nickname", ""),
                avatar_url=basic.get("images") or basic.get("image", ""),
                background_url=basic.get("imageb", ""),
                signature=basic.get("desc", ""),
                gender=gender,
                location=basic.get("location") or basic.get("ip_location", ""),
                extra={
                    "red_id": basic.get("red_id", ""),
                    "follows": interaction_counts.get("follows", basic.get("follows", 0)),
                    "fans": interaction_counts.get("fans", basic.get("fans", 0)),
                    "interaction": interaction_counts.get("interaction", basic.get("interaction", 0)),
                    "notes_count": basic.get("notes_count", 0),
                },
            )
        except RuntimeError:
            raise
        except (ValueError, AttributeError, TypeError) as e:
            raise RuntimeError(f"[小红书] 获取资料失败 ({uid}): {e}") from e

    # ==================== 内容列表 ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取用户的笔记列表"""
        if not self.api_pc:
            raise RuntimeError(self._uninit_error_msg())

        try:
            # 构建用户主页 URL
            user_url = f"https://www.xiaohongshu.com/user/profile/{uid}"
            self._rate_limit()
            success, msg, res = self.api_pc.get_user_all_notes(user_url)
            if not success:
                raise RuntimeError(f"[小红书] 获取笔记列表失败: {msg or '接口返回失败'}")
            if not res:
                return []

            items = []
            notes = res.get("notes", []) if isinstance(res, dict) else res
            for note in notes:
                if not isinstance(note, dict):
                    continue
                interact = note.get("interact_info") or {}
                cover = note.get("cover") or {}
                note_id = note.get("note_id") or note.get("id", "")
                title = note.get("display_title") or note.get("title") or "无标题"
                create_time = note.get("time", note.get("create_time", ""))
                user = note.get("user") or {}
                xsec_token = str(note.get("xsec_token") or "")
                if note_id and xsec_token:
                    self._note_tokens[str(note_id)] = xsec_token
                note_type = str(note.get("type") or "")
                items.append(ContentItem(
                    item_id=note_id,
                    title=str(title)[:200],
                    cover_url=cover.get("url_default", "") if isinstance(cover, dict) else "",
                    view_count=note.get("view_count", 0),
                    description=note.get("desc", "")[:200],
                    is_owner=True,
                    creator=user.get("nickname", "") if isinstance(user, dict) else "",
                    create_time=str(create_time) if create_time is not None else "",
                    url=f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else "",
                    extra={
                        "liked_count": interact.get("liked_count", note.get("liked_count", 0)),
                        "collected_count": interact.get("collected_count", note.get("collected_count", 0)),
                        "comment_count": interact.get("comment_count", note.get("comment_count", 0)),
                        "share_count": interact.get("share_count", note.get("share_count", 0)),
                        "type": note_type,
                        "media_type": "video" if note_type == "video" else "images",
                        "xsec_token": xsec_token,
                    },
                ))
            return items
        except RuntimeError:
            raise
        except (ValueError, AttributeError, TypeError) as e:
            raise RuntimeError(f"[小红书] 笔记列表解析失败 ({uid}): {e}") from e

    def get_content_detail(self, item_id: str, xsec_token: str = "") -> Optional[dict]:
        """获取小红书笔记完整图文与视频流（复用已移植的 XHS_Apis.get_note_info）。"""
        if not self.api_pc:
            raise RuntimeError(self._uninit_error_msg())
        note_id = str(item_id or "").strip()
        if not note_id:
            return None
        token = (xsec_token or "").strip() or self._note_tokens.get(note_id, "")
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if token:
            from urllib.parse import quote
            url += f"?xsec_token={quote(token)}&xsec_source=pc_user"

        self._rate_limit()
        success, msg, res = self.api_pc.get_note_info(url)
        if not success or not isinstance(res, dict):
            raise RuntimeError(f"[小红书] 获取笔记详情失败 ({note_id}): {msg or '接口返回失败'}")

        items_list = (res.get("data") or {}).get("items") or []
        if not items_list:
            return None
        card = (items_list[0] or {}).get("note_card") or {}
        if not isinstance(card, dict):
            return None

        images: list[str] = []
        for img in card.get("image_list") or []:
            if not isinstance(img, dict):
                continue
            img_url = str(img.get("url_default") or img.get("url_pre") or "")
            if not img_url:
                for info in img.get("info_list") or []:
                    if isinstance(info, dict) and info.get("url"):
                        img_url = str(info["url"])
                        break
            if img_url and img_url not in images:
                images.append(img_url)

        video_urls: list[str] = []
        video_obj = card.get("video") if isinstance(card.get("video"), dict) else {}
        media_obj = video_obj.get("media") if isinstance(video_obj.get("media"), dict) else {}
        stream = media_obj.get("stream") if isinstance(media_obj.get("stream"), dict) else {}
        for codec in ("h264", "h265", "av1"):
            for s_item in stream.get(codec) or []:
                if not isinstance(s_item, dict):
                    continue
                for u in [s_item.get("master_url"), *(s_item.get("backup_urls") or [])]:
                    if u and str(u) not in video_urls:
                        video_urls.append(str(u))
        consumer = video_obj.get("consumer") if isinstance(video_obj.get("consumer"), dict) else {}
        origin_key = str(consumer.get("origin_video_key") or "").strip()
        if origin_key:
            origin_url = f"https://sns-video-bd.xhscdn.com/{origin_key}"
            if origin_url not in video_urls:
                video_urls.append(origin_url)

        note_type = str(card.get("type") or "")
        if note_type == "video" and not video_urls:
            try:
                ok_v, _m, v_addr = self.api_pc.get_note_no_water_video(note_id)
                if ok_v and v_addr:
                    video_urls.append(str(v_addr))
            except Exception:
                pass

        interact = card.get("interact_info") if isinstance(card.get("interact_info"), dict) else {}
        user = card.get("user") if isinstance(card.get("user"), dict) else {}
        tag_list = [
            str(t.get("name"))
            for t in (card.get("tag_list") or [])
            if isinstance(t, dict) and t.get("name")
        ]
        return {
            "title": str(card.get("title") or card.get("desc") or "无标题")[:200],
            "coverUrl": images[0] if images else "",
            "count": len(images) if images else 1,
            "viewCount": 0,
            "description": str(card.get("desc") or "")[:1000],
            "creator": str(user.get("nickname") or ""),
            "createTime": str(card.get("time") or ""),
            "subscribedCount": interact.get("collected_count", 0),
            "media_type": "video" if (note_type == "video" or video_urls) else "images",
            "images": images,
            "video_url": video_urls[0] if video_urls else "",
            "video_urls": video_urls[:4],
            "tags": tag_list,
            "ip_location": str(card.get("ip_location") or ""),
            "items": [],
        }

    # ==================== 动态 ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户动态 — 基于笔记列表"""
        items = self.get_content_lists(uid)
        events = []
        for item in items[:limit]:
            timestamp = 0
            if item.create_time:
                try:
                    timestamp = int(item.create_time)
                    if timestamp < 1000000000000:
                        timestamp *= 1000
                except (TypeError, ValueError):
                    timestamp = 0
            events.append(EventItem(
                event_id=item.item_id,
                event_type="发布笔记",
                content=item.title,
                timestamp=timestamp,
                media_title=item.title,
                url=item.url,
                extra=item.extra,
            ))
        return events

    # ==================== 社交 ====================

    def refresh_user_info(self, uid: str) -> Optional[dict]:
        """重新拉取用户最新粉丝数（图谱"重新标记"用）；小红书资料接口无认证标记，不更新该字段"""
        profile = self.get_profile(uid)
        if not profile:
            return None
        return {"nickname": profile.nickname, "fans": profile.extra.get("fans") or 0}

    def get_follows(self, uid: str, limit: int = 100, skip: int = 0) -> tuple:
        """获取关注列表 — 暂不支持。返回 (条目, 还有更多, 总数)"""
        return [], False, -1

    def get_followers(self, uid: str, limit: int = 100, skip: int = 0) -> tuple:
        """获取粉丝列表 — 暂不支持。返回 (条目, 还有更多, 总数)"""
        return [], False, -1
