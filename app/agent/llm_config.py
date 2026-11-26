"""
LLM 模型配置管理、多提供商客户端工厂与模型列表拉取
（OpenAI 兼容 + Google Gemini 原生多模态 + Anthropic Messages 协议）

配置存储于 `<runtime_dir>/credentials/llm.json`（已被 .gitignore 忽略），
并支持通过环境变量兜底（SIGHT_LLM_* / GEMINI_API_KEY / ANTHROPIC_API_KEY / OPENAI_*）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from langchain_openai import ChatOpenAI

from app.paths import get_runtime_dir

PROVIDER_OPENAI = "openai_compatible"
PROVIDER_GEMINI = "gemini"
PROVIDER_ANTHROPIC = "anthropic"
VALID_PROVIDERS = {PROVIDER_OPENAI, PROVIDER_GEMINI, PROVIDER_ANTHROPIC}

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_STEPS = 8
DEFAULT_TIMEOUT = 90
ANTHROPIC_API_VERSION = "2023-06-01"

LLM_PRESETS: list[dict[str, str]] = [
    {
        "id": "gemini_flash",
        "name": "Gemini 2.5 Flash (原生多模态·推荐)",
        "provider": PROVIDER_GEMINI,
        "base_url": "",
        "model": "gemini-2.5-flash",
    },
    {
        "id": "gemini_pro",
        "name": "Gemini 2.5 Pro (原生多模态)",
        "provider": PROVIDER_GEMINI,
        "base_url": "",
        "model": "gemini-2.5-pro",
    },
    {
        "id": "anthropic_sonnet",
        "name": "Claude Sonnet (Anthropic 协议)",
        "provider": PROVIDER_ANTHROPIC,
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
    },
    {
        "id": "anthropic_haiku",
        "name": "Claude Haiku (Anthropic 协议)",
        "provider": PROVIDER_ANTHROPIC,
        "base_url": "https://api.anthropic.com",
        "model": "claude-haiku-4-5",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    {
        "id": "qwen",
        "name": "通义千问 (DashScope)",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 (SiliconFlow)",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-72B-Instruct",
    },
    {
        "id": "ollama",
        "name": "Ollama (本地)",
        "provider": PROVIDER_OPENAI,
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:14b",
    },
]

_CONFIG_LOCK = threading.RLock()


def get_llm_config_path() -> Path:
    """动态解析 llm.json 路径，自动兼容 SIGHT_DATA_DIR 覆盖与 PyInstaller 打包。"""
    return get_runtime_dir() / "credentials" / "llm.json"


def _normalize_provider(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().lower()
    if s in VALID_PROVIDERS:
        return s
    if s in ("google", "google_genai", "gemini_native"):
        return PROVIDER_GEMINI
    if s in ("claude", "a", "a/", "anthropic_messages"):
        return PROVIDER_ANTHROPIC
    if s in ("openai", "openai-compatible"):
        return PROVIDER_OPENAI
    return None


def _normalize_anthropic_base_url(base_url: str) -> str:
    """
    标准化 Anthropic Base URL：
    Anthropic SDK 会在 base_url 后自动拼接 `/v1/messages` 与 `/v1/models`。
    若用户习惯性粘贴了 `.../v1` 或 `.../v1/messages`，自动剥离尾部路径避免出现 `/v1/v1/...`。
    """
    u = str(base_url or "").strip().rstrip("/")
    if not u:
        return ""
    for suffix in ("/v1/messages", "/v1/models", "/v1"):
        if u.lower().endswith(suffix):
            u = u[: -len(suffix)].rstrip("/")
            break
    return u


def _parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _is_local_base_url(base_url: str) -> bool:
    try:
        host = (urlparse(base_url).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    except Exception:
        return False


def _mask_secret(secret: str) -> str:
    s = (secret or "").strip()
    if not s:
        return ""
    if len(s) <= 8:
        return s[:2] + "***"
    return f"{s[:4]}...{s[-4:]}"


def _clamp_float(val: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(val)
        return max(lo, min(hi, f))
    except (TypeError, ValueError):
        return default


def _clamp_int(val: Any, lo: int, hi: int, default: int) -> int:
    try:
        i = int(val)
        return max(lo, min(hi, i))
    except (TypeError, ValueError):
        return default


def _read_file_config() -> dict[str, Any]:
    path = get_llm_config_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[agent.llm_config] llm.json 读取失败，忽略: {e}")
        return {}


def _write_file_config(data: dict[str, Any]) -> None:
    path = get_llm_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_effective_config(overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    合并本地文件配置、环境变量兜底与可选临时覆盖（如连通性测试或拉取模型列表时的草稿）。
    """
    with _CONFIG_LOCK:
        file_cfg = _read_file_config()

    file_provider = _normalize_provider(file_cfg.get("provider"))
    override_provider = _normalize_provider(overrides.get("provider")) if overrides else None
    env_provider = _normalize_provider(os.environ.get("SIGHT_LLM_PROVIDER"))

    env_sight_key = (os.environ.get("SIGHT_LLM_API_KEY") or "").strip()
    env_openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    env_gemini_key = (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    ).strip()
    env_anthropic_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()

    if override_provider:
        provider = override_provider
    elif file_provider:
        provider = file_provider
    elif env_provider:
        provider = env_provider
    elif not file_cfg and not (env_sight_key or env_openai_key):
        if env_gemini_key:
            provider = PROVIDER_GEMINI
        elif env_anthropic_key:
            provider = PROVIDER_ANTHROPIC
        else:
            provider = PROVIDER_OPENAI
    else:
        provider = PROVIDER_OPENAI

    same_file_provider = (file_provider or PROVIDER_OPENAI) == provider

    if provider == PROVIDER_GEMINI:
        env_base_url = (os.environ.get("SIGHT_LLM_BASE_URL") or "").strip()
        env_api_key = env_sight_key or env_gemini_key
        env_model = (os.environ.get("SIGHT_LLM_MODEL") or "").strip()
    elif provider == PROVIDER_ANTHROPIC:
        env_base_url = (
            os.environ.get("SIGHT_LLM_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or ""
        ).strip()
        env_api_key = env_sight_key or env_anthropic_key
        env_model = (
            os.environ.get("SIGHT_LLM_MODEL")
            or os.environ.get("ANTHROPIC_MODEL")
            or ""
        ).strip()
    else:
        env_base_url = (
            os.environ.get("SIGHT_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or ""
        ).strip()
        env_api_key = env_sight_key or env_openai_key
        env_model = (
            os.environ.get("SIGHT_LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or ""
        ).strip()

    file_key = str(file_cfg.get("api_key") or "").strip()
    file_base_url = str(file_cfg.get("base_url") or "").strip() if same_file_provider else ""
    file_model = str(file_cfg.get("model") or "").strip() if same_file_provider else ""

    if provider == PROVIDER_GEMINI:
        base_url = file_base_url or env_base_url
        model = file_model or env_model or DEFAULT_GEMINI_MODEL
    elif provider == PROVIDER_ANTHROPIC:
        base_url = _normalize_anthropic_base_url(
            file_base_url or env_base_url or DEFAULT_ANTHROPIC_BASE_URL
        )
        model = file_model or env_model or DEFAULT_ANTHROPIC_MODEL
    else:
        base_url = file_base_url or env_base_url or DEFAULT_BASE_URL
        model = file_model or env_model or DEFAULT_MODEL

    api_key = file_key or env_api_key
    api_key_source = "file" if file_key else ("env" if env_api_key else "none")

    temperature = _clamp_float(
        file_cfg.get("temperature", os.environ.get("SIGHT_LLM_TEMPERATURE")),
        0.0,
        2.0,
        DEFAULT_TEMPERATURE,
    )
    max_steps = _clamp_int(
        file_cfg.get("max_steps", os.environ.get("SIGHT_LLM_MAX_STEPS")),
        2,
        20,
        DEFAULT_MAX_STEPS,
    )
    timeout = _clamp_int(
        file_cfg.get("timeout", os.environ.get("SIGHT_LLM_TIMEOUT")),
        10,
        300,
        DEFAULT_TIMEOUT,
    )
    enable_multimodal = _parse_bool(
        file_cfg.get("enable_multimodal", os.environ.get("SIGHT_LLM_MULTIMODAL")),
        True,
    )

    if overrides:
        if "base_url" in overrides and overrides["base_url"] is not None:
            raw_base = str(overrides["base_url"]).strip()
            if provider == PROVIDER_GEMINI:
                base_url = raw_base
            elif provider == PROVIDER_ANTHROPIC:
                base_url = _normalize_anthropic_base_url(raw_base) or DEFAULT_ANTHROPIC_BASE_URL
            elif raw_base:
                base_url = raw_base
        if overrides.get("model"):
            model = str(overrides["model"]).strip()
        if overrides.get("api_key"):
            api_key = str(overrides["api_key"]).strip()
            api_key_source = "override"
        if overrides.get("temperature") is not None:
            temperature = _clamp_float(overrides["temperature"], 0.0, 2.0, temperature)
        if overrides.get("max_steps") is not None:
            max_steps = _clamp_int(overrides["max_steps"], 2, 20, max_steps)
        if overrides.get("timeout") is not None:
            timeout = _clamp_int(overrides["timeout"], 10, 300, timeout)
        if "enable_multimodal" in overrides and overrides["enable_multimodal"] is not None:
            enable_multimodal = _parse_bool(overrides["enable_multimodal"], enable_multimodal)

    local_endpoint = (provider == PROVIDER_OPENAI) and _is_local_base_url(base_url)
    if provider in (PROVIDER_GEMINI, PROVIDER_ANTHROPIC):
        configured = bool(model and api_key)
    else:
        configured = bool(base_url and model and (api_key or local_endpoint))

    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "api_key_source": api_key_source,
        "model": model,
        "temperature": temperature,
        "max_steps": max_steps,
        "timeout": timeout,
        "enable_multimodal": enable_multimodal,
        "supports_vision": enable_multimodal,
        "supports_video": (provider == PROVIDER_GEMINI) and enable_multimodal,
        "is_local": local_endpoint,
        "configured": configured,
    }


def get_public_config() -> dict[str, Any]:
    """返回脱敏后的 LLM 配置（绝不暴露明文 api_key），供前端展示。"""
    cfg = load_effective_config()
    return {
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "max_steps": cfg["max_steps"],
        "timeout": cfg["timeout"],
        "enable_multimodal": cfg["enable_multimodal"],
        "supports_vision": cfg["supports_vision"],
        "supports_video": cfg["supports_video"],
        "has_api_key": bool(cfg["api_key"]),
        "api_key_preview": _mask_secret(cfg["api_key"]),
        "api_key_source": cfg["api_key_source"],
        "is_local": cfg["is_local"],
        "configured": cfg["configured"],
        "presets": LLM_PRESETS,
    }


def save_llm_config(payload: dict[str, Any]) -> dict[str, Any]:
    """
    保存 LLM 配置到 credentials/llm.json。
    若 payload 未提供 api_key 或为空字符串，默认保留旧密钥；显式传 clear_api_key=True 时清除。
    """
    if not isinstance(payload, dict):
        raise ValueError("配置格式错误")

    with _CONFIG_LOCK:
        existing = _read_file_config()
        raw_provider = payload.get("provider")
        if raw_provider is not None and str(raw_provider).strip():
            provider = _normalize_provider(raw_provider)
            if not provider:
                raise ValueError("不支持的模型提供商类型，请选择 gemini、anthropic 或 openai_compatible")
        else:
            provider = _normalize_provider(existing.get("provider")) or PROVIDER_OPENAI

        base_url = str(payload.get("base_url") or "").strip()
        model = str(payload.get("model") or "").strip()

        if provider == PROVIDER_OPENAI:
            if not base_url:
                raise ValueError("请填写 API Base URL")
            parsed = urlparse(base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("API Base URL 必须是以 http:// 或 https:// 开头的有效地址")
        elif provider == PROVIDER_ANTHROPIC:
            if base_url:
                parsed = urlparse(base_url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    raise ValueError("Anthropic Base URL 必须是以 http:// 或 https:// 开头的有效地址")
                base_url = _normalize_anthropic_base_url(base_url)
            else:
                base_url = DEFAULT_ANTHROPIC_BASE_URL
        else:
            if base_url:
                parsed = urlparse(base_url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    raise ValueError("自定义中转 Base URL 必须是以 http:// 或 https:// 开头的有效地址")

        if not model:
            raise ValueError("请填写模型名称 (model)")

        new_cfg: dict[str, Any] = {
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "temperature": _clamp_float(
                payload.get("temperature", existing.get("temperature")),
                0.0,
                2.0,
                DEFAULT_TEMPERATURE,
            ),
            "max_steps": _clamp_int(
                payload.get("max_steps", existing.get("max_steps")),
                2,
                20,
                DEFAULT_MAX_STEPS,
            ),
            "timeout": _clamp_int(
                payload.get("timeout", existing.get("timeout")),
                10,
                300,
                DEFAULT_TIMEOUT,
            ),
            "enable_multimodal": _parse_bool(
                payload.get("enable_multimodal", existing.get("enable_multimodal")),
                True,
            ),
        }

        if payload.get("clear_api_key"):
            new_cfg["api_key"] = ""
        else:
            raw_key = payload.get("api_key")
            if raw_key is not None and str(raw_key).strip():
                new_cfg["api_key"] = str(raw_key).strip()
            else:
                new_cfg["api_key"] = str(existing.get("api_key") or "").strip()

        _write_file_config(new_cfg)

    return get_public_config()


def build_chat_model(
    overrides: Optional[dict[str, Any]] = None,
    *,
    streaming: bool = True,
    timeout: Optional[int] = None,
) -> Any:
    """按当前有效配置构建 LangChain ChatModel（Gemini 原生 / Anthropic 协议 / OpenAI 兼容）。"""
    cfg = load_effective_config(overrides)
    if not cfg["configured"]:
        raise RuntimeError(
            "尚未配置可用的 LLM 模型，请先点击「模型配置」填写 API Key 与 Model"
        )

    eff_timeout = timeout or cfg["timeout"]
    if cfg["provider"] == PROVIDER_GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs: dict[str, Any] = {
            "model": cfg["model"],
            "google_api_key": cfg["api_key"],
            "temperature": cfg["temperature"],
            "timeout": eff_timeout,
            "max_retries": 1,
        }
        if cfg["base_url"]:
            kwargs["base_url"] = cfg["base_url"]
        return ChatGoogleGenerativeAI(**kwargs)

    if cfg["provider"] == PROVIDER_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        kwargs = {
            "model": cfg["model"],
            "anthropic_api_key": cfg["api_key"],
            "temperature": min(float(cfg["temperature"]), 1.0),
            "default_request_timeout": eff_timeout,
            "max_retries": 1,
            "streaming": streaming,
            "max_tokens": 8192,
        }
        norm_url = _normalize_anthropic_base_url(cfg["base_url"])
        if norm_url:
            kwargs["anthropic_api_url"] = norm_url
        return ChatAnthropic(**kwargs)

    effective_key = cfg["api_key"] or ("ollama" if cfg["is_local"] else "")
    return ChatOpenAI(
        model=cfg["model"],
        api_key=effective_key,
        base_url=cfg["base_url"],
        temperature=cfg["temperature"],
        timeout=eff_timeout,
        max_retries=1,
        streaming=streaming,
    )


def build_gemini_client(
    overrides: Optional[dict[str, Any]] = None,
    *,
    timeout: Optional[int] = None,
) -> Any:
    """构建原生 google-genai Client，用于图片字节流、视频多模态分析与模型列表查询。"""
    cfg = load_effective_config(overrides)
    if cfg["provider"] != PROVIDER_GEMINI:
        raise RuntimeError("当前未启用 Gemini 原生提供商")
    if not cfg["api_key"]:
        raise RuntimeError("缺少 Gemini API Key，请先在「模型配置」中填写或设置 GEMINI_API_KEY")

    from google import genai
    from google.genai import types

    eff_timeout_ms = int((timeout or cfg["timeout"]) * 1000)
    http_opts: dict[str, Any] = {"timeout": eff_timeout_ms}
    if cfg["base_url"]:
        http_opts["base_url"] = cfg["base_url"]
    return genai.Client(
        api_key=cfg["api_key"],
        http_options=types.HttpOptions(**http_opts),
    )


def format_llm_error(exc: Exception) -> str:
    """
    展开 OpenAI / Anthropic / Gemini / httpx 嵌套异常链，避免只显示笼统的 "Connection error."。
    若在存在代理环境变量时出现 SSL/连接异常，补充可操作排查提示。
    """
    primary = str(exc or "").strip() or type(exc).__name__
    root_msg = ""
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        nxt = cur.__cause__ or cur.__context__
        if nxt is not None:
            cand = str(nxt).strip()
            if cand and cand != primary:
                root_msg = cand
        cur = nxt

    msg = f"{primary} — {root_msg}" if (root_msg and root_msg not in primary) else primary
    low = msg.lower()
    if any(k in low for k in ("ssl", "unexpected_eof", "connection error", "connecterror", "proxy", "timed out")):
        proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or ""
        ).strip()
        if proxy:
            msg += f"（当前检测到代理环境变量 {proxy}，若使用国内中转站或出现 TLS 断开，请将其加入代理直连规则或切换代理节点）"
    return msg


def _extract_error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("type")
                if msg:
                    return f"HTTP {resp.status_code}: {msg}"
            elif isinstance(err, str) and err:
                return f"HTTP {resp.status_code}: {err}"
            if body.get("message"):
                return f"HTTP {resp.status_code}: {body['message']}"
    except Exception:
        pass
    text = (resp.text or "").strip()[:180]
    return f"HTTP {resp.status_code}: {text}" if text else f"HTTP {resp.status_code}"


def _dedupe_models(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        mid = str(item.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        entry = {"id": mid}
        name = str(item.get("name") or "").strip()
        if name and name != mid:
            entry["name"] = name
        owned = str(item.get("owned_by") or "").strip()
        if owned:
            entry["owned_by"] = owned
        result.append(entry)
    result.sort(key=lambda x: x["id"].lower())
    return result


def fetch_available_models(overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    按当前草稿或已保存配置，动态拉取指定协议的可用模型列表。

    - OpenAI 兼容: GET {base_url}/models
    - Anthropic 协议: GET {base_url}/v1/models (携带 x-api-key + anthropic-version)
    - Gemini 原生: google.genai Client models.list()（过滤支持 generateContent 的模型）
    """
    cfg = load_effective_config(overrides)
    provider = cfg["provider"]
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    req_timeout = min(int(cfg["timeout"] or DEFAULT_TIMEOUT), 25)
    t0 = time.perf_counter()

    def _fail(err: str) -> dict[str, Any]:
        return {
            "ok": False,
            "provider": provider,
            "base_url": base_url,
            "count": 0,
            "models": [],
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "error": err,
        }

    if provider in (PROVIDER_GEMINI, PROVIDER_ANTHROPIC) and not api_key:
        return _fail("请先填写 API Key（或配置对应环境变量）后再获取模型列表")
    if provider == PROVIDER_OPENAI:
        if not base_url:
            return _fail("请先填写 API Base URL")
        if not api_key and not cfg["is_local"]:
            return _fail("请先填写 API Key 后再获取模型列表")

    try:
        raw_models: list[dict[str, str]] = []

        if provider == PROVIDER_GEMINI:
            client = build_gemini_client(overrides, timeout=req_timeout)
            for m in client.models.list():
                raw_name = str(getattr(m, "name", "") or "").strip()
                if not raw_name:
                    continue
                actions = (
                    getattr(m, "supported_actions", None)
                    or getattr(m, "supported_generation_methods", None)
                    or []
                )
                if actions and not any("generateContent" in str(a) for a in actions):
                    continue
                clean_id = raw_name[7:] if raw_name.startswith("models/") else raw_name
                display_name = str(getattr(m, "display_name", "") or "").strip()
                raw_models.append({"id": clean_id, "name": display_name})

        elif provider == PROVIDER_ANTHROPIC:
            root = _normalize_anthropic_base_url(base_url) or DEFAULT_ANTHROPIC_BASE_URL
            url = f"{root}/v1/models"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "Accept": "application/json",
            }
            resp = requests.get(url, headers=headers, params={"limit": 100}, timeout=req_timeout)
            # 部分第三方 Anthropic 中转站要求 Bearer 鉴权，遇到 401/403 时兼容重试一次
            if resp.status_code in (401, 403):
                retry_headers = {**headers, "Authorization": f"Bearer {api_key}"}
                resp2 = requests.get(url, headers=retry_headers, params={"limit": 100}, timeout=req_timeout)
                if resp2.status_code == 200:
                    resp = resp2
            if resp.status_code != 200:
                return _fail(_extract_error_message(resp))
            body = resp.json()
            rows = (
                body.get("data")
                if isinstance(body, dict) and isinstance(body.get("data"), list)
                else (body.get("models") if isinstance(body, dict) and isinstance(body.get("models"), list) else (body if isinstance(body, list) else []))
            )
            for item in rows:
                if isinstance(item, str):
                    raw_models.append({"id": item})
                elif isinstance(item, dict):
                    mid = str(item.get("id") or item.get("name") or "").strip()
                    dname = str(item.get("display_name") or "").strip()
                    if mid:
                        raw_models.append({"id": mid, "name": dname})

        else:
            # OpenAI 兼容协议: GET {base_url}/models
            clean_base = base_url.rstrip("/")
            url = clean_base if clean_base.lower().endswith("/models") else f"{clean_base}/models"
            headers = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.get(url, headers=headers, timeout=req_timeout)
            if resp.status_code != 200:
                return _fail(_extract_error_message(resp))
            body = resp.json()
            rows = (
                body.get("data")
                if isinstance(body, dict) and isinstance(body.get("data"), list)
                else (body.get("models") if isinstance(body, dict) and isinstance(body.get("models"), list) else (body if isinstance(body, list) else []))
            )
            for item in rows:
                if isinstance(item, str):
                    raw_models.append({"id": item})
                elif isinstance(item, dict):
                    mid = str(item.get("id") or item.get("name") or "").strip()
                    dname = str(item.get("display_name") or "").strip()
                    owned = str(item.get("owned_by") or "").strip()
                    if mid:
                        raw_models.append({"id": mid, "name": dname, "owned_by": owned})

        models = _dedupe_models(raw_models)
        if not models:
            return _fail("接口返回成功，但未发现可用模型条目（您仍可手动输入模型名称）")
        return {
            "ok": True,
            "provider": provider,
            "base_url": base_url,
            "count": len(models),
            "models": models,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    except Exception as e:
        return _fail(format_llm_error(e))


def test_llm_connection(overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """发送一次最小对话请求探测 LLM 连通性与凭证有效性。"""
    cfg = load_effective_config(overrides)
    t0 = time.perf_counter()
    if not cfg["configured"]:
        return {
            "ok": False,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "supports_video": cfg["supports_video"],
            "latency_ms": 0,
            "error": "缺少 API Key 或模型配置",
        }
    try:
        llm = build_chat_model(overrides, streaming=False, timeout=min(cfg["timeout"], 25))
        resp = llm.invoke("请只回复 OK")
        content = getattr(resp, "content", "")
        if isinstance(content, list):
            text = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in content
            )
        else:
            text = str(content or "")
        return {
            "ok": True,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "supports_video": cfg["supports_video"],
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "reply_preview": text.strip()[:80],
        }
    except Exception as e:
        return {
            "ok": False,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "supports_video": cfg["supports_video"],
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "error": format_llm_error(e),
        }
