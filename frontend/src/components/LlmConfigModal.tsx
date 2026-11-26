import { useEffect, useId, useState, type FormEvent } from "react";
import { api, errorMessage } from "../api";
import { classNames } from "../classes";
import type { LlmConfig, LlmPreset, LlmProvider, LlmTestResult } from "../types";
import styles from "./LlmConfigModal.module.css";
import Icon from "./ui/Icon";
import Modal from "./ui/Modal";

const cx = classNames(styles);

export default function LlmConfigModal({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: (config: LlmConfig) => void;
}) {
  const idPrefix = useId();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [showKey, setShowKey] = useState(false);

  const [presets, setPresets] = useState<LlmPreset[]>([]);
  const [provider, setProvider] = useState<LlmProvider>("openai_compatible");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o-mini");
  const [maxSteps, setMaxSteps] = useState("8");
  const [temperature, setTemperature] = useState("0.2");
  const [enableMultimodal, setEnableMultimodal] = useState(true);
  const [keyPreview, setKeyPreview] = useState("");
  const [keySource, setKeySource] = useState("none");
  const [isLocal, setIsLocal] = useState(false);

  const [feedback, setFeedback] = useState<{
    kind: "ok" | "err";
    text: string;
  } | null>(null);

  const isGemini = provider === "gemini";

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setFeedback(null);
    setApiKey("");
    setShowKey(false);
    void api
      .get<LlmConfig>("/agent/config")
      .then((cfg) => {
        if (!active) return;
        const nextProvider: LlmProvider =
          cfg.provider === "gemini" ? "gemini" : "openai_compatible";
        setPresets(cfg.presets || []);
        setProvider(nextProvider);
        setBaseUrl(
          cfg.base_url ??
            (nextProvider === "gemini" ? "" : "https://api.openai.com/v1"),
        );
        setModel(
          cfg.model ||
            (nextProvider === "gemini" ? "gemini-2.5-flash" : "gpt-4o-mini"),
        );
        setMaxSteps(String(cfg.max_steps ?? 8));
        setTemperature(String(cfg.temperature ?? 0.2));
        setEnableMultimodal(cfg.enable_multimodal ?? true);
        setKeyPreview(cfg.api_key_preview || "");
        setKeySource(cfg.api_key_source || "none");
        setIsLocal(Boolean(cfg.is_local));
      })
      .catch((e) => {
        if (active) setFeedback({ kind: "err", text: errorMessage(e) });
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open]);

  function handleProviderChange(next: LlmProvider) {
    setProvider(next);
    setFeedback(null);
    if (next === "gemini") {
      setIsLocal(false);
      if (
        !model.trim() ||
        !model.toLowerCase().includes("gemini")
      ) {
        setModel("gemini-2.5-flash");
      }
      if (
        baseUrl.trim() === "https://api.openai.com/v1" ||
        baseUrl.includes("deepseek") ||
        baseUrl.includes("dashscope") ||
        baseUrl.includes("siliconflow") ||
        baseUrl.includes("11434")
      ) {
        setBaseUrl("");
      }
    } else {
      if (!baseUrl.trim()) {
        setBaseUrl("https://api.openai.com/v1");
      }
      if (model.toLowerCase().startsWith("gemini-")) {
        setModel("gpt-4o-mini");
      }
    }
  }

  function applyPreset(preset: LlmPreset) {
    const nextProvider: LlmProvider =
      preset.provider === "gemini" ? "gemini" : "openai_compatible";
    setProvider(nextProvider);
    setBaseUrl(preset.base_url);
    setModel(preset.model);
    setIsLocal(preset.id === "ollama");
    if (nextProvider === "gemini") setEnableMultimodal(true);
    setFeedback(null);
  }

  function buildPayload() {
    const payload: Record<string, unknown> = {
      provider,
      base_url: baseUrl.trim(),
      model: model.trim(),
      max_steps: Number(maxSteps) || 8,
      temperature: Number(temperature),
      enable_multimodal: enableMultimodal,
    };
    if (apiKey.trim()) payload.api_key = apiKey.trim();
    return payload;
  }

  async function handleTest() {
    setTesting(true);
    setFeedback(null);
    try {
      const res = await api.post<LlmTestResult>(
        "/agent/config/test",
        buildPayload(),
      );
      if (res.ok) {
        const capHint = res.supports_video ? " · 原生图/视频多模态" : "";
        setFeedback({
          kind: "ok",
          text: `连接成功（${res.model}${capHint} · ${res.latency_ms}ms）${res.reply_preview ? `：${res.reply_preview}` : ""}`,
        });
      } else {
        setFeedback({
          kind: "err",
          text: `连接失败：${res.error || "未知错误"}`,
        });
      }
    } catch (e) {
      setFeedback({ kind: "err", text: `测试请求失败：${errorMessage(e)}` });
    } finally {
      setTesting(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isGemini && !baseUrl.trim()) {
      setFeedback({ kind: "err", text: "请填写 API Base URL" });
      return;
    }
    if (!model.trim()) {
      setFeedback({ kind: "err", text: "请填写模型名称" });
      return;
    }
    setSaving(true);
    setFeedback(null);
    try {
      const saved = await api.post<LlmConfig>("/agent/config", buildPayload());
      setKeyPreview(saved.api_key_preview || "");
      setKeySource(saved.api_key_source || "none");
      setIsLocal(Boolean(saved.is_local));
      setApiKey("");
      setFeedback({
        kind: "ok",
        text: "模型配置已保存到本地 credentials/llm.json",
      });
      onSaved?.(saved);
    } catch (e) {
      setFeedback({ kind: "err", text: errorMessage(e) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title="AI 模型与多模态配置" width={580} onClose={onClose}>
      {loading ? (
        <div className="page-loading" style={{ padding: "36px 0" }}>
          <span className="spinner spinner-sm" />
          正在加载模型配置…
        </div>
      ) : (
        <form className={cx("form")} onSubmit={handleSubmit}>
          <fieldset className={cx("provider-fieldset")}>
            <legend>模型接入方式</legend>
            <label
              className={cx("provider-opt", { active: isGemini })}
            >
              <input
                type="radio"
                name="provider"
                value="gemini"
                checked={isGemini}
                onChange={() => handleProviderChange("gemini")}
              />
              <div>
                <div className={cx("provider-title")}>Gemini 原生多模态</div>
                <div className={cx("provider-sub")}>
                  原生支持跨平台图片与短视频（画面 + 语音）侧写
                </div>
              </div>
            </label>
            <label
              className={cx("provider-opt", { active: !isGemini })}
            >
              <input
                type="radio"
                name="provider"
                value="openai_compatible"
                checked={!isGemini}
                onChange={() => handleProviderChange("openai_compatible")}
              />
              <div>
                <div className={cx("provider-title")}>OpenAI 兼容接口</div>
                <div className={cx("provider-sub")}>
                  DeepSeek / OpenAI / 通义千问 / Ollama 等（视觉模型支持看图）
                </div>
              </div>
            </label>
          </fieldset>

          {presets.length > 0 ? (
            <div>
              <div className={cx("hint")} style={{ marginBottom: 6 }}>
                快捷填充常见提供商：
              </div>
              <div className={cx("presets")}>
                {presets.map((p) => {
                  const presetProvider: LlmProvider =
                    p.provider === "gemini" ? "gemini" : "openai_compatible";
                  const active =
                    provider === presetProvider &&
                    model.trim() === p.model &&
                    baseUrl.trim() === p.base_url;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      className={cx("preset-btn", { active })}
                      onClick={() => applyPreset(p)}
                    >
                      {p.name}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          <div className={cx("field")}>
            <label htmlFor={`${idPrefix}-base-url`}>
              {isGemini ? "自定义中转 Base URL（可选）" : "API Base URL"}
              {!isGemini ? (
                <span className={cx("required")} aria-hidden="true">*</span>
              ) : null}
            </label>
            <input
              id={`${idPrefix}-base-url`}
              name="base_url"
              type="url"
              className="input"
              required={!isGemini}
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              value={baseUrl}
              onChange={(e) => {
                setBaseUrl(e.currentTarget.value);
                setFeedback(null);
              }}
              placeholder={
                isGemini
                  ? "留空直连 Google Gemini 官方接口"
                  : "https://api.deepseek.com/v1"
              }
            />
            <span className={cx("hint")}>
              {isGemini
                ? "使用 Google AI Studio 官方接口请留空；如使用自建反向代理可填写完整 https:// 地址。"
                : "支持任何 OpenAI Chat Completions 兼容接口（DeepSeek / 通义千问 / OpenRouter / 本地 Ollama）。"}
            </span>
          </div>

          <div className={cx("field")}>
            <label htmlFor={`${idPrefix}-api-key`}>
              {isGemini ? "Gemini API Key" : "API Key"}
            </label>
            <div className={cx("password-row")}>
              <input
                id={`${idPrefix}-api-key`}
                name="api_key"
                type={showKey ? "text" : "password"}
                className="input"
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="none"
                spellCheck={false}
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.currentTarget.value);
                  setFeedback(null);
                }}
                placeholder={
                  keyPreview
                    ? `已配置 (${keyPreview})，留空则沿用原密钥`
                    : isGemini
                      ? "输入 AIza...（Google AI Studio Key）"
                      : isLocal
                        ? "本地 Ollama 可留空"
                        : "输入 sk-..."
                }
              />
              <button
                type="button"
                className="btn btn-icon"
                aria-pressed={showKey}
                title={showKey ? "隐藏 API Key" : "显示 API Key"}
                onClick={() => setShowKey((v) => !v)}
              >
                <Icon name={showKey ? "eyeOff" : "eye"} size={14} />
              </button>
            </div>
            <span className={cx("hint")}>
              {keySource === "file"
                ? `当前已保存本地密钥（${keyPreview}），仅存于 credentials/llm.json，不会被 Git 提交。`
                : keySource === "env"
                  ? `当前使用环境变量密钥（${keyPreview}），在此填写可覆盖。`
                  : isGemini
                    ? "亦支持通过环境变量 GEMINI_API_KEY 自动读取；密钥仅存于本机。"
                    : "密钥仅保存于本机 credentials/llm.json（已被 .gitignore 忽略）。"}
            </span>
          </div>

          <div className={cx("field")}>
            <label htmlFor={`${idPrefix}-model`}>
              模型名称 (Model)<span className={cx("required")} aria-hidden="true">*</span>
            </label>
            <input
              id={`${idPrefix}-model`}
              name="model"
              type="text"
              className="input"
              required
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              value={model}
              onChange={(e) => {
                setModel(e.currentTarget.value);
                setFeedback(null);
              }}
              placeholder={
                isGemini
                  ? "gemini-2.5-flash / gemini-2.5-pro"
                  : "deepseek-chat / qwen-plus / gpt-4o-mini"
              }
            />
          </div>

          <label className={cx("mm-toggle")}>
            <input
              type="checkbox"
              checked={enableMultimodal}
              onChange={(e) => setEnableMultimodal(e.currentTarget.checked)}
            />
            <div>
              <div className={cx("mm-title")}>
                启用多模态视觉与视频分析
              </div>
              <div className={cx("hint")}>
                {isGemini
                  ? "自动分析跨平台头像/背景视觉基线，并允许 Agent 按需查看图文与抖音/小红书/B站/微博短视频（本机防盗链缓存）。"
                  : "允许 Agent 查看头像与配图（需当前 OpenAI 兼容模型支持 Vision，纯文本模型失败时自动降级；视频理解请切换 Gemini 原生）。"}
              </div>
            </div>
          </label>

          <div className={cx("row-2")}>
            <div className={cx("field")}>
              <label htmlFor={`${idPrefix}-steps`}>最大侦查步数 (2~20)</label>
              <input
                id={`${idPrefix}-steps`}
                name="max_steps"
                type="text"
                inputMode="numeric"
                className="input"
                value={maxSteps}
                onChange={(e) => setMaxSteps(e.currentTarget.value)}
              />
            </div>
            <div className={cx("field")}>
              <label htmlFor={`${idPrefix}-temp`}>温度 Temperature (0~2)</label>
              <input
                id={`${idPrefix}-temp`}
                name="temperature"
                type="text"
                inputMode="decimal"
                className="input"
                value={temperature}
                onChange={(e) => setTemperature(e.currentTarget.value)}
              />
            </div>
          </div>

          {feedback ? (
            <div
              role="status"
              aria-live="polite"
              className={cx(
                "status-box",
                feedback.kind === "ok" ? "status-ok" : "status-err",
              )}
            >
              {feedback.text}
            </div>
          ) : null}

          <div className={cx("actions")}>
            <button
              type="button"
              className="btn"
              disabled={testing || saving}
              onClick={() => void handleTest()}
            >
              {testing ? <span className="spinner spinner-sm" /> : null}
              测试连接
            </button>
            <div className={cx("spacer")} />
            <button type="button" className="btn" onClick={onClose}>
              关闭
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving || testing}
            >
              {saving ? "保存中…" : "保存配置"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
