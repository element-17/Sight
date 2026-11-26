// timeline.ts — Sight B站宣传片单一事实源（所有镜头边界、转场、字幕与 SFX 均由此派生）
// BGM 源分析真值来自 analysis/beat_data.json（house-vibez.mp3, Mixkit Free License）

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

// 源音乐节拍网格真值（永不掺入渲染偏移，审计基准见 analysis/beat_data.json）
export const SOURCE_BEAT0 = 0.066905; // 秒
export const BEAT_INT = 0.491795; // 秒（BPM = 122.0019）

// 输出音轨偏移（Remotion 4.0.484 + AAC 48kHz mp4，初版 0，首次渲染后交叉相关实测再填入）
export const OUTPUT_AUDIO_OFFSET_SEC = 0;

export const beatT = (n: number) => SOURCE_BEAT0 + OUTPUT_AUDIO_OFFSET_SEC + n * BEAT_INT;
export const beatF = (n: number) => Math.round(beatT(n) * FPS);

const span = (bStart: number, bEnd: number) => {
  const from = bStart === 0 ? 0 : beatF(bStart);
  const to = beatF(bEnd);
  return { from, to, duration: to - from, bStart, bEnd };
};

// 全片 88 拍（10 个顺序单元：7 个主镜头 + 3 张呼吸引导字卡），全部切点锚定 4 拍小节强拍
export const SIGHT_SHOTS = {
  maskOpen: span(0, 12),        // 0–179   (179f / 6.0s)  S1 text-as-mask 品牌钩子开场
  spotlight: span(12, 24),      // 179–356 (177f / 5.9s)  S2 spotlight-hero-card 8平台档案单主角
  card1: span(24, 28),          // 356–415 (59f  / 2.0s)  C1 呼吸字卡① 8大公开平台
  typeFilter: span(28, 36),     // 415–533 (118f / 3.9s)  S3 type-and-filter 搜索与筛选穿透
  graphScan: span(36, 48),      // 533–710 (177f / 5.9s)  S4 scanline-annotate-focus ECharts关系图谱+SSE终端
  card2: span(48, 52),          // 710–769 (59f  / 2.0s)  C2 呼吸字卡② 时序快照Diff
  timelineStack: span(52, 60),  // 769–887 (118f / 3.9s)  S5 list-stack-press 行为演化时间线
  card3: span(60, 64),          // 887–946 (59f  / 2.0s)  C3 呼吸字卡③ 多模态AI侧写
  agentReveal: span(64, 76),    // 946–1123 (177f / 5.9s) S6 document-typewriter-reveal LangGraph多模态侧写
  outro: span(76, 88),          // 1123–1300 (177f / 5.9s) S7 outro-group-photo-launch 发布会合影+开源CTA
} as const;

export const SIGHT_TOTAL = SIGHT_SHOTS.outro.to;

// 字卡文案表（*词* = Sight 钴蓝强调词；使用 | 强制换行保持两行均衡）
export const TITLE_CARDS = {
  card1: {
    text: '8 大公开平台，|*一屏*实时检索',
    sub: '大公开平台全量接入 · 统一适配器架构',
    subDigits: '8',
  },
  card2: {
    text: '时序快照 *Diff*，|自动还原行为时间线',
    sub: '内容哈希去重 · 跨时段变更窗口自动推断',
    subDigits: '',
  },
  card3: {
    text: 'LangGraph 多模态 *AI*，|带证据溯源侧写',
    sub: 'GEMINI · CLAUDE · OPENAI 原生看图与看视频',
    subDigits: '',
  },
} as const;

export const parseTitleWords = (raw: string): { text: string; accent?: boolean; br?: boolean }[] => {
  const lines = raw.split('|');
  const out: { text: string; accent?: boolean; br?: boolean }[] = [];
  lines.forEach((line, li) => {
    const tokens = line.trim().split(/(\*[^*]+\*)/g).filter(Boolean);
    tokens.forEach((tok, ti) => {
      const accent = tok.startsWith('*') && tok.endsWith('*') && tok.length > 2;
      const clean = accent ? tok.slice(1, -1) : tok;
      const isLastInLine = ti === tokens.length - 1;
      out.push({ text: clean, accent, br: isLastInLine && li < lines.length - 1 });
    });
  });
  return out;
};

// 底部解说主字幕表（56px 粗体胶囊，严格满足 Q11 ≥56px 手机可读线；字卡/开场/outro 不加）
export const CAPTIONS = [
  {
    id: 'cap-spotlight',
    from: SIGHT_SHOTS.spotlight.from + 24,
    duration: SIGHT_SHOTS.spotlight.duration - 36,
    text: '8 大平台统一聚合，30 分钟快照智能缓存',
  },
  {
    id: 'cap-search',
    from: SIGHT_SHOTS.typeFilter.from + 12,
    duration: SIGHT_SHOTS.typeFilter.duration - 22,
    text: '输入昵称或 UID，秒级跨平台检索定位',
  },
  {
    id: 'cap-graph',
    from: SIGHT_SHOTS.graphScan.from + 18,
    duration: SIGHT_SHOTS.graphScan.duration - 28,
    text: 'ECharts 6 交互式关系图谱，互关与同名自动归并',
  },
  {
    id: 'cap-timeline',
    from: SIGHT_SHOTS.timelineStack.from + 12,
    duration: SIGHT_SHOTS.timelineStack.duration - 20,
    text: '逐对快照自动 Diff，精准推断跨时段变更窗口',
  },
  {
    id: 'cap-agent',
    from: SIGHT_SHOTS.agentReveal.from + 16,
    duration: 94, // 在底部大标语「每条结论，皆有据可查」(local f104) 升起前干净退场，绝不重叠
    text: '原生看图看视频，每条侧写结论皆有 [E#] 溯源',
  },
] as const;

// 闪切转场点（仅 S3 点击穿透进 S4 图谱 1 处，跨骑硬切 ±5f；全片全画面冲击 ≤2 处，远低于 R4 上限）
export const FLASH_CUTS = [SIGHT_SHOTS.graphScan.from] as const;
