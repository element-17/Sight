// SceneMaskOpen.tsx — S1 开场品牌钩子（忠实复刻 demos/opening/text-as-mask/TextAsMask.tsx 运动语法与参数）
// 瓷白舞台（Sight #f6f7f9）切出巨型 SIGHT 字形，字腔内透出暗色 8 平台实时雷达流线画板；
// 品牌落定 hold > 1.5s（满足 R1），随后吸气 8f → 对数指数 46× 冲入 I 竖笔，无缝接管进入产品世界。
import React from 'react';
import { AbsoluteFill, useCurrentFrame, interpolate } from 'remotion';
import { EASE, bezier, ramp } from '../lib/Polish';
import { LOOKS, Stage } from '../lib/Look';
import { PLATFORM_DOTS, SIGHT, SightMark } from '../lib/SightBrand';

export const SCENE_MASK_OPEN_DEFAULTS = {
  word: 'SIGHT',
  kicker: '开源 · 8大公开平台图谱与 AI 侧写',
  subtitle: '从碎片公开信息，一键构建完整数字画像',
  accent: SIGHT.accent,
  ink: SIGHT.ink,
  ink2: SIGHT.ink2,
};

const L = LOOKS.porcelain;
const FONT_STACK = 'system-ui, -apple-system, Segoe UI, Helvetica Neue, Arial, sans-serif';
const FS = 450;
const BASE_Y = 706;
// 放大原点钉在「I」竖笔正中（SIGHT 5 字中第 2 字 I 为实心竖杠，经计算与静帧校准确认）
const ORIGIN_X = 766;
const ORIGIN_Y = 542;
const ORIGIN = `${ORIGIN_X}px ${ORIGIN_Y}px`;
const MAX_S = 46;

// 节拍（总长 179f @30fps，b0–b12）
const IN_END = 18;
const DRIFT0 = 18;
const DRIFT1 = 106; // 留足 >1.8s 品牌清晰阅读 hold（R1）
const BREATH0 = 106;
const RUSH0 = 114;
const RUSH1 = 138;
const LAND1 = 144;
const DASH_S0 = 1.32;

const wave = (u: number) =>
  0.5 +
  0.17 * Math.sin(u * 0.12) +
  0.09 * Math.sin(u * 0.29 + 1.1) +
  0.06 * Math.sin(u * 0.67 + 0.4) +
  0.12 * Math.max(0, Math.sin(u * 0.05 - 0.5));

// 窗内暗色实时 Sight 情报总览看板（满足 text-as-mask 已知坑：高对比深蓝底 + 钴蓝/青亮线 + 8 平台脉冲，
// 让笔画内一眼看出"窗外有个活着的系统"，接管后过渡到真实 Sight 页面）
const SightRadarViewport: React.FC<{ frame: number; accent: string }> = ({ frame, accent }) => {
  const flow = frame * 0.58;
  const CW = 1540;
  const CH = 380;
  const N = 92;
  const pts = Array.from({ length: N + 1 }, (_, i) => {
    const x = (i / N) * CW;
    const y = CH - wave(i + flow) * CH * 0.9;
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const area = `${line} L${CW} ${CH} L0 ${CH} Z`;
  const last = pts[pts.length - 1];
  const nodesCount = Math.round(18 + 14 * ramp(frame, 10, 120, EASE.out));
  const bars = Array.from(
    { length: 24 },
    (_, i) => 0.32 + 0.58 * Math.abs(Math.sin(i * 1.65 + frame * 0.06)) * (0.65 + 0.35 * Math.sin(i * 0.4)),
  );

  // 确定性关系网络节点星座（装饰背景信号，非复刻真实界面）
  const graphNodes = PLATFORM_DOTS.map((p, i) => {
    const ang = (i / PLATFORM_DOTS.length) * Math.PI * 2 + frame * 0.008;
    const rx = 210 + (i % 2) * 45;
    const ry = 105 + ((i + 1) % 2) * 28;
    return { ...p, x: 1320 + Math.cos(ang) * rx, y: 260 + Math.sin(ang) * ry };
  });

  const panelBg = 'linear-gradient(180deg, #131f3e, #0e1730)';
  const lineCol = 'rgba(148,184,255,0.14)';

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: 'radial-gradient(ellipse 74% 62% at 56% 32%, #15285a 0%, #0a1022 72%)',
        fontFamily: SIGHT.fontSans,
        color: '#eef4ff',
      }}
    >
      {/* 左侧 8 平台实况栏 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: 244,
          borderRight: `1px solid ${lineCol}`,
          padding: '38px 26px',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <SightMark size={40} />
          <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: '-0.02em' }}>Sight</div>
        </div>
        <div style={{ marginTop: 34, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {PLATFORM_DOTS.map((p, i) => (
            <div
              key={p.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 14px',
                borderRadius: 10,
                background: i === 0 ? 'rgba(53,101,224,0.24)' : 'rgba(255,255,255,0.02)',
                fontSize: 22,
                color: i === 0 ? '#ffffff' : '#9fb0d3',
                fontWeight: i === 0 ? 700 : 500,
              }}
            >
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: p.color }} />
              <span>{p.name}</span>
              <span
                style={{
                  marginLeft: 'auto',
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: '#22c55e',
                  boxShadow: '0 0 8px #22c55e',
                }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* 顶栏标题 */}
      <div style={{ position: 'absolute', left: 292, top: 44, display: 'flex', alignItems: 'center', gap: 18 }}>
        <div style={{ fontSize: 48, fontWeight: 800, letterSpacing: '-0.02em' }}>多源实体信号流 · Sight Engine</div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '8px 18px',
            borderRadius: 999,
            background: 'rgba(34,197,94,0.16)',
            color: '#4ade80',
            fontSize: 22,
            fontWeight: 700,
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 5,
              background: '#4ade80',
              opacity: 0.6 + 0.4 * Math.sin(frame / 4),
            }}
          />
          LIVE SSE
        </div>
      </div>

      {/* KPI 三卡 */}
      <div
        style={{
          position: 'absolute',
          left: 292,
          top: 146,
          width: 470,
          height: 196,
          borderRadius: 20,
          background: panelBg,
          boxShadow: `0 0 0 1px ${lineCol}`,
          padding: '26px 30px',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ fontSize: 22, fontWeight: 600, color: '#9fb0d3', letterSpacing: '0.08em' }}>ACTIVE PLATFORMS</div>
        <div style={{ fontSize: 92, fontWeight: 800, marginTop: 8, color: '#ffffff', fontVariantNumeric: 'tabular-nums' }}>
          08<span style={{ fontSize: 34, color: '#60a5fa', marginLeft: 12 }}>ADAPTERS</span>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 786,
          top: 146,
          width: 450,
          height: 196,
          borderRadius: 20,
          background: panelBg,
          boxShadow: `0 0 0 1px ${lineCol}`,
          padding: '26px 30px',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ fontSize: 22, fontWeight: 600, color: '#9fb0d3', letterSpacing: '0.08em' }}>GRAPH ENTITIES</div>
        <div style={{ fontSize: 92, fontWeight: 800, marginTop: 8, color: '#38bdf8', fontVariantNumeric: 'tabular-nums' }}>
          {nodesCount}
          <span style={{ fontSize: 30, color: '#9fb0d3', marginLeft: 12 }}>NODES</span>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 1260,
          top: 146,
          width: 600,
          height: 196,
          borderRadius: 20,
          background: panelBg,
          boxShadow: `0 0 0 1px ${lineCol}`,
          padding: '26px 30px',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ fontSize: 22, fontWeight: 600, color: '#9fb0d3', letterSpacing: '0.08em' }}>MULTIMODAL QUEUE</div>
        <svg width={520} height={96} style={{ marginTop: 14 }}>
          {bars.map((b, i) => (
            <rect
              key={i}
              x={i * 21.5}
              y={96 - b * 96}
              width={13}
              height={b * 96}
              rx={3}
              fill={i > 16 ? '#38bdf8' : accent}
              opacity={0.55 + 0.45 * b}
            />
          ))}
        </svg>
      </div>

      {/* 主图：钴蓝→青 流式面积图（正好穿过 SIGHT 笔画腰线） */}
      <div
        style={{
          position: 'absolute',
          left: 292,
          top: 370,
          width: 1568,
          height: 480,
          borderRadius: 22,
          background: panelBg,
          boxShadow: `0 0 0 1px ${lineCol}`,
          padding: '26px 30px',
          boxSizing: 'border-box',
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 22, color: '#9fb0d3' }}>
          <span>SNAPSHOT DIFF & GRAPH EXPANSION THROUGHPUT</span>
          <span style={{ fontFamily: SIGHT.fontMono, color: '#60a5fa' }}>30m TTL · SQLITE · LANGGRAPH</span>
        </div>
        <svg width={CW} height={CH} style={{ position: 'absolute', left: 12, top: 76, overflow: 'visible' }}>
          <defs>
            <linearGradient id="sight-tam-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={accent} stopOpacity={0.62} />
              <stop offset="1" stopColor={accent} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="sight-tam-line" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor={accent} />
              <stop offset="0.55" stopColor="#38bdf8" />
              <stop offset="1" stopColor="#22d3ee" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((g) => (
            <line key={g} x1={0} x2={CW} y1={CH * g} y2={CH * g} stroke={lineCol} strokeWidth={1.5} />
          ))}
          <path d={area} fill="url(#sight-tam-area)" />
          <path d={line} fill="none" stroke="url(#sight-tam-line)" strokeWidth={6} strokeLinejoin="round" />
          <circle cx={last[0]} cy={last[1]} r={11} fill="#22d3ee" />
          <circle cx={last[0]} cy={last[1]} r={24} fill="#22d3ee" opacity={0.25} />
        </svg>
        {/* 右上浮动节点星座 */}
        <svg width={1568} height={480} style={{ position: 'absolute', inset: 0, pointerEvents: 'none', opacity: 0.55 }}>
          {graphNodes.map((n, i) => (
            <line key={`l-${i}`} x1={1320} y1={260} x2={n.x} y2={n.y} stroke="#60a5fa" strokeWidth={1.5} strokeOpacity={0.4} />
          ))}
          <circle cx={1320} cy={260} r={14} fill={accent} />
          {graphNodes.map((n) => (
            <circle key={n.id} cx={n.x} cy={n.y} r={9} fill={n.color} />
          ))}
        </svg>
      </div>

      {/* 底部 4 模块进度条 */}
      <div
        style={{
          position: 'absolute',
          left: 292,
          top: 874,
          width: 1568,
          height: 162,
          borderRadius: 20,
          background: panelBg,
          boxShadow: `0 0 0 1px ${lineCol}`,
          padding: '0 36px',
          boxSizing: 'border-box',
          display: 'flex',
          alignItems: 'center',
          gap: 44,
        }}
      >
        {[
          ['8 平台聚合', 0.96],
          ['ECharts 关系图谱', 0.88],
          ['快照 Diff 时间线', 0.82],
          ['LangGraph 多模态 AI', 0.94],
        ].map(([label, val]) => (
          <div key={label as string} style={{ flex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 24 }}>
              <span style={{ color: '#cbd5e1', fontWeight: 600 }}>{label as string}</span>
              <span style={{ fontFamily: SIGHT.fontMono, color: '#60a5fa', fontWeight: 700 }}>
                {Math.round((val as number) * 100)}%
              </span>
            </div>
            <div style={{ marginTop: 14, height: 10, borderRadius: 5, background: 'rgba(148,184,255,0.12)' }}>
              <div
                style={{
                  width: `${(val as number) * 100}%`,
                  height: '100%',
                  borderRadius: 5,
                  background: `linear-gradient(90deg, ${accent}, #38bdf8)`,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export const SceneMaskOpen: React.FC<Partial<typeof SCENE_MASK_OPEN_DEFAULTS>> = ({
  word = SCENE_MASK_OPEN_DEFAULTS.word,
  kicker = SCENE_MASK_OPEN_DEFAULTS.kicker,
  subtitle = SCENE_MASK_OPEN_DEFAULTS.subtitle,
  accent = SCENE_MASK_OPEN_DEFAULTS.accent,
  ink = SCENE_MASK_OPEN_DEFAULTS.ink,
  ink2 = SCENE_MASK_OPEN_DEFAULTS.ink2,
}) => {
  const f = useCurrentFrame();
  const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

  const textAttrs = `x="960" y="${BASE_Y}" font-family="${FONT_STACK}" font-size="${FS}" font-weight="900" letter-spacing="-18" text-anchor="middle"`;
  const maskSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><text ${textAttrs} fill="white">${word}</text></svg>`;
  const maskUrl = `url("data:image/svg+xml,${encodeURIComponent(maskSvg)}")`;
  const shadowSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><text ${textAttrs} fill="#0c1a3a">${word}</text></svg>`;
  const shadowUrl = `data:image/svg+xml,${encodeURIComponent(shadowSvg)}`;

  // 严格沿用 TextAsMask.tsx 参数：基线擦出 + 1.04→1 落定 → 字内平移 → 吸气 → 46× 对数加速冲入
  const intro = ramp(f, 0, IN_END, EASE.snappy);
  const wipe = ramp(f, 0, 16, EASE.out);
  const introS = 1.04 - 0.04 * intro;

  const breath = ramp(f, BREATH0, RUSH0 - BREATH0, EASE.swift);
  const rush = Math.pow(ramp(f, RUSH0, RUSH1 - RUSH0, EASE.linear), 1.8);
  const s0 = introS * (1 - 0.035 * breath);
  const maskS = s0 * Math.pow(MAX_S / s0, rush);

  const cdx = (960 - ORIGIN_X) * rush;
  const cdy = (540 - ORIGIN_Y) * rush;
  const wrapT = `translate(${cdx.toFixed(2)}px, ${cdy.toFixed(2)}px) scale(${maskS})`;
  const innerT = `scale(${1 / maskS}) translate(${(-cdx).toFixed(2)}px, ${(-cdy).toFixed(2)}px)`;

  const drift = ramp(f, DRIFT0, DRIFT1 - DRIFT0, bezier(0.3, 0, 0.7, 1));
  const land = ramp(f, RUSH0, LAND1 - RUSH0, EASE.snappy);
  const dx = (150 - 300 * drift) * (1 - land);
  const dy = -110 * (1 - land);
  const dashS = DASH_S0 + (1 - DASH_S0) * land;
  const cover = interpolate(rush, [0.86, 0.95], [0, 1], clamp);
  const rim = 1 - interpolate(rush, [0, 0.25], [0, 1], clamp);

  const eyebrow = ramp(f, 6, 20, EASE.out);
  const sub = ramp(f, 14, 18, EASE.out);
  const out = 1 - ramp(f, BREATH0, 10, EASE.exit);

  const dash = (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        transform: `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px) scale(${dashS.toFixed(4)})`,
        transformOrigin: '50% 50%',
      }}
    >
      <SightRadarViewport frame={f} accent={accent} />
    </div>
  );

  const clipBottom = `inset(0 0 ${((1 - wipe) * (1080 - BASE_Y + FS * 0.74)).toFixed(1)}px 0)`;

  return (
    <AbsoluteFill style={{ background: SIGHT.bg, overflow: 'hidden' }}>
      <Stage look={L} keyLight={{ x: 0.42, y: 0.12 }} fill={{ x: 0.85, y: 0.9 }} vignette={0.18} />

      {/* 字形深蓝软影 */}
      <img
        src={shadowUrl}
        style={{
          position: 'absolute',
          left: 0,
          top: 26,
          width: 1920,
          height: 1080,
          opacity: 0.22 * rim * intro,
          filter: 'blur(22px)',
          transform: wrapT,
          transformOrigin: ORIGIN,
          clipPath: clipBottom,
        }}
      />

      {/* 字形遮罩层：wrapper 放大，inner 反向补偿不畸变 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          transform: wrapT,
          transformOrigin: ORIGIN,
          clipPath: clipBottom,
          WebkitMaskImage: maskUrl,
          maskImage: maskUrl,
          WebkitMaskRepeat: 'no-repeat',
          maskRepeat: 'no-repeat',
          WebkitMaskSize: '1920px 1080px',
          maskSize: '1920px 1080px',
        }}
      >
        <div style={{ position: 'absolute', inset: 0, transform: innerT, transformOrigin: ORIGIN }}>{dash}</div>
      </div>

      {/* 接管层：冲入后段（S≈24×）无缝补齐字缝 */}
      {cover > 0 && <div style={{ position: 'absolute', inset: 0, opacity: cover }}>{dash}</div>}

      {/* 眉题：Sight 蓝眼睛图标 + 开源定位 */}
      <div style={{ position: 'absolute', top: 204, width: '100%', textAlign: 'center', opacity: eyebrow * out }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 16, verticalAlign: 'middle' }}>
          <SightMark size={50} glow />
          <span
            style={{
              fontFamily: SIGHT.fontSans,
              fontSize: 36,
              fontWeight: 700,
              color: ink,
              letterSpacing: `${(0.02 + (1 - eyebrow) * 0.16).toFixed(3)}em`,
            }}
          >
            {kicker}
          </span>
        </span>
      </div>

      {/* 副题 + 8 平台色点 */}
      <div
        style={{
          position: 'absolute',
          top: BASE_Y + 72,
          width: '100%',
          textAlign: 'center',
          opacity: sub * out,
          transform: `translateY(${((1 - sub) * 16).toFixed(2)}px)`,
        }}
      >
        <div
          style={{
            fontFamily: SIGHT.fontSans,
            fontSize: 42,
            fontWeight: 600,
            color: ink2,
            letterSpacing: '0.01em',
          }}
        >
          {subtitle}
        </div>
        <div style={{ display: 'inline-flex', gap: 14, marginTop: 22 }}>
          {PLATFORM_DOTS.map((p) => (
            <span
              key={p.id}
              style={{
                width: 13,
                height: 13,
                borderRadius: '50%',
                background: p.color,
                boxShadow: '0 2px 8px rgba(15,23,42,0.16)',
              }}
            />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
