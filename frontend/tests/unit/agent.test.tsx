import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MarkdownReport from "../../src/components/agent/MarkdownReport";
import LlmConfigModal from "../../src/components/LlmConfigModal";

const ok = (data: unknown) => new Response(JSON.stringify({ code: 200, data }));

describe("AI Agent frontend components", () => {
  it("renders Markdown report safely with clickable evidence citations and strips unsafe links", () => {
    const onSelect = vi.fn();
    render(
      <MarkdownReport
        markdown={
          "# 人物画像\n\n常驻上海 [高置信][E1, E2]，外链 [安全链接](https://example.com) 与 [恶意链接](javascript:alert(1))。"
        }
        evidence={{
          E1: {
            id: "E1",
            platform: "github",
            category: "profile",
            title: "GitHub 资料",
            snippet: "Shanghai",
          },
        }}
        onSelectEvidence={onSelect}
      />,
    );

    expect(screen.getByRole("heading", { name: "人物画像" })).toBeInTheDocument();
    expect(screen.getByText("高置信")).toBeInTheDocument();
    const safeLink = screen.getByRole("link", { name: "安全链接" });
    expect(safeLink).toHaveAttribute("href", "https://example.com");
    expect(screen.queryByRole("link", { name: "恶意链接" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "E1" }));
    expect(onSelect).toHaveBeenCalledWith("E1");
  });

  it("loads, switches to Gemini native, tests, and saves LLM configuration in LlmConfigModal", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/agent/config") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(
          ok({
            provider: "openai_compatible",
            base_url: "https://api.openai.com/v1",
            model: "gpt-4o-mini",
            temperature: 0.2,
            max_steps: 8,
            timeout: 90,
            enable_multimodal: true,
            supports_vision: true,
            supports_video: false,
            has_api_key: false,
            api_key_preview: "",
            api_key_source: "none",
            is_local: false,
            configured: false,
            presets: [
              {
                id: "gemini_flash",
                name: "Gemini 2.5 Flash (原生多模态·推荐)",
                provider: "gemini",
                base_url: "",
                model: "gemini-2.5-flash",
              },
              {
                id: "deepseek",
                name: "DeepSeek",
                provider: "openai_compatible",
                base_url: "https://api.deepseek.com/v1",
                model: "deepseek-chat",
              },
            ],
          }),
        );
      }
      if (url.endsWith("/agent/config/test")) {
        return Promise.resolve(
          ok({
            ok: true,
            provider: "gemini",
            model: "gemini-2.5-flash",
            base_url: "",
            supports_video: true,
            latency_ms: 55,
            reply_preview: "OK",
          }),
        );
      }
      return Promise.resolve(
        ok({
          provider: "gemini",
          base_url: "",
          model: "gemini-2.5-flash",
          temperature: 0.2,
          max_steps: 8,
          timeout: 90,
          enable_multimodal: true,
          supports_vision: true,
          supports_video: true,
          has_api_key: true,
          api_key_preview: "AIza...9999",
          api_key_source: "file",
          is_local: false,
          configured: true,
          presets: [],
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const onSaved = vi.fn();
    render(<LlmConfigModal open onClose={() => {}} onSaved={onSaved} />);

    const presetBtn = await screen.findByRole("button", {
      name: "Gemini 2.5 Flash (原生多模态·推荐)",
    });
    fireEvent.click(presetBtn);
    fireEvent.change(screen.getByLabelText("Gemini API Key"), {
      target: { value: "AIza-test-9999" },
    });

    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await screen.findByText(/连接成功（gemini-2\.5-flash · 原生图\/视频多模态 · 55ms）/);

    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const saveCall = fetchMock.mock.calls.find(
      ([u, init]) => u.endsWith("/agent/config") && init?.method === "POST",
    );
    expect(saveCall).toBeTruthy();
    const sentBody = JSON.parse(String(saveCall?.[1]?.body || "{}"));
    expect(sentBody.provider).toBe("gemini");
    expect(sentBody.base_url).toBe("");
    expect(sentBody.enable_multimodal).toBe(true);
  });
});
