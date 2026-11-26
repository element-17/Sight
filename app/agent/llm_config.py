"""
LLM 模型配置管理与多提供商客户端工厂（OpenAI 兼容 + Google Gemini 原生多模态）

配置存储于 `<runtime_dir>/credentials/llm.json`（已被 .gitignore 忽略），
并支持通过环境变量兜底（SIGHT_LLM_* / GEMINI_API_KEY / GOOGLE_API_KEY / OPENAI_*）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from langchain_openai import ChatOpenAI

from app.paths import get_runtime_dir

PROVIDER_OPENAI = "openai_compatible"
PROVIDER_GEMINI = "gemini"
VALID_PROVIDERS = {PROVIDER_OPENAI, PROVIDER_GEMINI}

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_STEPS = 8
DEFAULT_TIMEOUT = 90

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
    if s in ("openai", "openai-compatible"):
        return PROVIDER_OPENAI
    return None


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
    合并本地文件配置、环境变量兜底与可选临时覆盖（如连通性测试未保存草稿）。
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

    if override_provider:
        provider = override_provider
    elif file_provider:
        provider = file_provider
    elif env_provider:
        provider = env_provider
    elif not file_cfg and not (env_sight_key or env_openai_key) and env_gemini_key:
        provider = PROVIDER_GEMINI
    else:
        provider = PROVIDER_OPENAI

    same_file_provider = (file_provider or PROVIDER_OPENAI) == provider

    env_base_url = (
        os.environ.get("SIGHT_LLM_BASE_URL")
        or ("" if provider == PROVIDER_GEMINI else (os.environ.get("OPENAI_BASE_URL") or ""))
    ).strip()
    env_api_key = (
        env_sight_key or env_gemini_key
        if provider == PROVIDER_GEMINI
        else (env_sight_key or env_openai_key)
    )
    env_model = (
        os.environ.get("SIGHT_LLM_MODEL")
        or ("" if provider == PROVIDER_GEMINI else (os.environ.get("OPENAI_MODEL") or ""))
    ).strip()

    file_key = str(file_cfg.get("api_key") or "").strip()
    file_base_url = str(file_cfg.get("base_url") or "").strip() if same_file_provider else ""
    file_model = str(file_cfg.get("model") or "").strip() if same_file_provider else ""

    if provider == PROVIDER_GEMINI:
        base_url = file_base_url or env_base_url
        model = file_model or env_model or DEFAULT_GEMINI_MODEL
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
            if provider == PROVIDER_GEMINI or raw_base:
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
    if provider == PROVIDER_GEMINI:
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
                raise ValueError("不支持的模型提供商类型，请选择 openai_compatible 或 gemini")
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
    """按当前有效配置构建 LangChain ChatModel（Gemini 原生或 OpenAI 兼容）。"""
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
    """构建原生 google-genai Client，用于图片字节流与视频原生多模态分析。"""
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
            "error": str(e),
        }
