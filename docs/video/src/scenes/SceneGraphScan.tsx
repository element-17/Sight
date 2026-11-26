// SceneGraphScan.tsx — S4 ECharts 6 交互式社交关系图谱 + 实时 SSE 终端
// （忠实复刻 demos/effects/scanline-annotate-focus/ScanlineAnnotateFocus.tsx）
// 一条深科技蓝扫描线自上而下严格匀速掠过真实 graph-full.png 浏览器窗，越过各真实模块下缘即弹出
// 四角 L 取景框（spring damping 15 过冲锁定）+ 逐字打出的机器标注签，顶栏实时计数 00/05 → 05/05，
// 之后留足 65f+ hold 供观众读清图谱拓扑与实时日志。
import React from 'react';
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from 'remotion';
import { EASE, ramp, softShadow } from '../lib/Polish';
import { LOOKS, Stage, alpha, springAt } from '../lib/Look';
import { SIGHT } from '../lib/SightBrand';

export const SCENE_GRAPH_SCAN_DEFAULTS = {
  statusScanning: 'SCANNING TOPOLOGY',
  statusDone: 'GRAPH LOCKED',
  productTag: 'Sight · 跨平台关系图谱与 SSE 终端',
  machineColor: SIGHT.accentDeep,
};

const L = LOOKS.porcelain;
const MONO = SIGHT.fontMono;

// 浏览器窗（帧坐标：1920×1080 中居中留足顶部状态栏 + 底部 56px 字幕胶囊空间）
const WX = 190;
const WY = 122;
const WW = 1540;
const CHROME = 42;
const IMG_H = Math.round((WW * 1080) / 1920); // 866px 完整 16:9，无裁剪
const WH = CHROME + Math.min(782, IMG_H); // 824px，底缘 y=946，给底部 56px 字幕（y≈962..1040）留足呼吸间距
const SCALE = WW / 1920; // 0.8021

// 扫描线：严格匀速（零缓动，scanline-annotate-focus 命门！）
const SCAN0 = 8;
const SCAN1 = 92;
const Y0 = -16;
const Y1 = WH + 16;
const scanY = (f: number) => Y0 + (Y1 - Y0) * Math.min(1, Math.max(0, (f - SCAN0) / (SCAN1 - SCAN0)));
const frameAtY = (y: number) => SCAN0 + ((y - Y0) / (Y1 - Y0)) * (SCAN1 - SCAN0);

type TagPos = 'right' | 'above' | 'below' | 'belowRight' | 'left';
type Target = {
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
  head: string;
  detail: string;
  tag: TagPos;
  ft: number;
};

// 将 1920×1080 真实截图坐标精确映射到浏览器窗内坐标
const mapBox = (rx: number, ry: number, rw: number, rh: number) => ({
  x: Math.round(rx * SCALE),
  y: CHROME + Math.round(ry * SCALE),
  w: Math.round(rw * SCALE),
  h: Math.round(rh * SCALE),
});

export const GRAPH_SCAN_TARGETS: Target[] = (() => {
  const ts: Target[] = [
    {
      key: 'toolbar',
      ...mapBox(246, 68, 920, 174),
      head: 'FILTER',
      detail: '8 平台筛选 · 一键展开',
      tag: 'below',
      ft: 0,
    },
    {
      key: 'sidebar',
      ...mapBox(10, 66, 208, 300),
      head: 'POOL',
      detail: '8 平台多凭证绿灯在线',
      tag: 'right',
      ft: 0,
    },
    {
      key: 'sse',
      ...mapBox(1494, 42, 418, 370),
      head: 'SSE LOG',
      detail: '环形缓冲实时终端 · 熔断保护',
      tag: 'belowRight',
      ft: 0,
    },
    {
      key: 'cluster',
      ...mapBox(610, 380, 490, 390),
      head: 'TOPOLOGY',
      detail: '绿线互关 · 红线跨平台同名',
      tag: 'left',
      ft: 0,
    },
    {
      key: 'stats',
      ...mapBox(246, 895, 480, 56),
      head: 'PERSIST',
      detail: '21 节点 / 40 条边 SQLite 落库',
      tag: 'above',
      ft: 0,
    },
  ];
  // 按下缘严格排序，最小间隔 6f 防扎堆
  let prev = -99;
  for (const t of [...ts].sort((a, b) => a.y + a.h - (b.y + b.h))) {
    t.ft = Math.max(frameAtY(t.y + t.h), prev + 6);
    prev = t.ft;
  }
  return ts;
})();

const LAST_FIRE = Math.max(...GRAPH_SCAN_TARGETS.map((t) => t.ft));

const Bracket: React.FC<{ t: Target; frame: number; machine: string }> = ({ t, frame, machine }) => {
  const f = frame - t.ft;
  if (f < 0) return null;
  const s = springAt(frame, t.ft, { damping: 15, stiffness: 210 });
  const pad = 74 * (1 - s);
  const op = Math.min(1, f / 3);
  const arm = Math.min(34, Math.min(t.w, t.h) * 0.32) - 8 * ramp(frame, t.ft + 3, 12, EASE.out);
  const flash = ramp(frame, t.ft + 3, 3, EASE.out) * (1 - ramp(frame, t.ft + 6, 12, EASE.out));
  const x = t.x - pad;
  const y = t.y - pad;
  const w = t.w + pad * 2;
  const h = t.h + pad * 2;
  const d = [
    `M${x} ${y + arm}V${y}H${x + arm}`,
    `M${x + w - arm} ${y}H${x + w}V${y + arm}`,
    `M${x + w} ${y + h - arm}V${y + h}H${x + w - arm}`,
    `M${x + arm} ${y + h}H${x}V${y + h - arm}`,
  ].join('');
  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: t.x,
          top: t.y,
          width: t.w,
          height: t.h,
          borderRadius: 6,
          background: alpha(machine, 0.075 * flash),
          boxShadow: `inset 0 0 0 2px ${alpha(machine, 0.44 * flash)}`,
        }}
      />
      <svg width={WW} height={WH} style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', opacity: op }}>
        <path d={d} fill="none" stroke={machine} strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </>
  );
};

// 估算中英混排标签宽度（30px 字号，满足 Q11 清晰可读）
const TAG_H = 48;
const estimateTextW = (s: string) => {
  let w = 0;
  for (const ch of s) w += ch.charCodeAt(0) > 255 ? 29 : 16.5;
  return Math.round(w);
};

const Label: React.FC<{ t: Target; frame: number; machine: string }> = ({ t, frame, machine }) => {
  const s0 = t.ft + 5;
  if (frame < s0) return null;
  const rise = ramp(frame, s0, 12, EASE.out);
  const pop = ramp(frame, s0, 4, EASE.out);
  const full = `${t.head} · ${t.detail}`;
  const fullArr = Array.from(full);
  const typedF = Math.min(fullArr.length, (frame - s0) * 1.9 + 1);
  const typed = Math.floor(typedF);
  const wFull = estimateTextW(full) + 38;
  const wNow = Math.min(wFull, estimateTextW(fullArr.slice(0, typed).join('')) + 42);
  const typing = typed < fullArr.length;

  let x = t.x;
  let y = t.y;
  if (t.tag === 'right') {
    x = t.x + t.w + 14;
    y = t.y + 18;
  } else if (t.tag === 'left') {
    x = Math.max(12, t.x - wFull - 14);
    y = t.y + 24;
  } else if (t.tag === 'above') {
    x = t.x;
    y = t.y - TAG_H - 12;
  } else if (t.tag === 'below') {
    x = t.x;
    y = t.y + t.h + 12;
  } else if (t.tag === 'belowRight') {
    x = t.x + t.w - wFull;
    y = t.y + t.h + 12;
  }

  const headLen = Array.from(t.head).length;
  const head = fullArr.slice(0, Math.min(typed, headLen)).join('');
  const rest = typed > headLen ? fullArr.slice(headLen, typed).join('') : '';

  return (
    <div
      style={{
        position: 'absolute',
        left: t.tag === 'belowRight' ? x + wFull - wNow : x,
        top: y,
        width: wNow,
        height: TAG_H,
        borderRadius: 10,
        background: machine,
        boxShadow: `0 10px 24px -8px ${alpha('#0c1a5a', 0.52)}, inset 0 1px 0 rgba(255,255,255,0.22)`,
        opacity: pop,
        overflow: 'hidden',
        transform: `translateY(${((1 - rise) * 8).toFixed(2)}px)`,
        display: 'flex',
        alignItems: 'center',
        paddingLeft: 16,
        boxSizing: 'border-box',
        fontFamily: SIGHT.fontSans,
        fontSize: 28,
        whiteSpace: 'pre',
        color: '#ffffff',
      }}
    >
      <span style={{ fontFamily: MONO, fontWeight: 700, letterSpacing: '0.03em' }}>{head}</span>
      <span style={{ color: 'rgba(255,255,255,0.92)', fontWeight: 600 }}>{rest}</span>
      {typing && <span style={{ display: 'inline-block', width: 11, height: 24, marginLeft: 4, background: 'rgba(255,255,255,0.88)' }} />}
    </div>
  );
};

export const SceneGraphScan: React.FC<Partial<typeof SCENE_GRAPH_SCAN_DEFAULTS>> = ({
  statusScanning = SCENE_GRAPH_SCAN_DEFAULTS.statusScanning,
  statusDone = SCENE_GRAPH_SCAN_DEFAULTS.statusDone,
  productTag = SCENE_GRAPH_SCAN_DEFAULTS.productTag,
  machineColor = SCENE_GRAPH_SCAN_DEFAULTS.machineColor,
}) => {
  const frame = useCurrentFrame();
  const ly = scanY(frame);
  const lineOn = ramp(frame, SCAN0 - 4, 5, EASE.out) * (1 - ramp(frame, SCAN1, 8, EASE.exit));
  const fired = GRAPH_SCAN_TARGETS.filter((t) => frame >= t.ft).length;
  const done = ramp(frame, LAST_FIRE + 8, 8, EASE.out);
  const push = 1 + 0.028 * ramp(frame, 0, 177, EASE.swift);
  const statusIn = ramp(frame, 0, 10, EASE.out);
  const scanProg = Math.min(1, Math.max(0, (frame - SCAN0) / (SCAN1 - SCAN0)));

  return (
    <AbsoluteFill>
      <Stage look={L} keyLight={{ x: 0.3, y: 0.05 }} fill={{ x: 0.9, y: 0.95 }} vignette={0.16} />
      <div style={{ position: 'absolute', inset: 0, transform: `scale(${push.toFixed(5)})`, transformOrigin: '50% 50%' }}>
        {/* 顶部状态行（窗外上方，32px 辅助字号达标 Q11） */}
        <div
          style={{
            position: 'absolute',
            left: WX,
            top: 56,
            width: WW,
            height: 48,
            opacity: statusIn,
            fontFamily: MONO,
            fontSize: 30,
            fontWeight: 700,
            color: SIGHT.ink,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: 7,
              marginRight: 16,
              background: done > 0.5 ? machineColor : alpha(machineColor, 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(frame / 3))),
              boxShadow: `0 0 0 6px ${alpha(machineColor, 0.14)}`,
            }}
          />
          <span style={{ color: done > 0.5 ? machineColor : SIGHT.ink, letterSpacing: '0.05em' }}>
            {done > 0.5 ? statusDone : statusScanning}
          </span>
          <span style={{ fontFamily: SIGHT.fontSans, color: SIGHT.ink2, marginLeft: 20, fontWeight: 600, fontSize: 28 }}>{productTag}</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 20 }}>
            <div style={{ width: 220, height: 6, borderRadius: 3, background: alpha(SIGHT.ink, 0.1), overflow: 'hidden' }}>
              <div style={{ width: `${(scanProg * 100).toFixed(2)}%`, height: '100%', background: machineColor, borderRadius: 3 }} />
            </div>
            <span style={{ fontVariantNumeric: 'tabular-nums', letterSpacing: '0.04em' }}>
              <span style={{ color: SIGHT.ink3, fontWeight: 500 }}>SIGNALS </span>
              <span style={{ color: fired === GRAPH_SCAN_TARGETS.length ? machineColor : SIGHT.ink }}>
                {String(fired).padStart(2, '0')}
              </span>
              <span style={{ color: SIGHT.ink3 }}> / {String(GRAPH_SCAN_TARGETS.length).padStart(2, '0')}</span>
            </span>
          </div>
        </div>

        {/* 浏览器窗：真实 Sight 关系图谱 + 实时终端 + 扫描余晖 */}
        <div
          style={{
            position: 'absolute',
            left: WX,
            top: WY,
            width: WW,
            height: WH,
            borderRadius: 18,
            overflow: 'hidden',
            background: '#ffffff',
            boxShadow: `${softShadow(28, { color: '#0c1a3a', strength: 1.05 })}, 0 0 0 1px ${alpha(SIGHT.ink, 0.1)}`,
          }}
        >
          {/* 精致浏览器顶栏 */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              width: WW,
              height: CHROME,
              background: '#f1f4f9',
              borderBottom: `1px solid ${SIGHT.border}`,
              zIndex: 2,
            }}
          >
            {['#ef4444', '#f59e0b', '#22c55e'].map((col, i) => (
              <div key={col} style={{ position: 'absolute', left: 18 + i * 20, top: 15, width: 12, height: 12, borderRadius: 6, background: col, opacity: 0.78 }} />
            ))}
            <div
              style={{
                position: 'absolute',
                left: WW / 2 - 220,
                top: 8,
                width: 440,
                height: 26,
                borderRadius: 7,
                background: '#ffffff',
                border: `1px solid ${SIGHT.border}`,
                font: `600 16px ${MONO}`,
                color: SIGHT.ink2,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              http://127.0.0.1:5001/#/graph
            </div>
          </div>

          {/* 真实 2x graph-full.png 画面 */}
          <Img
            src={staticFile('textures/live/graph-full.png')}
            style={{
              position: 'absolute',
              left: 0,
              top: CHROME,
              width: WW,
              height: IMG_H,
              display: 'block',
            }}
          />

          {/* 已读扫描余晖 + 3px 钴蓝光芯 */}
          {lineOn > 0.01 && (
            <>
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  width: WW,
                  top: ly - 130,
                  height: 130,
                  opacity: lineOn,
                  background: `linear-gradient(180deg, ${alpha(machineColor, 0)} 0%, ${alpha(machineColor, 0.05)} 60%, ${alpha(machineColor, 0.14)} 100%)`,
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  width: WW,
                  top: ly - 84,
                  height: 84,
                  opacity: lineOn * 0.75,
                  backgroundImage: `radial-gradient(circle, ${alpha(machineColor, 0.52)} 1.3px, transparent 1.9px)`,
                  backgroundSize: '18px 18px',
                  WebkitMaskImage: 'linear-gradient(180deg, transparent, #000)',
                  maskImage: 'linear-gradient(180deg, transparent, #000)',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  width: WW,
                  top: ly - 1.5,
                  height: 3,
                  opacity: lineOn,
                  background: machineColor,
                  boxShadow: `0 0 10px ${alpha(machineColor, 0.6)}, 0 0 28px ${alpha(machineColor, 0.32)}`,
                }}
              />
            </>
          )}
        </div>

        {/* 窗框两侧游标与 Y 读数 */}
        {lineOn > 0.01 && (
          <div style={{ opacity: lineOn }}>
            <svg width={20} height={24} viewBox="0 0 22 26" style={{ position: 'absolute', left: WX - 28, top: WY + ly - 12 }}>
              <path d="M2 2 L20 13 L2 24 Z" fill={machineColor} />
            </svg>
            <svg width={20} height={24} viewBox="0 0 22 26" style={{ position: 'absolute', left: WX + WW + 8, top: WY + ly - 12 }}>
              <path d="M20 2 L2 13 L20 24 Z" fill={machineColor} />
            </svg>
            <div
              style={{
                position: 'absolute',
                left: WX - 144,
                top: WY + ly - 13,
                width: 108,
                textAlign: 'right',
                font: `700 22px ${MONO}`,
                color: machineColor,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              Y {String(Math.max(0, Math.round(ly))).padStart(4, '0')}
            </div>
          </div>
        )}

        {/* 取景框与标注签（叠在窗上，不裁切） */}
        <div style={{ position: 'absolute', left: WX, top: WY, width: WW, height: WH }}>
          {GRAPH_SCAN_TARGETS.map((t) => (
            <Bracket key={t.key} t={t} frame={frame} machine={machineColor} />
          ))}
          {GRAPH_SCAN_TARGETS.map((t) => (
            <Label key={t.key} t={t} frame={frame} machine={machineColor} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
