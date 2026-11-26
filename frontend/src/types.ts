export type PlatformId =
  | "netease"
  | "bilibili"
  | "douyin"
  | "qqmusic"
  | "weibo"
  | "genshin"
  | "xhs"
  | "github";
export type ViewId = PlatformId | "timeline" | "graph" | "agent";
export type Numeric = number | string;
export interface Stat {
  label: string;
  value: string;
}
export interface ProfileExtra extends Record<string, unknown> {
  followeds?: Numeric;
  follows?: Numeric;
  listenSongs?: Numeric;
  createdPlaylistCount?: Numeric;
  eventCount?: Numeric;
  official?: string;
  follower_count?: Numeric;
  following_count?: Numeric;
  video_count?: Numeric;
  likes?: Numeric;
  unique_id?: string;
  aweme_count?: Numeric;
  total_favorited?: Numeric;
  source?: string;
  fan_count?: Numeric;
  mFansNum?: Numeric;
  follow_count?: Numeric;
  mFollowNum?: Numeric;
  fans_count?: Numeric;
  weibo_count?: Numeric;
  server_name?: string;
  world_level?: Numeric;
  achievements?: Numeric;
  abyss_floor?: Numeric;
  abyss_room?: Numeric;
  characters_count?: Numeric;
  red_id?: string;
  fans?: Numeric;
  interaction?: Numeric;
  notes_count?: Numeric;
  login?: string;
  followers?: Numeric;
  following?: Numeric;
  public_repos?: Numeric;
  public_gists?: Numeric;
  company?: string;
  blog?: string;
}
export interface Profile {
  platform: PlatformId;
  uid: string;
  nickname: string;
  avatar_url?: string;
  background_url?: string;
  signature?: string;
  gender?: number;
  birthday?: string;
  location?: string;
  join_time?: Numeric;
  level: number;
  is_vip?: boolean;
  vip_label?: string;
  extra?: ProfileExtra;
}
export interface User {
  uid: string;
  nickname?: string;
  avatarUrl?: string;
  avatar_url?: string;
  signature?: string;
  sec_uid?: string;
  uin?: string;
  desc?: string;
}
export interface ContentExtra extends Record<string, unknown> {
  bvid?: string;
  danmaku_count?: Numeric;
  length?: string;
  digg_count?: Numeric;
  comment_count?: Numeric;
  duration?: Numeric;
  source?: string;
  reposts_count?: Numeric;
  comments_count?: Numeric;
  attitudes_count?: Numeric;
  is_retweet?: boolean;
  level?: Numeric;
  element?: string;
  constellation?: Numeric;
  weapon_name?: string;
  weapon_level?: Numeric;
  full_name?: string;
  language?: string;
  stargazers_count?: Numeric;
  forks_count?: Numeric;
  fork?: boolean;
}
export interface ContentItem {
  item_id: string;
  title?: string;
  cover_url?: string;
  count?: number;
  view_count?: number;
  creator?: string;
  description?: string;
  is_owner?: boolean;
  create_time?: Numeric;
  url?: string;
  extra?: ContentExtra;
}
export interface MediaEntry {
  entry_id?: string;
  title: string;
  artist_or_uploader?: string;
  album_or_category?: string;
  cover_url?: string;
  duration?: Numeric;
  play_count?: Numeric;
}
export interface ContentDetail {
  title?: string;
  count?: number;
  viewCount?: number;
  subscribedCount?: number;
  description?: string;
  items?: Array<{
    id?: string;
    title?: string;
    artist?: string;
    singer?: string;
    album?: string;
    duration?: Numeric;
  }>;
}
export interface ActivityEvent {
  event_id?: string;
  event_type?: string;
  content?: string;
  timestamp?: Numeric;
  media_title?: string;
  media_artist?: string;
  url?: string;
  extra?: { pics?: string[] } & Record<string, unknown>;
}
export interface PlatformPayload {
  profile: Profile | null;
  playlists: ContentItem[];
  records: { allTime?: MediaEntry[]; weekly?: MediaEntry[] } | null;
  events: ActivityEvent[];
  follows: User[];
  followers: User[];
  _errors?: string[];
}
export interface PlatformData extends Omit<PlatformPayload, "_errors"> {
  loading: boolean;
  loaded: boolean;
  fetchedAt: Date | null;
  error: string;
  errors: string[];
}
export interface PlatformMeta {
  id: PlatformId;
  name: string;
  has_credential: boolean;
  is_alive: boolean;
  login_user?: { uid: string; nickname?: string } | null;
}
export interface PlatformConfig {
  id: PlatformId;
  name: string;
  color: string;
  searchPlaceholder: string;
  uidHint: string;
  contentLabel: string;
  contentKind: "playlist" | "video" | "work" | "post" | "character" | "note";
  hasDetail: boolean;
  hasRecords: boolean;
  hasEvents: boolean;
  hasSocial: boolean;
  /** 图谱是否支持自动展开社交关系（默认同 hasSocial；搜索仅返回加密 uin 等受限平台可显式置 false） */
  graphSocial?: boolean;
  hasQrLogin?: boolean;
  looksLikeUid: (value: string) => boolean;
  resultUid: (user: User) => string;
  itemLink: (item: Pick<ContentItem, "item_id" | "extra">) => string;
  userLink?: (node: Pick<GraphNode, "uid" | "sec_uid">) => string;
  vipLabel?: (profile: Profile) => string;
  metaLine: (profile: Profile) => string[];
  stats: (profile: Profile) => Stat[];
}
export interface TimelineEntry {
  id?: number;
  platform: PlatformId;
  platform_name?: string;
  summary: string;
  detail?: string;
  timestamp?: Numeric;
  created_at?: string;
  time_str?: string;
  time_suffix?: string;
  event_type?: string;
  content_type?: string;
  type?: string;
}
export interface TimelineState {
  loading: boolean;
  loaded: boolean;
  error: string;
  source: "live" | "stored";
  entries: TimelineEntry[];
  fetchedAt: Date | null;
}
export interface CredentialStatus {
  has_credential: boolean;
  cookie_keys: string[];
}
export interface Account extends CredentialStatus {
  id: string;
  name: string;
  enabled: boolean;
  primary: boolean;
}
export interface AccountsResponse {
  accounts: Account[];
  pool_size: number;
}
export interface AccountTest {
  ok: boolean;
  login_user?: { uid?: string; nickname?: string };
  warning?: string;
  error?: string;
  latency_ms: number;
}
export interface QrStatus {
  status: string;
  qr_code?: string;
  error?: string;
  follow_data?: { count?: number; follows?: User[]; all_text_lines?: string[] };
}
export interface CacheStats {
  adapters_dropped?: number;
  cleared?: Record<string, number>;
  search_cache_cleared?: number;
}
export interface GraphNode extends Record<string, unknown> {
  id: string;
  platform: PlatformId | "keyword";
  uid: string;
  nickname: string;
  avatarUrl?: string;
  sec_uid?: string;
  signature?: string;
  fans?: Numeric;
  verified?: boolean;
  x?: number;
  y?: number;
}
export interface GraphEdge extends Record<string, unknown> {
  source: string;
  target: string;
  relation: string;
}
export interface ExpandProgress {
  followsLoaded: number;
  followsMore: boolean;
  followsTotal: number | null;
  followersLoaded: number;
  followersMore: boolean;
  followersTotal: number | null;
}
export interface GraphData extends Record<string, unknown> {
  keyword: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  platforms: string[];
  searched?: string[];
  errors?: Record<string, string>;
  cached?: string[];
  keywords?: Partial<Record<PlatformId, string>>;
  expanded_keys?: string[];
  interchecked_ids?: string[];
  hidden_ids?: string[];
  expand_prog?: Record<string, ExpandProgress>;
}
export interface SavedGraphMeta {
  id: number;
  name: string;
  keyword: string;
  node_count: number;
  edge_count: number;
  updated_at: string;
}
export interface SavedGraph extends SavedGraphMeta {
  data: GraphData;
}
export interface PausedQueue {
  platform: string;
  reason: string;
}
export interface ExpandItem {
  platform: string;
  uid: string;
  nickname?: string;
  follows_limit: number;
  followers_limit: number;
  follows_skip?: number;
  followers_skip?: number;
  known_ids?: string[];
  intercheck_skip?: string[];
  intercheck_extra?: string[];
  intercheck_limit?: number;
  intercheck_follow_limit?: number;
}
export interface EnqueueStats {
  queued: number;
  duplicates: number;
  rejected: number;
  paused?: PausedQueue[];
  task_ids?: number[];
  error?: string;
}
export interface ExpandPayload {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  errors?: Record<string, string>;
  intercheck?: {
    edges?: GraphEdge[];
    targets?: string[];
    checked?: number;
    total?: number;
  };
  counts?: {
    follows?: number;
    followers?: number;
    follows_offset?: number;
    followers_offset?: number;
    follows_more?: boolean;
    followers_more?: boolean;
    follows_total?: number;
    followers_total?: number;
  };
}
export interface ExpandTask {
  id: number;
  platform: string;
  uid: string;
  nickname?: string;
  status: string;
  error?: string;
  dirs?: { follows?: boolean; followers?: boolean };
  result?: ExpandPayload | null;
  accounts?: string[];
  account_map?: {
    follows?: string[];
    followers?: string[];
    intercheck?: string[];
  };
}
export interface QueueStatus {
  platform: string;
  pending: number;
  running: number;
  paused: boolean;
  pause_reason?: string;
  tasks?: ExpandTask[];
  running_tasks?: ExpandTask[];
  pending_tasks?: ExpandTask[];
  pool_size?: number;
  accounts_in_use?: number;
  accounts?: number;
  interval?: number;
}
export interface QueueResults {
  results: ExpandTask[];
  cursor: number;
  pending: number;
  paused: PausedQueue[];
}
export interface LogEntry {
  seq: number;
  boot: string;
  ts: string;
  text: string;
  source?: string;
  level?: string;
}
export interface LogResponse {
  entries: LogEntry[];
  last_seq?: number;
}
export type LlmProvider = "openai_compatible" | "gemini" | "anthropic";
export interface LlmModelOption {
  id: string;
  name?: string;
  owned_by?: string;
}
export interface LlmModelsResult {
  ok: boolean;
  provider?: LlmProvider;
  base_url?: string;
  count: number;
  models: LlmModelOption[];
  latency_ms: number;
  error?: string;
}
export interface LlmPreset {
  id: string;
  name: string;
  provider?: LlmProvider;
  base_url: string;
  model: string;
}
export interface LlmConfig {
  provider: LlmProvider;
  base_url: string;
  model: string;
  temperature: number;
  max_steps: number;
  timeout: number;
  enable_multimodal: boolean;
  supports_vision?: boolean;
  supports_video?: boolean;
  has_api_key: boolean;
  api_key_preview: string;
  api_key_source: string;
  is_local: boolean;
  configured: boolean;
  presets: LlmPreset[];
}
export interface LlmTestResult {
  ok: boolean;
  provider?: LlmProvider;
  model: string;
  base_url: string;
  supports_video?: boolean;
  latency_ms: number;
  reply_preview?: string;
  error?: string;
}
export interface AgentEvidenceItem {
  id: string;
  platform: string;
  platform_name?: string;
  uid?: string;
  category: string;
  title: string;
  snippet: string;
  url?: string;
  timestamp?: string;
  media_urls?: string[];
  video_url?: string;
}
export interface AgentGapItem {
  platform: string;
  category: string;
  reason: string;
  error_kind?: string;
}
export interface AgentTraceItem {
  ts: string;
  stage: string;
  tool?: string;
  title: string;
  detail: string;
  status: string;
  elapsed_ms?: number;
  evidence_ids?: string[];
}
export interface AgentCandidate {
  id: string;
  platform: PlatformId;
  platform_name: string;
  uid: string;
  nickname: string;
  avatarUrl?: string;
  signature?: string;
  fans?: Numeric;
  verified?: boolean;
  similarity?: number;
  cross_platform_hits?: number;
  confidence: number;
  recommended: boolean;
}
export interface AgentPendingInterrupt {
  type: string;
  query?: string;
  message?: string;
  candidates?: AgentCandidate[];
}
export interface AgentActivityStats {
  total_timed_events: number;
  hourly_distribution: number[];
  weekday_distribution: Array<{ day: string; count: number }>;
  peak_hours: number[];
  late_night_ratio: number;
  chronotype: string;
  timezone_hint: string;
  date_span?: { earliest: string; latest: string };
  platform_activity?: Array<{
    platform: string;
    platform_name: string;
    count: number;
  }>;
  top_artists?: Array<{ name: string; score: number }>;
  top_languages?: Array<{ name: string; count: number }>;
  locations?: string[];
}
export interface AgentSocialContact {
  id: string;
  platform: string;
  platform_name: string;
  uid: string;
  nickname: string;
  fans: number;
  verified: boolean;
  signature?: string;
  degree: number;
  relation: string;
}
export interface AgentSocialStats {
  total_nodes: number;
  total_follow_edges: number;
  mutual_core_contacts: AgentSocialContact[];
  followed_public_accounts: AgentSocialContact[];
  notable_neighbors?: AgentSocialContact[];
  cross_platform_links?: Array<{ relation: string; a: string; b: string }>;
}
export interface AgentProfileMeta {
  headline?: string;
  tags?: string[];
  confidence_overall?: string;
  dimensions?: Array<{
    key?: string;
    title: string;
    summary: string;
    confidence?: string;
    evidence_ids?: string[];
  }>;
  blind_spots?: string[];
}
export interface AgentPrunedCandidate {
  id: string;
  platform: string;
  platform_name: string;
  uid: string;
  nickname: string;
  fans: number;
  verified: boolean;
  signature?: string;
  relation: string;
  triangle_links?: number;
  probed?: boolean;
  score: number;
  reasons: string[];
}
export interface AgentPrunedGraph {
  total_nodes: number;
  total_edges: number;
  triangle_edges_count: number;
  pruned_summary?: {
    total_pruned: number;
    by_reason: Record<string, number>;
    samples?: Array<{ id: string; nickname: string; reason: string; fans?: number }>;
  };
  core_circle: AgentPrunedCandidate[];
  saved_graph_id?: number | null;
  saved_graph_name?: string;
}
export interface AgentStructured {
  profile_meta?: AgentProfileMeta;
  baseline_stats?: {
    activity?: AgentActivityStats;
    social?: AgentSocialStats;
    graph_id?: number | null;
    graph_name?: string;
    timeline_count?: number;
  };
  pruned_graph?: AgentPrunedGraph;
  citation_report?: {
    total_evidence: number;
    cited_valid: string[];
    removed_invalid: string[];
  };
  candidate_accounts?: AgentCandidate[];
  pending_interrupt?: AgentPendingInterrupt;
}
export interface AgentChatMessage {
  role: "user" | "assistant";
  content: string;
  ts?: string;
}
export type AgentStatus =
  | "idle"
  | "running"
  | "waiting_confirm"
  | "done"
  | "failed"
  | "cancelled";
export interface AgentSessionMeta {
  id: string;
  title: string;
  target_query: string;
  focus: string;
  uids: Record<string, string>;
  graph_id: number | null;
  status: AgentStatus;
  model: string;
  error: string;
  created_at: string;
  updated_at: string;
  has_report?: boolean;
  running?: boolean;
}
export interface AgentSessionDetail extends AgentSessionMeta {
  report_markdown: string;
  structured: AgentStructured;
  evidence: Record<string, AgentEvidenceItem>;
  gaps: AgentGapItem[];
  trace: AgentTraceItem[];
  chat_history: AgentChatMessage[];
  last_seq?: number;
  can_resume?: boolean;
  resume_nodes?: string[];
}
export interface AgentStreamEvent {
  seq: number;
  ts: string;
  type: string;
  stage?: string;
  label?: string;
  tool?: string;
  delta?: string;
  message?: string;
  answer?: string;
  item?: AgentTraceItem;
  stats?: AgentStructured["baseline_stats"];
  new_evidence?: Record<string, AgentEvidenceItem>;
  payload?: AgentPendingInterrupt;
  session?: AgentSessionDetail;
}
export interface AgentEventsResponse {
  entries: AgentStreamEvent[];
  last_seq: number;
  running: boolean;
}
