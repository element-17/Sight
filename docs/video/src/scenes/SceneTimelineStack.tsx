// SceneTimelineStack.tsx — S5 时序快照 Diff 行为时间线（忠实复刻 demos/ui-entrance/list-stack-press/ListStackPress.tsx）
// 严格正视机位（Q6 列表信息密度高不倾斜）+ 计数器预备拍 + 5 条跨平台 Diff 卡逐张压弹摞起（6px 下压 8f 弹回）
// + 滞后钴蓝荧光笔高亮推断时间窗 + 屏幕右上角 DigitRoll 同步滚定 05 + 末尾单次柔光扫过 + ≥28f 静止呼吸（R2）。
import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, Easing } from 'remotion';
import { PageCam, CamKey } from '../lib/PageCam';
import { SpeedBlur, bezier, softShadow, velocity } from '../lib/Polish';
import { SIGHT } from '../lib/SightBrand';
import layout from '../live-layout.json';

export const SCENE_TIMELINE_STACK_DEFAULTS = {
  title: 'SNAPSHOT DIFF',
  subtitle: '跨平台快照新增变更',
  counterSize: 108,
  accent: SIGHT.accent,
  muted: SIGHT.ink2,
};

const entries = layout.timeline.entries;
const PAGE_H = layout.timeline.pageH;

// 节拍（总长 118f，b52–b60：0–6 预备拍 → 5 张卡 f6..f76 落完 → f84 计数滚定 → f92 扫光完 → 26f 静止呼吸）
export const TIMELINE_CUES = [6, 18, 30, 42, 54];
const DUR = 22;
const FLY_EASE = Easing.bezier(0.45, 0.05, 0.25, 1.12);
const TILTS = [1.8, -1.8, 1.8, -1.8, 1.8];

// 连续相机曲线（正视机位跟随堆叠向下，86f 后彻底静止留呼吸）
const CAM_END = 86;
const CY_EASE = bezier(0.42, 0, 0.2, 1);
const Z_EASE = bezier(0.3, 0, 0.18, 1);
const camAt = (f: number) => {
  const u = Math.min(1, Math.max(0, f / CAM_END));
  return {
    cx: 1020,
    cy: 270 + (400 - 270) * CY_EASE(u),
    zoom: 1.32 + (1.06 - 1.32) * Z_EASE(u),
  };
};
const CAM_KEYS: CamKey[] = Array.from({ length: 120 }, (_, f) => ({ frame: f, ...camAt(f) }));
const LINEAR = (t: number) => t;

// 连续里程计 DigitRoll（单格 8f < 12f 间距，最后一格 f84 滚定早于 f118）
const DIGITS = '0123456789';
const ROLL_DUR = 8;
const ROLL_EASE = Easing.bezier(0.25, 0.8, 0.25, 1);
const rollAt = (frame: number) => {
  let pos = 0;
  for (const c of TIMELINE_CUES) {
    pos += interpolate(frame, [c + DUR, c + DUR + ROLL_DUR], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: ROLL_EASE,
    });
  }
  return pos;
};

const DigitRollCol: React.FC<{ pos: number; size: number; color: string; blur: number }> = ({
  pos,
  size,
  color,
  blur,
}) => {
  const lineH = size * 1.12;
  return (
    <span style={{ display: 'inline-flex', overflow: 'hidden', height: lineH, verticalAlign: 'bottom' }}>
      <span style={{ display: 'inline-block', height: lineH }}>
        <span style={{ display: 'block', transform: `translateY(${(-pos * lineH).toFixed(2)}px)`, filter: blur > 0.3 ? `blur(${blur.toFixed(2)}px)` : undefined }}>
          {(DIGITS + DIGITS).split('').map((d, j) => (
            <span
              key={j}
              style={{
                display: 'block',
                fontFamily: SIGHT.fontSans,
                fontWeight: 800,
                fontSize: size,
                letterSpacing: '-0.04em',
                lineHeight: `${lineH}px`,
                color,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {d}
            </span>
          ))}
        </span>
      </span>
    </span>
  );
};

const flyT = (i: number, f: number) =>
  interpolate(f, [TIMELINE_CUES[i], TIMELINE_CUES[i] + DUR], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: FLY_EASE,
  });
const flyY = (i: number, f: number) => 560 * (1 - flyT(i, f));

// 每条 tl-entry 顶行「时间窗口」徽章大致位置（卡内坐标）
const HL_W = [420, 490, 440, 460, 450];

export const SceneTimelineStack: React.FC<Partial<typeof SCENE_TIMELINE_STACK_DEFAULTS>> = ({
  title = SCENE_TIMELINE_STACK_DEFAULTS.title,
  subtitle = SCENE_TIMELINE_STACK_DEFAULTS.subtitle,
  counterSize = SCENE_TIMELINE_STACK_DEFAULTS.counterSize,
  accent = SCENE_TIMELINE_STACK_DEFAULTS.accent,
  muted = SCENE_TIMELINE_STACK_DEFAULTS.muted,
}) => {
  const frame = useCurrentFrame();
  const rollPos = rollAt(frame);
  const rollV = Math.abs(velocity(rollAt, frame));

  // 预备拍（0–6f）
  const antT = interpolate(frame, [0, 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.quad),
  });
  const counterScale = 0.94 + 0.06 * antT;
  const counterOpacity = 0.25 + 0.75 * antT;

  const stackPress = (settledIndex: number) => {
    let press = 0;
    for (let j = settledIndex + 1; j < TIMELINE_CUES.length; j++) {
      const cue = TIMELINE_CUES[j];
      const p = interpolate(frame, [cue, cue + 4, cue + 8], [0, 6, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: Easing.inOut(Easing.sin),
      });
      press = Math.max(press, p);
    }
    return press;
  };

  // 单次冷白柔光扫过整摞（仅最后一张落定后，裁进圆角，Q4）
  const glazeX = interpolate(frame, [78, 92], [-460, 2240], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.45, 0, 0.35, 1),
  });
  const glazeVis = interpolate(frame, [78, 81, 89, 92], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ backgroundColor: SIGHT.bg }}>
      <PageCam src="textures/live/timeline-full.png" pageH={PAGE_H} keys={CAM_KEYS} ease={LINEAR} bg={SIGHT.bg}>
        {/* 盖住已印在整页上的条目，留出空槽等待真实卡片压入 */}
        {entries.map((c, i) => (
          <div
            key={`slot-${i}`}
            style={{
              position: 'absolute',
              left: c.x - 4,
              top: c.y - 2,
              width: c.w + 8,
              height: c.h + 4,
              background: '#ffffff',
              opacity: frame >= TIMELINE_CUES[i] + DUR - 2 ? 0 : 1,
            }}
          />
        ))}

        {entries.map((c, i) => {
          const cue = TIMELINE_CUES[i];
          const t = flyT(i, frame);
          if (t <= 0) return null;
          const settled = t >= 0.999;
          const dy = flyY(i, frame) + (settled ? stackPress(i) : 0);
          const rot = TILTS[i] * (1 - t);
          const scale = 1.05 - 0.05 * t;
          const elev = settled ? 3 - stackPress(i) * 0.3 : 3 + 48 * Math.min(1, Math.max(0, 1 - t));
          const vy = settled ? 0 : velocity((f) => flyY(i, f), frame);

          const hlStart = cue + DUR + 3;
          const hlGrow = interpolate(frame, [hlStart, hlStart + 7], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: Easing.bezier(0.3, 0, 0.2, 1),
          });
          const hlFade = interpolate(frame, [hlStart + 7, hlStart + 13], [1, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });

          const card = (
            <div
              style={{
                position: 'absolute',
                left: c.x,
                top: c.y,
                width: c.w,
                height: c.h,
                transform: `translateY(${dy.toFixed(3)}px) rotate(${rot.toFixed(4)}deg) scale(${scale.toFixed(5)})`,
                transformOrigin: 'center center',
                borderRadius: 10,
                boxShadow: softShadow(elev, { color: '#0f172a', strength: 0.95 }),
              }}
            >
              <div style={{ position: 'absolute', inset: 0, borderRadius: 10, overflow: 'hidden' }}>
                <Img src={staticFile(`textures/live/${c.file}`)} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }} />
                {/* 滞后蓝色荧光底色条（multiply 叠在标题行下，不洗字） */}
                {hlGrow > 0 && hlFade > 0 ? (
                  <div
                    style={{
                      position: 'absolute',
                      left: 42,
                      top: 32,
                      height: 22,
                      width: HL_W[i] * hlGrow,
                      borderRadius: 4,
                      background: '#dbeafe',
                      mixBlendMode: 'multiply',
                      opacity: 0.9 * hlFade,
                      pointerEvents: 'none',
                    }}
                  />
                ) : null}
                {/* 单次整摞冷白扫光，严格裁在卡片圆角内 */}
                {glazeVis > 0 && (
                  <div
                    style={{
                      position: 'absolute',
                      top: -160,
                      height: c.h + 320,
                      left: glazeX - c.x - (c.y - 160) * 0.22,
                      width: 340,
                      transform: 'rotate(14deg)',
                      opacity: glazeVis * 0.52,
                      mixBlendMode: 'soft-light',
                      background: 'linear-gradient(90deg, rgba(219,234,254,0), rgba(147,197,253,0.9) 48%, rgba(219,234,254,0))',
                      pointerEvents: 'none',
                    }}
                  />
                )}
              </div>
              <div style={{ position: 'absolute', inset: 0, borderRadius: 10, boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.9)', pointerEvents: 'none' }} />
            </div>
          );

          return Math.abs(vy) > 1 ? (
            <SpeedBlur key={c.file} vx={0} vy={vy} amount={0.2} max={12}>
              {card}
            </SpeedBlur>
          ) : (
            <React.Fragment key={c.file}>{card}</React.Fragment>
          );
        })}
      </PageCam>

      {/* 右上角屏幕空间计数器（Q11 辅助文字清晰 ≥32px，DigitRoll 同步落定） */}
      <div
        style={{
          position: 'absolute',
          top: 76,
          right: 76,
          textAlign: 'right',
          pointerEvents: 'none',
          opacity: counterOpacity,
          transform: `scale(${counterScale.toFixed(4)})`,
          transformOrigin: 'top right',
          background: 'rgba(255,255,255,0.92)',
          border: `1px solid ${SIGHT.borderStrong}`,
          borderRadius: 16,
          padding: '22px 28px',
          boxShadow: '0 16px 40px rgba(16,24,40,0.09)',
        }}
      >
        <div
          style={{
            fontFamily: SIGHT.fontMono,
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: '0.14em',
            color: muted,
          }}
        >
          {title}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline', marginTop: 4 }}>
          <span style={{ fontFamily: SIGHT.fontSans, fontWeight: 800, fontSize: counterSize, color: accent, lineHeight: 1.12 }}>0</span>
          <DigitRollCol pos={rollPos} size={counterSize} color={accent} blur={Math.min(6, rollV * 28)} />
        </div>
        <div style={{ height: 2, background: SIGHT.border, margin: '8px 0 12px auto', width: 220 }} />
        <div style={{ fontFamily: SIGHT.fontSans, fontSize: 28, fontWeight: 600, color: SIGHT.ink }}>{subtitle}</div>
      </div>
    </AbsoluteFill>
  );
};
