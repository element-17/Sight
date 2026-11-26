// SightTitleCard.tsx — 呼吸引导字卡（沿用 paper-title-card 压印曲线与 DigitRoll，完全重蒙皮为 Sight 冷白+钴蓝）
import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, Easing } from 'remotion';
import { parseTitleWords } from '../timeline';
import { SIGHT } from '../lib/SightBrand';

export const TITLE_CARD_DEFAULTS = {
  fontSize: 96,
  ink: SIGHT.ink,
  accent: SIGHT.accent,
  muted: SIGHT.ink2,
  bg: SIGHT.bg,
};

const DIGITS = '0123456789';

const DigitColumn: React.FC<{ ch: string; delay: number; lineH: number; color: string; size: number }> = ({
  ch,
  delay,
  lineH,
  color,
  size,
}) => {
  const frame = useCurrentFrame();
  if (ch < '0' || ch > '9') {
    return <span style={{ fontSize: size, lineHeight: `${lineH}px`, color }}>{ch}</span>;
  }
  const target = DIGITS.indexOf(ch);
  const t = interpolate(frame, [delay, delay + 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0.8, 0.25, 1),
  });
  const offset = (10 + target) * t * lineH;
  return (
    <span style={{ display: 'inline-block', height: lineH }}>
      <span style={{ display: 'block', transform: `translateY(${-offset}px)` }}>
        {(DIGITS + DIGITS).split('').map((d, j) => (
          <span
            key={j}
            style={{
              display: 'block',
              fontSize: size,
              fontWeight: 800,
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
  );
};

export const SightTitleCard: React.FC<
  Partial<typeof TITLE_CARD_DEFAULTS> & {
    text: string;
    sub?: string;
    subDigits?: string;
    duration?: number;
  }
> = ({
  text,
  sub = '',
  subDigits = '',
  duration = 59,
  fontSize = TITLE_CARD_DEFAULTS.fontSize,
  ink = TITLE_CARD_DEFAULTS.ink,
  accent = TITLE_CARD_DEFAULTS.accent,
  muted = TITLE_CARD_DEFAULTS.muted,
  bg = TITLE_CARD_DEFAULTS.bg,
}) => {
  const frame = useCurrentFrame();
  const words = parseTitleWords(text);

  const fadeOut = interpolate(frame, [Math.max(10, duration - 8), duration], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const underline = interpolate(frame, [16, 34], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });
  const subT = interpolate(frame, [10, 22], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const subFontSize = 34; // Q11 辅助文字 ≥32px
  const lineH = subFontSize * 1.15;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: bg,
        justifyContent: 'center',
        alignItems: 'center',
        opacity: fadeOut,
        backgroundImage:
          'radial-gradient(1200px 760px at 50% 42%, rgba(255,255,255,0.92), rgba(237,242,253,0.42) 56%, transparent 80%)',
      }}
    >
      {/* 极淡工程点阵底纹（呼应 Sight 情报工作台气质） */}
      <AbsoluteFill
        style={{
          pointerEvents: 'none',
          backgroundImage: 'radial-gradient(circle, rgba(53,101,224,0.09) 1.2px, transparent 1.4px)',
          backgroundSize: '36px 36px',
          maskImage: 'radial-gradient(ellipse 75% 75% at 50% 50%, #000 30%, transparent 88%)',
          WebkitMaskImage: 'radial-gradient(ellipse 75% 75% at 50% 50%, #000 30%, transparent 88%)',
        }}
      />

      <div style={{ textAlign: 'center', maxWidth: 1620, padding: '0 60px' }}>
        <div
          style={{
            fontFamily: SIGHT.fontSans,
            fontSize,
            fontWeight: 800,
            lineHeight: 1.26,
            color: ink,
            letterSpacing: '-0.02em',
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'center',
            columnGap: '0.12em',
          }}
        >
          {words.map((w, i) => {
            const delay = 4 + i * 4;
            const t = interpolate(frame, [delay, delay + 9], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
              easing: Easing.bezier(0.2, 0.75, 0.3, 1),
            });
            return (
              <React.Fragment key={i}>
                <span
                  style={{
                    opacity: t,
                    transform: `scale(${(1.26 - 0.26 * t).toFixed(4)})`,
                    filter: t < 0.99 ? `blur(${((1 - t) * 7).toFixed(2)}px)` : undefined,
                    display: 'inline-block',
                    color: w.accent ? accent : undefined,
                  }}
                >
                  {w.text}
                </span>
                {w.br && <span style={{ flexBasis: '100%', height: 0 }} />}
              </React.Fragment>
            );
          })}
        </div>

        <div
          style={{
            height: 6,
            width: 220,
            margin: '38px auto 0',
            borderRadius: 3,
            background: accent,
            transform: `scaleX(${underline})`,
          }}
        />

        {(sub || subDigits) && (
          <div
            style={{
              fontFamily: SIGHT.fontSans,
              fontSize: subFontSize,
              fontWeight: 600,
              letterSpacing: '0.04em',
              color: muted,
              marginTop: 34,
              opacity: subT,
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'baseline',
              gap: '0.28em',
            }}
          >
            {subDigits ? (
              <span style={{ display: 'inline-flex', overflow: 'hidden', height: lineH, verticalAlign: 'bottom' }}>
                {subDigits.split('').map((c, i) => (
                  <DigitColumn key={i} ch={c} delay={10 + i * 4} lineH={lineH} color={accent} size={subFontSize + 6} />
                ))}
              </span>
            ) : null}
            <span>{sub}</span>
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
