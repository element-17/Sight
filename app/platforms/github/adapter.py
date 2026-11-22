"""
GitHub 平台适配器

基于 GitHub REST API v3 (https://api.github.com) 的数据采集实现。

功能映射:
  - search_user       → /search/users 搜索 GitHub 用户/组织
  - get_profile       → /users/{username}（或 /user/{id}）获取用户公开资料
  - get_content_lists → /users/{username}/repos（自建/Fork 公开仓库）+ /users/{username}/starred（Star 仓库）
  - get_content_detail→ /repos/{owner}/{repo} + /repos/{owner}/{repo}/commits（仓库详情与最近提交）
  - get_events        → /users/{username}/events/public（公开活动事件流：Push/Star/PR/Issue/Release 等）
  - get_follows       → /users/{username}/following（关注列表，支持 skip 增量续拉）
  - get_followers     → /users/{username}/followers（粉丝列表，支持 skip 增量续拉）
  - refresh_user_info → 重新拉取用户最新 followers 与认证状态

凭证支持:
  - 支持直接粘贴 GitHub Personal Access Token（ghp_... / github_pat_... / Bearer ...）
  - 支持键值格式（token=ghp_...）或浏览器 Cookie（含 dotcom_user 等）
  - 未配置凭证时自动以公开免鉴权模式请求（60 次/小时；配置 Token 后 5000 次/小时）
"""
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests

from app.config import MAX_RETRIES, REQUEST_TIMEOUT
from app.platforms.base import (
    BasePlatformAdapter,
    ContentItem,
    EventItem,
    PlatformProfile,
)

_GH_CLI_TOKEN_CACHE: Optional[str] = None
_GH_CLI_LOCK = threading.Lock()


def _detect_gh_cli_token() -> str:
    """尝试从本机已登录的 GitHub CLI (gh auth token) 获取 Token（进程级缓存一次）"""
    global _GH_CLI_TOKEN_CACHE
    with _GH_CLI_LOCK:
        if _GH_CLI_TOKEN_CACHE is not None:
            return _GH_CLI_TOKEN_CACHE
        try:
            res = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            token = (res.stdout or "").strip() if res.returncode == 0 else ""
            _GH_CLI_TOKEN_CACHE = token if token.startswith(("gh", "github_pat_")) else ""
        except Exception:
            _GH_CLI_TOKEN_CACHE = ""
        return _GH_CLI_TOKEN_CACHE


def _github_verified(user: dict) -> bool:
    """GitHub 认证/特殊身份判定：GitHub Staff (site_admin) 或 Organization 组织账号"""
    if not isinstance(user, dict):
        return False
    return bool(user.get("site_admin")) or user.get("type") == "Organization"


class GitHubAdapter(BasePlatformAdapter):
    """GitHub 平台适配器"""

    platform_id = "github"
    platform_name = "GitHub"

    BASE_API = "https://api.github.com"
    USER_CACHE_TTL = 30 * 60

    _TOKEN_KEYS = ("token", "access_token", "github_token", "pat", "authorization")
    _TOKEN_PREFIXES = ("ghp_", "github_pat_", "gho_", "ghu_", "ghs_", "ghr_")

    def __init__(self, credentials: dict = None, account_id: str = None):
        super().__init__(credentials, account_id)
        self._session: requests.Session | None = None
        self._last_request_at = 0.0
        self._rl_lock = threading.Lock()
        self._user_cache: dict[str, dict] = {}
        self.last_api_error: str | None = None

    # ==================== 凭证与会话 ====================

    def _raw_cookies(self) -> dict:
        cookies = dict(self._load_cookies() or {})
        if self.credentials:
            cookies.update(self.credentials)
        return cookies

    def _extract_account_token(self) -> str:
        """从当前账号配置中提取 GitHub Token（不含环境变量兜底）"""
        cookies = self._raw_cookies()
        for k, v in cookies.items():
            if not isinstance(v, str):
                continue
            val = v.strip()
            if k.lower() in self._TOKEN_KEYS and val:
                if val.lower().startswith("bearer "):
                    val = val[7:].strip()
                elif val.lower().startswith("token "):
                    val = val[6:].strip()
                return val
            if val.lower().startswith(self._TOKEN_PREFIXES):
                return val
        return ""

    def _extract_effective_token(self) -> str:
        """获取请求实际使用的 Token：优先账号配置，其次环境变量 GITHUB_TOKEN，最后本机 gh CLI"""
        token = self._extract_account_token()
        if token:
            return token
        env_token = (
            os.environ.get("SIGHT_GITHUB_TOKEN", "").strip()
            or os.environ.get("GITHUB_TOKEN", "").strip()
        )
        if env_token:
            return env_token
        return _detect_gh_cli_token()

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        cookies = self._raw_cookies()
        token = self._extract_effective_token()

        for k, v in cookies.items():
            if k.lower() not in self._TOKEN_KEYS and isinstance(v, str):
                s.cookies.set(k, v)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36 Sight/1.0"
            ),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        s.headers.update(headers)
        return s

    def _rate_limit(self):
        """请求限速（持锁串行化，防止图谱多线程并发打爆 GitHub 速率限制）"""
        min_interval = 0.25 if self._extract_effective_token() else 0.8
        with self._rl_lock:
            now = time.time()
            elapsed = now - self._last_request_at
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_request_at = time.time()

    def clear_cache(self) -> dict:
        count = len(self._user_cache)
        self._user_cache.clear()
        return {"用户信息缓存": count}

    # ==================== 时间与 UID 工具 ====================

    @staticmethod
    def _parse_iso_ms(iso_str: str) -> int:
        """解析 GitHub ISO-8601 时间（如 2024-05-01T12:30:00Z）为毫秒级时间戳"""
        if not iso_str or not isinstance(iso_str, str):
            return 0
        try:
            normalized = iso_str.strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            dt = datetime.fromisoformat(normalized)
            return int(dt.timestamp() * 1000)
        except (ValueError, TypeError, OSError):
            return 0

    @staticmethod
    def _clean_uid(uid: str) -> str:
        """清洗用户输入的 UID（支持 username、@username、https://github.com/username、数字 ID）"""
        raw = str(uid or "").strip()
        if not raw:
            return ""
        m = re.match(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)", raw, re.I)
        if m:
            return m.group(1)
        if raw.startswith("@"):
            raw = raw[1:].strip()
        return raw.strip("/")

    # ==================== 底层请求 ====================

    def _get(
        self,
        endpoint: str,
        params: dict = None,
        allow_404: bool = False,
        allow_409: bool = False,
    ):
        """
        调用 GitHub REST API；失败一律抛 RuntimeError（带 [GitHub] 前缀与状态码/原因）。
        allow_404=True 时 HTTP 404 返回 None（供 get_profile 用户不存在判定）。
        allow_409=True 时 HTTP 409 返回 []（供空仓库 commits 接口兼容）。
        """
        url = endpoint if endpoint.startswith("http") else f"{self.BASE_API}{endpoint}"
        last_error = "未知错误"

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError as e:
                        raise RuntimeError(f"[GitHub] 接口未返回有效 JSON: {endpoint}") from e
                    self.last_api_error = None
                    return data

                if resp.status_code == 404 and allow_404:
                    self.last_api_error = None
                    return None

                if resp.status_code == 409 and allow_409:
                    self.last_api_error = None
                    return []

                msg = ""
                try:
                    err_body = resp.json()
                    if isinstance(err_body, dict):
                        msg = str(err_body.get("message") or "")
                except ValueError:
                    msg = (resp.text or "").strip()[:120]

                if resp.status_code == 401:
                    self.last_api_error = f"凭证无效或已过期 (HTTP 401: {msg or 'Bad credentials'})"
                    raise RuntimeError(f"[GitHub] {self.last_api_error}")

                if resp.status_code in (403, 429):
                    remaining = resp.headers.get("X-RateLimit-Remaining", "")
                    if remaining == "0" or "rate limit" in msg.lower():
                        self.last_api_error = (
                            f"API 速率限制已耗尽 (HTTP {resp.status_code}: {msg or 'rate limit exceeded'})，"
                            "请配置 GitHub Personal Access Token 提升限额"
                        )
                    else:
                        self.last_api_error = f"访问受限 (HTTP {resp.status_code}: {msg or 'Forbidden'})"
                    raise RuntimeError(f"[GitHub] {self.last_api_error}")

                if resp.status_code == 404:
                    self.last_api_error = f"目标不存在 (HTTP 404): {endpoint}"
                    raise RuntimeError(f"[GitHub] {self.last_api_error}")

                if resp.status_code == 422:
                    self.last_api_error = f"请求参数校验失败 (HTTP 422: {msg or 'Validation Failed'})"
                    raise RuntimeError(f"[GitHub] {self.last_api_error}")

                last_error = f"HTTP {resp.status_code}" + (f" ({msg})" if msg else "")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.0 + attempt)
                    continue

            except RuntimeError:
                raise
            except requests.RequestException as e:
                last_error = f"网络请求失败: {e}"
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.0 + attempt)
                    continue

        self.last_api_error = last_error
        raise RuntimeError(f"[GitHub] 请求失败 ({endpoint}): {last_error}")

    # ==================== 用户缓存与解析 ====================

    def _cache_get_user(self, key: str) -> Optional[dict]:
        entry = self._user_cache.get(key.lower())
        if entry and time.time() - entry.get("_cached_at", 0) < self.USER_CACHE_TTL:
            return entry.get("data")
        return None

    def _cache_set_user(self, data: dict, alias_key: str = "") -> dict:
        now = time.time()
        record = {"data": data, "_cached_at": now}
        login = str(data.get("login") or "").strip()
        uid_num = str(data.get("id") or "").strip()
        if login:
            self._user_cache[login.lower()] = record
        if uid_num:
            self._user_cache[uid_num.lower()] = record
        if alias_key:
            self._user_cache[alias_key.lower()] = record
        return data

    def _fetch_user_raw(self, uid: str, force: bool = False) -> Optional[dict]:
        """根据用户名或数字 ID 获取 GitHub 用户原始 JSON；404 返回 None"""
        clean = self._clean_uid(uid)
        if not clean:
            return None
        if not force:
            cached = self._cache_get_user(clean)
            if cached:
                return cached

        data = None
        if clean.isdigit():
            # 支持纯数字 GitHub User ID 直查 (/user/{id})，若无则回退用户名 (/users/{name})
            data = self._get(f"/user/{quote(clean)}", allow_404=True)
            if not isinstance(data, dict) or not data.get("login"):
                data = self._get(f"/users/{quote(clean)}", allow_404=True)
        else:
            data = self._get(f"/users/{quote(clean)}", allow_404=True)

        if not isinstance(data, dict) or not data.get("login"):
            return None
        return self._cache_set_user(data, alias_key=clean)

    def _resolve_login(self, uid: str) -> str:
        """将输入 UID（可能是数字 ID 或 @username）解析为标准 GitHub login"""
        clean = self._clean_uid(uid)
        if not clean:
            raise ValueError("[GitHub] 未提供有效的用户名或 UID")
        if clean.isdigit():
            raw = self._fetch_user_raw(clean)
            if not raw or not raw.get("login"):
                raise RuntimeError(f"[GitHub] 未找到数字 ID 为 {clean} 的用户")
            return str(raw["login"])
        cached = self._cache_get_user(clean)
        if cached and cached.get("login"):
            return str(cached["login"])
        return clean

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        """检查账号凭证是否有效（未配置凭证返回 False）"""
        cookies = self._raw_cookies()
        if not cookies:
            return False
        token = self._extract_account_token()
        try:
            if token:
                data = self._get("/user")
                return isinstance(data, dict) and bool(data.get("login"))
            cookie_user = (
                cookies.get("dotcom_user")
                or cookies.get("user_login")
                or ""
            ).strip()
            if cookie_user:
                raw = self._fetch_user_raw(cookie_user, force=True)
                return bool(raw and raw.get("login"))
            return False
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        """获取当前凭证对应的 GitHub 登录用户"""
        cookies = self._raw_cookies()
        if not cookies:
            return None
        token = self._extract_account_token()
        try:
            if token:
                data = self._get("/user")
                if isinstance(data, dict) and data.get("login"):
                    self._cache_set_user(data)
                    return {
                        "uid": str(data["login"]),
                        "nickname": str(data.get("name") or data["login"]),
                        "avatarUrl": str(data.get("avatar_url") or ""),
                    }
            cookie_user = (
                cookies.get("dotcom_user")
                or cookies.get("user_login")
                or ""
            ).strip()
            if cookie_user:
                raw = self._fetch_user_raw(cookie_user)
                if raw and raw.get("login"):
                    return {
                        "uid": str(raw["login"]),
                        "nickname": str(raw.get("name") or raw["login"]),
                        "avatarUrl": str(raw.get("avatar_url") or ""),
                    }
                return {"uid": cookie_user, "nickname": cookie_user, "avatarUrl": ""}
        except Exception:
            pass
        return None

    def test_account(self) -> dict:
        """测试当前 GitHub 凭证可用性"""
        cookies = self._raw_cookies()
        if not cookies:
            return {"ok": False, "error": "未配置 Token 或 Cookie"}
        token = self._extract_account_token()
        if token:
            try:
                data = self._get("/user")
                if not isinstance(data, dict) or not data.get("login"):
                    return {"ok": False, "error": "Token 验证失败：未返回登录用户"}
                return {
                    "ok": True,
                    "login_user": {
                        "uid": str(data["login"]),
                        "nickname": str(data.get("name") or data["login"]),
                        "avatarUrl": str(data.get("avatar_url") or ""),
                    },
                }
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # 浏览器 Cookie 降级检查
        cookie_user = (cookies.get("dotcom_user") or cookies.get("user_login") or "").strip()
        if cookie_user:
            try:
                raw = self._fetch_user_raw(cookie_user, force=True)
                if raw and raw.get("login"):
                    return {
                        "ok": True,
                        "login_user": {
                            "uid": str(raw["login"]),
                            "nickname": str(raw.get("name") or raw["login"]),
                            "avatarUrl": str(raw.get("avatar_url") or ""),
                        },
                        "warning": (
                            "当前配置的是浏览器 Cookie（dotcom_user），"
                            "GitHub REST API 建议粘贴 Personal Access Token (ghp_/github_pat_) 以获得 5000 次/小时速率配额"
                        ),
                    }
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {
            "ok": False,
            "error": "未能识别有效的 GitHub Token（ghp_/github_pat_）或 dotcom_user Cookie",
        }

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜索 GitHub 用户/组织"""
        kw = self._clean_uid(keyword) or (keyword or "").strip()
        if not kw:
            return []
        per_page = max(1, min(int(limit or 20), 100))
        data = self._get("/search/users", params={"q": kw, "per_page": per_page})
        items = (data.get("items") or []) if isinstance(data, dict) else []
        results = []
        for u in items[:limit]:
            if not isinstance(u, dict) or not u.get("login"):
                continue
            login = str(u.get("login", ""))
            results.append({
                "uid": login,
                "nickname": str(u.get("name") or login),
                "avatarUrl": str(u.get("avatar_url") or ""),
                "signature": str(u.get("bio") or u.get("html_url") or f"https://github.com/{login}"),
                "fans": int(u.get("followers") or 0),
                "is_verified": _github_verified(u),
            })
        return results

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """获取 GitHub 用户公开资料（用户不存在返回 None，其余错误上抛）"""
        user = self._fetch_user_raw(uid)
        if not user:
            return None

        login = str(user.get("login") or self._clean_uid(uid))
        nickname = str(user.get("name") or login)
        created_ms = self._parse_iso_ms(str(user.get("created_at") or ""))
        is_org = user.get("type") == "Organization"
        is_staff = bool(user.get("site_admin"))
        is_hireable = bool(user.get("hireable"))

        vip_label = ""
        if is_org:
            vip_label = "Organization"
        elif is_staff:
            vip_label = "GitHub Staff"
        elif is_hireable:
            vip_label = "Hireable"

        return PlatformProfile(
            platform="github",
            uid=login,
            nickname=nickname,
            avatar_url=str(user.get("avatar_url") or ""),
            background_url="",
            signature=str(user.get("bio") or ""),
            gender=0,
            birthday="",
            location=str(user.get("location") or ""),
            join_time=str(created_ms) if created_ms > 0 else "",
            level=0,
            is_vip=bool(vip_label),
            vip_label=vip_label,
            extra={
                "login": login,
                "id": user.get("id", 0),
                "followers": int(user.get("followers") or 0),
                "following": int(user.get("following") or 0),
                "follow_count": int(user.get("following") or 0),
                "fan_count": int(user.get("followers") or 0),
                "public_repos": int(user.get("public_repos") or 0),
                "public_gists": int(user.get("public_gists") or 0),
                "company": str(user.get("company") or ""),
                "blog": str(user.get("blog") or ""),
                "twitter_username": str(user.get("twitter_username") or ""),
                "html_url": str(user.get("html_url") or f"https://github.com/{login}"),
                "type": str(user.get("type") or "User"),
            },
        )

    # ==================== 内容列表（公开仓库 + Star 仓库） ====================

    def _repo_to_content_item(self, repo: dict, is_owner: bool) -> Optional[ContentItem]:
        if not isinstance(repo, dict):
            return None
        owner = repo.get("owner") if isinstance(repo.get("owner"), dict) else {}
        owner_login = str(owner.get("login") or "")
        name = str(repo.get("name") or "")
        full_name = str(repo.get("full_name") or (f"{owner_login}/{name}" if owner_login and name else name))
        if not full_name:
            return None

        # Flask 路由 /api/<platform>/playlist/<item_id> 的 item_id 不宜含 '/'，用 '__' 编码 owner/repo
        item_id = full_name.replace("/", "__")
        title = name if (is_owner and name) else full_name
        pushed_or_created = (
            repo.get("pushed_at")
            or repo.get("updated_at")
            or repo.get("created_at")
            or ""
        )
        ts_ms = self._parse_iso_ms(str(pushed_or_created))
        lang = str(repo.get("language") or "")
        desc = str(repo.get("description") or "")

        return ContentItem(
            item_id=item_id,
            title=title[:200],
            cover_url=str(owner.get("avatar_url") or ""),
            count=int(repo.get("stargazers_count") or 0),
            view_count=int(repo.get("forks_count") or 0),
            creator=owner_login,
            description=desc[:200],
            is_owner=is_owner,
            create_time=str(ts_ms) if ts_ms > 0 else "",
            url=str(repo.get("html_url") or f"https://github.com/{full_name}"),
            extra={
                "full_name": full_name,
                "language": lang,
                "stargazers_count": int(repo.get("stargazers_count") or 0),
                "forks_count": int(repo.get("forks_count") or 0),
                "watchers_count": int(repo.get("watchers_count") or 0),
                "open_issues_count": int(repo.get("open_issues_count") or 0),
                "fork": bool(repo.get("fork")),
                "topics": list(repo.get("topics") or []),
                "default_branch": str(repo.get("default_branch") or "main"),
            },
        )

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取用户的公开仓库（is_owner=True）与 Star 仓库（is_owner=False）"""
        login = self._resolve_login(uid)
        owned_raw = self._get(
            f"/users/{quote(login)}/repos",
            params={"sort": "updated", "per_page": 50, "type": "owner"},
        )
        starred_raw = self._get(
            f"/users/{quote(login)}/starred",
            params={"per_page": 30},
        )

        items: list[ContentItem] = []
        seen_ids: set[str] = set()

        for repo in (owned_raw if isinstance(owned_raw, list) else []):
            ci = self._repo_to_content_item(repo, is_owner=True)
            if ci and ci.item_id not in seen_ids:
                seen_ids.add(ci.item_id)
                items.append(ci)

        for repo in (starred_raw if isinstance(starred_raw, list) else []):
            ci = self._repo_to_content_item(repo, is_owner=False)
            if ci and ci.item_id not in seen_ids:
                seen_ids.add(ci.item_id)
                items.append(ci)

        return items

    def get_content_detail(self, item_id: str) -> Optional[dict]:
        """获取仓库详情及最近提交记录（点击仓库卡片弹窗展示）"""
        raw_id = str(item_id or "").strip()
        if not raw_id:
            return None
        full_name = raw_id.replace("__", "/", 1) if "__" in raw_id else raw_id
        if "/" not in full_name:
            return None
        owner, repo_name = full_name.split("/", 1)
        repo = self._get(f"/repos/{quote(owner)}/{quote(repo_name)}", allow_404=True)
        if not isinstance(repo, dict) or not repo.get("full_name"):
            return None

        commits_raw = self._get(
            f"/repos/{quote(owner)}/{quote(repo_name)}/commits",
            params={"per_page": 25},
            allow_404=True,
            allow_409=True,
        )
        commit_items = []
        for c in (commits_raw if isinstance(commits_raw, list) else []):
            if not isinstance(c, dict):
                continue
            sha = str(c.get("sha") or "")[:7]
            commit_obj = c.get("commit") if isinstance(c.get("commit"), dict) else {}
            msg = str(commit_obj.get("message") or "").splitlines()[0].strip() or "Commit"
            author_obj = commit_obj.get("author") if isinstance(commit_obj.get("author"), dict) else {}
            top_author = c.get("author") if isinstance(c.get("author"), dict) else {}
            author_name = (
                str(top_author.get("login") or "")
                or str(author_obj.get("name") or "")
                or owner
            )
            date_str = str(author_obj.get("date") or "")[:10]
            album_info = " · ".join(filter(None, [sha, date_str]))
            commit_items.append({
                "id": sha or str(len(commit_items) + 1),
                "title": msg[:200],
                "artist": author_name,
                "album": album_info,
                "duration": 0,
            })

        meta_parts = []
        if repo.get("language"):
            meta_parts.append(f"语言: {repo['language']}")
        license_obj = repo.get("license") if isinstance(repo.get("license"), dict) else {}
        if license_obj.get("spdx_id"):
            meta_parts.append(f"协议: {license_obj['spdx_id']}")
        topics = repo.get("topics") or []
        if topics:
            meta_parts.append(f"标签: {', '.join(str(t) for t in topics[:6])}")

        desc = str(repo.get("description") or "").strip()
        if meta_parts:
            desc = (f"{desc}\n" if desc else "") + " | ".join(meta_parts)

        owner_obj = repo.get("owner") if isinstance(repo.get("owner"), dict) else {}
        created_ms = self._parse_iso_ms(str(repo.get("created_at") or ""))

        return {
            "title": str(repo.get("full_name") or full_name),
            "coverUrl": str(owner_obj.get("avatar_url") or ""),
            "count": len(commit_items),
            "viewCount": int(repo.get("forks_count") or 0),
            "description": desc[:500],
            "creator": str(owner_obj.get("login") or owner),
            "createTime": str(created_ms) if created_ms > 0 else "",
            "subscribedCount": int(repo.get("stargazers_count") or 0),
            "items": commit_items,
        }

    # ==================== 动态（公开活动事件） ====================

    _EVENT_TYPE_MAP = {
        "PushEvent": "推送代码",
        "WatchEvent": "Star 仓库",
        "ForkEvent": "Fork 仓库",
        "CreateEvent": "创建分支/仓库",
        "DeleteEvent": "删除分支/标签",
        "IssuesEvent": "Issue 动态",
        "IssueCommentEvent": "评论 Issue",
        "PullRequestEvent": "Pull Request",
        "PullRequestReviewEvent": "审查 PR",
        "PullRequestReviewCommentEvent": "评论 PR",
        "ReleaseEvent": "发布版本",
        "PublicEvent": "开源仓库",
        "MemberEvent": "协作者变更",
        "GollumEvent": "更新 Wiki",
        "CommitCommentEvent": "评论提交",
    }

    @classmethod
    def _summarize_github_event(cls, ev: dict) -> tuple[str, str, str]:
        """从 GitHub Event 提取 (中文类型, 内容摘要, 链接)"""
        ev_type = str(ev.get("type") or "Event")
        label = cls._EVENT_TYPE_MAP.get(ev_type, ev_type)
        repo_obj = ev.get("repo") if isinstance(ev.get("repo"), dict) else {}
        repo_name = str(repo_obj.get("name") or "")
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        default_url = f"https://github.com/{repo_name}" if repo_name else ""

        if ev_type == "PushEvent":
            ref = str(payload.get("ref") or "").replace("refs/heads/", "")
            commits = payload.get("commits") if isinstance(payload.get("commits"), list) else []
            msgs = [
                str(c.get("message") or "").splitlines()[0].strip()
                for c in commits if isinstance(c, dict) and c.get("message")
            ]
            if msgs:
                prefix = f"[{ref}] " if ref else ""
                return label, f"{prefix}{'; '.join(msgs[:3])}"[:500], default_url
            size = payload.get("size") or len(commits)
            return label, (f"推送到 {ref} ({size} 个提交)" if ref else "推送了代码更新"), default_url

        if ev_type == "WatchEvent":
            return label, f"Star 了仓库 {repo_name}", default_url

        if ev_type == "ForkEvent":
            forkee = payload.get("forkee") if isinstance(payload.get("forkee"), dict) else {}
            fork_name = str(forkee.get("full_name") or "")
            url = str(forkee.get("html_url") or default_url)
            return label, (f"Fork 为 {fork_name}" if fork_name else f"Fork 了 {repo_name}"), url

        if ev_type == "CreateEvent":
            ref_type = str(payload.get("ref_type") or "repository")
            ref = str(payload.get("ref") or "")
            desc = str(payload.get("description") or "")
            text = f"创建了 {ref_type}" + (f" {ref}" if ref else "") + (f"：{desc}" if desc else "")
            return label, text[:500], default_url

        if ev_type in ("IssuesEvent", "IssueCommentEvent"):
            action = str(payload.get("action") or "")
            issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
            title = str(issue.get("title") or "")
            num = issue.get("number")
            comment = payload.get("comment") if isinstance(payload.get("comment"), dict) else {}
            body = str(comment.get("body") or "").strip()
            url = str(comment.get("html_url") or issue.get("html_url") or default_url)
            head = f"#{num} {title}".strip()
            text = f"{head}：{body}" if body else f"{action} {head}".strip()
            return label, text[:500], url

        if ev_type in ("PullRequestEvent", "PullRequestReviewEvent", "PullRequestReviewCommentEvent"):
            action = str(payload.get("action") or "")
            pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
            title = str(pr.get("title") or "")
            num = pr.get("number") or payload.get("number")
            url = str(pr.get("html_url") or default_url)
            head = f"PR #{num} {title}".strip() if num else title
            return label, f"{action} {head}".strip()[:500], url

        if ev_type == "ReleaseEvent":
            release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
            tag = str(release.get("tag_name") or release.get("name") or "")
            url = str(release.get("html_url") or default_url)
            return label, f"发布版本 {tag}".strip(), url

        return label, repo_name, default_url

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户的 GitHub 公开动态"""
        login = self._resolve_login(uid)
        per_page = max(1, min(int(limit or 30), 100))
        raw_events = self._get(
            f"/users/{quote(login)}/events/public",
            params={"per_page": per_page},
        )
        events: list[EventItem] = []
        for ev in (raw_events if isinstance(raw_events, list) else [])[:limit]:
            if not isinstance(ev, dict):
                continue
            label, content, url = self._summarize_github_event(ev)
            repo_obj = ev.get("repo") if isinstance(ev.get("repo"), dict) else {}
            repo_name = str(repo_obj.get("name") or "")
            actor_obj = ev.get("actor") if isinstance(ev.get("actor"), dict) else {}
            actor_login = str(actor_obj.get("login") or login)
            ts_ms = self._parse_iso_ms(str(ev.get("created_at") or ""))

            events.append(EventItem(
                event_id=str(ev.get("id") or f"{ts_ms}_{len(events)}"),
                event_type=label,
                content=content,
                timestamp=ts_ms,
                media_title=repo_name,
                media_artist=actor_login,
                url=url,
                extra={
                    "raw_type": str(ev.get("type") or ""),
                    "repo": repo_name,
                },
            ))
        return events

    # ==================== 社交关系（关注/粉丝） ====================

    def _social_page(
        self, uid: str, kind: str, limit: int, skip: int
    ) -> tuple[list[dict], bool, int]:
        """
        增量拉取 GitHub 关注/粉丝列表。
        kind: "following" | "followers"
        单页 100 条，支持 skip 跳过已拉取条目；返回 (条目列表, has_more, 真实总数或 -1)。
        """
        login = self._resolve_login(uid)
        need = max(0, int(limit or 0))
        skip = max(0, int(skip or 0))
        if need == 0:
            return [], False, -1

        per_page = 100
        page = skip // per_page + 1
        skip_in_page = skip % per_page
        items: list[dict] = []
        last_batch_len = 0

        while len(items) < need:
            batch = self._get(
                f"/users/{quote(login)}/{kind}",
                params={"per_page": per_page, "page": page},
            )
            if not isinstance(batch, list) or not batch:
                last_batch_len = 0
                break
            last_batch_len = len(batch)
            for u in batch:
                if not isinstance(u, dict) or not u.get("login"):
                    continue
                if skip_in_page > 0:
                    skip_in_page -= 1
                    continue
                u_login = str(u["login"])
                items.append({
                    "uid": u_login,
                    "nickname": u_login,
                    "avatarUrl": str(u.get("avatar_url") or ""),
                    "signature": str(u.get("html_url") or f"https://github.com/{u_login}"),
                    "fans": 0,
                    "is_verified": _github_verified(u),
                })
                if len(items) >= need:
                    break
            if last_batch_len < per_page or len(items) >= need:
                break
            page += 1

        # 如果缓存中已有该用户资料，直接读取真实关注/粉丝总数
        total = -1
        cached_user = self._cache_get_user(login)
        if isinstance(cached_user, dict):
            count_field = "following" if kind == "following" else "followers"
            if cached_user.get(count_field) is not None:
                try:
                    total = int(cached_user[count_field])
                except (TypeError, ValueError):
                    total = -1

        if total >= 0:
            has_more = (skip + len(items)) < total
        else:
            has_more = len(items) >= need and last_batch_len == per_page

        return items, has_more, total

    def get_follows(self, uid: str, limit: int = 100, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取关注列表"""
        return self._social_page(uid, "following", limit, skip)

    def get_followers(self, uid: str, limit: int = 100, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取粉丝列表"""
        return self._social_page(uid, "followers", limit, skip)

    def refresh_user_info(self, uid: str) -> Optional[dict]:
        """重新拉取单个用户的最新 followers 与认证状态（图谱重新标记大V用）"""
        raw = self._fetch_user_raw(uid, force=True)
        if not raw:
            return None
        login = str(raw.get("login") or self._clean_uid(uid))
        return {
            "nickname": str(raw.get("name") or login),
            "fans": int(raw.get("followers") or 0),
            "is_verified": _github_verified(raw),
        }
