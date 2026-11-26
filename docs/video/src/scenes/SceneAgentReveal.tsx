// SceneAgentReveal.tsx — S6 LangGraph 原生多模态 AI 人物侧写
// （忠实复刻 demos/ui-entrance/document-typewriter-reveal/DocumentTypewriterReveal.tsx）
// 深海蓝灰暗场（Sight 色系，不漂移极光紫）悬浮完整三栏真实 ViewAgent 出版级界面（Q10）：
// 斜侧标题特写起，正文块与维度卡片两两成对打字揭示 + 单一钴蓝笔尖 + h2 蓝底高亮 →
// 相机单调 Hermite 样条丝滑后撤到全窗（左右双栏揭开 + 右侧 6 条真实 ev1–ev6 证据卡片逐条弹落进真实槽位！）
// → 底部升起 84px 大标语「每条结论，皆有据可查」并稳稳 hold。
import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, Easing } from 'remotion';
import { EASE, ramp } from '../lib/Polish';
import { LOOKS, Stage, Dust, TextReveal, alpha } from '../lib/Look';
import { SIGHT } from '../lib/SightBrand';
import layout from '../live-layout.json';

export const SCENE_AGENT_REVEAL_DEFAULTS = {
  sloganLeft: '每条结论，',
  sloganRight: '皆有据可查。',
  accent: SIGHT.accent,
  sloganColor: '#f1f5f9',
};

type Block = { x: number; y: number; w: number; h: number; tag: string };
type EvCard = { x: number; y: number; w: number; h: number; file?: string };

const blocks = layout.agent.blocks as Block[];
const evCards = layout.agent.evCards as EvCard[];
const leftRail = layout.agent.leftRail;
const rightRail = layout.agent.rightRail;
const PAGE_W = 1920;
const PAGE_H = layout.agent.pageH;

const L = LOOKS.midnight; // Sight 深海蓝暗场（钴蓝主光，绝不漂移紫粉）
const SURFACE = '#ffffff';
const WASH = 'rgba(53,101,224,0.18)';

// 3D 悬浮窗相机（布局级 CSS zoom 保文字锐度 Q2；单调三次 Hermite 样条零突变）
type Cam = { cx: number; cy: number; zoom: number; rotX: number; rotY: number; sx: number; sy: number };
type Key = Cam & { frame: number };
const ANCHORS: Key[] = [
  { frame: 0, cx: 840, cy: 290, zoom: 1.38, rotX: 7, rotY: -16, sx: 0, sy: 0 },
  { frame: 30, cx: 880, cy: 520, zoom: 1.18, rotX: 5, rotY: -11, sx: 0, sy: 0 },
  { frame: 68, cx: 960, cy: 540, zoom: 0.86, rotX: 3, rotY: -5, sx: 0, sy: -10 },
  { frame: 112, cx: 960, cy: 540, zoom: 0.75, rotX: 7, rotY: -2, sx: 0, sy: -74 },
  { frame: 177, cx: 960, cy: 540, zoom: 0.758, rotX: 7, rotY: -2, sx: 0, sy: -76 },
];
const PARAMS: (keyof Cam)[] = ['cx', 'cy', 'zoom', 'rotX', 'rotY', 'sx', 'sy'];

const hermite = (xs: number[], ys: number[]) => {
  const n = xs.length;
  const d = xs.slice(0, -1).map((x, i) => (ys[i + 1] - ys[i]) / (xs[i + 1] - x));
  const m = xs.map((_, i) => (i === 0 || i === n - 1 ? 0 : d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2));
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const h = a * a + b * b;
    if (h > 9) {
      const k = 3 / Math.sqrt(h);
      m[i] = k * a * d[i];
      m[i + 1] = k * b * d[i];
    }
  }
  return (x: number) => {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let i = 0;
    while (i < n - 2 && x > xs[i + 1]) i++;
    const h = xs[i + 1] - xs[i];
    const t = (x - xs[i]) / h;
    const t2 = t * t;
    const t3 = t2 * t;
    return (
      (2 * t3 - 3 * t2 + 1) * ys[i] +
      (t3 - 2 * t2 + t) * h * m[i] +
      (-2 * t3 + 3 * t2) * ys[i + 1] +
      (t3 - t2) * h * m[i + 1]
    );
  };
};

const CURVES = Object.fromEntries(
  PARAMS.map((p) => [p, hermite(ANCHORS.map((k) => k.frame), ANCHORS.map((k) => k[p]))]),
) as Record<keyof Cam, (x: number) => number>;
const camAt = (f: number): Cam => Object.fromEntries(PARAMS.map((p) => [p, CURVES[p](f)])) as Cam;
const PERSP = 2200;

// 写入节拍（10 块两两成对，f8 开始每对 8.5f，f58 前全部写完，赶在 f68 全窗落位前）
const REVEAL_EASE = Easing.bezier(0.4, 0, 0.6, 1);
const cueFor = (i: number) => 8 + Math.floor(i / 2) * 8.5;
const WIPE = 10;

export const AGENT_EV_CUE = (i: number) => 70 + i * 5;
const EV_DROP = Easing.bezier(0.2, 1.15, 0.3, 1);

export const SceneAgentReveal: React.FC<Partial<typeof SCENE_AGENT_REVEAL_DEFAULTS>> = ({
  sloganLeft = SCENE_AGENT_REVEAL_DEFAULTS.sloganLeft,
  sloganRight = SCENE_AGENT_REVEAL_DEFAULTS.sloganRight,
  accent = SCENE_AGENT_REVEAL_DEFAULTS.accent,
  sloganColor = SCENE_AGENT_REVEAL_DEFAULTS.sloganColor,
}) => {
  const frame = useCurrentFrame();
  const cam = camAt(frame);

  let caretIdx = -1;
  blocks.forEach((_, i) => {
    if (frame >= cueFor(i) && frame <= cueFor(i) + WIPE + 2) caretIdx = i;
  });
  const idleBlink = frame < cueFor(0) ? (Math.floor(frame / 4) % 2 === 0 ? 1 : 0.25) : 0;
  const tagIn = ramp(frame, 108, 20, EASE.out);

  return (
    <AbsoluteFill style={{ fontFamily: SIGHT.fontSans, overflow: 'hidden' }}>
      <Stage look={L} keyLight={{ x: 0.5, y: 0.04 }} fill={{ x: 0.88, y: 0.92 }} horizon={0.9} breathe={0.6} intensity={0.95}>
        <Dust look={L} count={24} seed={9} drift={0.16} opacity={0.38} color="#93c5fd" />
      </Stage>

      <AbsoluteFill style={{ transform: `translate(${cam.sx.toFixed(2)}px, ${cam.sy.toFixed(2)}px)` }}>
        <div style={{ position: 'absolute', inset: 0, perspective: `${(PERSP * cam.zoom).toFixed(2)}px`, perspectiveOrigin: '960px 540px' }}>
          <div
            style={{
              position: 'absolute',
              width: PAGE_W,
              height: PAGE_H,
              zoom: cam.zoom,
              transform: `translate(${(960 / cam.zoom - cam.cx).toFixed(3)}px, ${(540 / cam.zoom - cam.cy).toFixed(3)}px) rotateY(${cam.rotY.toFixed(3)}deg) rotateX(${cam.rotX.toFixed(3)}deg)`,
              transformOrigin: `${cam.cx.toFixed(2)}px ${cam.cy.toFixed(2)}px`,
              transformStyle: 'preserve-3d',
            }}
          >
            {/* 窗口背后钴蓝背光 */}
            <div
              style={{
                position: 'absolute',
                left: -220,
                top: -180,
                width: PAGE_W + 440,
                height: PAGE_H + 400,
                pointerEvents: 'none',
                background: `radial-gradient(ellipse 52% 52% at 50% 50%, ${alpha(accent, 0.36)} 0%, ${alpha('#38bdf8', 0.12)} 55%, transparent 74%)`,
                transform: 'translateZ(-40px)',
              }}
            />

            {/* 悬浮真实 Sight AI 侧写工作台应用窗 */}
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                width: PAGE_W,
                height: PAGE_H,
                borderRadius: 24,
                overflow: 'hidden',
                background: SIGHT.bg,
                boxShadow: `0 0 0 1.5px ${alpha('#ffffff', 0.32)}, 0 70px 160px -20px rgba(0,2,8,0.95), 0 20px 60px rgba(0,0,0,0.55)`,
              }}
            >
              <Img src={staticFile('textures/live/agent-full.png')} style={{ position: 'absolute', width: PAGE_W, height: PAGE_H }} />

              {/* 正文/维度块两两成对打字揭示 + 单一钴蓝笔尖 + h2 蓝底高亮 */}
              {blocks.map((p, i) => {
                const cue = cueFor(i);
                const coverT = interpolate(frame, [cue, cue + WIPE], [1, 0], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                  easing: REVEAL_EASE,
                });
                const bx = p.x - 4;
                const by = p.y - 3;
                const bw = p.w + 16;
                const bh = p.h + 6;
                const caretX = bx + bw * (1 - coverT);
                const caretH = Math.min(24, Math.max(16, p.h - 2));
                const isH2 = p.tag === 'h2';
                const hlCue = cue + WIPE + 4;
                const hlGrow = isH2
                  ? interpolate(frame, [hlCue, hlCue + 8], [0, 1], {
                      extrapolateLeft: 'clamp',
                      extrapolateRight: 'clamp',
                      easing: Easing.bezier(0.3, 0, 0.2, 1),
                    })
                  : 0;
                const textRight = p.x + p.w + 6;
                return (
                  <React.Fragment key={i}>
                    {hlGrow > 0 ? (
                      <div
                        style={{
                          position: 'absolute',
                          left: p.x - 4,
                          top: p.y - 1,
                          width: Math.min(340, p.w) * hlGrow,
                          height: p.h + 2,
                          background: WASH,
                          borderRadius: 4,
                          mixBlendMode: 'multiply',
                        }}
                      />
                    ) : null}
                    {coverT > 0 ? (
                      <div style={{ position: 'absolute', left: bx, top: by, width: bw, height: bh, overflow: 'hidden' }}>
                        <div style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: `${coverT * 100}%`, background: SURFACE }} />
                      </div>
                    ) : null}
                    {i === caretIdx ? (
                      <div
                        style={{
                          position: 'absolute',
                          left: Math.min(caretX, textRight),
                          top: p.y + (p.h - caretH) / 2,
                          width: 3,
                          height: caretH,
                          background: accent,
                          borderRadius: 2,
                          boxShadow: `0 0 8px ${alpha(accent, 0.7)}, 0 0 18px ${alpha('#60a5fa', 0.5)}`,
                          opacity: coverT > 0 ? 1 : interpolate(frame, [cue + WIPE, cue + WIPE + 2], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }),
                        }}
                      />
                    ) : null}
                  </React.Fragment>
                );
              })}

              {/* 开场待命笔尖 */}
              {idleBlink > 0 && blocks[0] ? (
                <div
                  style={{
                    position: 'absolute',
                    left: blocks[0].x - 4,
                    top: blocks[0].y + 2,
                    width: 3,
                    height: 22,
                    background: accent,
                    borderRadius: 2,
                    opacity: idleBlink,
                    boxShadow: `0 0 8px ${alpha(accent, 0.65)}`,
                  }}
                />
              ) : null}

              {/* 左右双栏自上而下揭开 + 内缘钴蓝细线 */}
              {[
                { rail: leftRail, cue: 54, inner: 'right' as const, bg: '#ffffff' },
                { rail: rightRail, cue: 62, inner: 'left' as const, bg: '#ffffff' },
              ].map(({ rail, cue, inner, bg }, i) => {
                const t = interpolate(frame, [cue, cue + 10], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                  easing: Easing.bezier(0.3, 0, 0.2, 1),
                });
                const lineFade = interpolate(frame, [cue + 10, cue + 24], [1, 0], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                });
                return (
                  <React.Fragment key={`rail-${i}`}>
                    {t < 1 ? (
                      <div
                        style={{
                          position: 'absolute',
                          left: rail.x,
                          top: rail.y + rail.h * t,
                          width: rail.w,
                          height: rail.h * (1 - t),
                          background: bg,
                        }}
                      />
                    ) : null}
                    {frame >= cue && lineFade > 0 ? (
                      <div
                        style={{
                          position: 'absolute',
                          left: inner === 'right' ? rail.x + rail.w - 2 : rail.x,
                          top: rail.y,
                          width: 2.5,
                          height: rail.h * t,
                          background: accent,
                          opacity: lineFade,
                          boxShadow: `0 0 10px ${alpha(accent, 0.7)}`,
                        }}
                      />
                    ) : null}
                  </React.Fragment>
                );
              })}

              {/* 遮罩住右栏已烤入的 6 张证据卡片，等待真实 cutout 逐条弹落进槽位 */}
              {evCards.map((ev, i) => (
                <div
                  key={`ev-mask-${i}`}
                  style={{
                    position: 'absolute',
                    left: ev.x - 2,
                    top: ev.y - 2,
                    width: ev.w + 4,
                    height: ev.h + 4,
                    background: '#ffffff',
                    opacity: frame >= AGENT_EV_CUE(i) + 9 ? 0 : 1,
                  }}
                />
              ))}

              {/* 右侧 6 条真实图文证据卡片（ev1–ev6）逐条落入轨道 */}
              {evCards.map((ev, i) => {
                const cue = AGENT_EV_CUE(i);
                if (frame < cue || !ev.file) return null;
                const t = interpolate(frame, [cue, cue + 9], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                  easing: EV_DROP,
                });
                const appear = interpolate(frame, [cue, cue + 3], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                });
                const air = Math.max(0, 1 - t);
                return (
                  <div
                    key={ev.file}
                    style={{
                      position: 'absolute',
                      left: ev.x,
                      top: ev.y,
                      width: ev.w,
                      height: ev.h,
                      borderRadius: 8,
                      overflow: 'hidden',
                      transform: `translateY(${(-42 * air).toFixed(2)}px)`,
                      opacity: appear,
                      boxShadow: air > 0.02 ? `0 ${(12 * air).toFixed(1)}px ${(24 * air).toFixed(1)}px rgba(15,23,42,${(0.22 * air).toFixed(3)})` : 'none',
                    }}
                  >
                    <Img src={staticFile(`textures/live/${ev.file}`)} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }} />
                  </div>
                );
              })}

              {/* 窗口上沿玻璃高光 */}
              <div style={{ position: 'absolute', left: 0, right: 0, top: 0, height: 3, background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.92), transparent)' }} />
            </div>
          </div>
        </div>
      </AbsoluteFill>

      {/* 窗底大标语（f108 升起，此时底部 56px 字幕已干净退场，绝不重叠；字号 78px 清晰利落） */}
      <div
        style={{
          position: 'absolute',
          left: 240,
          top: 944,
          display: 'flex',
          alignItems: 'baseline',
          fontFamily: SIGHT.fontSans,
          fontSize: 78,
          fontWeight: 800,
          letterSpacing: '-0.02em',
          color: sloganColor,
          opacity: tagIn > 0 ? 1 : 0,
        }}
      >
        <TextReveal text={sloganLeft} by="char" variant="rise" start={108} each={14} gap={2} />
        <TextReveal text={sloganRight} by="char" variant="rise" start={118} each={14} gap={2} style={{ color: '#60a5fa' }} />
      </div>
    </AbsoluteFill>
  );
};
