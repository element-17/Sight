// workbench.ts — 动效工作台拆解清单（与 timeline.ts / audio.ts / Main.tsx 单一事实源同源）
import { createElement, type FC } from 'react';
import { CAPTIONS, FLASH_CUTS, FPS, HEIGHT, SIGHT_SHOTS, SIGHT_TOTAL, TITLE_CARDS, WIDTH } from './timeline';
import { SFX_CUES, sfxDuration } from './audio';
import { SightMain } from './Main';
import { CAPTION_DEFAULTS, SIGHT, SightCaption, SightFlashCut } from './lib/SightBrand';
import { SceneMaskOpen, SCENE_MASK_OPEN_DEFAULTS } from './scenes/SceneMaskOpen';
import { SceneSpotlightHero, SCENE_SPOTLIGHT_DEFAULTS } from './scenes/SceneSpotlightHero';
import { SightTitleCard, TITLE_CARD_DEFAULTS } from './scenes/SightTitleCard';
import { SceneTypeFilter, SCENE_TYPE_FILTER_DEFAULTS } from './scenes/SceneTypeFilter';
import { SceneGraphScan, SCENE_GRAPH_SCAN_DEFAULTS } from './scenes/SceneGraphScan';
import { SceneTimelineStack, SCENE_TIMELINE_STACK_DEFAULTS } from './scenes/SceneTimelineStack';
import { SceneAgentReveal, SCENE_AGENT_REVEAL_DEFAULTS } from './scenes/SceneAgentReveal';
import { SceneOutroLaunch, SCENE_OUTRO_DEFAULTS } from './scenes/SceneOutroLaunch';

type Field = Record<string, unknown> & { type: string; key: string; label: string; default: unknown };
const text = (key: string, label: string, def: string): Field => ({ type: 'text', key, label, default: def });
const textarea = (key: string, label: string, def: string): Field => ({ type: 'textarea', key, label, default: def });
const color = (key: string, label: string, def: string): Field => ({ type: 'color', key, label, default: def });
const size = (key: string, label: string, def: number, min: number, max: number): Field => ({
  type: 'slider',
  key,
  label,
  default: def,
  min,
  max,
  step: 1,
  unit: 'px',
});

type TitleProps = Partial<typeof TITLE_CARD_DEFAULTS> & {
  text?: string;
  sub?: string;
  subDigits?: string;
  duration?: number;
};
export const TitleCardUnit: FC<TitleProps> = ({ text: t = '', sub = '', subDigits = '', duration = 59, ...style }) =>
  createElement(SightTitleCard, { text: t, sub, subDigits, duration, ...style });
TitleCardUnit.displayName = 'SightTitleCard';

type CaptionProps = Partial<typeof CAPTION_DEFAULTS> & { text?: string; duration?: number };
export const CaptionUnit: FC<CaptionProps> = ({ text: t = '', duration = 90, ...style }) =>
  createElement(SightCaption, { text: t, duration, ...style });
CaptionUnit.displayName = 'SightCaption';

export const FlashUnit: FC<{ duration?: number }> = ({ duration = 10 }) => createElement(SightFlashCut, { duration });
FlashUnit.displayName = 'SightFlashCut';

const SCHEMAS = {
  maskOpen: [
    text('word', '巨字遮罩词', SCENE_MASK_OPEN_DEFAULTS.word),
    text('kicker', '顶部眉题', SCENE_MASK_OPEN_DEFAULTS.kicker),
    text('subtitle', '底部副题', SCENE_MASK_OPEN_DEFAULTS.subtitle),
    color('accent', '品牌主色', SCENE_MASK_OPEN_DEFAULTS.accent),
    color('ink', '主文字色', SCENE_MASK_OPEN_DEFAULTS.ink),
    color('ink2', '副题文字色', SCENE_MASK_OPEN_DEFAULTS.ink2),
  ],
  spotlight: [
    text('noteLine1', '3D 注记 · 上行', SCENE_SPOTLIGHT_DEFAULTS.noteLine1),
    text('noteLine2', '3D 注记 · 下行（高亮）', SCENE_SPOTLIGHT_DEFAULTS.noteLine2),
    color('accent', '光束与高亮色', SCENE_SPOTLIGHT_DEFAULTS.accent),
  ],
  typeFilter: [
    text('query', '搜索输入词', SCENE_TYPE_FILTER_DEFAULTS.query),
    color('accent', '聚焦与点击色', SCENE_TYPE_FILTER_DEFAULTS.accent),
  ],
  graphScan: [
    text('statusScanning', '扫描中状态文案', SCENE_GRAPH_SCAN_DEFAULTS.statusScanning),
    text('statusDone', '锁定后状态文案', SCENE_GRAPH_SCAN_DEFAULTS.statusDone),
    text('productTag', '顶栏副标', SCENE_GRAPH_SCAN_DEFAULTS.productTag),
    color('machineColor', '扫描与取景框颜色', SCENE_GRAPH_SCAN_DEFAULTS.machineColor),
  ],
  timelineStack: [
    text('title', '计数器标题', SCENE_TIMELINE_STACK_DEFAULTS.title),
    text('subtitle', '计数器副标', SCENE_TIMELINE_STACK_DEFAULTS.subtitle),
    size('counterSize', '计数器字号', SCENE_TIMELINE_STACK_DEFAULTS.counterSize, 64, 150),
    color('accent', '数字强调色', SCENE_TIMELINE_STACK_DEFAULTS.accent),
  ],
  agentReveal: [
    text('sloganLeft', '底标语 · 前半', SCENE_AGENT_REVEAL_DEFAULTS.sloganLeft),
    text('sloganRight', '底标语 · 后半（高亮）', SCENE_AGENT_REVEAL_DEFAULTS.sloganRight),
    color('accent', '笔尖与背光色', SCENE_AGENT_REVEAL_DEFAULTS.accent),
  ],
  outro: [
    text('wordmark', '品牌字标', SCENE_OUTRO_DEFAULTS.wordmark),
    size('wordmarkSize', '字标字号', SCENE_OUTRO_DEFAULTS.wordmarkSize, 72, 200),
    text('tagline', '开源下载口号', SCENE_OUTRO_DEFAULTS.tagline),
    text('repoUrl', 'GitHub 地址', SCENE_OUTRO_DEFAULTS.repoUrl),
    text('disclaimer', '底部合规声明', SCENE_OUTRO_DEFAULTS.disclaimer),
    color('accent', '品牌主色', SCENE_OUTRO_DEFAULTS.accent),
  ],
  title: [
    textarea('text', '字卡文案（*词*=高亮，|=换行）', ''),
    text('sub', '副标', ''),
    text('subDigits', '滚动数字', ''),
    size('fontSize', '标题字号', TITLE_CARD_DEFAULTS.fontSize, 56, 140),
    color('ink', '主字色', TITLE_CARD_DEFAULTS.ink),
    color('accent', '强调色', TITLE_CARD_DEFAULTS.accent),
    color('bg', '底色', TITLE_CARD_DEFAULTS.bg),
  ],
  caption: [
    text('text', '底部解说字幕', ''),
    size('fontSize', '字号', CAPTION_DEFAULTS.fontSize, 40, 72),
    size('bottom', '底距', CAPTION_DEFAULTS.bottom, 16, 160),
    color('accent', '方点强调色', CAPTION_DEFAULTS.accent),
  ],
};

type ShotKey = keyof typeof SIGHT_SHOTS;
const scene = <T extends Record<string, unknown>>(
  key: ShotKey,
  label: string,
  component: FC<Partial<T>>,
  defaults: T,
  schema: Field[],
  durationProp?: string,
) => ({
  id: key,
  label,
  from: SIGHT_SHOTS[key].from,
  duration: SIGHT_SHOTS[key].duration,
  component: component as FC<Record<string, unknown>>,
  props: { ...defaults },
  schema,
  ...(durationProp ? { durationProp } : {}),
});

const title = (key: keyof typeof TITLE_CARDS, label: string) => {
  const t = TITLE_CARDS[key] as { text: string; sub?: string; subDigits?: string };
  return {
    id: key,
    label,
    from: SIGHT_SHOTS[key].from,
    duration: SIGHT_SHOTS[key].duration,
    component: TitleCardUnit as FC<Record<string, unknown>>,
    props: { text: t.text, sub: t.sub ?? '', subDigits: t.subDigits ?? '', ...TITLE_CARD_DEFAULTS },
    schema: SCHEMAS.title,
    durationProp: 'duration',
    cardId: 'sight-title-card',
    cardName: 'Sight 呼吸字卡',
    accent: SIGHT.accent,
  };
};

export const WORKBENCH = {
  name: 'Sight · B站开源宣传片',
  fps: FPS,
  width: WIDTH,
  height: HEIGHT,
  total: SIGHT_TOTAL,
  background: SIGHT.bg,
  shots: [
    scene('maskOpen', 'S1 SIGHT 巨字遮罩开场', SceneMaskOpen, SCENE_MASK_OPEN_DEFAULTS, SCHEMAS.maskOpen),
    scene('spotlight', 'S2 8平台档案卡聚光特写', SceneSpotlightHero, SCENE_SPOTLIGHT_DEFAULTS, SCHEMAS.spotlight),
    title('card1', '字卡① 8大公开平台'),
    scene('typeFilter', 'S3 跨平台搜索与筛选穿透', SceneTypeFilter, SCENE_TYPE_FILTER_DEFAULTS, SCHEMAS.typeFilter),
    scene('graphScan', 'S4 ECharts 关系图谱扫描标注', SceneGraphScan, SCENE_GRAPH_SCAN_DEFAULTS, SCHEMAS.graphScan),
    title('card2', '字卡② 时序快照 Diff'),
    scene('timelineStack', 'S5 行为演化时间线堆叠', SceneTimelineStack, SCENE_TIMELINE_STACK_DEFAULTS, SCHEMAS.timelineStack),
    title('card3', '字卡③ 多模态 AI 侧写'),
    scene('agentReveal', 'S6 LangGraph 多模态侧写揭示', SceneAgentReveal, SCENE_AGENT_REVEAL_DEFAULTS, SCHEMAS.agentReveal),
    scene('outro', 'S7 发布会合影与开源 CTA', SceneOutroLaunch, SCENE_OUTRO_DEFAULTS, SCHEMAS.outro, 'duration'),
  ],
  transitions: FLASH_CUTS.map((cut, i) => ({
    id: `flash-${i + 1}`,
    label: `钴白闪切 @${cut}f`,
    from: cut - 5,
    duration: 10,
    component: FlashUnit as FC<Record<string, unknown>>,
    durationProp: 'duration',
    cardId: 'sight-flash-cut',
    cardName: '钴白闪转场',
  })),
  captions: CAPTIONS.map((c) => ({
    id: c.id,
    label: c.text,
    from: c.from,
    duration: c.duration,
    component: CaptionUnit as FC<Record<string, unknown>>,
    props: { text: c.text, ...CAPTION_DEFAULTS },
    schema: SCHEMAS.caption,
    durationProp: 'duration',
    cardId: 'sight-caption',
    cardName: '解说主字幕条',
  })),
  sfx: SFX_CUES.map((s) => ({
    from: s.from,
    duration: sfxDuration(s),
    src: `audio/${s.src}`,
    volume: s.volume,
  })),
  bgm: [{ from: 0, duration: SIGHT_TOTAL, src: 'audio/bgm.mp3', volume: 0.30 }],
  order: ['transitions', 'captions', 'overlays'] as const,
  original: SightMain as FC<Record<string, unknown>>,
};
