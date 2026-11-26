import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useShallow } from "zustand/react/shallow";
import { api, errorMessage } from "../api";
import { classNames } from "../classes";
import { PLATFORMS, PLATFORM_MAP } from "../platforms";
import {
  loadAgentSessions,
  openLlmModal,
  setActiveAgentId,
  useAppStore,
} from "../store";
import type {
  AgentCandidate,
  AgentEventsResponse,
  AgentSessionDetail,
  AgentStatus,
  AgentStreamEvent,
  LlmConfig,
  PlatformId,
} from "../types";
import styles from "./ViewAgent.module.css";
import ActivityChart from "./agent/ActivityChart";
import MarkdownReport from "./agent/MarkdownReport";
import Icon from "./ui/Icon";

const cx = classNames(styles);

const STATUS_LABELS: Record<AgentStatus, string> = {
  idle: "未开始",
  running: "推理中",
  waiting_confirm: "待确认候选",
  done: "已完成",
  failed: "执行失败",
  cancelled: "已中止",
};

type SideTab = "trace" | "chat" | "evidence";

export default function ViewAgent() {
  const idPrefix = useId();
  const {
    panelUids,
    savedGraphs,
    activeAgentId,
    llmModalOpen,
  } = useAppStore(
    useShallow((s) => ({
      panelUids: s.uids,
      savedGraphs: s.savedGraphs,
      activeAgentId: s.activeAgentId,
      llmModalOpen: s.llmModalOpen,
    })),
  );

  // LLM 配置摘要
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);

  // 新建侧写表单状态
  const [setupOpen, setSetupOpen] = useState(!activeAgentId);
  const [inputMode, setInputMode] = useState<"accounts" | "discover">("accounts");
  const [draftUids, setDraftUids] = useState<Record<string, string>>({});
  const [addPlatform, setAddPlatform] = useState<PlatformId>("bilibili");
  const [addUid, setAddUid] = useState("");
  const [targetQuery, setTargetQuery] = useState("");
  const [focus, setFocus] = useState("");
  const [selectedGraphId, setSelectedGraphId] = useState<string>("");
  const [autoConfirm, setAutoConfirm] = useState(false);
  const [refreshData, setRefreshData] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  // 当前活跃侧写档案与流式状态
  const [session, setSession] = useState<AgentSessionDetail | null>(null);
  const [loadingSession, setLoadingSession] = useState(false);
  const [liveStage, setLiveStage] = useState("");
  const [streamReport, setStreamReport] = useState("");
  const [streamChat, setStreamChat] = useState("");
  const [streamError, setStreamError] = useState("");

  // 人工确认候选勾选状态: {platform: uid}
  const [confirmSelection, setConfirmSelection] = useState<Record<string, string>>({});
  const [resuming, setResuming] = useState(false);

  // 右侧面板状态
  const [sideTab, setSideTab] = useState<SideTab>("trace");
  const [focusedEvidenceId, setFocusedEvidenceId] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [sendingChat, setSendingChat] = useState(false);

  const lastSeqRef = useRef(0);
  const evidenceRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // 加载 LLM 配置状态（弹窗关闭后同步刷新）
  const refreshLlmConfig = useCallback(async () => {
    try {
      const cfg = await api.get<LlmConfig>("/agent/config");
      setLlmConfig(cfg);
    } catch {
      /* ignore transient fetch failure */
    }
  }, []);

  useEffect(() => {
    if (!llmModalOpen) void refreshLlmConfig();
  }, [llmModalOpen, refreshLlmConfig]);

  // 初次进入时默认带入面板已绑定的非空 UIDs
  useEffect(() => {
    const initial: Record<string, string> = {};
    for (const p of PLATFORMS) {
      const v = (panelUids[p.id] || "").trim();
      if (v) initial[p.id] = v;
    }
    setDraftUids((prev) => (Object.keys(prev).length ? prev : initial));
  }, [panelUids]);

  // 切换侧边栏选中档案时加载详情
  useEffect(() => {
    if (!activeAgentId) {
      setSession(null);
      setSetupOpen(true);
      setLiveStage("");
      setStreamReport("");
      setStreamChat("");
      setStreamError("");
      lastSeqRef.current = 0;
      return;
    }
    let active = true;
    setLoadingSession(true);
    setStreamReport("");
    setStreamChat("");
    setStreamError("");
    void api
      .get<AgentSessionDetail>(`/agent/sessions/${activeAgentId}`)
      .then((detail) => {
        if (!active) return;
        setSession(detail);
        setSetupOpen(false);
        lastSeqRef.current = detail.last_seq || 0;
      })
      .catch((e) => {
        if (active) setStreamError(errorMessage(e));
      })
      .finally(() => {
        if (active) setLoadingSession(false);
      });
    return () => {
      active = false;
    };
  }, [activeAgentId]);

  // 当出现 waiting_confirm 候选账号时，默认勾选每平台推荐项
  const pendingCandidates = useMemo<AgentCandidate[]>(
    () => session?.structured?.pending_interrupt?.candidates || [],
    [session],
  );
  useEffect(() => {
    if (session?.status !== "waiting_confirm" || !pendingCandidates.length) return;
    const defaults: Record<string, string> = {};
    for (const c of pendingCandidates) {
      if (c.recommended && !defaults[c.platform]) {
        defaults[c.platform] = c.uid;
      }
    }
    if (!Object.keys(defaults).length && pendingCandidates[0]) {
      defaults[pendingCandidates[0].platform] = pendingCandidates[0].uid;
    }
    setConfirmSelection(defaults);
  }, [session?.id, session?.status, pendingCandidates]);

  // 处理单条 SSE / 轮询事件
  const applyEvent = useCallback((ev: AgentStreamEvent) => {
    if (ev.seq <= lastSeqRef.current) return;
    lastSeqRef.current = ev.seq;

    if (ev.type === "run_start" || ev.type === "stage") {
      if (ev.label) setLiveStage(ev.label);
    } else if (ev.type === "tool_start") {
      if (ev.label) setLiveStage(ev.label);
    } else if (ev.type === "trace" && ev.item) {
      setSession((prev) =>
        prev ? { ...prev, trace: [...(prev.trace || []), ev.item!] } : prev,
      );
    } else if (ev.type === "tool_end") {
      setSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          trace: ev.item ? [...(prev.trace || []), ev.item] : prev.trace,
          evidence: ev.new_evidence
            ? { ...(prev.evidence || {}), ...ev.new_evidence }
            : prev.evidence,
        };
      });
    } else if (ev.type === "baseline_stats" && ev.stats) {
      setSession((prev) =>
        prev
          ? {
              ...prev,
              structured: {
                ...(prev.structured || {}),
                baseline_stats: ev.stats,
              },
            }
          : prev,
      );
    } else if (ev.type === "report_delta" && ev.delta) {
      setStreamReport((prev) => prev + ev.delta);
    } else if (ev.type === "chat_delta" && ev.delta) {
      setStreamChat((prev) => prev + ev.delta);
    } else if (ev.type === "interrupt") {
      setLiveStage("");
      if (ev.session) setSession({ ...ev.session, running: false });
      void loadAgentSessions();
    } else if (ev.type === "done") {
      setLiveStage("");
      setStreamReport("");
      if (ev.session) setSession({ ...ev.session, running: false });
      void loadAgentSessions();
    } else if (ev.type === "chat_done") {
      setLiveStage("");
      setStreamChat("");
      if (ev.session) setSession({ ...ev.session, running: false });
      void loadAgentSessions();
    } else if (ev.type === "error") {
      setLiveStage("");
      setStreamError(ev.message || "执行失败");
      if (ev.session) setSession({ ...ev.session, running: false });
      void loadAgentSessions();
    }
  }, []);

  // 订阅运行中会话的 SSE 事件流（EventSource 不可用或断开时自动降级为轮询）
  const sessionId = session?.id || "";
  const isRunning = Boolean(session?.running || session?.status === "running");

  useEffect(() => {
    if (!sessionId || !isRunning) return;
    let disposed = false;
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let fallbackTimer: ReturnType<typeof setTimeout> | undefined;

    async function pollOnce() {
      if (disposed) return;
      try {
        const data = await api.get<AgentEventsResponse>(
          `/agent/sessions/${sessionId}/events`,
          { after: lastSeqRef.current },
        );
        if (disposed) return;
        for (const ev of data.entries || []) applyEvent(ev);
        if (!data.running) {
          const detail = await api.get<AgentSessionDetail>(
            `/agent/sessions/${sessionId}`,
          );
          if (!disposed) {
            setSession({ ...detail, running: false });
            setLiveStage("");
            setStreamReport("");
            setStreamChat("");
            void loadAgentSessions();
          }
          return;
        }
      } catch {
        /* retry next tick */
      }
      if (!disposed) pollTimer = setTimeout(() => void pollOnce(), 900);
    }

    function startPolling() {
      source?.close();
      source = null;
      clearTimeout(fallbackTimer);
      if (!disposed) void pollOnce();
    }

    if (typeof EventSource === "undefined") {
      startPolling();
    } else {
      source = new EventSource(
        `/api/agent/sessions/${sessionId}/stream?after=${lastSeqRef.current}`,
      );
      source.onopen = () => {
        clearTimeout(fallbackTimer);
        fallbackTimer = undefined;
      };
      source.onmessage = (event) => {
        try {
          applyEvent(JSON.parse(event.data) as AgentStreamEvent);
        } catch {
          /* ignore malformed frame */
        }
      };
      source.onerror = () => {
        if (!source || disposed) return;
        if (source.readyState === EventSource.CLOSED) {
          startPolling();
          return;
        }
        if (!fallbackTimer) fallbackTimer = setTimeout(startPolling, 2000);
      };
    }

    return () => {
      disposed = true;
      source?.close();
      clearTimeout(pollTimer);
      clearTimeout(fallbackTimer);
    };
  }, [sessionId, isRunning, applyEvent]);

  // 表单交互
  function handleImportPanelUids() {
    const next: Record<string, string> = {};
    for (const p of PLATFORMS) {
      const v = (panelUids[p.id] || "").trim();
      if (v) next[p.id] = v;
    }
    setDraftUids(next);
    setFormError("");
  }

  function handleAddUid() {
    const uid = addUid.trim();
    if (!uid) return;
    setDraftUids((prev) => ({ ...prev, [addPlatform]: uid }));
    setAddUid("");
    setFormError("");
  }

  function handleRemoveUid(pid: string) {
    setDraftUids((prev) => {
      const next = { ...prev };
      delete next[pid];
      return next;
    });
  }

  async function handleStartSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    if (llmConfig && !llmConfig.configured) {
      setFormError("请先点击右上角「模型配置」填写可用的 LLM 模型后再开始侧写。");
      return;
    }
    const body: Record<string, unknown> = {
      focus: focus.trim(),
      refresh_data: refreshData,
      auto_start: true,
    };
    if (inputMode === "accounts") {
      if (!Object.keys(draftUids).length) {
        setFormError("请先导入当前面板 UID 或手动添加至少一个平台账号。");
        return;
      }
      body.uids = draftUids;
      if (selectedGraphId) body.graph_id = Number(selectedGraphId);
    } else {
      if (!targetQuery.trim()) {
        setFormError("请输入要排查的关键词或昵称。");
        return;
      }
      body.target_query = targetQuery.trim();
      body.auto_confirm = autoConfirm;
    }

    setSubmitting(true);
    setStreamReport("");
    setStreamChat("");
    setStreamError("");
    lastSeqRef.current = 0;
    try {
      const created = await api.post<AgentSessionDetail>("/agent/sessions", body);
      const activeRun = Boolean(created.running ?? created.status === "running");
      setSession({ ...created, running: activeRun });
      setActiveAgentId(created.id);
      setSetupOpen(false);
      setSideTab("trace");
      setLiveStage(activeRun ? "已提交任务，正在启动 LangGraph 工作流…" : "");
      void loadAgentSessions();
    } catch (e) {
      setFormError(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRerun() {
    if (!session) return;
    setStreamReport("");
    setStreamError("");
    lastSeqRef.current = 0;
    try {
      const updated = await api.post<AgentSessionDetail>(
        `/agent/sessions/${session.id}/run`,
        { refresh_data: true },
      );
      const activeRun = Boolean(updated.running ?? updated.status === "running");
      setSession({ ...updated, running: activeRun });
      setSideTab("trace");
      setLiveStage(activeRun ? "正在重新采集数据并生成侧写…" : "");
      void loadAgentSessions();
    } catch (e) {
      setStreamError(errorMessage(e));
    }
  }

  async function handleContinueFromCheckpoint() {
    if (!session) return;
    setStreamReport("");
    setStreamError("");
    lastSeqRef.current = 0;
    try {
      const updated = await api.post<AgentSessionDetail>(
        `/agent/sessions/${session.id}/continue`,
      );
      const activeRun = Boolean(updated.running ?? updated.status === "running");
      setSession({ ...updated, running: activeRun });
      setSideTab("trace");
      setLiveStage(
        activeRun
          ? "正在从 LangGraph 失败断点继续执行（跳过已完成阶段）…"
          : "",
      );
      void loadAgentSessions();
    } catch (e) {
      setStreamError(errorMessage(e));
    }
  }

  async function handleCancel() {
    if (!session) return;
    try {
      await api.post(`/agent/sessions/${session.id}/cancel`);
    } catch (e) {
      setStreamError(errorMessage(e));
    }
  }

  async function handleConfirmResume() {
    if (!session) return;
    if (!Object.keys(confirmSelection).length) {
      setStreamError("请至少勾选一个候选账号再继续。");
      return;
    }
    setResuming(true);
    setStreamError("");
    try {
      const resumed = await api.post<AgentSessionDetail>(
        `/agent/sessions/${session.id}/resume`,
        { confirmed_accounts: confirmSelection },
      );
      const activeRun = Boolean(resumed.running ?? resumed.status === "running");
      setSession({ ...resumed, running: activeRun });
      setLiveStage(activeRun ? "已确认账号，正在恢复执行基线采集与深度侧写…" : "");
      void loadAgentSessions();
    } catch (e) {
      setStreamError(errorMessage(e));
    } finally {
      setResuming(false);
    }
  }

  async function submitChat() {
    const text = chatInput.trim();
    if (!session || !text || isRunning || sendingChat) return;
    setSendingChat(true);
    setStreamError("");
    setStreamChat("");
    try {
      const updated = await api.post<AgentSessionDetail>(
        `/agent/sessions/${session.id}/chat`,
        { message: text },
      );
      const activeRun = Boolean(updated.running ?? updated.status === "running");
      setSession({ ...updated, running: activeRun });
      setChatInput("");
      setSideTab("chat");
      setLiveStage(activeRun ? "正在基于证据账本检索并回答追问…" : "");
    } catch (e) {
      setStreamError(errorMessage(e));
    } finally {
      setSendingChat(false);
    }
  }

  function handleChatKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // 遵循 modern-web-guidance forms 规范：中文输入法组字期间不把 Enter 当提交
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitChat();
    }
  }

  function handleSelectEvidence(eid: string) {
    setSideTab("evidence");
    setFocusedEvidenceId(eid);
    requestAnimationFrame(() => {
      evidenceRefs.current[eid]?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    });
  }

  function handleExportMarkdown() {
    if (!session?.report_markdown) return;
    const blob = new Blob([session.report_markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sight-侧写-${session.title.replace(/[\\/:*?"<>|]/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function toggleCandidate(cand: AgentCandidate) {
    setConfirmSelection((prev) => {
      const next = { ...prev };
      if (next[cand.platform] === cand.uid) {
        delete next[cand.platform];
      } else {
        next[cand.platform] = cand.uid;
      }
      return next;
    });
  }

  const evidenceMap = session?.evidence || {};
  const evidenceList = Object.values(evidenceMap);
  const traceList = session?.trace || [];
  const chatHistory = session?.chat_history || [];
  const profileMeta = session?.structured?.profile_meta;
  const activityStats = session?.structured?.baseline_stats?.activity;
  const socialStats = session?.structured?.baseline_stats?.social;
  const citationReport = session?.structured?.citation_report;
  const displayMarkdown = streamReport || session?.report_markdown || "";

  return (
    <div className={cx("page")}>
      {/* 顶部新建 / 配置面板 */}
      <section className={`card ${cx("setup-card")}`}>
        <div className={cx("setup-head")}>
          <div className={cx("setup-title")}>
            <Icon name="sparkles" size={16} />
            <span>AI 人物侧写工作台（LangGraph）</span>
            {session ? (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setSetupOpen((v) => !v)}
              >
                {setupOpen ? "收起新建表单" : "新建侧写"}
              </button>
            ) : null}
          </div>
          <button
            type="button"
            className={`btn btn-sm ${cx("llm-pill")}`}
            onClick={openLlmModal}
          >
            <span
              className={cx("dot", llmConfig?.configured ? "dot-ok" : "dot-warn")}
            />
            <Icon name="sliders" size={13} />
            <span>
              {llmConfig?.configured
                ? `模型：${llmConfig.model}${
                    llmConfig.supports_video
                      ? " · 原生多模态"
                      : llmConfig.enable_multimodal
                        ? " · 视觉"
                        : ""
                  }`
                : "模型配置（未配置）"}
            </span>
          </button>
        </div>

        {setupOpen ? (
          <form className={cx("setup-form")} onSubmit={handleStartSession}>
            <fieldset className={cx("mode-fieldset")}>
              <legend>侧写启动方式</legend>
              <label className={cx("radio-opt")}>
                <input
                  type="radio"
                  name="agent-mode"
                  value="accounts"
                  checked={inputMode === "accounts"}
                  onChange={() => {
                    setInputMode("accounts");
                    setFormError("");
                  }}
                />
                <span>基于已绑定 / 指定平台账号（直接采集侧写）</span>
              </label>
              <label className={cx("radio-opt")}>
                <input
                  type="radio"
                  name="agent-mode"
                  value="discover"
                  checked={inputMode === "discover"}
                  onChange={() => {
                    setInputMode("discover");
                    setFormError("");
                  }}
                />
                <span>输入关键词跨平台搜人（支持候选账号人工确认断点）</span>
              </label>
            </fieldset>

            {inputMode === "accounts" ? (
              <>
                <div className={cx("chips-row")}>
                  {Object.entries(draftUids).length ? (
                    Object.entries(draftUids).map(([pid, uid]) => {
                      const p = PLATFORM_MAP[pid];
                      return (
                        <span key={pid} className={cx("uid-chip")}>
                          <span
                            className={cx("dot")}
                            style={{ background: p?.color || "#3565e0" }}
                          />
                          <span>
                            {p?.name || pid}: {uid}
                          </span>
                          <button
                            type="button"
                            className={cx("uid-chip-rm")}
                            title={`移除 ${p?.name || pid}`}
                            onClick={() => handleRemoveUid(pid)}
                          >
                            <Icon name="x" size={11} />
                          </button>
                        </span>
                      );
                    })
                  ) : (
                    <span className="chip">暂未绑定任何平台账号</span>
                  )}
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={handleImportPanelUids}
                  >
                    导入当前面板 UIDs
                  </button>
                </div>

                <div className={cx("inline-row")}>
                  <label
                    htmlFor={`${idPrefix}-add-pid`}
                    className={cx("field-label")}
                  >
                    补充账号
                  </label>
                  <select
                    id={`${idPrefix}-add-pid`}
                    name="add_platform"
                    className="input"
                    value={addPlatform}
                    onChange={(e) =>
                      setAddPlatform(e.currentTarget.value as PlatformId)
                    }
                  >
                    {PLATFORMS.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <input
                    id={`${idPrefix}-add-uid`}
                    name="add_uid"
                    type="text"
                    className={`input ${cx("grow")}`}
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    value={addUid}
                    onChange={(e) => setAddUid(e.currentTarget.value)}
                    placeholder="输入平台 UID / 用户名"
                  />
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={handleAddUid}
                  >
                    添加
                  </button>
                  {savedGraphs.length > 0 ? (
                    <>
                      <label
                        htmlFor={`${idPrefix}-graph-select`}
                        className={cx("field-label")}
                      >
                        关联图谱
                      </label>
                      <select
                        id={`${idPrefix}-graph-select`}
                        name="graph_id"
                        className="input"
                        value={selectedGraphId}
                        onChange={(e) => setSelectedGraphId(e.currentTarget.value)}
                      >
                        <option value="">不关联关系图谱</option>
                        {savedGraphs.map((g) => (
                          <option key={g.id} value={String(g.id)}>
                            {g.name} ({g.node_count} 节点)
                          </option>
                        ))}
                      </select>
                    </>
                  ) : null}
                </div>
              </>
            ) : (
              <div className={cx("inline-row")}>
                <div className={`${cx("field-group")} ${cx("grow")}`}>
                  <label
                    htmlFor={`${idPrefix}-query`}
                    className={cx("field-label")}
                  >
                    搜索关键词 / 网名
                  </label>
                  <input
                    id={`${idPrefix}-query`}
                    name="target_query"
                    type="text"
                    className="input"
                    value={targetQuery}
                    onChange={(e) => {
                      setTargetQuery(e.currentTarget.value);
                      setFormError("");
                    }}
                    placeholder="输入目标昵称或 ID，跨平台搜索候选账号…"
                  />
                </div>
                <label className={cx("checkbox-opt")} style={{ marginTop: 18 }}>
                  <input
                    type="checkbox"
                    checked={autoConfirm}
                    onChange={(e) => setAutoConfirm(e.currentTarget.checked)}
                  />
                  <span>高置信自动归并（不暂停确认）</span>
                </label>
              </div>
            )}

            <div className={cx("inline-row")}>
              <div className={`${cx("field-group")} ${cx("grow")}`}>
                <label
                  htmlFor={`${idPrefix}-focus`}
                  className={cx("field-label")}
                >
                  调查关注重点（可选）
                </label>
                <input
                  id={`${idPrefix}-focus`}
                  name="focus"
                  type="text"
                  className="input"
                  value={focus}
                  onChange={(e) => setFocus(e.currentTarget.value)}
                  placeholder="例如：重点分析作息规律、技术栈偏好与核心社交圈"
                />
              </div>
            </div>

            {formError ? (
              <div className="banner banner-error" role="status" aria-live="polite" style={{ marginBottom: 0 }}>
                <Icon name="alert" size={15} />
                <span>{formError}</span>
              </div>
            ) : null}

            <div className={cx("setup-footer")}>
              <label className={cx("checkbox-opt")}>
                <input
                  type="checkbox"
                  checked={refreshData}
                  onChange={(e) => setRefreshData(e.currentTarget.checked)}
                />
                <span>绕过 30 分钟本地快照缓存强制实时拉取</span>
              </label>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={submitting}
              >
                {submitting ? (
                  <span className="spinner spinner-sm" />
                ) : (
                  <Icon name="sparkles" size={14} />
                )}
                <span>开始生成侧写</span>
              </button>
            </div>
          </form>
        ) : null}
      </section>

      {loadingSession ? (
        <div className="page-loading">
          <span className="spinner" />
          正在加载人物侧写档案…
        </div>
      ) : null}

      {streamError ? (
        <div className="banner banner-error" role="status" aria-live="polite">
          <Icon name="alert" size={15} />
          <span>{streamError}</span>
        </div>
      ) : null}

      {/* 当前活跃侧写档案工作区 */}
      {session ? (
        <>
          <section className={`card ${cx("session-bar")}`}>
            <div className={cx("session-meta")}>
              <span className={cx("session-title")}>{session.title}</span>
              <span className={cx("status-pill", `st-${session.status}`)}>
                {isRunning ? <span className="spinner spinner-sm" /> : null}
                {STATUS_LABELS[session.status] || session.status}
              </span>
              {session.model ? <span className="chip">{session.model}</span> : null}
              {Object.entries(session.uids || {}).map(([pid, uid]) => (
                <span key={pid} className="chip">
                  {PLATFORM_MAP[pid]?.name || pid}: {uid}
                </span>
              ))}
            </div>
            <div className={cx("inline-row")}>
              {isRunning ? (
                <button
                  type="button"
                  className="btn btn-sm btn-danger-ghost"
                  onClick={() => void handleCancel()}
                >
                  <Icon name="square" size={12} />
                  中止
                </button>
              ) : (
                <>
                  {session.can_resume ? (
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      title={
                        session.resume_nodes?.length
                          ? `跳过已完成阶段，直接从 ${session.resume_nodes.join(", ")} 节点继续`
                          : "跳过已完成阶段，从 LangGraph 失败断点继续"
                      }
                      onClick={() => void handleContinueFromCheckpoint()}
                    >
                      <Icon name="sparkles" size={12} />
                      从断点继续
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => void handleRerun()}
                  >
                    <Icon name="refresh" size={12} />
                    重新生成
                  </button>
                </>
              )}
              {session.report_markdown ? (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={handleExportMarkdown}
                >
                  <Icon name="download" size={12} />
                  导出 Markdown
                </button>
              ) : null}
            </div>
          </section>

          <div className={cx("workspace")}>
            {/* 左侧主报告区 */}
            <div className={cx("main-col")}>
              {/* 人机协同确认断点卡片（LangGraph interrupt） */}
              {session.status === "waiting_confirm" &&
              pendingCandidates.length > 0 ? (
                <section className={`card ${cx("confirm-card")}`}>
                  <div className={cx("confirm-head")}>
                    <Icon name="alert" size={16} />
                    <span>请确认跨平台候选账号（LangGraph 断点暂停）</span>
                  </div>
                  <div className={cx("confirm-desc")}>
                    {session.structured?.pending_interrupt?.message ||
                      "请勾选属于同一目标对象的平台账号（每平台最多选 1 个），确认后将从断点无缝继续深度侧写。"}
                  </div>
                  <div className={cx("cand-list")}>
                    {pendingCandidates.map((c) => {
                      const checked = confirmSelection[c.platform] === c.uid;
                      const p = PLATFORM_MAP[c.platform];
                      return (
                        <label
                          key={c.id}
                          className={cx("cand-item", { checked })}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleCandidate(c)}
                          />
                          <div className={cx("cand-body")}>
                            <div className={cx("cand-top")}>
                              <span
                                className={cx("dot")}
                                style={{ background: p?.color || "#3565e0" }}
                              />
                              <span className={cx("cand-nick")}>
                                {c.nickname}
                              </span>
                              <span className="chip">{c.platform_name}</span>
                              <span className="tag">
                                {`${Math.round(c.confidence * 100)}%`}
                                {c.recommended ? " 推荐" : ""}
                              </span>
                            </div>
                            <div className={cx("cand-uid")}>
                              UID: {c.uid}
                              {c.fans ? ` · 粉丝 ${c.fans}` : ""}
                            </div>
                            {c.signature ? (
                              <div className={cx("cand-sig")} title={c.signature}>
                                {c.signature}
                              </div>
                            ) : null}
                          </div>
                        </label>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={resuming || !Object.keys(confirmSelection).length}
                    onClick={() => void handleConfirmResume()}
                  >
                    {resuming ? <span className="spinner spinner-sm" /> : null}
                    确认所选账号并继续侧写（已选{" "}
                    {Object.keys(confirmSelection).length} 个平台）
                  </button>
                </section>
              ) : null}

              {/* 结构化画像概览卡片 */}
              {profileMeta &&
              (profileMeta.headline ||
                profileMeta.tags?.length ||
                profileMeta.dimensions?.length) ? (
                <section className={`card ${cx("meta-card")}`}>
                  {profileMeta.headline ? (
                    <div className={cx("headline")}>{profileMeta.headline}</div>
                  ) : null}
                  <div className={cx("chips-row")}>
                    {(profileMeta.tags || []).map((t) => (
                      <span key={t} className="tag">
                        {t}
                      </span>
                    ))}
                    {citationReport ? (
                      <span className="chip">
                        证据校验：有效引用 {citationReport.cited_valid.length}/
                        {citationReport.total_evidence}
                        {citationReport.removed_invalid.length
                          ? `（已过滤 ${citationReport.removed_invalid.length} 条无效引用）`
                          : " · 零幻觉"}
                      </span>
                    ) : null}
                  </div>
                  {profileMeta.dimensions && profileMeta.dimensions.length > 0 ? (
                    <div className={cx("dim-grid")}>
                      {profileMeta.dimensions.map((d, idx) => (
                        <div key={d.key || idx} className={cx("dim-item")}>
                          <div className={cx("dim-title")}>{d.title}</div>
                          <div className={cx("dim-summary")}>{d.summary}</div>
                          {d.evidence_ids?.length ? (
                            <div
                              className={cx("chips-row")}
                              style={{ marginTop: 6 }}
                            >
                              {d.evidence_ids.map((eid) => (
                                <button
                                  key={eid}
                                  type="button"
                                  className="tag"
                                  style={{ border: "none", cursor: "pointer" }}
                                  onClick={() => handleSelectEvidence(eid)}
                                >
                                  {eid}
                                </button>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

              {/* 24h 作息分布 ECharts 图表 */}
              {activityStats && activityStats.total_timed_events > 0 ? (
                <ActivityChart stats={activityStats} />
              ) : null}

              {/* 核心社交关系摘要 */}
              {socialStats &&
              (socialStats.mutual_core_contacts?.length ||
                socialStats.followed_public_accounts?.length) ? (
                <section className={`card ${cx("social-card")}`}>
                  <div className={cx("social-section-title")}>
                    社交网络拓扑摘录（{socialStats.total_nodes} 节点 /{" "}
                    {socialStats.total_follow_edges} 条关注边）
                  </div>
                  {socialStats.mutual_core_contacts?.length > 0 ? (
                    <div style={{ marginBottom: 8 }}>
                      <div className={cx("field-label")} style={{ marginBottom: 5 }}>
                        互关核心候选（已过滤大V）：
                      </div>
                      <div className={cx("contact-grid")}>
                        {socialStats.mutual_core_contacts.slice(0, 12).map((c) => (
                          <span key={c.id} className="chip" title={c.signature}>
                            {c.nickname} · {c.platform_name}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {socialStats.followed_public_accounts?.length > 0 ? (
                    <div>
                      <div className={cx("field-label")} style={{ marginBottom: 5 }}>
                        关注公众账号 / 大V：
                      </div>
                      <div className={cx("contact-grid")}>
                        {socialStats.followed_public_accounts
                          .slice(0, 10)
                          .map((c) => (
                            <span key={c.id} className="chip">
                              {c.nickname} ({c.platform_name})
                            </span>
                          ))}
                      </div>
                    </div>
                  ) : null}
                </section>
              ) : null}

              {/* 深度侧写 Markdown 报告 */}
              <section className={`card ${cx("report-card")}`}>
                {isRunning && !displayMarkdown ? (
                  <div className="page-loading" style={{ padding: "48px 0" }}>
                    <span className="spinner" />
                    <span>{liveStage || "正在执行多阶段侦查与侧写…"}</span>
                  </div>
                ) : displayMarkdown ? (
                  <>
                    {isRunning && streamReport ? (
                      <div className={cx("streaming-note")}>
                        <span className="spinner spinner-sm" />
                        <span>正在实时生成侧写报告…</span>
                      </div>
                    ) : null}
                    <MarkdownReport
                      markdown={displayMarkdown}
                      evidence={evidenceMap}
                      onSelectEvidence={handleSelectEvidence}
                    />
                  </>
                ) : (
                  <div className="empty-state">
                    <div className="empty-title">
                      {session.status === "waiting_confirm"
                        ? "等待确认跨平台候选账号"
                        : session.status === "failed"
                          ? `生成失败：${session.error || "未知错误"}`
                          : "尚未生成侧写报告"}
                    </div>
                    <div>
                      {session.status === "waiting_confirm"
                        ? "请在上方勾选确认目标账号，系统会自动从断点继续推理。"
                        : session.status === "failed" && session.can_resume
                          ? `已通过 LangGraph 保留前面完成的基线数据与证据（待续跑节点：${(session.resume_nodes || []).join(", ")}）。修复网络或模型配置后，点击「从断点继续」即可直接续跑，无需重新抓取。`
                          : "点击右上角「重新生成」即可再次运行工作流。"}
                    </div>
                    {session.status === "failed" && session.can_resume ? (
                      <div style={{ marginTop: 12 }}>
                        <button
                          type="button"
                          className="btn btn-primary"
                          onClick={() => void handleContinueFromCheckpoint()}
                        >
                          <Icon name="sparkles" size={14} />
                          从断点继续（跳过已完成阶段）
                        </button>
                      </div>
                    ) : null}
                  </div>
                )}
              </section>

              {/* 信息盲区提示 */}
              {session.gaps && session.gaps.length > 0 ? (
                <section className={cx("gaps-card")}>
                  <div className={cx("gaps-title")}>
                    信息盲区与受限记录（{session.gaps.length} 项）
                  </div>
                  <ul className={cx("gaps-list")}>
                    {session.gaps.map((g, idx) => (
                      <li key={`${g.platform}-${idx}`}>
                        <strong>{PLATFORM_MAP[g.platform]?.name || g.platform}</strong>
                        （{g.category}）：{g.reason}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>

            {/* 右侧：执行轨迹 / 多轮追问 / 证据账本 */}
            <aside className={`card ${cx("side-col")}`}>
              <div className={cx("tabs")} role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={sideTab === "trace"}
                  className={cx("tab-btn", { active: sideTab === "trace" })}
                  onClick={() => setSideTab("trace")}
                >
                  执行轨迹
                  <span className={cx("tab-count")}>{traceList.length}</span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={sideTab === "chat"}
                  className={cx("tab-btn", { active: sideTab === "chat" })}
                  onClick={() => setSideTab("chat")}
                >
                  多轮追问
                  <span className={cx("tab-count")}>
                    {Math.ceil(chatHistory.length / 2)}
                  </span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={sideTab === "evidence"}
                  className={cx("tab-btn", { active: sideTab === "evidence" })}
                  onClick={() => setSideTab("evidence")}
                >
                  证据账本
                  <span className={cx("tab-count")}>{evidenceList.length}</span>
                </button>
              </div>

              {sideTab === "trace" ? (
                <div className={cx("side-body")}>
                  {isRunning && liveStage ? (
                    <div className={cx("stage-live")} role="status" aria-live="polite">
                      <span className="spinner spinner-sm" />
                      <span>{liveStage}</span>
                    </div>
                  ) : null}
                  {traceList.length === 0 ? (
                    <div className="empty-state" style={{ padding: "28px 12px" }}>
                      暂无执行记录
                    </div>
                  ) : (
                    traceList.map((item, idx) => (
                      <div
                        key={idx}
                        className={cx("trace-item", {
                          err: item.status === "error",
                        })}
                      >
                        <div className={cx("trace-top")}>
                          <span>{item.title}</span>
                          <span className={cx("trace-ts")}>
                            {item.ts}
                            {item.elapsed_ms ? ` · ${item.elapsed_ms}ms` : ""}
                          </span>
                        </div>
                        <div className={cx("trace-detail")}>{item.detail}</div>
                        {item.evidence_ids?.length ? (
                          <div className={cx("chips-row")} style={{ marginTop: 6 }}>
                            {item.evidence_ids.map((eid) => (
                              <button
                                key={eid}
                                type="button"
                                className="tag"
                                style={{ border: "none", cursor: "pointer" }}
                                onClick={() => handleSelectEvidence(eid)}
                              >
                                {eid}
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
              ) : null}

              {sideTab === "chat" ? (
                <>
                  <div className={cx("side-body")}>
                    <div className={cx("chat-list")}>
                      {chatHistory.length === 0 && !streamChat ? (
                        <div
                          className="empty-state"
                          style={{ padding: "28px 12px" }}
                        >
                          <div className="empty-title">基于同一档案继续深挖</div>
                          <div>
                            例如：“深入查一下他 B 站评论区的发言风格”、“分析他网易云最常听的歌手”
                          </div>
                        </div>
                      ) : null}
                      {chatHistory.map((m, idx) => (
                        <div
                          key={idx}
                          className={cx(
                            "chat-msg",
                            m.role === "user" ? "chat-user" : "chat-assistant",
                          )}
                        >
                          {m.role === "user" ? (
                            m.content
                          ) : (
                            <MarkdownReport
                              markdown={m.content}
                              evidence={evidenceMap}
                              onSelectEvidence={handleSelectEvidence}
                            />
                          )}
                        </div>
                      ))}
                      {streamChat ? (
                        <div className={cx("chat-msg", "chat-assistant")}>
                          <MarkdownReport
                            markdown={streamChat}
                            evidence={evidenceMap}
                            onSelectEvidence={handleSelectEvidence}
                          />
                        </div>
                      ) : null}
                    </div>
                  </div>
                  <form
                    className={cx("chat-form")}
                    onSubmit={(e) => {
                      e.preventDefault();
                      void submitChat();
                    }}
                  >
                    <textarea
                      name="followup"
                      aria-label="追问内容"
                      className={`input ${cx("chat-input")}`}
                      rows={1}
                      value={chatInput}
                      disabled={isRunning || session.status === "waiting_confirm"}
                      onChange={(e) => setChatInput(e.currentTarget.value)}
                      onKeyDown={handleChatKeyDown}
                      placeholder={
                        session.status === "waiting_confirm"
                          ? "请先确认候选账号…"
                          : "继续追问或要求深挖（Enter 发送）"
                      }
                    />
                    <button
                      type="submit"
                      className="btn btn-primary btn-sm"
                      disabled={
                        isRunning ||
                        sendingChat ||
                        !chatInput.trim() ||
                        session.status === "waiting_confirm"
                      }
                      title="发送追问"
                    >
                      <Icon name="send" size={13} />
                    </button>
                  </form>
                </>
              ) : null}

              {sideTab === "evidence" ? (
                <div className={cx("side-body")}>
                  {evidenceList.length === 0 ? (
                    <div className="empty-state" style={{ padding: "28px 12px" }}>
                      暂无证据记录
                    </div>
                  ) : (
                    evidenceList.map((ev) => (
                      <div
                        key={ev.id}
                        ref={(el) => {
                          evidenceRefs.current[ev.id] = el;
                        }}
                        className={cx("ev-item", {
                          focused: focusedEvidenceId === ev.id,
                        })}
                      >
                        <div className={cx("ev-head")}>
                          <span className={cx("ev-id")}>{ev.id}</span>
                          <span className="chip">
                            {ev.platform_name || ev.platform}
                          </span>
                          <span className={cx("ev-title")}>{ev.title}</span>
                        </div>
                        <div className={cx("ev-snippet")}>{ev.snippet}</div>
                        {ev.media_urls && ev.media_urls.length > 0 ? (
                          <div className={cx("ev-media-strip")}>
                            {ev.media_urls
                              .filter((u) => u.startsWith("/api/agent/media/"))
                              .slice(0, 6)
                              .map((u, idx) => (
                                <a
                                  key={u}
                                  href={u}
                                  target="_blank"
                                  rel="noreferrer"
                                  className={cx("ev-thumb-link")}
                                  title="点击查看原图"
                                >
                                  <img
                                    src={u}
                                    alt={`${ev.title} 预览图 ${idx + 1}`}
                                    loading="lazy"
                                    className={cx("ev-thumb")}
                                  />
                                </a>
                              ))}
                          </div>
                        ) : null}
                        {(ev.url && /^https?:\/\//i.test(ev.url)) ||
                        (ev.video_url &&
                          ev.video_url.startsWith("/api/agent/media/")) ? (
                          <div className={cx("ev-links")}>
                            {ev.url && /^https?:\/\//i.test(ev.url) ? (
                              <a
                                href={ev.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                查看来源链接
                              </a>
                            ) : null}
                            {ev.video_url &&
                            ev.video_url.startsWith("/api/agent/media/") ? (
                              <a
                                href={ev.video_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                播放缓存视频
                              </a>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
              ) : null}
            </aside>
          </div>
        </>
      ) : null}
    </div>
  );
}
