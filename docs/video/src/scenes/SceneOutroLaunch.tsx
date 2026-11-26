// SceneOutroLaunch.tsx — S7 发布会合影峰值收场（忠实复刻 demos/outro/outro-group-photo-launch/OutroGroupPhotoLaunch.tsx）
// 9 件覆盖全片全部核心功能的真实 Sight 切片从四方过冲飞入合影 → crane 运镜 + 钴蓝舞台光 + 冰蓝微粒
// → Sight 蓝眼睛标志与大字标踩 b80（local f59）压印砸落 + 延长线射出 + 大字号开源免费 CTA（Q11 ≥36px）
// → 满 2.0s+ sign-off hold（R1）→ 末 12f 优雅熄灯。
import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, Easing } from 'remotion';
import { PageCam } from '../lib/PageCam';
import { EASE, Grain, SpeedBlur, ramp, velocity } from '../lib/Polish';
import { SIGHT, SightMark } from '../lib/SightBrand';
import { SIGHT_SHOTS, beatF } from '../timeline';

export const SCENE_OUTRO_DEFAULTS = {
  wordmark: 'Sight',
  wordmarkSize: 132,
  tagline: '开源免费 · Win / Mac / Linux 解压即用',
  repoUrl: 'github.com/element-17/Sight',
  disclaimer: '演示数据均为虚构 · 仅用于公开数据工程与图谱可视化研究学习',
  ink: SIGHT.ink,
  accent: SIGHT.accent,
  muted: SIGHT.ink2,
};

// 字标砸落拍点精确锚定在 b80（beatF(80) - SIGHT_SHOTS.outro.from ≈ 59f）
export const OUTRO_STAMP_F = beatF(80) - SIGHT_SHOTS.outro.from;

const FLY_EASE = Easing.bezier(0.34, 1.4, 0.44, 1); // y1 > 1 真过冲（已知命门！）
const CRANE_EASE = Easing.bezier(0.3, 0, 0.2, 1);

type FlyEl = {
  key: string;
  file: string;
  w: number;
  h: number;
  cx: number;
  cy: number;
  scale: number;
  rot: number;
  dx: number;
  dy: number;
  radius: number;
  cue: number;
};

// 9 件全片功能全家福（覆盖：顶栏/侧栏、档案卡、投稿卡×2、搜索条、关系图谱、时间线Diff、AI画像卡、SSE终端）
const ELS: FlyEl[] = [
  { key: 'topbar', file: 'topbar.png', w: 1692, h: 56, cx: 960, cy: 76, scale: 0.7, rot: 0, dx: 0, dy: -130, radius: 10, cue: 4 },
  { key: 'profile', file: 'profile-card-hires.png', w: 1060, h: 114, cx: 430, cy: 230, scale: 0.56, rot: -4, dx: -520, dy: -60, radius: 12, cue: 8 },
  { key: 'graph', file: 'graph-stage.png', w: 540, h: 334, cx: 1610, cy: 290, scale: 0.78, rot: 4, dx: 520, dy: -40, radius: 14, cue: 12 },
  { key: 'agent', file: 'agent-meta.png', w: 984, h: 205, cx: 340, cy: 760, scale: 0.56, rot: 3, dx: -480, dy: 280, radius: 12, cue: 16 },
  { key: 'terminal', file: 'terminal-panel.png', w: 280, h: 460, cx: 1680, cy: 760, scale: 0.72, rot: -3.5, dx: 460, dy: 260, radius: 12, cue: 20 },
  { key: 'tl1', file: 'tl1.png', w: 1058, h: 80, cx: 610, cy: 930, scale: 0.5, rot: 1.5, dx: -100, dy: 340, radius: 10, cue: 24 },
  { key: 'card1', file: 'card1.png', w: 258, h: 120, cx: 210, cy: 490, scale: 0.92, rot: -5, dx: -460, dy: 0, radius: 12, cue: 28 },
  { key: 'search', file: 'float-search.png', w: 344, h: 35, cx: 1020, cy: 170, scale: 1.05, rot: -1.5, dx: 0, dy: -220, radius: 9, cue: 32 },
  { key: 'ev1', file: 'ev5.png', w: 330, h: 146, cx: 1310, cy: 910, scale: 0.88, rot: -2, dx: 260, dy: 310, radius: 12, cue: 36 },
];

// 20 颗确定性钴蓝/冰蓝微粒 + 6 颗前景景深散景（全参数 index 派生，确定性渲染）
const DUST = Array.from({ length: 20 }, (_, i) => ({
  x: (i * 439 + 137) % 1920,
  y0: (i * 613 + 271) % 1080,
  rise: 0.32 + (i % 5) * 0.11,
  swayAmp: 9 + (i % 4) * 5,
  swayFreq: 0.022 + (i % 3) * 0.008,
  phase: (i * 0.83) % (Math.PI * 2),
  size: 2.6 + (i % 3) * 0.9,
  opacity: 0.36 + ((i * 7) % 5) * 0.09,
}));
const BOKEH = Array.from({ length: 6 }, (_, i) => ({
  x: (i * 701 + 260) % 1920,
  y0: (i * 389 + 640) % 1080,
  rise: 0.55 + (i % 3) * 0.2,
  size: 16 + (i % 3) * 7,
  opacity: 0.12 + (i % 2) * 0.06,
}));

export const SceneOutroLaunch: React.FC<Partial<typeof SCENE_OUTRO_DEFAULTS> & { duration?: number }> = ({
  wordmark = SCENE_OUTRO_DEFAULTS.wordmark,
  wordmarkSize = SCENE_OUTRO_DEFAULTS.wordmarkSize,
  tagline = SCENE_OUTRO_DEFAULTS.tagline,
  repoUrl = SCENE_OUTRO_DEFAULTS.repoUrl,
  disclaimer = SCENE_OUTRO_DEFAULTS.disclaimer,
  ink = SCENE_OUTRO_DEFAULTS.ink,
  accent = SCENE_OUTRO_DEFAULTS.accent,
  muted = SCENE_OUTRO_DEFAULTS.muted,
  duration = SIGHT_SHOTS.outro.duration,
}) => {
  const frame = useCurrentFrame();
  const letters = Array.from(wordmark);
  const S = OUTRO_STAMP_F; // 字标主砸落帧（锚定 b80）

  const blur = interpolate(frame, [0, 24], [0, 14], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.4, 1),
  });
  const rule = interpolate(frame, [S + 14, S + 26], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });
  const tag = ramp(frame, S + 22, 14, EASE.out);
  const fadeOut = 1 - ramp(frame, duration - 12, 11, EASE.exit);
  const recede = interpolate(frame, [S - 4, S + 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // crane 运镜（前 44f 落下，之后零速衔接缓推）
  const craneT = interpolate(frame, [0, 44], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: CRANE_EASE,
  });
  const pushT = ramp(frame, 40, Math.max(30, duration - 40), EASE.smooth);
  const camScale = 1.06 - 0.06 * craneT + 0.032 * pushT;
  const camTilt = 4 * (1 - craneT);

  const sweepX = interpolate(frame, [2, 16], [-700, 2020], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.6, 1),
  });
  const sweepOpacity = interpolate(frame, [2, 5, 12, 16], [0, 0.16, 0.16, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const stageLight = interpolate(frame, [S - 4, S + 6, S + 16], [0, 0.65, 0.4], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const vignette = interpolate(frame, [S - 4, S + 10], [0, 0.14], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const ruleExt = interpolate(frame, [S + 14, S + 22], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });
  const ruleExtFade = interpolate(frame, [S + 22, S + 28], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const wordSpacing = interpolate(frame, [S + 18, S + 24], [-0.02, 0.005], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });

  return (
    <AbsoluteFill style={{ background: '#080d1a' }}>
      <AbsoluteFill style={{ opacity: fadeOut }}>
        <AbsoluteFill
          style={{
            transform: `perspective(1400px) rotateX(${camTilt.toFixed(3)}deg) scale(${camScale.toFixed(5)})`,
            transformOrigin: '50% 45%',
          }}
        >
          {/* 虚焦景深底图（真实 Sight 图谱页） */}
          <PageCam src="textures/live/graph-full.png" pageH={1080} keys={[{ frame: 0, cx: 960, cy: 540, zoom: 0.92 }]} blur={blur} bg={SIGHT.bg} />
          {/* Sight 冷白景深幕布 */}
          <AbsoluteFill
            style={{
              background:
                'radial-gradient(1240px 820px at 50% 48%, rgba(246,248,252,0.88), rgba(240,244,251,0.68) 60%, rgba(226,232,240,0.48))',
              pointerEvents: 'none',
            }}
          />

          {/* 9 件功能全家福四方飞入 */}
          <AbsoluteFill style={{ pointerEvents: 'none' }}>
            {ELS.map((el) => {
              if (frame < el.cue) return null;
              const t = interpolate(frame, [el.cue, el.cue + 13], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
                easing: FLY_EASE,
              });
              const opacity = interpolate(frame, [el.cue, el.cue + 3], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              const x = el.dx * (1 - t);
              const y = el.dy * (1 - t);
              const rot = el.rot * (2 - t);
              const scale = el.scale * (1.12 - 0.12 * t);
              const air = Math.max(0, 1 - t);
              const shadow =
                air > 0.01
                  ? `0 ${10 + 26 * air}px ${24 + 46 * air}px rgba(15,23,42,${(0.16 + 0.1 * air).toFixed(3)}), 0 2px 6px rgba(15,23,42,.08)`
                  : '0 10px 24px rgba(15,23,42,.15), 0 2px 6px rgba(15,23,42,.08)';
              const settledOpacity = opacity * (1 - 0.18 * recede);
              const saturate = 1 - 0.1 * recede;

              const posAt = (fr: number) => {
                const tt = interpolate(fr, [el.cue, el.cue + 13], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                  easing: FLY_EASE,
                });
                return [el.dx * (1 - tt), el.dy * (1 - tt)];
              };
              const vx = velocity((fr) => posAt(fr)[0], frame);
              const vy = velocity((fr) => posAt(fr)[1], frame);
              const land = interpolate(frame, [el.cue + 10, el.cue + 13, el.cue + 17], [0, 1, 0], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });

              return (
                <SpeedBlur key={el.key} vx={vx} vy={vy} amount={0.28} max={20}>
                  <div
                    style={{
                      position: 'absolute',
                      left: el.cx - el.w / 2,
                      top: el.cy - el.h / 2,
                      width: el.w,
                      height: el.h,
                      transform: `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px) rotate(${rot.toFixed(3)}deg) scale(${(scale * (1 - 0.015 * land)).toFixed(4)})`,
                      transformOrigin: 'center center',
                      borderRadius: el.radius,
                      overflow: 'hidden',
                      border: '1px solid rgba(15,23,42,0.08)',
                      boxShadow:
                        land > 0.01
                          ? `0 ${(10 - 5 * land).toFixed(1)}px ${(24 - 12 * land).toFixed(1)}px rgba(15,23,42,${(0.16 + 0.06 * land).toFixed(3)})`
                          : shadow,
                      opacity: settledOpacity,
                      filter: `saturate(${saturate.toFixed(3)})`,
                    }}
                  >
                    <Img src={staticFile(`textures/live/${el.file}`)} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                  </div>
                </SpeedBlur>
              );
            })}
          </AbsoluteFill>
        </AbsoluteFill>

        {/* 确定性冰蓝微粒与前景散景 */}
        <AbsoluteFill style={{ pointerEvents: 'none' }}>
          {DUST.map((d, i) => {
            const y = (((d.y0 - frame * d.rise) % 1080) + 1080) % 1080;
            const x = d.x + Math.sin(frame * d.swayFreq + d.phase) * d.swayAmp;
            const twinkle = 0.7 + 0.3 * Math.sin(frame * 0.21 + d.phase * 3);
            return (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: x,
                  top: y,
                  width: d.size,
                  height: d.size,
                  borderRadius: '50%',
                  background: '#3565e0',
                  opacity: d.opacity * twinkle,
                  boxShadow: `0 0 ${d.size * 2.5}px ${d.size * 0.6}px rgba(96,165,250,0.55)`,
                }}
              />
            );
          })}
          {BOKEH.map((b, i) => {
            const y = ((((b.y0 - frame * b.rise) % 1180) + 1180) % 1180) - 50;
            return (
              <div
                key={`b${i}`}
                style={{
                  position: 'absolute',
                  left: b.x,
                  top: y,
                  width: b.size,
                  height: b.size,
                  borderRadius: '50%',
                  background: 'radial-gradient(circle, rgba(96,165,250,0.8) 0%, rgba(53,101,224,0.28) 55%, rgba(53,101,224,0) 72%)',
                  opacity: b.opacity,
                  filter: 'blur(2px)',
                }}
              />
            );
          })}
        </AbsoluteFill>

        {/* 开场冷白扫光带 */}
        {sweepOpacity > 0 ? (
          <AbsoluteFill style={{ pointerEvents: 'none', mixBlendMode: 'overlay' }}>
            <div
              style={{
                position: 'absolute',
                top: 0,
                bottom: 0,
                left: sweepX - 300,
                width: 600,
                background: 'linear-gradient(90deg, rgba(219,234,254,0), rgba(255,255,255,1) 50%, rgba(219,234,254,0))',
                opacity: sweepOpacity,
              }}
            />
          </AbsoluteFill>
        ) : null}

        {/* 字标背后舞台冷白光垫（把中间合影轻轻推后，保字标和 CTA 绝对清晰） */}
        {stageLight > 0 ? (
          <AbsoluteFill
            style={{
              pointerEvents: 'none',
              background: 'radial-gradient(760px 420px at 960px 510px, rgba(255,255,255,0.97), rgba(241,245,254,0.72) 55%, rgba(241,245,254,0) 78%)',
              opacity: stageLight,
            }}
          />
        ) : null}

        {vignette > 0 ? (
          <AbsoluteFill
            style={{
              pointerEvents: 'none',
              background: 'radial-gradient(1400px 900px at 50% 50%, rgba(15,23,42,0) 55%, rgba(15,23,42,0.55) 100%)',
              opacity: vignette,
            }}
          />
        ) : null}

        {/* 品牌落版：蓝眼睛标志 + Sight 字标 + 延长线 + Q11 大字号开源 CTA */}
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', pointerEvents: 'none' }}>
          <div style={{ textAlign: 'center', marginTop: -20 }}>
            <div
              style={{
                fontFamily: SIGHT.fontSans,
                fontSize: wordmarkSize,
                fontWeight: 800,
                lineHeight: 1.12,
                color: ink,
                letterSpacing: `${wordSpacing.toFixed(4)}em`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                textShadow: '0 2px 0 rgba(255,255,255,0.85), 0 16px 38px rgba(15,23,42,0.14)',
              }}
            >
              {(() => {
                const t = interpolate(frame, [S - 4, S + 4], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                  easing: Easing.bezier(0.2, 0.75, 0.3, 1),
                });
                return (
                  <div
                    style={{
                      marginRight: 34,
                      opacity: t,
                      transform: `translateY(${((1 - t) * 26).toFixed(2)}px) scale(${(1.34 - 0.34 * t).toFixed(4)})`,
                      filter: t < 0.995 ? `blur(${((1 - t) * 8).toFixed(2)}px)` : undefined,
                    }}
                  >
                    <SightMark size={136} glow />
                  </div>
                );
              })()}
              {letters.map((ch, i) => {
                const delay = Math.round(S + i * 2);
                const t = interpolate(frame, [delay, delay + 8], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                  easing: Easing.bezier(0.2, 0.75, 0.3, 1),
                });
                return (
                  <span
                    key={i}
                    style={{
                      opacity: t,
                      transform: `translateY(${((1 - t) * 26).toFixed(2)}px) scale(${(1.34 - 0.34 * t).toFixed(4)})`,
                      filter: t < 0.995 ? `blur(${((1 - t) * 8).toFixed(2)}px)` : undefined,
                      display: 'inline-block',
                      whiteSpace: 'pre',
                    }}
                  >
                    {ch}
                  </span>
                );
              })}
            </div>

            <div style={{ position: 'relative', height: 6, width: 280, margin: '30px auto 0' }}>
              <div style={{ position: 'absolute', inset: 0, borderRadius: 3, background: accent, transform: `scaleX(${rule})` }} />
              {ruleExt > 0 && ruleExtFade > 0 ? (
                <>
                  <div style={{ position: 'absolute', top: 2.5, height: 1.5, right: '100%', width: 190 * ruleExt, background: accent, opacity: ruleExtFade }} />
                  <div style={{ position: 'absolute', top: 2.5, height: 1.5, left: '100%', width: 190 * ruleExt, background: accent, opacity: ruleExtFade }} />
                </>
              ) : null}
            </div>

            <div
              style={{
                fontFamily: SIGHT.fontSans,
                fontSize: 40,
                fontWeight: 700,
                color: ink,
                marginTop: 28,
                letterSpacing: '0.03em',
                opacity: tag,
                transform: `translateY(${((1 - tag) * 8).toFixed(2)}px)`,
              }}
            >
              {tagline}
            </div>

            <div
              style={{
                fontFamily: SIGHT.fontMono,
                fontSize: 36,
                fontWeight: 700,
                color: accent,
                marginTop: 14,
                letterSpacing: '0.02em',
                opacity: tag,
                transform: `translateY(${((1 - tag) * 8).toFixed(2)}px)`,
              }}
            >
              {repoUrl}
            </div>
          </div>
        </AbsoluteFill>

        {/* 克制合规声明（面向 B站 公开演示） */}
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 24,
            textAlign: 'center',
            fontFamily: SIGHT.fontSans,
            fontSize: 22,
            fontWeight: 500,
            color: muted,
            opacity: tag * 0.85,
            pointerEvents: 'none',
          }}
        >
          {disclaimer}
        </div>

        <Grain opacity={0.04} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
