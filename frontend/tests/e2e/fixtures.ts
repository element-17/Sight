import type { Page } from "@playwright/test";
import type {
  Account,
  AgentSessionDetail,
  GraphData,
  GraphNode,
  LlmConfig,
  TimelineEntry,
} from "../../src/types";
export const ids = [
  "netease",
  "bilibili",
  "douyin",
  "qqmusic",
  "weibo",
  "genshin",
  "xhs",
  "github",
] as const;
export const graphNode = (
  platform: GraphNode["platform"],
  uid: string,
  nickname: string,
): GraphNode => ({
  id: platform === "keyword" ? "keyword" : `${platform}:${uid}`,
  platform,
  uid,
  nickname,
  fans: 12,
  signature: "公开资料示例",
});
export function sampleGraph(): GraphData {
  const nodes = [
    graphNode("keyword", "示例", "示例"),
    graphNode("netease", "1", "示例"),
    graphNode("bilibili", "2", "示例"),
    graphNode("netease", "3", "朋友"),
  ];
  return {
    keyword: "示例",
    platforms: ["netease", "bilibili"],
    searched: ids.slice(),
    nodes,
    edges: nodes
      .slice(1)
      .map((n) => ({ source: "keyword", target: n.id, relation: "hit" })),
    keywords: { netease: "专属昵称" },
    custom_metadata: { keep: true },
  };
}
export async function installMockApi(page: Page) {
  const requests: Array<{ path: string; method: string; body: unknown }> = [];
  let graph = sampleGraph(),
    name = "旧图谱",
    accountList: Account[] = [
      {
        id: "primary",
        name: "主账号",
        enabled: true,
        primary: true,
        has_credential: true,
        cookie_keys: ["session"],
      },
    ];
  let timeline: TimelineEntry[] = [
    {
      id: 1,
      platform: "netease",
      summary: "新增收藏歌单",
      detail: "测试详情",
      timestamp: 1792375200,
      event_type: "歌单",
      created_at: "2026-10-19T10:00:00",
    },
  ];
  let qrPolls = 0,
    queued = false,
    cursor = 0;
  let llmConfig: LlmConfig = {
    provider: "openai_compatible",
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    temperature: 0.2,
    max_steps: 8,
    timeout: 90,
    enable_multimodal: true,
    supports_vision: true,
    supports_video: false,
    has_api_key: true,
    api_key_preview: "sk-1...cdef",
    api_key_source: "file",
    is_local: false,
    configured: true,
    presets: [
      {
        id: "gemini_flash",
        name: "Gemini 2.5 Flash (原生多模态·推荐)",
        provider: "gemini",
        base_url: "",
        model: "gemini-2.5-flash",
      },
      {
        id: "anthropic_sonnet",
        name: "Claude Sonnet (Anthropic 协议)",
        provider: "anthropic",
        base_url: "https://api.anthropic.com",
        model: "claude-sonnet-4-5",
      },
      {
        id: "deepseek",
        name: "DeepSeek",
        provider: "openai_compatible",
        base_url: "https://api.deepseek.com/v1",
        model: "deepseek-chat",
      },
      {
        id: "ollama",
        name: "Ollama (本地)",
        provider: "openai_compatible",
        base_url: "http://127.0.0.1:11434/v1",
        model: "qwen2.5:14b",
      },
    ],
  };
  let agentSessions: AgentSessionDetail[] = [];
  const sampleDoneSession = (
    id: string,
    title: string,
    uids: Record<string, string>,
  ): AgentSessionDetail => ({
    id,
    title,
    target_query: "",
    focus: "",
    uids,
    graph_id: null,
    status: "done",
    model: llmConfig.model,
    error: "",
    created_at: "2026-11-26T10:00:00+08:00",
    updated_at: "2026-11-26T10:00:05+08:00",
    has_report: true,
    running: false,
    last_seq: 3,
    report_markdown:
      "# 人物形象侧写：示例开发者\n\n## 一、核心概览\n常驻杭州的开源开发者 [高置信][E1]，偏夜间活跃 [中置信][E2]。",
    structured: {
      profile_meta: {
        headline: "常驻杭州的开源开发者",
        tags: ["Python", "开源", "夜猫子"],
        confidence_overall: "high",
        dimensions: [
          {
            key: "identity",
            title: "身份线索",
            summary: "公开资料指向技术开发者",
            confidence: "high",
            evidence_ids: ["E1"],
          },
        ],
        blind_spots: [],
      },
      baseline_stats: {
        activity: {
          total_timed_events: 8,
          hourly_distribution: [
            2, 3, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            1, 1,
          ],
          weekday_distribution: [],
          peak_hours: [1],
          late_night_ratio: 0.875,
          chronotype: "深夜活跃型（夜猫子）",
          timezone_hint: "CST (UTC+8)",
        },
        social: {
          total_nodes: 3,
          total_follow_edges: 2,
          mutual_core_contacts: [
            {
              id: "github:peer1",
              platform: "github",
              platform_name: "GitHub",
              uid: "peer1",
              nickname: "核心互关好友",
              fans: 32,
              verified: false,
              degree: 2,
              relation: "mutual",
            },
          ],
          followed_public_accounts: [],
        },
      },
      citation_report: {
        total_evidence: 2,
        cited_valid: ["E1", "E2"],
        removed_invalid: [],
      },
      pruned_graph: {
        total_nodes: 18,
        total_edges: 22,
        triangle_edges_count: 3,
        pruned_summary: {
          total_pruned: 12,
          by_reason: { "官方认证/公众账号": 7, "高粉公众账号 (≥20000 粉)": 5 },
        },
        core_circle: [
          {
            id: "github:peer1",
            platform: "github",
            platform_name: "GitHub",
            uid: "peer1",
            nickname: "核心互关好友",
            fans: 32,
            verified: false,
            relation: "mutual",
            triangle_links: 2,
            score: 0.88,
            reasons: ["与目标双向互关", "圈内三角闭合 ×2"],
          },
        ],
        saved_graph_id: 1,
        saved_graph_name: "AI剪枝 · 示例开发者",
      },
    },
    evidence: {
      E1: {
        id: "E1",
        platform: "github",
        platform_name: "GitHub",
        uid: "100",
        category: "profile",
        title: "GitHub 主页资料",
        snippet: "昵称「测试用户-github」 | 地区: Hangzhou",
        url: "https://github.com/100",
      },
      E2: {
        id: "E2",
        platform: "multi",
        platform_name: "作息统计",
        category: "activity_stats",
        title: "确定性作息统计",
        snippet: "深夜活跃型（夜猫子），高峰时段 01:00",
      },
      E3: {
        id: "E3",
        platform: "multi",
        platform_name: "多模态视觉基线",
        category: "visual_baseline",
        title: "跨平台头像与背景视觉基线（1 张）",
        snippet: "头像风格偏极简科技插画，跨平台视觉一致",
        media_urls: ["/api/agent/media/0123456789abcdef01234567"],
      },
    },
    gaps: [],
    trace: [
      {
        ts: "10:00:01",
        stage: "collect_baseline",
        title: "基线采集与确定性统计完成",
        detail: "建立 2 条初始证据",
        status: "done",
        elapsed_ms: 120,
      },
    ],
    chat_history: [],
  });
  await page.addInitScript(() => {
    // Exercise the documented SSE fallback without opening external connections.
    class UnavailableEventSource {
      static CLOSED = 2;
      readyState = 2;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onopen: (() => void) | null = null;
      constructor(_url: string) {
        queueMicrotask(() => this.onerror?.(new Event("error")));
      }
      close() {}
    }
    window.EventSource =
      UnavailableEventSource as unknown as typeof EventSource;
  });
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname.replace("/api", ""),
      method = req.method(),
      body = req.postDataJSON();
    requests.push({ path, method, body });
    let data: unknown = {};
    const meta = ids.map((id) => ({
      id,
      name: id,
      has_credential: true,
      is_alive: true,
      login_user: {
        uid:
          id === "genshin"
            ? "123456789"
            : id === "xhs"
              ? "5d8c00000000000010000000"
              : "100",
        nickname: `测试用户-${id}`,
      },
    }));
    if (path === "/platforms") data = meta;
    else if (path.endsWith("/all")) {
      const id = path.split("/")[1],
        uid = url.searchParams.get("uid");
      data = {
        profile: {
          platform: id,
          uid,
          nickname: `测试用户-${id}`,
          level: 9,
          signature: "这是用于界面回归的公开资料示例",
          extra: {
            followeds: 88,
            follows: 12,
            fan_count: 88,
            follow_count: 12,
            world_level: 8,
          },
        },
        playlists: [
          {
            item_id: "p1",
            title: id === "genshin" ? "胡桃 Lv.90" : "测试内容",
            count: 3,
            is_owner: true,
            creator: "测试用户",
            extra: {
              level: 90,
              element: "火",
              constellation: 1,
              weapon_name: "护摩之杖",
              weapon_level: 90,
            },
          },
        ],
        records: {
          allTime: [
            {
              entry_id: "s1",
              title: "测试歌曲",
              artist_or_uploader: "歌手",
              play_count: 42,
            },
          ],
          weekly: [],
        },
        events: [
          {
            event_id: "e1",
            event_type: "发布",
            content: "一条公开动态",
            timestamp: 1792375200,
          },
        ],
        follows: [{ uid: "200", nickname: "示例关注" }],
        followers: [{ uid: "300", nickname: "示例粉丝" }],
        _errors: [],
      };
    } else if (path.endsWith("/search") && path !== "/graph/search")
      data = [
        { uid: "201", nickname: "搜索结果甲" },
        { uid: "202", nickname: "搜索结果乙" },
      ];
    else if (path.includes("/playlist/"))
      data = {
        title: "测试歌单详情",
        count: 1,
        items: [
          { id: "s1", title: "详情歌曲", artist: "测试歌手", duration: 180000 },
        ],
      };
    else if (path === "/timeline") data = timeline;
    else if (path === "/timeline/1") {
      if (method === "PUT") timeline = [{ ...timeline[0], ...body }];
      if (method === "DELETE") timeline = [];
      data = {};
    } else if (path.startsWith("/credentials/"))
      data = { has_credential: true, cookie_keys: ["session"] };
    else if (/^\/accounts\/[^/]+$/.test(path)) {
      if (method === "POST")
        accountList.push({
          id: "extra1",
          name: body.name || "账号2",
          primary: false,
          enabled: true,
          has_credential: true,
          cookie_keys: ["session"],
        });
      data = {
        accounts: accountList,
        pool_size: accountList.filter((a) => a.enabled).length,
      };
    } else if (path.startsWith("/accounts/") && path.endsWith("/test"))
      data = { ok: true, latency_ms: 15, login_user: { nickname: "测试账号" } };
    else if (path.startsWith("/accounts/")) {
      const id = path.split("/")[3];
      if (method === "DELETE")
        accountList = accountList.filter((a) => a.id !== id);
      else
        accountList = accountList.map((a) =>
          a.id === id ? { ...a, ...body } : a,
        );
      data = {};
    } else if (path === "/qqmusic/qr-login/start") {
      qrPolls = 0;
      data = {};
    } else if (path === "/qqmusic/qr-login/status")
      data =
        ++qrPolls === 1
          ? {
              status: "qr_ready",
              qr_code:
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==",
            }
          : {
              status: "done",
              follow_data: {
                count: 1,
                follows: [{ uid: "2", nickname: "扫码关注示例" }],
              },
            };
    else if (path === "/graph/search")
      data = {
        ...sampleGraph(),
        keyword: url.searchParams.get("keyword") || "示例",
      };
    else if (path === "/graph/save") {
      graph = body.data;
      name = body.name;
      data = { id: 1, name };
    } else if (path === "/graph/saved")
      data = [
        {
          id: 1,
          name,
          keyword: graph.keyword,
          node_count: graph.nodes.length - 1,
          edge_count: graph.edges.length,
          updated_at: "2026-10-19T10:00:00",
        },
      ];
    else if (path === "/graph/saved/1") data = { id: 1, name, data: graph };
    else if (path === "/graph/expand/enqueue") {
      queued = true;
      data = {
        queued: body.items.length,
        duplicates: 0,
        rejected: 0,
        task_ids: body.items.map((_: unknown, i: number) => 100 + i),
      };
    } else if (path === "/graph/expand/results") {
      const task =
        queued && Number(url.searchParams.get("since_id")) < 100
          ? {
              id: 100,
              platform: "netease",
              uid: "1",
              nickname: "示例",
              status: "done",
              dirs: { follows: true, followers: true },
              result: {
                nodes: [graphNode("netease", "4", "新邻居")],
                edges: [
                  {
                    source: "netease:1",
                    target: "netease:4",
                    relation: "follows",
                  },
                ],
                counts: {
                  follows: 1,
                  followers: 0,
                  follows_more: false,
                  followers_more: false,
                },
              },
            }
          : null;
      if (task) {
        queued = false;
        cursor = 100;
      }
      data = { results: task ? [task] : [], pending: 0, cursor, paused: [] };
    } else if (path === "/graph/expand/status")
      data = {
        queues: [
          {
            platform: "netease",
            pending: 0,
            running: 0,
            paused: false,
            accounts: 1,
            interval: 1,
            running_tasks: [],
            pending_tasks: [],
          },
        ],
      };
    else if (path === "/graph/refresh_nodes")
      data = {
        nodes: graph.nodes.filter((n) => n.platform !== "keyword"),
        errors: {},
      };
    else if (path === "/logs/recent")
      data = {
        entries: [
          {
            seq: 1,
            boot: "fixture",
            ts: "10:00:00",
            text: "[netease] 资料加载完成",
            source: "netease",
            level: "info",
          },
        ],
        last_seq: 1,
      };
    else if (path.endsWith("/cache/clear")) data = { adapters_dropped: 1 };
    else if (path.startsWith("/agent/media/")) {
      const tinyPng = Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==",
        "base64",
      );
      await route.fulfill({ status: 200, contentType: "image/png", body: tinyPng });
      return;
    } else if (path === "/agent/config") {
      if (method === "POST") {
        const nextProvider =
          body.provider === "gemini"
            ? "gemini"
            : body.provider === "anthropic"
              ? "anthropic"
              : "openai_compatible";
        const nextMm = body.enable_multimodal ?? llmConfig.enable_multimodal;
        llmConfig = {
          ...llmConfig,
          provider: nextProvider,
          base_url: body.base_url ?? llmConfig.base_url,
          model: body.model || llmConfig.model,
          enable_multimodal: nextMm,
          supports_vision: nextMm,
          supports_video: nextProvider === "gemini" && nextMm,
          configured: true,
        };
      }
      data = llmConfig;
    } else if (path === "/agent/config/models") {
      const reqProvider = body?.provider || llmConfig.provider;
      const models =
        reqProvider === "gemini"
          ? [
              { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash" },
              { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro" },
            ]
          : reqProvider === "anthropic"
            ? [
                { id: "claude-sonnet-4-5", name: "Claude Sonnet 4.5" },
                { id: "claude-haiku-4-5", name: "Claude Haiku 4.5" },
              ]
            : [
                { id: "deepseek-chat", owned_by: "deepseek" },
                { id: "deepseek-reasoner", owned_by: "deepseek" },
              ];
      data = {
        ok: true,
        provider: reqProvider,
        count: models.length,
        models,
        latency_ms: 35,
      };
    } else if (path === "/agent/config/test") {
      const testProvider = body?.provider || llmConfig.provider;
      const testMm = body?.enable_multimodal ?? llmConfig.enable_multimodal;
      data = {
        ok: true,
        provider: testProvider,
        model: body?.model || llmConfig.model,
        base_url: body?.base_url ?? llmConfig.base_url,
        supports_video: testProvider === "gemini" && testMm,
        latency_ms: 42,
        reply_preview: "OK",
      };
    } else if (path === "/agent/sessions") {
      if (method === "POST") {
        const id = `sess_${agentSessions.length + 1}`;
        if (body.target_query && !body.auto_confirm) {
          const paused: AgentSessionDetail = {
            ...sampleDoneSession(id, `${body.target_query} · 人物侧写`, {}),
            target_query: body.target_query,
            status: "waiting_confirm",
            report_markdown: "",
            has_report: false,
            running: false,
            structured: {
              pending_interrupt: {
                type: "confirm_identities",
                query: body.target_query,
                message: "请勾选属于同一目标的候选账号",
                candidates: [
                  {
                    id: "github:cand_dev",
                    platform: "github",
                    platform_name: "GitHub",
                    uid: "cand_dev",
                    nickname: body.target_query,
                    signature: "开源开发者",
                    fans: 88,
                    confidence: 0.95,
                    recommended: true,
                  },
                ],
              },
            },
          };
          agentSessions = [paused, ...agentSessions];
          data = paused;
        } else if (body.focus === "simulate-failed-checkpoint") {
          const failed: AgentSessionDetail = {
            ...sampleDoneSession(
              id,
              body.title || "失败断点 · 人物侧写",
              body.uids || { github: "100" },
            ),
            status: "failed",
            error: "Connection error. — [SSL: UNEXPECTED_EOF_WHILE_READING]",
            report_markdown: "",
            has_report: false,
            running: false,
            can_resume: true,
            resume_nodes: ["investigator"],
          };
          agentSessions = [failed, ...agentSessions];
          data = failed;
        } else {
          const done = sampleDoneSession(
            id,
            body.title || "面板账号 · 人物侧写",
            body.uids || { github: "100" },
          );
          agentSessions = [done, ...agentSessions];
          data = done;
        }
      } else {
        data = agentSessions;
      }
    } else if (/^\/agent\/sessions\/[^/]+$/.test(path)) {
      const sid = path.split("/")[3];
      if (method === "DELETE") {
        agentSessions = agentSessions.filter((s) => s.id !== sid);
        data = { id: sid, deleted: true };
      } else {
        data = agentSessions.find((s) => s.id === sid) || null;
      }
    } else if (/^\/agent\/sessions\/[^/]+\/resume$/.test(path)) {
      const sid = path.split("/")[3];
      const resumed = sampleDoneSession(
        sid,
        "确认后 · 人物侧写",
        body.confirmed_accounts || { github: "cand_dev" },
      );
      agentSessions = agentSessions.map((s) => (s.id === sid ? resumed : s));
      data = resumed;
    } else if (/^\/agent\/sessions\/[^/]+\/continue$/.test(path)) {
      const sid = path.split("/")[3];
      const existing = agentSessions.find((s) => s.id === sid);
      const continued = sampleDoneSession(
        sid,
        existing?.title || "断点续跑 · 人物侧写",
        existing?.uids || { github: "100" },
      );
      agentSessions = agentSessions.map((s) => (s.id === sid ? continued : s));
      data = continued;
    } else if (/^\/agent\/sessions\/[^/]+\/chat$/.test(path)) {
      const sid = path.split("/")[3];
      agentSessions = agentSessions.map((s) =>
        s.id === sid
          ? {
              ...s,
              chat_history: [
                ...s.chat_history,
                { role: "user", content: body.message },
                {
                  role: "assistant",
                  content: "根据 [E1] 和 [E2]，该目标常在深夜活跃。",
                },
              ],
            }
          : s,
      );
      data = agentSessions.find((s) => s.id === sid);
    } else if (/^\/agent\/sessions\/[^/]+\/events$/.test(path)) {
      data = { entries: [], last_seq: 3, running: false };
    }
    await route.fulfill({ json: { code: 200, data } });
  });
  return { requests, getGraph: () => graph };
}
