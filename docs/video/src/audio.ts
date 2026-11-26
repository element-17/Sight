// audio.ts — 中央 SFX 注册表（从 SIGHT_SHOTS 与 beatF 派生，零裸绝对帧号；按 sound-design §4.6 补偿峰值滞后与输出偏移）
import { FPS, OUTPUT_AUDIO_OFFSET_SEC, SIGHT_SHOTS, beatF } from './timeline';
import { GRAPH_SCAN_TARGETS } from './scenes/SceneGraphScan';
import { TIMELINE_CUES } from './scenes/SceneTimelineStack';
import { AGENT_EV_CUE } from './scenes/SceneAgentReveal';
import { OUTRO_STAMP_F } from './scenes/SceneOutroLaunch';

// 输出音轨偏移（帧）：由 timeline.ts 实测常量统一换算，首次渲染后交叉相关实测更新
export const OUTPUT_AUDIO_OFFSET_F = OUTPUT_AUDIO_OFFSET_SEC * FPS;

// 各 Freesound CC0 音源实测峰值滞后（帧，来源 public/audio/sfx/audio-manifest.json，下载完成后同步精确值）
export const PEAK_F: Record<string, number> = {
  'sfx/fs-475896.mp3': 4,   // quick whoosh
  'sfx/fs-648729.mp3': 18,  // cinematic whoosh
  'sfx/fs-278205.mp3': 2,   // mechanical switch flip
  'sfx/fs-778444.mp3': 2,   // metallic mechanical click
  'sfx/fs-270435.mp3': 1,   // Canon 5D shutter click
  'sfx/fs-629979.mp3': 2,   // Canon camera click / snap
  'sfx/fs-152586.mp3': 0,   // Dell desktop keyboard typing (continuous)
  'sfx/fs-859482.mp3': 78,  // subtle cinematic riser (peaks near end)
  'sfx/fs-558238.mp3': 2,   // short cinematic impact
  'sfx/fs-879797.mp3': 6,   // shine chime / sparkle
};

export const sfxFrom = (targetPeakF: number, src: string) =>
  Math.max(0, Math.round(targetPeakF - (PEAK_F[src] ?? 0) - OUTPUT_AUDIO_OFFSET_F));

export type SfxCue = {
  from: number;
  src: string; // 相对 public/audio/
  volume: number;
  durationInFrames?: number; // 长样本显式裁窗（S4 / A5）
  note: string;
};

// S4 扫描锁定 5 个目标的双样本交替机械点击（防机枪感：交替样本 + 音量缓降）
const SCAN_LOCK_CUES: SfxCue[] = [...GRAPH_SCAN_TARGETS]
  .sort((a, b) => a.ft - b.ft)
  .map((t, i) => {
    const src = i % 2 === 0 ? 'sfx/fs-778444.mp3' : 'sfx/fs-270435.mp3';
    return {
      from: sfxFrom(SIGHT_SHOTS.graphScan.from + Math.round(t.ft) + 2, src),
      src,
      volume: Number((0.46 - i * 0.03).toFixed(2)),
      durationInFrames: 18,
      note: `S4 扫描锁定 ${t.head}`,
    };
  });

// S5 时间线 5 条卡片落地压弹（双样本交替 + 阶梯降音量防机枪感，S2）
const TIMELINE_LAND_CUES: SfxCue[] = TIMELINE_CUES.map((cue, i) => {
  const src = i % 2 === 0 ? 'sfx/fs-629979.mp3' : 'sfx/fs-778444.mp3';
  return {
    from: sfxFrom(SIGHT_SHOTS.timelineStack.from + cue + 22, src),
    src,
    volume: Number((0.42 - i * 0.03).toFixed(2)),
    durationInFrames: 18,
    note: `S5 时间线第 ${i + 1} 条落位压弹`,
  };
});

// S6 右侧 6 条证据卡片逐条落轨（双样本交替 + 音量 0.40→0.25 阶梯递减，S2）
const AGENT_EV_CUES: SfxCue[] = Array.from({ length: 6 }, (_, i) => {
  const src = i % 2 === 0 ? 'sfx/fs-270435.mp3' : 'sfx/fs-629979.mp3';
  return {
    from: sfxFrom(SIGHT_SHOTS.agentReveal.from + AGENT_EV_CUE(i) + 6, src),
    src,
    volume: Number((0.4 - i * 0.03).toFixed(2)),
    durationInFrames: 15,
    note: `S6 证据账本 E${i + 1} 落轨`,
  };
});

export const SFX_CUES: SfxCue[] = [
  // —— S1 开场品牌遮罩 ——
  {
    from: sfxFrom(SIGHT_SHOTS.maskOpen.from + 12, 'sfx/fs-475896.mp3'),
    src: 'sfx/fs-475896.mp3',
    volume: 0.45,
    durationInFrames: 24,
    note: 'S1 品牌字形基线擦出',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.maskOpen.from + 126, 'sfx/fs-648729.mp3'),
    src: 'sfx/fs-648729.mp3',
    volume: 0.62,
    durationInFrames: 52,
    note: 'S1 SIGHT 字腔 46× 冲入接管',
  },

  // —— S2 单主角聚光立传 ——
  {
    from: sfxFrom(SIGHT_SHOTS.spotlight.from + 3, 'sfx/fs-278205.mp3'),
    src: 'sfx/fs-278205.mp3',
    volume: 0.54,
    durationInFrames: 30,
    note: 'S2 剧场聚光推闸开灯',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.spotlight.from + 58, 'sfx/fs-648729.mp3'),
    src: 'sfx/fs-648729.mp3',
    volume: 0.56,
    durationInFrames: 50,
    note: 'S2 主角档案卡弹起悬浮',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.spotlight.from + 72, 'sfx/fs-879797.mp3'),
    src: 'sfx/fs-879797.mp3',
    volume: 0.42,
    durationInFrames: 64,
    note: 'S2 钴蓝轮廓光束双圈扫描',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.spotlight.from + 142, 'sfx/fs-629979.mp3'),
    src: 'sfx/fs-629979.mp3',
    volume: 0.58,
    durationInFrames: 20,
    note: 'S2 档案卡落回原位触地',
  },

  // —— 字卡① 呼吸转场 ——
  {
    from: sfxFrom(SIGHT_SHOTS.card1.from + 6, 'sfx/fs-475896.mp3'),
    src: 'sfx/fs-475896.mp3',
    volume: 0.48,
    durationInFrames: 22,
    note: 'C1 字卡①入场',
  },

  // —— S3 跨平台搜索与筛选 ——
  {
    from: Math.max(0, Math.round(SIGHT_SHOTS.typeFilter.from + 10 - OUTPUT_AUDIO_OFFSET_F)),
    src: 'sfx/fs-152586.mp3',
    volume: 0.52,
    durationInFrames: 26, // 严格匹配 8 字×3f = 24f 打字段（S4）
    note: 'S3 搜索框真实键盘打字（26f 裁剪）',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.typeFilter.from + 54, 'sfx/fs-475896.mp3'),
    src: 'sfx/fs-475896.mp3',
    volume: 0.5,
    durationInFrames: 24,
    note: 'S3 非目标卡筛选退场 + 目标卡滑位',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.typeFilter.from + 86, 'sfx/fs-270435.mp3'),
    src: 'sfx/fs-270435.mp3',
    volume: 0.68, // 全片清脆点击峰值（Canon 5D 真实快门）
    durationInFrames: 16,
    note: 'S3 光标点击目标卡确认',
  },
  {
    from: sfxFrom(beatF(36), 'sfx/fs-648729.mp3'),
    src: 'sfx/fs-648729.mp3',
    volume: 0.58,
    durationInFrames: 42,
    note: 'S3→S4 FlashCut 推进穿透切入图谱',
  },

  // —— S4 ECharts 关系图谱扫描标注 ——
  ...SCAN_LOCK_CUES,

  // —— 字卡② ——
  {
    from: sfxFrom(SIGHT_SHOTS.card2.from + 6, 'sfx/fs-475896.mp3'),
    src: 'sfx/fs-475896.mp3',
    volume: 0.48,
    durationInFrames: 22,
    note: 'C2 字卡②入场',
  },

  // —— S5 时序快照 Diff 时间线 ——
  ...TIMELINE_LAND_CUES,
  {
    from: sfxFrom(SIGHT_SHOTS.timelineStack.from + 84, 'sfx/fs-270435.mp3'),
    src: 'sfx/fs-270435.mp3',
    volume: 0.56,
    durationInFrames: 16,
    note: 'S5 DigitRoll 计数器 05 滚定',
  },

  // —— 字卡③ ——
  {
    from: sfxFrom(SIGHT_SHOTS.card3.from + 6, 'sfx/fs-475896.mp3'),
    src: 'sfx/fs-475896.mp3',
    volume: 0.48,
    durationInFrames: 22,
    note: 'C3 字卡③入场',
  },

  // —— S6 LangGraph 多模态 AI 人物侧写 ——
  {
    from: Math.max(0, Math.round(SIGHT_SHOTS.agentReveal.from + 8 - OUTPUT_AUDIO_OFFSET_F)),
    src: 'sfx/fs-152586.mp3',
    volume: 0.48,
    durationInFrames: 50, // 严格匹配 f8–f58 报告打字揭示段（S4）
    note: 'S6 AI 侧写报告打字揭示（50f 裁剪）',
  },
  ...AGENT_EV_CUES,

  // —— S7 发布会合影峰值收场（固定三拍句式：riser → impact @b80 → sparkle） ——
  {
    from: sfxFrom(SIGHT_SHOTS.outro.from + OUTRO_STAMP_F - 2, 'sfx/fs-859482.mp3'),
    src: 'sfx/fs-859482.mp3',
    volume: 0.55,
    durationInFrames: 84,
    note: 'S7 合影组装渐强 riser',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.outro.from + OUTRO_STAMP_F, 'sfx/fs-558238.mp3'),
    src: 'sfx/fs-558238.mp3',
    volume: 0.66, // 全片收官字标砸落峰值
    durationInFrames: 82,
    note: 'S7 Sight 标志与字标砸落 impact @b80',
  },
  {
    from: sfxFrom(SIGHT_SHOTS.outro.from + OUTRO_STAMP_F + 20, 'sfx/fs-879797.mp3'),
    src: 'sfx/fs-879797.mp3',
    volume: 0.46,
    durationInFrames: 68,
    note: 'S7 延长线与开源 CTA 辉光 sparkle',
  },
];

export const sfxDuration = (s: SfxCue) => s.durationInFrames ?? 60;
