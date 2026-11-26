// SightBrand.tsx — 从 Sight 源码 style.css / platforms.ts / favicon.svg 提取的原生视觉资产
import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, Easing } from 'remotion';

export const SIGHT = {
  bg: '#f6f7f9',
  surface: '#ffffff',
  surfaceSoft: '#f0f3f8',
  border: '#e6e8eb',
  borderStrong: '#d5d8dd',
  ink: '#1c1f23',
  ink2: '#5c6470',
  ink3: '#8f98a6',
  accent: '#3565e0',
  accentDeep: '#1d4ed8',
  accentLight: '#60a5fa',
  accentSoft: '#edf2fd',
  stageDarkTop: '#0e172a',
  stageDarkMid: '#0a1020',
  stageDarkBot: '#050812',
  success: '#1e9e55',
  danger: '#d5372f',
  fontSans:
    '"Microsoft YaHei", "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
  fontMono: '"JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, Menlo, monospace',
} as const;

export const PLATFORM_DOTS = [
  { id: 'bilibili', name: '哔哩哔哩', color: '#fb7299' },
  { id: 'douyin', name: '抖音', color: '#fe2c55' },
  { id: 'xhs', name: '小红书', color: '#ff2442' },
  { id: 'weibo', name: '微博', color: '#e6702e' },
  { id: 'github', name: 'GitHub', color: '#24292f' },
  { id: 'netease', name: '网易云', color: '#e60026' },
  { id: 'qqmusic', name: 'QQ音乐', color: '#31c27c' },
  { id: 'genshin', name: '原神', color: '#3565e0' },
] as const;

// 源自 frontend/public/favicon.svg 的 Sight 标志（蓝底白眼）
export const SightMark: React.FC<{ size?: number; glow?: boolean }> = ({ size = 48, glow = false }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    style={{
      display: 'block',
      flexShrink: 0,
      filter: glow ? 'drop-shadow(0 10px 26px rgba(53,101,224,0.45))' : undefined,
    }}
  >
    <rect width="24" height="24" rx="6" fill={SIGHT.accent} />
    <path
      d="M4.5 12s3-5.5 7.5-5.5S19.5 12 19.5 12s-3 5.5-7.5 5.5S4.5 12 4.5 12z"
      stroke="#ffffff"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <circle cx="12" cy="12" r="2.6" fill="#ffffff" />
  </svg>
);

// Q11 严格达标叙事主字幕条（56px 粗体中文字幕 + 深蓝灰磨砂底衬 + 钴蓝方点，手机端 480px 小窗清晰可读）
export const CAPTION_DEFAULTS = {
  fontSize: 56,
  bottom: 40,
  color: '#ffffff',
  accent: SIGHT.accent,
  bg: 'rgba(13, 21, 38, 0.88)',
};

export const SightCaption: React.FC<
  Partial<typeof CAPTION_DEFAULTS> & { text: string; duration: number }
> = ({
  text,
  duration,
  fontSize = CAPTION_DEFAULTS.fontSize,
  bottom = CAPTION_DEFAULTS.bottom,
  color = CAPTION_DEFAULTS.color,
  accent = CAPTION_DEFAULTS.accent,
  bg = CAPTION_DEFAULTS.bg,
}) => {
  const frame = useCurrentFrame();
  const inT = interpolate(frame, [0, 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const outT = interpolate(frame, [Math.max(8, duration - 8), duration], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = inT * outT;
  if (opacity <= 0.002) return null;

  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom,
        display: 'flex',
        justifyContent: 'center',
        pointerEvents: 'none',
        opacity,
        transform: `translateY(${((1 - inT) * 14).toFixed(2)}px)`,
      }}
    >
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 18,
          padding: '12px 34px',
          borderRadius: 16,
          background: bg,
          border: '1px solid rgba(255,255,255,0.14)',
          boxShadow: '0 14px 36px rgba(8, 15, 32, 0.32)',
          maxWidth: 1760,
        }}
      >
        <span
          style={{
            width: 14,
            height: 14,
            borderRadius: 3,
            background: accent,
            boxShadow: `0 0 12px ${accent}`,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontFamily: SIGHT.fontSans,
            fontSize,
            fontWeight: 700,
            lineHeight: 1.18,
            color,
            letterSpacing: '0.01em',
            whiteSpace: 'nowrap',
          }}
        >
          {text}
        </span>
      </div>
    </div>
  );
};

// Sight 冷白钴蓝闪转场（只盖硬切两侧 ±5f，不漂移暖黄）
export const SightFlashCut: React.FC<{ duration?: number }> = ({ duration = 10 }) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [0, duration * 0.4, duration], [0, 0.88, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill
      style={{
        pointerEvents: 'none',
        opacity: o,
        background:
          'radial-gradient(ellipse at 50% 48%, rgba(246,249,255,0.98), rgba(219,234,254,0.62) 55%, transparent 82%)',
      }}
    />
  );
};
