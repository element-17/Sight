import { expect, test } from "@playwright/test";
import { installMockApi } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
});

test("AI profiling workspace: LLM config, bound-account profiling, evidence jump, follow-up chat, and interrupt resume", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/#/agent");
  await expect(page.getByText("AI 人物侧写工作台（LangGraph）")).toBeVisible();

  // 1. 打开模型配置弹窗，切换 Anthropic 协议拉取模型列表，再切换 Gemini 原生多模态预设并测试/保存
  await page.getByRole("button", { name: /模型：deepseek-chat/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel(/Anthropic 协议/).check();
  await dialog.getByRole("button", { name: "获取模型列表", exact: true }).click();
  await expect(dialog.getByText(/已获取 2 个可用模型（35ms）/)).toBeVisible();
  await dialog.getByRole("button", { name: /claude-haiku-4-5/ }).click();
  await expect(dialog.getByLabel(/模型名称/)).toHaveValue("claude-haiku-4-5");

  await dialog
    .getByRole("button", { name: "Gemini 2.5 Flash (原生多模态·推荐)", exact: true })
    .click();
  await dialog.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect(
    dialog.getByText(/连接成功（gemini-2\.5-flash · 原生图\/视频多模态 · 42ms）/),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(dialog.getByText(/模型配置已保存到本地/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /模型：gemini-2\.5-flash · 原生多模态/ }),
  ).toBeVisible();

  // 2. 基于当前面板 UIDs 生成侧写
  await page.getByRole("button", { name: "导入当前面板 UIDs", exact: true }).click();
  await page.getByRole("button", { name: "开始生成侧写" }).click();

  await expect(page.getByText("常驻杭州的开源开发者", { exact: true })).toBeVisible();
  await expect(page.getByText("深夜活跃型（夜猫子）", { exact: true })).toBeVisible();
  await expect(page.getByText("核心互关好友 · GitHub", { exact: true })).toBeVisible();

  // 3. 点击报告中的 [E1] 证据角标，右侧自动切换至证据账本并展示多模态缩略图
  await page.locator("article, section").getByRole("button", { name: "E1", exact: true }).first().click();
  await expect(page.getByText("GitHub 主页资料", { exact: true })).toBeVisible();
  await expect(page.getByText("跨平台头像与背景视觉基线（1 张）", { exact: true })).toBeVisible();
  await expect(page.locator('img[src="/api/agent/media/0123456789abcdef01234567"]')).toBeVisible();

  // 4. 多轮追问对话
  await page.getByRole("tab", { name: /多轮追问/ }).click();
  const chatInput = page.getByLabel("追问内容");
  await chatInput.fill("他平时什么时候最活跃？");
  await chatInput.press("Enter");
  await expect(page.getByText(/该目标常在深夜活跃/)).toBeVisible();

  // 5. 关键词搜人 -> LangGraph interrupt 人工确认断点 -> 恢复生成
  await page.getByRole("button", { name: "新建侧写", exact: true }).click();
  await page.getByLabel(/输入关键词跨平台搜人/).check();
  await page.getByLabel("搜索关键词 / 网名").fill("神秘开发者");
  await page.getByRole("button", { name: "开始生成侧写" }).click();

  await expect(
    page.getByText("请确认跨平台候选账号（LangGraph 断点暂停）"),
  ).toBeVisible();
  await page.getByRole("button", { name: /确认所选账号并继续侧写/ }).click();
  await expect(
    page.getByRole("main").getByText("确认后 · 人物侧写", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "确认后 · 人物侧写", exact: true }),
  ).toBeVisible();

  // 6. 失败后保留基线进度并支持 LangGraph「从断点继续」
  await page.getByRole("button", { name: "新建侧写", exact: true }).click();
  await page.getByLabel(/基于已绑定/).check();
  await page.getByRole("button", { name: "导入当前面板 UIDs", exact: true }).click();
  await page.getByLabel("调查关注重点（可选）").fill("simulate-failed-checkpoint");
  await page.getByRole("button", { name: "开始生成侧写" }).click();

  await expect(page.getByText(/UNEXPECTED_EOF_WHILE_READING/)).toBeVisible();
  await expect(page.getByRole("button", { name: "从断点继续", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "从断点继续", exact: true }).click();
  await expect(page.getByText("常驻杭州的开源开发者", { exact: true })).toBeVisible();

  expect(errors).toEqual([]);
});
