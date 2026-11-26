// capture-sight.mjs — 以 100% 虚构/脱敏演示数据驱动真实 Sight 生产前端，
// 采集 styleframe 静帧 + 2x 全页纹理 + 4x 主角特写 + 元素级 cutout + live-layout.json
// 完全隔离本地 data/ 与 credentials/，零外部网络请求、零真实用户数据。
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../../..');
const videoDir = path.resolve(here, '..');
const webRoot = path.join(repoRoot, 'app', 'web');
const outDir = path.join(videoDir, 'public', 'textures', 'live');
const qaDir = path.join(videoDir, 'out', 'qa');
const layoutPath = path.join(videoDir, 'src', 'live-layout.json');

fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(qaDir, { recursive: true });
fs.mkdirSync(path.dirname(layoutPath), { recursive: true });

// 复用 frontend 已安装的 playwright
const req = createRequire(path.join(repoRoot, 'frontend', 'package.json'));
const { chromium } = req('@playwright/test');

// ---------- 原创 SVG 头像与封面（纯矢量、零外部 CDN、零真人照片） ----------
const svgAvatar = (bg1, bg2, ch) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">` +
      `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${bg1}"/><stop offset="1" stop-color="${bg2}"/></linearGradient></defs>` +
      `<rect width="160" height="160" rx="80" fill="url(#g)"/>` +
      `<circle cx="122" cy="36" r="28" fill="#ffffff" fill-opacity="0.16"/>` +
      `<text x="80" y="98" text-anchor="middle" font-family="Microsoft YaHei, PingFang SC, sans-serif" font-size="64" font-weight="700" fill="#ffffff">${ch}</text>` +
      `</svg>`
  )}`;

const svgCover = (bg1, bg2, accent, tag, headline, sub) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">` +
      `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${bg1}"/><stop offset="1" stop-color="${bg2}"/></linearGradient></defs>` +
      `<rect width="640" height="360" fill="url(#g)"/>` +
      `<circle cx="540" cy="70" r="140" fill="${accent}" fill-opacity="0.28"/>` +
      `<circle cx="110" cy="310" r="120" fill="${accent}" fill-opacity="0.18"/>` +
      `<g stroke="#ffffff" stroke-opacity="0.09" stroke-width="1">` +
      `<line x1="0" y1="90" x2="640" y2="90"/><line x1="0" y1="180" x2="640" y2="180"/><line x1="0" y1="270" x2="640" y2="270"/>` +
      `<line x1="160" y1="0" x2="160" y2="360"/><line x1="320" y1="0" x2="320" y2="360"/><line x1="480" y1="0" x2="480" y2="360"/>` +
      `</g>` +
      `<rect x="180" y="54" width="280" height="44" rx="22" fill="${accent}"/>` +
      `<text x="320" y="84" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="24" font-weight="700" fill="#ffffff">${tag}</text>` +
      `<text x="320" y="196" text-anchor="middle" font-family="Microsoft YaHei, PingFang SC, sans-serif" font-size="44" font-weight="800" fill="#ffffff">${headline}</text>` +
      `<text x="320" y="254" text-anchor="middle" font-family="Microsoft YaHei, PingFang SC, sans-serif" font-size="24" font-weight="500" fill="#cbd5e1">${sub}</text>` +
      `<rect x="230" y="294" width="180" height="8" rx="4" fill="${accent}"/>` +
      `</svg>`
  )}`;

// ---------- 本地静态文件服务器（托管 app/web 构建产物，不启动后端） ----------
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.json': 'application/json; charset=utf-8',
  '.woff2': 'font/woff2',
};

const server = http.createServer((req, res) => {
  const urlPath = (req.url || '/').split('?')[0];
  let filePath = path.join(webRoot, urlPath === '/' ? 'index.html' : urlPath);
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(webRoot, 'index.html');
  }
  const ext = path.extname(filePath).toLowerCase();
  res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
  fs.createReadStream(filePath).pipe(res);
});

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const { port } = server.address();
const BASE = `http://127.0.0.1:${port}`;
console.log('Static Sight UI server on', BASE);

// ---------- 100% 虚构演示数据集（林屿森 / linyusen-dev） ----------
const PLATFORMS = ['netease', 'bilibili', 'douyin', 'qqmusic', 'weibo', 'genshin', 'xhs', 'github'];

const DEMO_UIDS = {
  bilibili: '88421036',
  github: 'linyusen-dev',
  netease: '32984102',
  douyin: 'MS4wLjABAAAA_demo_linyusen',
  weibo: '5984210360',
  xhs: '65a0demo0000000000018842',
  qqmusic: '2840193620',
  genshin: '108421036',
};

const BILIBILI_VIDEOS = [
  {
    item_id: 'BV1SG4y1demo1',
    title: '【开源发布】用 LangGraph + ECharts 6 打造跨平台知识图谱工作台',
    view_count: 186400,
    create_time: 1795406400,
    cover_url: svgCover('#0f172a', '#1e3a8a', '#3565e0', '开源架构', 'LangGraph 图谱引擎', 'ECharts 6 · React 19 · 全栈实战'),
    extra: { bvid: 'BV1SG4y1demo1', danmaku_count: 1420, length: '14:28' },
  },
  {
    item_id: 'BV1SG4y1demo2',
    title: 'React 19 + Zustand 5 状态架构深度拆解：大型数据面板如何零卡顿',
    view_count: 124800,
    create_time: 1794801600,
    cover_url: svgCover('#111827', '#1f2937', '#fb7299', '前端工程', 'React 19 性能实战', '状态分片 · 增量渲染 · 虚拟列表'),
    extra: { bvid: 'BV1SG4y1demo2', danmaku_count: 980, length: '18:05' },
  },
  {
    item_id: 'BV1SG4y1demo3',
    title: '多模态 AI Agent 实战：如何让大模型「看图看视频」且实现零幻觉溯源',
    view_count: 243100,
    create_time: 1794196800,
    cover_url: svgCover('#0c1426', '#1e293b', '#0ea5e9', 'AI Agent', '林屿森 · 证据溯源框架', '原生多模态 · [E#] 引用校验'),
    extra: { bvid: 'BV1SG4y1demo3', danmaku_count: 2180, length: '16:42' },
  },
  {
    item_id: 'BV1SG4y1demo4',
    title: 'Python 异步爬虫池与熔断设计：AdapterPool 多凭证并发调度详解',
    view_count: 92600,
    create_time: 1793592000,
    cover_url: svgCover('#0b132b', '#1c2541', '#1e9e55', '后端架构', '多凭证租借轮询池', '限速队列 · 自动熔断 · 断点续拉'),
    extra: { bvid: 'BV1SG4y1demo4', danmaku_count: 640, length: '12:19' },
  },
  {
    item_id: 'BV1SG4y1demo5',
    title: 'SQLite 快照 Diff 算法：用 30 行代码自动反推跨平台行为时间线',
    view_count: 78300,
    create_time: 1792987200,
    cover_url: svgCover('#18181b', '#27272a', '#e6702e', '数据算法', '时序快照 Diff 引擎', '内容哈希去重 · 变更窗口推断'),
    extra: { bvid: 'BV1SG4y1demo5', danmaku_count: 512, length: '10:54' },
  },
  {
    item_id: 'BV1SG4y1demo6',
    title: 'GitHub Actions 三端自动打包：Win / Mac / Linux 免 Python 一键发布',
    view_count: 112500,
    create_time: 1792382400,
    cover_url: svgCover('#0f172a', '#312e81', '#6366f1', 'CI / CD', 'PyInstaller 三端发版', '语义化版本 · 自动化冒烟验收'),
    extra: { bvid: 'BV1SG4y1demo6', danmaku_count: 790, length: '11:36' },
  },
  {
    item_id: 'BV1SG4y1demo7',
    title: 'Server-Sent Events 实战：用环形日志缓冲打造浏览器实时运行终端',
    view_count: 68900,
    create_time: 1791777600,
    cover_url: svgCover('#0c1a2e', '#1e3a5f', '#0284c7', '实时通信', 'SSE 实时日志终端', 'log_hub 环形缓冲 · 零延迟推送'),
    extra: { bvid: 'BV1SG4y1demo7', danmaku_count: 420, length: '09:48' },
  },
  {
    item_id: 'BV1SG4y1demo8',
    title: 'Playwright 端到端全链路自动化验收：从 Mock 路由到可视化回归',
    view_count: 84200,
    create_time: 1791172800,
    cover_url: svgCover('#111827', '#1e293b', '#10b981', '工程质量', 'Vitest + Playwright', '前后端契约测试 · CI 门禁实战'),
    extra: { bvid: 'BV1SG4y1demo8', danmaku_count: 585, length: '13:12' },
  },
];

// 丰富的虚构跨平台关系图谱（22 个虚构节点 + 互关绿线 / 同名红线 / 单向蓝箭头）
const DEMO_GRAPH = (() => {
  const mk = (platform, uid, nickname, fans, signature, verified = false) => ({
    id: platform === 'keyword' ? 'keyword' : `${platform}:${uid}`,
    platform,
    uid,
    nickname,
    fans,
    signature,
    is_verified: verified,
    avatarUrl: platform === 'keyword' ? '' : svgAvatar('#3565e0', '#1d4ed8', nickname[0]),
  });
  const nodes = [
    mk('keyword', '林屿森', '林屿森', 0, '跨平台搜索核心'),
    mk('bilibili', '88421036', '林屿森', 86400, '独立全栈开发者 · 数据可视化与 AI 工具链', true),
    mk('github', 'linyusen-dev', '林屿森', 3420, 'Open-source tooling & Graph Analytics · Hangzhou'),
    mk('netease', '32984102', '林屿森', 1240, '写代码时只听氛围电子与后摇'),
    mk('douyin', 'dy_8842', '林屿森Studio', 42800, '每周拆解一个开源黑科技'),
    mk('weibo', '5984210', '林屿森_Dev', 15600, '开源项目笔记与技术随笔'),
    mk('xhs', 'xhs_8842', '林屿森的桌面', 9300, '独立开发者效率工作台分享'),
    // 核心互关圈与跨平台连接节点（100% 虚构人名）
    mk('bilibili', '90112', '江晚舟', 320, '前端图形学研究 · WebGL / ECharts'),
    mk('github', 'jiangwanzhou', '江晚舟', 280, 'Visualization & shaders'),
    mk('bilibili', '90113', '陈知遥', 410, 'AI Agent 开源贡献者'),
    mk('github', 'chenzhiyao', '陈知遥', 520, 'LangGraph / RAG systems'),
    mk('netease', '71001', '陆星河', 190, '深夜合成器歌单收藏家'),
    mk('bilibili', '90114', '陆星河', 260, '独立游戏音效设计'),
    mk('github', 'zhoumingyuan', '周明远', 340, 'Python 异步并发与数据库内核'),
    mk('weibo', '60101', '许知意', 680, '信息设计 / 交互研究'),
    mk('douyin', 'dy_902', '沈清川', 510, '开源软硬件评测'),
    mk('netease', '71002', '苏景行', 145, '后摇 & Lo-Fi 歌单维护'),
    mk('github', 'guchengfeng', '顾承风', 490, 'Rust CLI & 开发者工具'),
    mk('bilibili', '90115', '唐墨白', 820, '数据新闻可视化'),
    mk('xhs', 'xhs_903', '程书禾', 430, '产品设计系统拆解'),
    mk('qqmusic', 'qq_901', '林屿森', 180, '电子与纯音乐收藏'),
    mk('weibo', '60102', '宋以安', 370, '知识图谱算法笔记'),
  ];
  const edges = [
    // 搜索命中
    { source: 'keyword', target: 'bilibili:88421036', relation: 'hit' },
    { source: 'keyword', target: 'github:linyusen-dev', relation: 'hit' },
    { source: 'keyword', target: 'netease:32984102', relation: 'hit' },
    { source: 'keyword', target: 'douyin:dy_8842', relation: 'hit' },
    { source: 'keyword', target: 'weibo:5984210', relation: 'hit' },
    { source: 'keyword', target: 'xhs:xhs_8842', relation: 'hit' },
    { source: 'keyword', target: 'qqmusic:qq_901', relation: 'hit' },
    // 跨平台同名 / 相似归并（红线）
    { source: 'bilibili:88421036', target: 'github:linyusen-dev', relation: 'same_name' },
    { source: 'bilibili:88421036', target: 'netease:32984102', relation: 'same_name' },
    { source: 'netease:32984102', target: 'qqmusic:qq_901', relation: 'same_name' },
    { source: 'bilibili:88421036', target: 'douyin:dy_8842', relation: 'similar_name' },
    { source: 'github:linyusen-dev', target: 'weibo:5984210', relation: 'similar_name' },
    { source: 'bilibili:90112', target: 'github:jiangwanzhou', relation: 'same_name' },
    { source: 'bilibili:90113', target: 'github:chenzhiyao', relation: 'same_name' },
    { source: 'netease:71001', target: 'bilibili:90114', relation: 'same_name' },
    // 互相关注（绿粗线）
    { source: 'bilibili:88421036', target: 'bilibili:90112', relation: 'mutual' },
    { source: 'bilibili:88421036', target: 'bilibili:90113', relation: 'mutual' },
    { source: 'github:linyusen-dev', target: 'github:jiangwanzhou', relation: 'mutual' },
    { source: 'github:linyusen-dev', target: 'github:chenzhiyao', relation: 'mutual' },
    { source: 'github:linyusen-dev', target: 'github:zhoumingyuan', relation: 'mutual' },
    { source: 'netease:32984102', target: 'netease:71001', relation: 'mutual' },
    { source: 'bilibili:90112', target: 'bilibili:90115', relation: 'mutual' },
    // 单向关注（蓝箭头）
    { source: 'bilibili:88421036', target: 'bilibili:90114', relation: 'follows' },
    { source: 'bilibili:88421036', target: 'bilibili:90115', relation: 'follows' },
    { source: 'github:linyusen-dev', target: 'github:guchengfeng', relation: 'follows' },
    { source: 'weibo:5984210', target: 'weibo:60101', relation: 'follows' },
    { source: 'weibo:5984210', target: 'weibo:60102', relation: 'follows' },
    { source: 'douyin:dy_8842', target: 'douyin:dy_902', relation: 'follows' },
    { source: 'netease:32984102', target: 'netease:71002', relation: 'follows' },
    { source: 'xhs:xhs_8842', target: 'xhs:xhs_903', relation: 'follows' },
    { source: 'github:chenzhiyao', target: 'github:zhoumingyuan', relation: 'follows' },
  ];
  return {
    keyword: '林屿森',
    platforms: PLATFORMS,
    searched: PLATFORMS,
    nodes,
    edges,
    keywords: {},
  };
})();

const DEMO_TIMELINE = [
  {
    id: 101,
    platform: 'github',
    platform_name: 'GitHub',
    event_type: 'Star 仓库',
    time_str: '2026-11-26 14:22',
    time_suffix: '14:05 ~ 14:35 之间',
    summary: '新增 Star 仓库：element-17/graph-engine-rs（图谱布局加速库）',
    detail: '快照 Diff 检出：Star 列表 +1 · 语言 Rust · 关联技术栈高度吻合',
    timestamp: 1795674120,
  },
  {
    id: 102,
    platform: 'bilibili',
    platform_name: '哔哩哔哩',
    event_type: '投稿更新',
    time_str: '2026-11-26 11:40',
    time_suffix: '精确发布时间',
    summary: '发布新视频：《用 LangGraph + ECharts 6 打造跨平台知识图谱工作台》',
    detail: '14:28 · 播放 18.6 万 · 弹幕 1,420 · 标签：开源 / 全栈 / AI Agent',
    timestamp: 1795664400,
  },
  {
    id: 103,
    platform: 'netease',
    platform_name: '网易云音乐',
    event_type: '歌单变更',
    time_str: '2026-11-26 01:18',
    time_suffix: '00:50 ~ 01:25 之间',
    summary: '歌单「深夜写代码 · Synthwave」新增 3 首曲目',
    detail: '快照对比推断：连续 4 天在 00:00–02:00 区间活跃，符合深夜开发者作息',
    timestamp: 1795627080,
  },
  {
    id: 104,
    platform: 'douyin',
    platform_name: '抖音',
    event_type: '新增互关',
    time_str: '2026-11-25 22:10',
    time_suffix: '21:40 ~ 22:15 之间',
    summary: '关注列表新增「沈清川」（开源软硬件评测），并触发双端互关确认',
    detail: '关联图谱边权重更新：douyin:dy_8842 ↔ douyin:dy_902',
    timestamp: 1795615800,
  },
  {
    id: 105,
    platform: 'weibo',
    platform_name: '微博',
    event_type: '公开动态',
    time_str: '2026-11-25 19:05',
    time_suffix: '精确发布时间',
    summary: '发布技术随笔：「把 8 个平台的异步展开队列拆开做熔断，稳定性直接拉满」',
    detail: '获赞 412 · 转发 86 · 评论 53 · 来自 杭州',
    timestamp: 1795604700,
  },
];

const DEMO_AGENT_SESSION = {
  id: 'sess_demo_linyusen',
  title: '林屿森 · 跨平台多模态人物侧写',
  target_query: '林屿森',
  focus: '技术栈画像、作息规律、核心互关圈与视觉风格一致性',
  uids: {
    bilibili: '88421036',
    github: 'linyusen-dev',
    netease: '32984102',
    douyin: 'dy_8842',
    weibo: '5984210',
  },
  graph_id: 1,
  status: 'done',
  model: 'gemini-2.5-flash · 原生多模态',
  error: '',
  created_at: '2026-11-26T14:30:00+08:00',
  updated_at: '2026-11-26T14:30:18+08:00',
  has_report: true,
  running: false,
  last_seq: 6,
  report_markdown: [
    '# 实体综合侧写：林屿森（虚构演示档案）',
    '',
    '## 一、核心身份与技术画像',
    '目标为常驻杭州的**独立全栈开源创作者**，长期深耕 React / TypeScript 前端可视化与 Python AI Agent 工程化落地 [高置信][E1]。其 GitHub 与 B站投稿内容高度一致，近期主攻 LangGraph 状态机编排与 ECharts 6 大规模关系图谱渲染 [高置信][E2]。',
    '',
    '## 二、作息节律与跨平台活跃窗口',
    '基于 142 条跨平台带时间戳事件确定性统计，目标呈典型的**夜间深度研发型作息**：22:00–02:00 贡献 68.4% 有效活跃度，峰值落于 00:00–01:00，上午时段极少触发公开变更 [高置信][E3]。',
    '',
    '## 三、社交核心圈与多模态视觉基线',
    '在 21 个图谱节点中已识别 5 位高置信互关技术同行（江晚舟、陈知遥、周明远等），集中在前端图形学与 AI 基础设施领域 [高置信][E4]。多模态视觉抽检证实：其跨平台封面统一采用深蓝工程网格排版，B站视频口播节奏明快且代码演示占比超 70% [中置信][E5]。',
  ].join('\n'),
  structured: {
    profile_meta: {
      headline: '常驻杭州的独立全栈开源创作者 · 图谱可视化与 AI Agent 方向',
      tags: ['React 19 / TS', 'LangGraph Agent', '数据可视化', '夜间活跃型', '零幻觉校验'],
      confidence_overall: 'high',
      dimensions: [
        {
          key: 'identity',
          title: '技术身份定位',
          summary: 'GitHub 开源维护者 + B站硬核技术 UP 主，主攻全栈与 AI 工具链',
          confidence: 'high',
          evidence_ids: ['E1', 'E2'],
        },
        {
          key: 'chronotype',
          title: '作息与行为窗口',
          summary: '22:00–02:00 深度高频活跃（夜间占比 68.4%），CST (UTC+8)',
          confidence: 'high',
          evidence_ids: ['E3'],
        },
        {
          key: 'social',
          title: '核心互关技术圈',
          summary: '跨 B站 / GitHub / 网易云识别 5 位高紧密互关协作者',
          confidence: 'high',
          evidence_ids: ['E4'],
        },
        {
          key: 'multimodal',
          title: '原生多模态视觉基线',
          summary: 'Gemini 2.5 Flash 跨平台头像/封面/视频抽帧核验风格一致',
          confidence: 'medium',
          evidence_ids: ['E5', 'E6'],
        },
      ],
      blind_spots: [],
    },
    baseline_stats: {
      activity: {
        total_timed_events: 142,
        hourly_distribution: [18, 16, 9, 3, 1, 0, 0, 1, 2, 4, 6, 7, 5, 4, 6, 7, 6, 5, 6, 8, 10, 11, 14, 17],
        weekday_distribution: [18, 21, 19, 24, 22, 20, 18],
        peak_hours: [0, 1, 23],
        late_night_ratio: 0.684,
        chronotype: '深夜深度研发型（夜间占比 68.4%）',
        timezone_hint: 'CST (UTC+8)',
      },
      social: {
        total_nodes: 21,
        total_follow_edges: 31,
        mutual_core_contacts: [
          { id: 'bilibili:90112', platform: 'bilibili', platform_name: '哔哩哔哩', uid: '90112', nickname: '江晚舟', fans: 320, verified: false, degree: 4, relation: 'mutual' },
          { id: 'github:chenzhiyao', platform: 'github', platform_name: 'GitHub', uid: 'chenzhiyao', nickname: '陈知遥', fans: 520, verified: false, degree: 4, relation: 'mutual' },
          { id: 'github:zhoumingyuan', platform: 'github', platform_name: 'GitHub', uid: 'zhoumingyuan', nickname: '周明远', fans: 340, verified: false, degree: 3, relation: 'mutual' },
          { id: 'netease:71001', platform: 'netease', platform_name: '网易云音乐', uid: '71001', nickname: '陆星河', fans: 190, verified: false, degree: 3, relation: 'mutual' },
        ],
        followed_public_accounts: [],
      },
    },
    citation_report: {
      total_evidence: 6,
      cited_valid: ['E1', 'E2', 'E3', 'E4', 'E5', 'E6'],
      removed_invalid: [],
    },
  },
  evidence: {
    E1: { id: 'E1', platform: 'github', platform_name: 'GitHub', uid: 'linyusen-dev', category: 'profile', title: 'GitHub 主页与活跃仓库', snippet: '坐标 Hangzhou · 主力语言 TypeScript / Python / Rust · 3.4k Followers' },
    E2: { id: 'E2', platform: 'bilibili', platform_name: '哔哩哔哩', uid: '88421036', category: 'content', title: 'B站代表投稿与技术标签', snippet: '近 6 期全栈与 AI Agent 视频均播 13.9 万，高互动集中在架构拆解' },
    E3: { id: 'E3', platform: 'multi', platform_name: '确定性统计器', uid: 'multi', category: 'activity_stats', title: '24 小时跨平台作息分布', snippet: '142 条时间戳样本：峰值 00:00–01:00，深夜活跃占比 68.4%' },
    E4: { id: 'E4', platform: 'multi', platform_name: '关系图谱拓扑', uid: 'multi', category: 'social_graph', title: '核心互关圈识别（5 人）', snippet: '江晚舟 / 陈知遥 / 周明远 / 陆星河在 B站与 GitHub 双端互关' },
    E5: { id: 'E5', platform: 'multi', platform_name: '多模态视觉基线', uid: 'multi', category: 'visual_baseline', title: '跨平台封面与头像视觉核验', snippet: '统一深蓝科技网格与简洁无衬线排版，跨平台品牌一致性 96%', media_urls: ['/api/agent/media/demo_thumb_1'] },
    E6: { id: 'E6', platform: 'bilibili', platform_name: '短视频分析工具', uid: '88421036', category: 'video_inspect', title: 'inspect_video 原生看视频抽析', snippet: 'Gemini 2.5 Flash 原生解析 14 分钟开源视频：代码实操占比 72%' },
  },
  gaps: [],
  trace: [
    { ts: '14:30:01', stage: 'collect_baseline', title: '基线聚合 · 5 平台快照拉取完成', detail: '命中 30 分钟本地快照缓存，零重复风控请求', status: 'done', elapsed_ms: 145, evidence_ids: ['E1', 'E2'] },
    { ts: '14:30:03', stage: 'deterministic_stats', title: '确定性统计 · 作息与互关拓扑计算', detail: '统计 142 条行为事件与 21 节点社交图谱', status: 'done', elapsed_ms: 62, evidence_ids: ['E3', 'E4'] },
    { ts: '14:30:06', stage: 'visual_baseline', title: '多模态视觉基线 · inspect_images', detail: '比对跨平台头像与 6 张作品封面视觉特征', status: 'done', elapsed_ms: 1280, evidence_ids: ['E5'] },
    { ts: '14:30:10', stage: 'inspect_video', title: '原生短视频侦查 · inspect_video', detail: '下载并解析最新开源发布视频关键技术帧', status: 'done', elapsed_ms: 2150, evidence_ids: ['E6'] },
    { ts: '14:30:15', stage: 'synthesize_report', title: 'LangGraph 综合侧写与引用生成', detail: '输出结构化画像、维度评分与 Markdown 报告', status: 'done', elapsed_ms: 1840 },
    { ts: '14:30:18', stage: 'citation_guard', title: '零幻觉引用校验通过（6 / 6）', detail: '全部 [E1]–[E6] 溯源指针核验有效，无虚构引用', status: 'done', elapsed_ms: 18 },
  ],
  chat_history: [
    { role: 'user', content: '他的核心技术协作者主要分布在哪些平台？' },
    { role: 'assistant', content: '根据 [E4]，江晚舟与陈知遥在 B站和 GitHub 均与目标呈高置信双端互关，属于核心研发协作圈。' },
  ],
};

const DEMO_LOGS = [
  { seq: 1, boot: 'demo', ts: '14:28:12', source: 'bilibili', level: 'info', text: 'AdapterPool 租借凭证 primary · 拉取 UID 88421036 资料与 6 条投稿 (210ms)' },
  { seq: 2, boot: 'demo', ts: '14:28:14', source: 'github', level: 'info', text: 'GitHub REST v3 命中 30 分钟快照 TTL · 直接复用本地 SQLite 快照' },
  { seq: 3, boot: 'demo', ts: '14:28:17', source: 'graph', level: 'info', text: '跨平台实体归并完成：命中 7 平台同名/相似账号，构建 21 节点 / 31 条关系边' },
  { seq: 4, boot: 'demo', ts: '14:28:19', source: 'netease', level: 'info', text: '异步展开队列 [netease] 限速 1.2s/次 · 互关检出 陆星河 (skip=0)' },
  { seq: 5, boot: 'demo', ts: '14:28:22', source: 'douyin', level: 'info', text: '异步展开队列 [douyin] 串行锁保护中 · 连续失败 0/5 · 状态正常' },
  { seq: 6, boot: 'demo', ts: '14:28:25', source: 'timeline', level: 'info', text: '快照集合 Diff 完成：检出 5 条跨时段新增行为，幂等写入 SQLite' },
  { seq: 7, boot: 'demo', ts: '14:28:29', source: 'agent', level: 'info', text: 'LangGraph StateGraph 校验通过：有效图文证据 6/6，零幻觉' },
];

const DEMO_QUEUES = [
  { platform: 'bilibili', pending: 1, running: 1, paused: false, accounts: 2, interval: 1.0, running_tasks: [{ id: 1, uid: '88421036', nickname: '林屿森', accounts: ['主账号'] }], pending_tasks: [{ id: 2, uid: '90112', nickname: '江晚舟' }] },
  { platform: 'github', pending: 0, running: 1, paused: false, accounts: 1, interval: 0.5, running_tasks: [{ id: 3, uid: 'linyusen-dev', nickname: '林屿森', accounts: ['Token池'] }], pending_tasks: [] },
  { platform: 'netease', pending: 0, running: 0, paused: false, accounts: 2, interval: 0.8, running_tasks: [], pending_tasks: [] },
  { platform: 'douyin', pending: 0, running: 0, paused: false, accounts: 1, interval: 2.0, running_tasks: [], pending_tasks: [] },
];

async function installDemoRoutes(page) {
  await page.addInitScript((uids) => {
    localStorage.setItem('sight_uids', JSON.stringify(uids));
    class MockEventSource {
      static CLOSED = 2;
      readyState = 2;
      constructor() {
        queueMicrotask(() => this.onerror?.(new Event('error')));
      }
      close() {}
    }
    window.EventSource = MockEventSource;
  }, DEMO_UIDS);

  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname.replace(/^\/api/, '');

    if (p.startsWith('/agent/media/')) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180"><defs><linearGradient id="m" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f172a"/><stop offset="1" stop-color="#1e3a8a"/></linearGradient></defs><rect width="320" height="180" rx="10" fill="url(#m)"/><circle cx="240" cy="48" r="54" fill="#3565e0" fill-opacity="0.35"/><text x="24" y="88" font-family="Microsoft YaHei, sans-serif" font-size="22" font-weight="700" fill="#fff">视觉基线核验 · 96%</text><text x="24" y="122" font-family="Consolas, monospace" font-size="14" fill="#93c5fd">GEMINI-2.5-FLASH MULTIMODAL</text></svg>`;
      await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: svg });
      return;
    }

    let data = {};
    if (p === '/platforms') {
      data = PLATFORMS.map((id) => ({
        id,
        name: id,
        has_credential: true,
        is_alive: true,
        login_user: { uid: DEMO_UIDS[id], nickname: '林屿森' },
      }));
    } else if (p.endsWith('/all')) {
      const id = p.split('/')[1];
      data = {
        profile: {
          platform: id,
          uid: DEMO_UIDS[id] || '88421036',
          nickname: '林屿森',
          avatar_url: svgAvatar('#3565e0', '#1d4ed8', '林'),
          level: 6,
          is_vip: true,
          vip_label: id === 'bilibili' ? '年度大会员 · 开源作者' : '认证开发者',
          signature: '独立全栈开发者 · 专注多源数据图谱可视化与 AI Agent 工具链（虚构演示账号）',
          location: '浙江 · 杭州',
          join_time: 1584201600,
          extra: {
            follower_count: 86400,
            following_count: 128,
            video_count: 1420000,
            likes: 318000,
            followeds: 1240,
            follows: 96,
            listenSongs: 6420,
            createdPlaylistCount: 18,
            eventCount: 84,
            official: '开源工具作者 · 科技区 UP 主',
          },
        },
        playlists: BILIBILI_VIDEOS,
        records: { allTime: [], weekly: [] },
        events: [
          { event_id: 'ev1', event_type: '投稿动态', content: 'Sight v1.4 正式集成 LangGraph 原生多模态人物侧写，支持 Gemini / Claude / OpenAI 零幻觉证据溯源！', timestamp: 1795664400 },
          { event_id: 'ev2', event_type: '开源发布', content: 'GitHub Actions 三端独立包已自动发版，Win / Mac / Linux 解压双击即用，免装 Python 环境。', timestamp: 1795578000 },
        ],
        follows: [
          { uid: '90112', nickname: '江晚舟', avatarUrl: svgAvatar('#0ea5e9', '#2563eb', '江'), signature: '前端图形学研究' },
          { uid: '90113', nickname: '陈知遥', avatarUrl: svgAvatar('#10b981', '#059669', '陈'), signature: 'AI Agent 开源贡献者' },
          { uid: '90114', nickname: '陆星河', avatarUrl: svgAvatar('#6366f1', '#4f46e5', '陆'), signature: '独立音效设计' },
        ],
        followers: [
          { uid: '90115', nickname: '唐墨白', avatarUrl: svgAvatar('#f59e0b', '#d97706', '唐'), signature: '数据新闻可视化' },
        ],
        _errors: [],
      };
    } else if (p === '/timeline') {
      data = DEMO_TIMELINE;
    } else if (p === '/graph/search') {
      data = DEMO_GRAPH;
    } else if (p === '/graph/saved') {
      data = [
        { id: 1, name: '林屿森 · 8平台社交图谱', keyword: '林屿森', node_count: 21, edge_count: 31, updated_at: '2026-11-26T14:28:00' },
      ];
    } else if (p === '/graph/saved/1') {
      data = { id: 1, name: '林屿森 · 8平台社交图谱', data: DEMO_GRAPH };
    } else if (p === '/graph/expand/status') {
      data = { queues: DEMO_QUEUES };
    } else if (p === '/graph/expand/results') {
      data = { results: [], pending: 0, cursor: 0, paused: [] };
    } else if (p === '/logs/recent') {
      data = { entries: DEMO_LOGS, last_seq: DEMO_LOGS.length };
    } else if (p === '/agent/config') {
      data = {
        provider: 'gemini',
        base_url: '',
        model: 'gemini-2.5-flash',
        temperature: 0.2,
        max_steps: 8,
        timeout: 90,
        enable_multimodal: true,
        supports_vision: true,
        supports_video: true,
        has_api_key: true,
        api_key_preview: 'AIza...demo',
        api_key_source: 'file',
        is_local: false,
        configured: true,
        presets: [],
      };
    } else if (p === '/agent/sessions') {
      data = [DEMO_AGENT_SESSION];
    } else if (p.startsWith('/agent/sessions/')) {
      data = DEMO_AGENT_SESSION;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data }) });
  });
}

const boxOf = (el) =>
  el.evaluate((e) => {
    const r = e.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  });

const browser = await chromium.launch({ headless: true });

try {
  // ───────── 0. Styleframe 截图验收（3 张 1920×1080） ─────────
  const sfCtx = await browser.newContext({ viewport: { width: 1984, height: 1144 }, deviceScaleFactor: 1 });
  const sfPage = await sfCtx.newPage();
  await sfPage.goto(`file:///${path.join(videoDir, 'styleframe.html').replace(/\\/g, '/')}`, { waitUntil: 'networkidle' });
  await sfPage.evaluate(() => document.fonts.ready);
  const sfFrames = await sfPage.$$('.frame');
  for (let i = 0; i < sfFrames.length; i++) {
    await sfFrames[i].screenshot({ path: path.join(qaDir, `styleframe-${i + 1}.png`) });
  }
  await sfCtx.close();
  console.log('Captured 3 styleframes');

  // ───────── 1. 主 2x 采集上下文（1920×1080 @2x） ─────────
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await installDemoRoutes(page);

  const settle = async (ms = 700) => {
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(ms);
  };

  const layout = { pageW: 1920, pageH: 1080 };

  // ====== PAGE 1: B站平台档案页 (/bilibili) ======
  await page.goto(`${BASE}/#/bilibili`, { waitUntil: 'networkidle' });
  await settle(900);
  await page.screenshot({ path: path.join(outDir, 'platform-full.png') });

  const sidebarEl = await page.$('aside[class*="app-sidebar"]');
  const topbarEl = await page.$('header, [class*="topbar"]');
  const searchEl = await page.$('[class*="sb-field"]');
  const profileEl = await page.$('[class*="profile"].card, .card[class*="profile"]');
  const cardEls = await page.$$('[class*="citem"]');

  const pEntry = {
    pageH: 1080,
    sidebar: sidebarEl ? await boxOf(sidebarEl) : null,
    topbar: topbarEl ? await boxOf(topbarEl) : null,
    search: searchEl ? await boxOf(searchEl) : null,
    profile: profileEl ? await boxOf(profileEl) : null,
    cards: [],
  };

  if (sidebarEl) await sidebarEl.screenshot({ path: path.join(outDir, 'sidebar.png') });
  if (topbarEl) await topbarEl.screenshot({ path: path.join(outDir, 'topbar.png') });
  if (searchEl) await searchEl.screenshot({ path: path.join(outDir, 'float-search.png'), omitBackground: true });
  if (profileEl) await profileEl.screenshot({ path: path.join(outDir, 'profile-card.png'), omitBackground: true });

  for (let i = 0; i < Math.min(cardEls.length, 8); i++) {
    const bb = await boxOf(cardEls[i]);
    const file = `card${i + 1}.png`;
    await cardEls[i].screenshot({ path: path.join(outDir, file), omitBackground: true });
    pEntry.cards.push({ file, ...bb });
  }

  // 空底板（隐藏内容卡，供 type-and-filter 飞出/滑位）
  await page.evaluate(() => {
    document.querySelectorAll('[class*="citem"]').forEach((el) => { el.style.visibility = 'hidden'; });
  });
  await page.screenshot({ path: path.join(outDir, 'platform-empty.png') });
  await page.evaluate(() => {
    document.querySelectorAll('[class*="citem"]').forEach((el) => { el.style.visibility = ''; });
  });
  layout.platform = pEntry;
  console.log('Captured platform:', pEntry.cards.length, 'cards, profile:', pEntry.profile);

  // ====== 4x 主角特写单独采集（Q2 铁律：特写卡 4x 原生栅格化） ======
  const ctx4 = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 4 });
  const page4 = await ctx4.newPage();
  await installDemoRoutes(page4);
  await page4.goto(`${BASE}/#/bilibili`, { waitUntil: 'networkidle' });
  await page4.evaluate(() => document.fonts.ready);
  await page4.waitForTimeout(800);
  const profile4 = await page4.$('[class*="profile"].card, .card[class*="profile"]');
  if (profile4) {
    await profile4.screenshot({ path: path.join(outDir, 'profile-card-hires.png'), omitBackground: true });
    console.log('Captured 4x profile-card-hires.png');
  }
  await ctx4.close();

  // ====== PAGE 2: 社交关系图谱 (/graph) + 实时 SSE 终端 ======
  await page.evaluate(() => localStorage.setItem('sight_terminal_open', '1'));
  await page.goto(`${BASE}/#/graph`, { waitUntil: 'networkidle' });
  await settle(700);
  // 点击左侧已保存图谱「林屿森 · 8平台社交图谱」直接调出完整 22 节点图谱
  const savedGraphBtn = page.getByText('林屿森 · 8平台社交图谱').first();
  if (await savedGraphBtn.count()) {
    await savedGraphBtn.click();
  } else {
    const kwInput = page.locator('input[placeholder*="关键词"]').first();
    if (await kwInput.count()) {
      await kwInput.fill('林屿森');
      await kwInput.press('Enter');
    }
  }
  // 等 ECharts 6 力导图稳定展开
  await settle(2600);
  // 打开实时终端面板（确保可见）
  const termBtn = page.locator('button[title*="日志"], button[title*="终端"]').first();
  const termOpen = await page.$('[class*="terminal-panel"][class*="open"]');
  if (!termOpen && (await termBtn.count())) {
    await termBtn.click();
    await settle(500);
  }
  await page.screenshot({ path: path.join(outDir, 'graph-full.png') });

  const graphToolbarEl = await page.$('[class*="vg-toolbar"], [class*="toolbar"]');
  const graphStatusEl = await page.$('[class*="vg-status"], [class*="status"]');
  const graphCanvasEl = await page.$('[class*="vg-stage"]');
  const termEl = await page.$('[class*="terminal-panel"]');
  if (termEl) {
    try { await termEl.screenshot({ path: path.join(outDir, 'terminal-panel.png'), omitBackground: true }); } catch {}
  }
  if (graphCanvasEl) {
    try { await graphCanvasEl.screenshot({ path: path.join(outDir, 'graph-stage.png') }); } catch {}
  }
  layout.graph = {
    pageH: 1080,
    toolbar: graphToolbarEl ? await boxOf(graphToolbarEl) : null,
    status: graphStatusEl ? await boxOf(graphStatusEl) : null,
    stage: graphCanvasEl ? await boxOf(graphCanvasEl) : null,
    terminal: termEl ? await boxOf(termEl) : null,
  };
  console.log('Captured graph:', layout.graph);

  // 关闭终端面板，拍干净的 Timeline 和 Agent
  if (await page.$('[class*="terminal-panel"][class*="open"]')) {
    const closeBtn = await page.$('[class*="t-close"]');
    if (closeBtn) { await closeBtn.click(); await settle(400); }
  }
  await page.evaluate(() => localStorage.setItem('sight_terminal_open', '0'));

  // ====== PAGE 3: 时序快照 Diff 时间线 (/timeline) ======
  await page.goto(`${BASE}/#/timeline`, { waitUntil: 'networkidle' });
  await settle(900);
  await page.screenshot({ path: path.join(outDir, 'timeline-full.png') });

  const tlEls = await page.$$('[class*="tl-entry"]');
  const tlCards = [];
  for (let i = 0; i < Math.min(tlEls.length, 5); i++) {
    const bb = await boxOf(tlEls[i]);
    const file = `tl${i + 1}.png`;
    await tlEls[i].screenshot({ path: path.join(outDir, file) });
    tlCards.push({ file, ...bb });
  }
  layout.timeline = { pageH: 1080, entries: tlCards };
  console.log('Captured timeline:', tlCards.length, 'entries');

  // ====== PAGE 4: LangGraph 多模态 AI 人物侧写 (/agent) ======
  await page.goto(`${BASE}/#/agent`, { waitUntil: 'networkidle' });
  await settle(700);
  // 点击左侧已保存侧写档案「林屿森 · 跨平台多模态人物侧写」
  const savedAgentBtn = page.getByText('林屿森 · 跨平台多模态人物侧写').first();
  if (await savedAgentBtn.count()) {
    await savedAgentBtn.click();
    await settle(1100);
  }
  // 切换右侧面板到「证据账本」以便清晰展示图文证据 + 多模态缩略图
  const evTab = page.getByRole('tab', { name: /证据账本/ }).first();
  if (await evTab.count()) {
    await evTab.click();
    await settle(600);
  }
  // 滚动 .app-content 使 session-bar 紧贴顶栏下方，无多余白边露出
  await page.evaluate(() => {
    const main = document.querySelector('.app-content');
    if (main) main.scrollTop = 94;
  });
  await settle(500);
  await page.screenshot({ path: path.join(outDir, 'agent-full.png') });

  // 提取 Agent 页面中栏核心块坐标 + 左栏 + 右栏（供 document-typewriter-reveal）
  const agentMetrics = await page.evaluate(() => {
    const box = (el) => {
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    };
    const leftRail = document.querySelector('aside[class*="app-sidebar"]');
    const rightRail = document.querySelector('aside[class*="side-col"]');
    const mainCol = document.querySelector('[class*="main-col"]');
    const reportCard = document.querySelector('[class*="report-card"]');
    const metaCard = document.querySelector('[class*="meta-card"]');
    const blocks = [];
    if (mainCol) {
      const sels = '[class*="headline"], [class*="dim-item"], h1, h2, h3, p, li';
      for (const el of mainCol.querySelectorAll(sels)) {
        const b = box(el);
        if (b.w > 40 && b.h > 10 && b.y >= 56 && b.y + b.h <= 1075) {
          blocks.push({ ...b, tag: el.tagName.toLowerCase() });
        }
      }
    }
    const evCards = [];
    const sideBody = rightRail ? rightRail.querySelector('[class*="side-body"]') : null;
    if (sideBody) {
      for (const el of sideBody.children) {
        const b = box(el);
        if (b.w > 80 && b.h > 30 && b.y >= 56 && b.y <= 1070) {
          evCards.push(b);
        }
      }
    }
    return {
      leftRail: leftRail ? box(leftRail) : { x: 0, y: 0, w: 228, h: 1080 },
      rightRail: rightRail ? box(rightRail) : { x: 1394, y: 140, w: 360, h: 700 },
      metaCard: metaCard ? box(metaCard) : null,
      reportCard: reportCard ? box(reportCard) : null,
      blocks: blocks.slice(0, 18),
      evCards: evCards.slice(0, 6),
    };
  });

  // 逐条截取右侧证据卡片 cutout，供 S6 证据落轨动画直接复用真实 UI
  const evEls = await page.$$('aside[class*="side-col"] [class*="side-body"] > *');
  for (let i = 0; i < Math.min(evEls.length, 6); i++) {
    const file = `ev${i + 1}.png`;
    try {
      await evEls[i].screenshot({ path: path.join(outDir, file) });
      if (agentMetrics.evCards[i]) agentMetrics.evCards[i].file = file;
    } catch {}
  }

  // 截取 AI 画像概览卡 & 右侧证据账本栏供收尾合影使用
  const metaEl = await page.$('[class*="meta-card"]');
  if (metaEl) await metaEl.screenshot({ path: path.join(outDir, 'agent-meta.png'), omitBackground: true });
  const sideEl = await page.$('aside[class*="side-col"]');
  if (sideEl) await sideEl.screenshot({ path: path.join(outDir, 'agent-evidence.png'), omitBackground: true });

  layout.agent = { pageH: 1080, ...agentMetrics };
  console.log('Captured agent:', agentMetrics.blocks.length, 'blocks,', agentMetrics.evCards.length, 'evCards');

  fs.writeFileSync(layoutPath, JSON.stringify(layout, null, 2), 'utf-8');
  console.log('Wrote layout JSON:', layoutPath);
  await ctx.close();
} finally {
  await browser.close();
  server.close();
}
