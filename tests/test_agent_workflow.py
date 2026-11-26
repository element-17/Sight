"""
LangGraph AI 侧写智能体单元测试与端到端工作流测试。

覆盖：
1. LLM 配置读写、脱敏掩码、环境变量兜底、本地 Ollama 端点识别与连通性测试。
2. 确定性特征分析器（24h 作息分布、夜猫子分类、社交图谱互关与大V过滤、引用编号提取）。
3. LangGraph StateGraph 全链路（带真实 SqliteSaver）：
   - 已有 UIDs 模式：基线采集 → 侦查员 Tool Calling (B站存档) → 侧写报告合成 → 幻觉引用剔除 → 同 thread_id 多轮追问；
   - 关键词搜人模式：discover_identities → LangGraph 原生 interrupt() 挂起 → Command(resume=...) 恢复完成侧写。
4. REST / SSE 路由契约（/api/agent/config*, /api/agent/sessions*）。
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from langchain_core.messages import AIMessage

from app.agent.analyzers import (
    analyze_social_network,
    compute_activity_stats,
    extract_citation_ids,
)
from app.agent.llm_config import (
    get_public_config,
    load_effective_config,
    save_llm_config,
    test_llm_connection,
)
from app.agent.runner import AgentRunManager
from app.data.store import DataStore
from app.platforms.base import ContentItem, EventItem, PlatformProfile


class _ScriptedFakeLLM:
    """支持 bind_tools() 的可控模拟 LLM，按预置响应序列返回 AIMessage。"""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self.calls: list[list] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return AIMessage(content="默认回复")


class LLMConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env_patch = patch.dict(
            os.environ,
            {
                "SIGHT_DATA_DIR": self.tmpdir.name,
                "SIGHT_LLM_PROVIDER": "",
                "SIGHT_LLM_API_KEY": "",
                "SIGHT_LLM_BASE_URL": "",
                "SIGHT_LLM_MODEL": "",
                "SIGHT_LLM_MULTIMODAL": "",
                "OPENAI_API_KEY": "",
                "OPENAI_BASE_URL": "",
                "OPENAI_MODEL": "",
                "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "",
                "ANTHROPIC_API_KEY": "",
                "ANTHROPIC_BASE_URL": "",
                "ANTHROPIC_MODEL": "",
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_save_mask_preserve_key_and_local_ollama(self):
        pub0 = get_public_config()
        self.assertFalse(pub0["configured"])
        self.assertFalse(pub0["has_api_key"])

        saved = save_llm_config(
            {
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-1234567890abcdef",
                "model": "deepseek-chat",
                "max_steps": 6,
            }
        )
        self.assertTrue(saved["configured"])
        self.assertTrue(saved["has_api_key"])
        self.assertEqual(saved["api_key_preview"], "sk-1...cdef")
        self.assertNotIn("api_key", saved)

        # 不传 api_key 更新模型时保留旧密钥
        updated = save_llm_config(
            {
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-reasoner",
            }
        )
        self.assertEqual(updated["model"], "deepseek-reasoner")
        self.assertTrue(updated["has_api_key"])
        self.assertEqual(load_effective_config()["api_key"], "sk-1234567890abcdef")

        # 本地 Ollama 无需 API Key 即视为可用
        ollama_cfg = save_llm_config(
            {
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen2.5:14b",
                "clear_api_key": True,
            }
        )
        self.assertTrue(ollama_cfg["is_local"])
        self.assertTrue(ollama_cfg["configured"])
        self.assertFalse(ollama_cfg["has_api_key"])

    def test_connection_probe_reports_ok(self):
        fake = _ScriptedFakeLLM([AIMessage(content="OK")])
        with patch("app.agent.llm_config.build_chat_model", return_value=fake):
            res = test_llm_connection(
                {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-test-key",
                    "model": "gpt-4o-mini",
                }
            )
        self.assertTrue(res["ok"])
        self.assertEqual(res["reply_preview"], "OK")

    def test_gemini_native_provider_config_and_env_fallback(self):
        from langchain_google_genai import ChatGoogleGenerativeAI
        from app.agent.llm_config import build_chat_model

        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaEnvTestKey9876"}, clear=False):
            cfg = load_effective_config()
            self.assertEqual(cfg["provider"], "gemini")
            self.assertEqual(cfg["model"], "gemini-2.5-flash")
            self.assertTrue(cfg["configured"])
            self.assertTrue(cfg["supports_video"])

        # 保存 Gemini 原生配置允许 base_url 留空
        saved = save_llm_config(
            {
                "provider": "gemini",
                "base_url": "",
                "api_key": "AIzaSavedKey12345678",
                "model": "gemini-2.5-pro",
                "enable_multimodal": True,
            }
        )
        self.assertEqual(saved["provider"], "gemini")
        self.assertEqual(saved["base_url"], "")
        self.assertTrue(saved["configured"])
        self.assertTrue(saved["supports_video"])
        self.assertEqual(saved["api_key_preview"], "AIza...5678")

        model = build_chat_model()
        self.assertIsInstance(model, ChatGoogleGenerativeAI)

        with self.assertRaises(ValueError):
            save_llm_config({"provider": "gemini", "base_url": "not-a-url", "model": "gemini-2.5-flash"})

    def test_anthropic_provider_config_normalization_and_model_listing(self):
        from types import SimpleNamespace
        from langchain_anthropic import ChatAnthropic
        from app.agent.llm_config import build_chat_model, fetch_available_models

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-env-12345"}, clear=False):
            cfg = load_effective_config()
            self.assertEqual(cfg["provider"], "anthropic")
            self.assertEqual(cfg["model"], "claude-sonnet-4-5")
            self.assertTrue(cfg["configured"])
            self.assertTrue(cfg["supports_vision"])
            self.assertFalse(cfg["supports_video"])

        # 中转站误带 /v1/messages 或 /v1 时自动规范化为根地址
        saved = save_llm_config(
            {
                "provider": "anthropic",
                "base_url": "https://relay.example.com/v1/messages",
                "api_key": "sk-ant-saved-998877",
                "model": "claude-sonnet-4-5",
            }
        )
        self.assertEqual(saved["provider"], "anthropic")
        self.assertEqual(saved["base_url"], "https://relay.example.com")
        self.assertEqual(saved["api_key_preview"], "sk-a...8877")

        llm = build_chat_model()
        self.assertIsInstance(llm, ChatAnthropic)
        self.assertEqual(str(llm.anthropic_api_url).rstrip("/"), "https://relay.example.com")

        # 1) Anthropic 模型列表拉取（验证归一化后的 /v1/models 路径与请求头）
        seen_ant: dict = {}

        def _fake_ant_get(url, headers=None, params=None, timeout=None):
            seen_ant["url"] = url
            seen_ant["headers"] = dict(headers or {})
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "data": [
                        {"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"},
                        {"id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5"},
                    ]
                },
            )

        with patch("app.agent.llm_config.requests.get", side_effect=_fake_ant_get):
            ant_res = fetch_available_models(
                {
                    "provider": "anthropic",
                    "base_url": "https://relay.example.com/v1",
                    "api_key": "sk-ant-draft-123",
                }
            )
        self.assertTrue(ant_res["ok"])
        self.assertEqual(seen_ant["url"], "https://relay.example.com/v1/models")
        self.assertEqual(seen_ant["headers"]["x-api-key"], "sk-ant-draft-123")
        self.assertEqual(seen_ant["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual([m["id"] for m in ant_res["models"]], ["claude-haiku-4-5", "claude-sonnet-4-5"])

        # 2) OpenAI 兼容模型列表拉取
        seen_oai: dict = {}

        def _fake_oai_get(url, headers=None, timeout=None):
            seen_oai["url"] = url
            seen_oai["headers"] = dict(headers or {})
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "data": [
                        {"id": "deepseek-reasoner", "owned_by": "deepseek"},
                        {"id": "deepseek-chat", "owned_by": "deepseek"},
                    ]
                },
            )

        with patch("app.agent.llm_config.requests.get", side_effect=_fake_oai_get):
            oai_res = fetch_available_models(
                {
                    "provider": "openai_compatible",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-ds-123",
                }
            )
        self.assertTrue(oai_res["ok"])
        self.assertEqual(seen_oai["url"], "https://api.deepseek.com/v1/models")
        self.assertEqual(seen_oai["headers"]["Authorization"], "Bearer sk-ds-123")
        self.assertEqual([m["id"] for m in oai_res["models"]], ["deepseek-chat", "deepseek-reasoner"])

        # 3) Gemini 原生模型列表拉取（自动剥离 models/ 前缀并过滤非 generateContent 模型）
        fake_gem_client = SimpleNamespace(
            models=SimpleNamespace(
                list=lambda: [
                    SimpleNamespace(
                        name="models/gemini-2.5-flash",
                        display_name="Gemini 2.5 Flash",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/text-embedding-004",
                        display_name="Embedding",
                        supported_actions=["embedContent"],
                    ),
                ]
            )
        )
        with patch("app.agent.llm_config.build_gemini_client", return_value=fake_gem_client):
            gem_res = fetch_available_models({"provider": "gemini", "api_key": "AIzaFake123"})
        self.assertTrue(gem_res["ok"])
        self.assertEqual([m["id"] for m in gem_res["models"]], ["gemini-2.5-flash"])


class AnalyzerTests(unittest.TestCase):
    def test_activity_stats_and_social_filtering(self):
        # 构造 4 条深夜时间（CST 01:00 ~ 02:30）
        # 2026-10-19 01:30:00+08:00 -> unix = 1792344600
        ts_0130 = 1792344600 * 1000
        payloads = {
            "github": {
                "uid": "dev1",
                "profile": {"nickname": "dev1", "location": "Shanghai", "signature": "Rust & Python"},
                "playlists": [
                    {"title": "sight", "create_time": "2026-10-19T02:10:00+08:00", "extra": {"language": "Python"}},
                    {"title": "fast-rs", "create_time": "2026-10-20T01:40:00+08:00", "extra": {"language": "Rust"}},
                ],
                "events": [
                    {"event_type": "PushEvent", "content": "commit 1", "timestamp": ts_0130},
                    {"event_type": "PushEvent", "content": "commit 2", "timestamp": ts_0130 + 1800 * 1000},
                ],
                "records": {},
                "follows": [
                    {"uid": "friend1", "nickname": "老同学", "fans": 120, "is_verified": False},
                    {"uid": "bigv", "nickname": "官方大V", "fans": 500000, "is_verified": True},
                ],
                "followers": [
                    {"uid": "friend1", "nickname": "老同学", "fans": 120, "is_verified": False},
                ],
            }
        }
        act = compute_activity_stats(payloads)
        self.assertEqual(act["total_timed_events"], 4)
        self.assertEqual(act["chronotype"], "深夜活跃型（夜猫子）")
        self.assertGreaterEqual(act["late_night_ratio"], 0.9)
        self.assertEqual(act["top_languages"][0]["name"], "Python")

        social = analyze_social_network(
            platform_payloads=payloads,
            target_accounts={"github": "dev1"},
        )
        mutual_uids = [c["uid"] for c in social["mutual_core_contacts"]]
        celeb_uids = [c["uid"] for c in social["followed_public_accounts"]]
        self.assertIn("friend1", mutual_uids)
        self.assertNotIn("bigv", mutual_uids)
        self.assertIn("bigv", celeb_uids)

        self.assertEqual(extract_citation_ids("依据 [E1] 和 [E2, E5] 以及 [E1]"), ["E1", "E2", "E5"])


class LangGraphWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.store = DataStore(db_path=Path(self.tmpdir.name) / "sight.db")
        self.ckpt_path = Path(self.tmpdir.name) / "checkpoints.db"

    def _wait_idle(self, runner: AgentRunManager, session_id: str, timeout: float = 8.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            detail = runner.get_session_detail(session_id)
            if detail and not detail.get("running") and detail.get("status") != "running":
                return detail
            time.sleep(0.05)
        self.fail("Agent run timed out")

    def test_bound_uids_tool_calling_citation_verify_and_followup(self):
        # 预热一条 GitHub 与 B 站快照，避免任何真实外网请求
        self.store.save_snapshot(
            "github",
            "octocat",
            "profile",
            {
                "platform": "github",
                "uid": "octocat",
                "nickname": "Octo Dev",
                "location": "Hangzhou",
                "signature": "Building AI agents",
            },
        )
        self.store.save_snapshot(
            "github",
            "octocat",
            "playlists",
            {
                "count": 1,
                "items": [
                    {
                        "item_id": "octocat__sight",
                        "title": "sight",
                        "is_owner": True,
                        "create_time": "2026-10-19T23:30:00+08:00",
                        "extra": {"language": "Python"},
                    }
                ],
            },
        )
        self.store.save_snapshot(
            "bilibili",
            "12345",
            "profile",
            {
                "platform": "bilibili",
                "uid": "12345",
                "nickname": "Octo_B",
                "signature": "代码与动漫",
            },
        )

        report_with_meta = (
            "# 人物形象侧写：Octo Dev\n\n"
            "## 一、核心概览\n"
            "一位常驻杭州的开源开发者 [高置信][E1]，在 B 站有活跃评论互动 [高置信][E4]，"
            "不存在的引用测试 [E999]。\n\n"
            "```json:profile_meta\n"
            '{"headline":"常驻杭州的 Python/AI 开源开发者","tags":["Python","AI","开源"],'
            '"confidence_overall":"high","dimensions":[{"key":"identity","title":"身份线索",'
            '"summary":"GitHub 标注位于杭州","confidence":"high","evidence_ids":["E1","E999"]}],'
            '"blind_spots":["小红书未绑定"]}\n'
            "```"
        )

        fake_llm = _ScriptedFakeLLM(
            [
                # Step 1 (investigator): 主动调用 B 站评论存档工具深挖
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_bilibili_archives",
                            "args": {"uid": "12345", "source": "aicu_reply", "page": 1},
                            "id": "call_bili_1",
                        }
                    ],
                ),
                # Step 2 (investigator): 信息充足，结束侦查
                AIMessage(content="已获取 B 站评论存档，证据充足。"),
                # Step 3 (synthesize_profile): 生成带引用与 profile_meta 的侧写报告
                AIMessage(content=report_with_meta),
                # Step 4 (followup_agent): 回答用户多轮追问
                AIMessage(content="根据 [E1] 与 B 站存档证据，目标偏夜间活跃且关注技术社区。"),
            ]
        )

        runner = AgentRunManager(
            store=self.store,
            checkpoint_db_path=self.ckpt_path,
            llm_factory=lambda: fake_llm,
        )
        self.addCleanup(runner.close)

        fake_archive = {
            "source_name": "Aicu · 评论",
            "source_url": "https://www.aicu.cc/reply?uid=12345",
            "total": 12,
            "has_more": False,
            "notice": "test",
            "events": [
                {
                    "event_type": "评论",
                    "content": "这个 LangGraph 教程讲得很清楚",
                    "timestamp": 1792344600000,
                    "url": "https://www.bilibili.com/video/av123",
                }
            ],
        }

        with patch("app.agent.tools.bilibili_archives_svc.fetch", return_value=fake_archive), patch(
            "app.services.platform_fetcher.get_adapter"
        ) as mock_get_adapter:
            # 快照未命中的模块返回空列表即可
            adapter = mock_get_adapter.return_value
            adapter.get_content_lists.return_value = []
            adapter.get_events.return_value = []
            adapter.get_follows.return_value = ([], False, 0)
            adapter.get_followers.return_value = ([], False, 0)
            adapter.get_history.return_value = []

            session = runner.create_session(
                title="Octo 测试侧写",
                uids={"github": "octocat", "bilibili": "12345"},
                focus="关注技术栈与发言风格",
            )
            detail = self._wait_idle(runner, session["id"])

        self.assertEqual(detail["status"], "done")
        self.assertIn("Octo Dev", detail["report_markdown"])
        # 幻觉编号 [E999] 已被确定性校验节点剔除
        self.assertNotIn("[E999]", detail["report_markdown"])
        self.assertNotIn("```json:profile_meta", detail["report_markdown"])

        citation = detail["structured"]["citation_report"]
        self.assertIn("E1", citation["cited_valid"])
        self.assertIn("E999", citation["removed_invalid"])

        meta = detail["structured"]["profile_meta"]
        self.assertEqual(meta["tags"], ["Python", "AI", "开源"])
        self.assertEqual(meta["dimensions"][0]["evidence_ids"], ["E1"])
        # 证据账本包含基线证据 + 工具补充的 B 站存档证据
        self.assertTrue(any(ev["category"] == "archive:aicu_reply" for ev in detail["evidence"].values()))

        # 同 thread_id 多轮追问
        runner.send_followup(session["id"], "他平时主要关注什么方向？")
        after_chat = self._wait_idle(runner, session["id"])
        self.assertEqual(after_chat["status"], "done")
        self.assertEqual(len(after_chat["chat_history"]), 2)
        self.assertEqual(after_chat["chat_history"][0]["role"], "user")
        self.assertIn("夜间活跃", after_chat["chat_history"][1]["content"])

    def test_discover_interrupt_and_command_resume(self):
        fake_search_result = {
            "keyword": "神秘开发者",
            "keywords": {},
            "searched": ["github", "bilibili"],
            "platforms": ["github", "bilibili"],
            "nodes": [
                {"id": "keyword", "platform": "keyword", "uid": "", "nickname": "神秘开发者"},
                {
                    "id": "github:mystery_dev",
                    "platform": "github",
                    "uid": "mystery_dev",
                    "nickname": "神秘开发者",
                    "signature": "Open Source",
                    "fans": 42,
                },
                {
                    "id": "bilibili:998877",
                    "platform": "bilibili",
                    "uid": "998877",
                    "nickname": "神秘开发者_B",
                    "signature": "技术UP",
                    "fans": 1200,
                },
            ],
            "edges": [
                {"source": "keyword", "target": "github:mystery_dev", "relation": "hit"},
                {"source": "keyword", "target": "bilibili:998877", "relation": "hit"},
                {"source": "github:mystery_dev", "target": "bilibili:998877", "relation": "alike"},
            ],
            "errors": {},
            "cached": [],
        }

        self.store.save_snapshot(
            "github",
            "mystery_dev",
            "profile",
            {"platform": "github", "uid": "mystery_dev", "nickname": "神秘开发者", "signature": "Open Source"},
        )

        fake_llm = _ScriptedFakeLLM(
            [
                AIMessage(content="证据已够，直接合成报告。"),
                AIMessage(
                    content=(
                        "# 人物形象侧写：神秘开发者\n\n"
                        "确认为开源社区活跃者 [高置信][E1]。\n\n"
                        '```json:profile_meta\n{"headline":"开源社区开发者","tags":["开源"],'
                        '"confidence_overall":"medium","dimensions":[],"blind_spots":[]}\n```'
                    )
                ),
            ]
        )

        runner = AgentRunManager(
            store=self.store,
            checkpoint_db_path=self.ckpt_path,
            llm_factory=lambda: fake_llm,
        )
        self.addCleanup(runner.close)

        with patch("app.agent.graph.search_cross_platform", return_value=fake_search_result), patch(
            "app.services.platform_fetcher.get_adapter"
        ) as mock_get_adapter:
            adapter = mock_get_adapter.return_value
            adapter.get_content_lists.return_value = []
            adapter.get_events.return_value = []
            adapter.get_follows.return_value = ([], False, 0)
            adapter.get_followers.return_value = ([], False, 0)
            adapter.get_history.return_value = []

            session = runner.create_session(target_query="神秘开发者", auto_confirm=False)
            paused = self._wait_idle(runner, session["id"])

            self.assertEqual(paused["status"], "waiting_confirm")
            pending = paused["structured"].get("pending_interrupt")
            self.assertIsNotNone(pending)
            self.assertEqual(pending["type"], "confirm_identities")
            self.assertEqual(len(pending["candidates"]), 2)

            # 用户勾选确认 github:mystery_dev 后恢复执行
            runner.resume_session(session["id"], {"github": "mystery_dev"})
            done = self._wait_idle(runner, session["id"])

        self.assertEqual(done["status"], "done")
        self.assertEqual(done["uids"], {"github": "mystery_dev"})
        self.assertNotIn("pending_interrupt", done["structured"])
        self.assertIn("神秘开发者", done["report_markdown"])

    def test_llm_failure_unwraps_root_cause_and_preserves_baseline_checkpoint(self):
        self.store.save_snapshot(
            "github",
            "faildev",
            "profile",
            {"platform": "github", "uid": "faildev", "nickname": "FailDev", "location": "Beijing"},
        )

        class _SwitchableLLM:
            def __init__(self):
                self.should_fail = True
                self.ok_responses = [
                    AIMessage(content="断点续跑侦查完成，证据充足。"),
                    AIMessage(
                        content=(
                            "# 人物形象侧写：FailDev\n\n"
                            "常驻北京的开源开发者 [高置信][E1]。\n\n"
                            '```json:profile_meta\n{"headline":"断点续跑恢复的开发者画像","tags":["开源"],'
                            '"confidence_overall":"high","dimensions":[],"blind_spots":[]}\n```'
                        )
                    ),
                ]

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                if self.should_fail:
                    root = OSError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
                    outer = RuntimeError("Connection error.")
                    raise outer from root
                return self.ok_responses.pop(0)

        switch_llm = _SwitchableLLM()
        runner = AgentRunManager(
            store=self.store,
            checkpoint_db_path=self.ckpt_path,
            llm_factory=lambda: switch_llm,
        )
        self.addCleanup(runner.close)

        with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7897"}, clear=False), patch(
            "app.services.platform_fetcher.get_adapter"
        ) as mock_get_adapter:
            adapter = mock_get_adapter.return_value
            adapter.get_content_lists.return_value = []
            adapter.get_events.return_value = []
            adapter.get_follows.return_value = ([], False, 0)
            adapter.get_followers.return_value = ([], False, 0)
            adapter.get_history.return_value = []

            session = runner.create_session(title="失败保留基线测试", uids={"github": "faildev"})
            failed = self._wait_idle(runner, session["id"])
            baseline_fetch_calls = adapter.get_content_lists.call_count

        self.assertEqual(failed["status"], "failed")
        self.assertIn("UNEXPECTED_EOF_WHILE_READING", failed["error"])
        self.assertIn("127.0.0.1:7897", failed["error"])
        self.assertTrue(failed["can_resume"])
        self.assertEqual(failed["resume_nodes"], ["investigator"])
        # 基线阶段采集到的证据和轨迹被保留在失败档案中
        self.assertGreaterEqual(len(failed["evidence"]), 1)
        self.assertTrue(any(t.get("stage") == "collect_baseline" for t in failed["trace"]))
        self.assertTrue(any(t.get("stage") == "error" for t in failed["trace"]))

        # 网络/代理恢复后调用 continue_session (LangGraph stream(None, config)) 直接续跑，不再重复抓取基线
        switch_llm.should_fail = False
        with patch("app.services.platform_fetcher.get_adapter") as mock_get_adapter_2:
            runner.continue_session(session["id"])
            resumed_done = self._wait_idle(runner, session["id"])
            self.assertEqual(mock_get_adapter_2.call_count, 0)

        self.assertEqual(baseline_fetch_calls, 1)
        self.assertEqual(resumed_done["status"], "done")
        self.assertFalse(resumed_done["can_resume"])
        self.assertIn("FailDev", resumed_done["report_markdown"])
        self.assertEqual(
            resumed_done["structured"]["profile_meta"]["headline"],
            "断点续跑恢复的开发者画像",
        )


class AgentRestRoutesTests(unittest.TestCase):
    def setUp(self):
        from app.routes import api as api_module

        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env_patch = patch.dict(
            os.environ,
            {"SIGHT_DATA_DIR": self.tmpdir.name, "SIGHT_LLM_API_KEY": "", "OPENAI_API_KEY": ""},
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        self.store = DataStore(db_path=Path(self.tmpdir.name) / "sight.db")
        self.runner = AgentRunManager(
            store=self.store,
            checkpoint_db_path=Path(self.tmpdir.name) / "ckpt.db",
            llm_factory=lambda: _ScriptedFakeLLM(
                [
                    AIMessage(content="ok"),
                    AIMessage(content="# 报告\n内容 [E1]"),
                ]
            ),
        )
        self.addCleanup(self.runner.close)

        self.store_patch = patch.object(api_module, "_store", self.store)
        self.runner_patch = patch("app.routes.agent_routes.get_agent_runner", return_value=self.runner)
        self.store_patch.start()
        self.runner_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.addCleanup(self.runner_patch.stop)

        app = Flask(__name__)
        app.register_blueprint(api_module.bp)
        self.client = app.test_client()

    def test_config_and_session_crud_routes(self):
        res_cfg = self.client.get("/api/agent/config")
        self.assertEqual(res_cfg.status_code, 200)
        self.assertEqual(res_cfg.json["code"], 200)
        self.assertIn("presets", res_cfg.json["data"])

        res_bad = self.client.post("/api/agent/config", json={"base_url": "bad-url", "model": "m"})
        self.assertEqual(res_bad.status_code, 400)

        res_save = self.client.post(
            "/api/agent/config",
            json={"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:14b"},
        )
        self.assertEqual(res_save.status_code, 200)
        self.assertTrue(res_save.json["data"]["configured"])

        with patch(
            "app.routes.agent_routes.fetch_available_models",
            return_value={
                "ok": True,
                "provider": "anthropic",
                "count": 1,
                "models": [{"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5"}],
                "latency_ms": 25,
            },
        ):
            res_models = self.client.post(
                "/api/agent/config/models",
                json={"provider": "anthropic", "api_key": "sk-ant-test"},
            )
        self.assertEqual(res_models.status_code, 200)
        self.assertTrue(res_models.json["data"]["ok"])
        self.assertEqual(res_models.json["data"]["models"][0]["id"], "claude-sonnet-4-5")

        # 创建一个不自动启动的档案测试列表/详情/事件/删除
        res_create = self.client.post(
            "/api/agent/sessions",
            json={"title": "API测试档案", "uids": {"github": "torvalds"}, "auto_start": False},
        )
        self.assertEqual(res_create.status_code, 200)
        sid = res_create.json["data"]["id"]

        res_list = self.client.get("/api/agent/sessions")
        self.assertEqual(len(res_list.json["data"]), 1)
        self.assertEqual(res_list.json["data"][0]["id"], sid)

        res_detail = self.client.get(f"/api/agent/sessions/{sid}")
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.json["data"]["title"], "API测试档案")

        res_events = self.client.get(f"/api/agent/sessions/{sid}/events?after=0")
        self.assertEqual(res_events.status_code, 200)
        self.assertEqual(res_events.json["data"]["entries"], [])

        # 未启动过没有可续跑断点时 /continue 返回明确 400
        res_cont = self.client.post(f"/api/agent/sessions/{sid}/continue")
        self.assertEqual(res_cont.status_code, 400)

        res_del = self.client.delete(f"/api/agent/sessions/{sid}")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(self.client.get(f"/api/agent/sessions/{sid}").status_code, 404)

    def test_media_cache_route_security_and_serving(self):
        from app.services.media_fetcher import download_media

        class _FakeResp:
            status_code = 200
            headers = {"Content-Type": "image/png", "Content-Length": "16"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_content(self, chunk_size=65536):
                yield b"\x89PNG\r\n\x1a\n" + b"01234567"

        with patch("app.services.media_fetcher.requests.get", return_value=_FakeResp()):
            cached = download_media("https://i0.hdslb.com/bfs/face/demo.png", platform="bilibili")

        # 合法 24 位 hex media_id 返回图片字节
        with self.client.get(cached.preview_url) as res_ok:
            self.assertEqual(res_ok.status_code, 200)
            self.assertEqual(res_ok.mimetype, "image/png")
            self.assertTrue(res_ok.data.startswith(b"\x89PNG"))

        # 非法路径/穿越 ID 全部 404
        self.assertEqual(self.client.get("/api/agent/media/not-a-valid-hex").status_code, 404)
        self.assertEqual(self.client.get("/api/agent/media/000000000000000000000000").status_code, 404)


class MultimodalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env_patch = patch.dict(
            os.environ,
            {
                "SIGHT_DATA_DIR": self.tmpdir.name,
                "SIGHT_LLM_PROVIDER": "",
                "SIGHT_LLM_API_KEY": "",
                "OPENAI_API_KEY": "",
                "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "",
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.store = DataStore(db_path=Path(self.tmpdir.name) / "sight.db")

    def test_platform_adapters_extract_images_and_video_streams(self):
        from types import SimpleNamespace
        from app.platforms.bilibili.adapter import BilibiliAdapter
        from app.platforms.douyin.adapter import DouyinAdapter
        from app.platforms.weibo.adapter import WeiboAdapter
        from app.platforms.xhs.adapter import XhsAdapter

        # 1. Douyin: 视频按最低码率/体积优先排序 + 图文多图提取
        dy_vid = DouyinAdapter._extract_work_media(
            {
                "video": {
                    "bit_rate": [
                        {"bit_rate": 2000, "play_addr": {"data_size": 9000000, "url_list": ["https://dy.example/hd.mp4"]}},
                        {"bit_rate": 600, "play_addr": {"data_size": 2000000, "url_list": ["https://dy.example/sd.mp4"]}},
                    ]
                }
            }
        )
        self.assertEqual(dy_vid["media_type"], "video")
        self.assertEqual(dy_vid["video_url"], "https://dy.example/sd.mp4")

        dy_img = DouyinAdapter._extract_work_media(
            {"images": [{"url_list": ["https://dy.example/img1.jpg"]}, {"url_list": ["https://dy.example/img2.jpg"]}]}
        )
        self.assertEqual(dy_img["media_type"], "images")
        self.assertEqual(len(dy_img["images"]), 2)

        # 2. Weibo: 大图列表与低码率视频直链优先
        wb_media = WeiboAdapter._extract_mblog_media(
            {
                "pics": [{"url": "https://wb.example/sm.jpg", "large": {"url": "https://wb.example/lg.jpg"}}],
                "page_info": {
                    "type": "video",
                    "media_info": {
                        "mp4_hd_url": "https://wb.example/hd.mp4",
                        "mp4_ld_mp4": "https://wb.example/ld.mp4",
                    },
                },
            }
        )
        self.assertEqual(wb_media["pics"], ["https://wb.example/lg.jpg"])
        self.assertEqual(wb_media["video_url"], "https://wb.example/ld.mp4")

        # 3. Bilibili: 动态配图 + playurl 360p MP4 直链解析
        bili = BilibiliAdapter()
        fake_dyn_data = {
            "items": [
                {
                    "id_str": "dyn1",
                    "type": "DYNAMIC_TYPE_DRAW",
                    "modules": {
                        "module_author": {"pub_ts": 1792344600},
                        "module_dynamic": {
                            "desc": {"text": "周末骑行"},
                            "major": {
                                "draw": {"items": [{"src": "https://i0.hdslb.com/bfs/new_dyn/1.jpg"}]}
                            },
                        },
                    },
                }
            ]
        }
        with patch.object(bili, "_get", side_effect=[fake_dyn_data, {"items": []}]):
            evs = bili.get_events("12345")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].extra["pics"], ["https://i0.hdslb.com/bfs/new_dyn/1.jpg"])

        with patch.object(
            bili,
            "get_content_detail",
            return_value={"bvid": "BV1xx411c7mD", "cid": 888, "title": "测试视频", "coverUrl": "https://i0.hdslb.com/c.jpg", "duration": 45},
        ), patch.object(
            bili,
            "_get",
            return_value={"durl": [{"url": "https://upos.bilivideo.com/360p.mp4", "size": 1024000}]},
        ):
            stream = bili.get_video_stream_url("BV1xx411c7mD")
        self.assertIsNotNone(stream)
        self.assertEqual(stream["video_url"], "https://upos.bilivideo.com/360p.mp4")

        # 4. XHS: 笔记详情提取多图、视频与标签
        xhs = XhsAdapter()
        xhs._note_tokens["note123"] = "tok_abc"
        fake_note = {
            "data": {
                "items": [
                    {
                        "note_card": {
                            "title": "桌面分享",
                            "desc": "新买的键盘",
                            "type": "normal",
                            "ip_location": "浙江",
                            "tag_list": [{"name": "桌搭"}],
                            "image_list": [{"url_default": "https://sns-webpic-qc.xhscdn.com/a.webp"}],
                        }
                    }
                ]
            }
        }
        with patch.object(
            XhsAdapter,
            "api_pc",
            new=SimpleNamespace(get_note_info=lambda url: (True, "ok", fake_note)),
        ):
            detail = xhs.get_content_detail("note123")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["images"], ["https://sns-webpic-qc.xhscdn.com/a.webp"])
        self.assertEqual(detail["ip_location"], "浙江")
        self.assertEqual(detail["tags"], ["桌搭"])

    def test_media_fetcher_headers_cache_and_size_limit(self):
        from app.services.media_fetcher import download_media, lookup_cached_media

        seen_headers = {}

        class _FakeResp:
            def __init__(self, chunks, cl=None):
                self.status_code = 200
                self.headers = {"Content-Type": "image/jpeg"}
                if cl is not None:
                    self.headers["Content-Length"] = str(cl)
                self._chunks = chunks

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_content(self, chunk_size=65536):
                yield from self._chunks

        def _fake_get(url, headers=None, **kwargs):
            seen_headers.update(headers or {})
            return _FakeResp([b"\xff\xd8\xff\xe0test-jpeg-bytes"], cl=19)

        with patch("app.services.media_fetcher.requests.get", side_effect=_fake_get) as mock_get:
            m1 = download_media("https://i0.hdslb.com/bfs/face/avatar.jpg", platform="bilibili")
            m2 = download_media("https://i0.hdslb.com/bfs/face/avatar.jpg", platform="bilibili")
            # 第二次直接命中本地 24h 缓存
            self.assertEqual(mock_get.call_count, 1)
            self.assertEqual(m1.media_id, m2.media_id)
            self.assertEqual(seen_headers.get("Referer"), "https://www.bilibili.com/")
            self.assertIsNotNone(lookup_cached_media(m1.media_id))
            self.assertIsNone(lookup_cached_media("../../etc/passwd"))

        # 超过大小上限立即中止
        with patch("app.services.media_fetcher.requests.get", return_value=_FakeResp([b"x" * 2048], cl=2048)):
            with self.assertRaises(RuntimeError):
                download_media("https://example.com/huge.mp4", platform="douyin", kind="video", max_bytes=1024)

    def test_gemini_multimodal_images_video_tools_and_visual_baseline(self):
        from types import SimpleNamespace
        from app.agent.graph import compile_profile_graph
        from app.agent.multimodal import analyze_images, analyze_video
        from app.agent.tools import exec_inspect_images, exec_inspect_video
        from app.services.media_fetcher import CachedMedia

        save_llm_config(
            {
                "provider": "gemini",
                "api_key": "AIzaFakeMultimodalKey123",
                "model": "gemini-2.5-flash",
                "enable_multimodal": True,
            }
        )

        img_path = Path(self.tmpdir.name) / "sample.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpg")
        vid_path = Path(self.tmpdir.name) / "sample.mp4"
        vid_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

        cached_img = CachedMedia(
            media_id="aaaaaaaaaaaaaaaaaaaaaaaa",
            url="https://example.com/a.jpg",
            path=img_path,
            mime_type="image/jpeg",
            size_bytes=img_path.stat().st_size,
            kind="image",
            platform="xhs",
        )
        cached_vid = CachedMedia(
            media_id="bbbbbbbbbbbbbbbbbbbbbbbb",
            url="https://example.com/v.mp4",
            path=vid_path,
            mime_type="video/mp4",
            size_bytes=vid_path.stat().st_size,
            kind="video",
            platform="douyin",
        )

        deleted_files: list[str] = []

        class _FakeModels:
            def generate_content(self, model, contents, config=None):
                return SimpleNamespace(text="画面展示极简桌面与机械键盘，风格偏科技极客。")

        class _FakeFiles:
            def upload(self, file, config=None):
                return SimpleNamespace(name="files/vid-123", state=SimpleNamespace(name="PROCESSING"))

            def get(self, name):
                return SimpleNamespace(name=name, state=SimpleNamespace(name="ACTIVE"))

            def delete(self, name):
                deleted_files.append(name)

        fake_client = SimpleNamespace(models=_FakeModels(), files=_FakeFiles())

        with patch("app.agent.multimodal.build_gemini_client", return_value=fake_client):
            img_res = analyze_images([("小红书配图", cached_img)], "分析风格")
            self.assertEqual(img_res["provider"], "gemini")
            self.assertIn("机械键盘", img_res["analysis"])

        # Anthropic 视觉图片分析走 Claude 原生 base64 image block
        captured_ant_msgs: list = []

        class _FakeAnthropicVisionLLM:
            def invoke(self, msgs):
                captured_ant_msgs.extend(msgs)
                return AIMessage(content="Claude 视觉识别：极简机械键盘桌搭。")

        with patch("app.agent.multimodal.build_chat_model", return_value=_FakeAnthropicVisionLLM()):
            ant_img_res = analyze_images(
                [("小红书配图", cached_img)],
                "分析风格",
                overrides={"provider": "anthropic", "api_key": "sk-ant-test", "model": "claude-sonnet-4-5"},
            )
        self.assertEqual(ant_img_res["provider"], "anthropic")
        self.assertIn("Claude 视觉识别", ant_img_res["analysis"])
        self.assertTrue(
            any(
                isinstance(b, dict) and b.get("type") == "image" and b.get("source", {}).get("type") == "base64"
                for b in captured_ant_msgs[0].content
            )
        )

        with patch("app.agent.multimodal.build_gemini_client", return_value=fake_client):

            # 小视频走内联 Part.from_bytes
            vid_inline = analyze_video(cached_vid, "分析视频")
            self.assertEqual(vid_inline["mode"], "inline")
            self.assertEqual(deleted_files, [])

            # 大于内联阈值的视频走 Files API 并在结束后自动 delete
            with patch("app.agent.multimodal.INLINE_VIDEO_MAX_BYTES", 10):
                vid_files = analyze_video(cached_vid, "分析大视频")
            self.assertEqual(vid_files["mode"], "files_api")
            self.assertEqual(deleted_files, ["files/vid-123"])

            # 工具层 inspect_images / inspect_video 端到端测试
            catalog = {
                "xhs": {
                    "platform": "xhs",
                    "uid": "u1",
                    "avatar_url": "https://example.com/a.jpg",
                    "items": {
                        "note1": {
                            "item_id": "note1",
                            "title": "桌搭",
                            "images": ["https://example.com/a.jpg"],
                            "cover_url": "https://example.com/a.jpg",
                            "url": "https://www.xiaohongshu.com/explore/note1",
                        }
                    },
                    "events": [],
                },
                "douyin": {
                    "platform": "douyin",
                    "uid": "d1",
                    "items": {
                        "aweme1": {
                            "item_id": "aweme1",
                            "title": "开箱视频",
                            "cover_url": "https://example.com/a.jpg",
                            "video_url": "https://example.com/v.mp4",
                            "video_urls": ["https://example.com/v.mp4"],
                            "url": "https://www.douyin.com/video/aweme1",
                        }
                    },
                    "events": [],
                },
            }
            with patch("app.agent.tools.download_media", side_effect=lambda u, **kw: cached_vid if kw.get("kind") == "video" else cached_img):
                r_img = exec_inspect_images(self.store, "xhs", item_ids=["note1"], media_catalog=catalog)
                self.assertTrue(r_img.ok)
                self.assertEqual(r_img.evidence_items[0]["media_urls"], [cached_img.preview_url])

                r_vid = exec_inspect_video(self.store, "douyin", "aweme1", media_catalog=catalog)
                self.assertTrue(r_vid.ok)
                self.assertEqual(r_vid.evidence_items[0]["video_url"], cached_vid.preview_url)
                self.assertEqual(r_vid.evidence_items[0]["media_urls"], [cached_img.preview_url])

        # Level 1 视觉基线节点测试
        self.store.save_snapshot(
            "github",
            "visdev",
            "profile",
            {
                "platform": "github",
                "uid": "visdev",
                "nickname": "VisDev",
                "avatar_url": "https://example.com/a.jpg",
            },
        )
        fake_llm = _ScriptedFakeLLM(
            [
                AIMessage(content="视觉与基线信息充足。"),
                AIMessage(content="# 人物侧写\n视觉偏极简极客 [高置信][E1][E2]。"),
            ]
        )
        graph = compile_profile_graph(
            self.store,
            llm_factory=lambda: fake_llm,
            enable_visual_baseline=True,
        )
        with patch("app.services.platform_fetcher.get_adapter") as mock_get_adapter, patch(
            "app.agent.graph.download_media", return_value=cached_img
        ), patch(
            "app.agent.graph.analyze_images",
            return_value={"analysis": "跨平台头像为同源二次元极简风格", "provider": "gemini", "model": "gemini-2.5-flash", "media_count": 1},
        ):
            adp = mock_get_adapter.return_value
            adp.get_content_lists.return_value = []
            adp.get_events.return_value = []
            adp.get_follows.return_value = ([], False, 0)
            adp.get_followers.return_value = ([], False, 0)
            adp.get_history.return_value = []
            out = graph.invoke({"mode": "profile", "confirmed_accounts": {"github": "visdev"}})

        ev_list = list((out.get("evidence") or {}).values())
        vis_ev = [e for e in ev_list if e.get("category") == "visual_baseline"]
        self.assertEqual(len(vis_ev), 1)
        self.assertEqual(vis_ev[0]["media_urls"], [cached_img.preview_url])


if __name__ == "__main__":
    unittest.main()
