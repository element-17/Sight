// SceneTypeFilter.tsx — S3 跨平台搜索与筛选穿透（忠实复刻 demos/interaction/type-and-filter/TypeAndFilter.tsx）
// 真人速度打字（3f/字符，R3）→ 12f 呼吸拉开全景 → 7 张非目标卡错峰下沉淡出 → 目标卡滑入首行真实槽位（Q9）
// → macOS 指针沿弧线滑入双圈钴蓝 ripple 点击确认 → 相机推进交棒 FlashCut 切入关系图谱。
import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, Easing } from 'remotion';
import { PageCam, CamKey } from '../lib/PageCam';
import { SpeedBlur, velocity } from '../lib/Polish';
import { SIGHT } from '../lib/SightBrand';
import layout from '../live-layout.json';

export const SCENE_TYPE_FILTER_DEFAULTS = {
  query: '林屿森 · 多模态',
  accent: SIGHT.accent,
  bg: SIGHT.bg,
};

const PAGE_H = layout.platform.pageH;
const cards = layout.platform.cards;
const SEARCH = layout.platform.search; // { x: 544, y: 76, w: 344, h: 35 }
const TARGET_IDX = 2; // card3: 「多模态 AI Agent 实战」
const targetCard = cards[TARGET_IDX];
const TARGET_TO = { x: cards[0].x, y: cards[0].y }; // 首行首位真实槽位（Q9）
const CLICK_C = { x: TARGET_TO.x + targetCard.w * 0.52, y: TARGET_TO.y + targetCard.h * 0.55 };

// 节拍（总长 118f，b28–b36）
const TYPE_START = 10;
const FILTER_START = 52; // 8 字 × 3f = 24f（f10–f34）+ 18f 真人呼吸确认
const CLICK = 86; // 踩 b34 附近，随后 f90–118 相机推进穿透接 b36 FlashCut

const leaveRank = new Map<number, number>();
cards.forEach((_, i) => {
  if (i !== TARGET_IDX) leaveRank.set(i, leaveRank.size);
});

const CAM_KEYS: CamKey[] = [
  { frame: 0, cx: 740, cy: 148, zoom: 2.25 },
  { frame: 44, cx: 740, cy: 148, zoom: 2.25 },
  { frame: 60, cx: 960, cy: 480, zoom: 1.0 },
  { frame: 84, cx: 960, cy: 480, zoom: 1.0 },
  { frame: 118, cx: CLICK_C.x, cy: CLICK_C.y, zoom: 2.35 },
];

const CAM_EASE = Easing.bezier(0.33, 0, 0.15, 1);
const camZoom = (f: number) => {
  for (let i = 0; i < CAM_KEYS.length - 1; i++) {
    const a = CAM_KEYS[i];
    const b = CAM_KEYS[i + 1];
    if (f >= a.frame && f <= b.frame) {
      const t = interpolate(f, [a.frame, b.frame], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: CAM_EASE,
      });
      return a.zoom + (b.zoom - a.zoom) * t;
    }
  }
  return f < CAM_KEYS[0].frame ? CAM_KEYS[0].zoom : CAM_KEYS[CAM_KEYS.length - 1].zoom;
};

const PTR_FROM = { x: 1180, y: 180 };
const ptrAt = (f: number) => {
  const t = interpolate(f, [62, 84], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.45, 0, 0.2, 1),
  });
  const arc = Math.sin(t * Math.PI) * 58;
  return {
    x: PTR_FROM.x + (CLICK_C.x - PTR_FROM.x) * t,
    y: PTR_FROM.y + (CLICK_C.y - PTR_FROM.y) * t + arc,
  };
};

export const SceneTypeFilter: React.FC<Partial<typeof SCENE_TYPE_FILTER_DEFAULTS>> = ({
  query = SCENE_TYPE_FILTER_DEFAULTS.query,
  accent = SCENE_TYPE_FILTER_DEFAULTS.accent,
  bg = SCENE_TYPE_FILTER_DEFAULTS.bg,
}) => {
  const frame = useCurrentFrame();
  const ACCENT_RGB = '53,101,224';

  const chars = Array.from(query);
  const typedCount = frame < TYPE_START ? 0 : Math.min(chars.length, Math.floor((frame - TYPE_START) / 3) + 1);
  const typeEnd = TYPE_START + chars.length * 3;
  const caretOn =
    frame >= TYPE_START - 2 &&
    frame <= CLICK + 4 &&
    (frame <= typeEnd || Math.floor((frame - typeEnd) / 8) % 2 === 0);

  const focus = interpolate(frame, [TYPE_START - 6, TYPE_START - 2, CLICK, CLICK + 6], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const ptr = ptrAt(frame);
  const ptrO = interpolate(frame, [58, 64, CLICK + 6, CLICK + 12], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const ptrPress = interpolate(frame, [CLICK - 1, CLICK + 1, CLICK + 5], [1, 0.85, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const ptrScale = (1 / camZoom(frame)) * ptrPress;

  const slideAt = (f: number) =>
    interpolate(f, [FILTER_START + 4, FILTER_START + 18], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.bezier(0.35, 0, 0.2, 1),
    });
  const slideT = slideAt(frame);
  const slideVx = velocity((f) => (TARGET_TO.x - targetCard.x) * slideAt(f), frame);

  return (
    <AbsoluteFill style={{ backgroundColor: bg }}>
      <PageCam src="textures/live/platform-empty.png" pageH={PAGE_H} keys={CAM_KEYS} bg={bg}>
        {/* 7 张非目标内容卡：错峰下沉淡出 */}
        {cards.map((c, i) => {
          if (i === TARGET_IDX) return null;
          const outCue = FILTER_START + (leaveRank.get(i) ?? 0) * 1.1;
          if (frame >= outCue + 7) return null;
          const outT = interpolate(frame, [outCue, outCue + 7], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: Easing.inOut(Easing.quad),
          });
          return (
            <div
              key={c.file}
              style={{
                position: 'absolute',
                left: c.x,
                top: c.y,
                width: c.w,
                height: c.h,
                transform: `translate3d(0px, ${(10 * outT).toFixed(2)}px, 0px) scale(${(1 - 0.02 * outT).toFixed(4)})`,
                opacity: 1 - outT,
                borderRadius: 10,
                overflow: 'hidden',
                filter: outT > 0.02 ? `blur(${(1.6 * outT).toFixed(2)}px)` : undefined,
                boxShadow: '0 1px 2px rgba(16,24,40,0.05)',
              }}
            >
              <Img src={staticFile(`textures/live/${c.file}`)} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }} />
            </div>
          );
        })}

        {/* 目标卡：沿真实网格滑到首行首位真实槽位（浮起 + 方向速度拖影，Q9） */}
        {(() => {
          const slideDx = (TARGET_TO.x - targetCard.x) * slideT;
          const slideDy = (TARGET_TO.y - targetCard.y) * slideT;
          const float = Math.sin(slideT * Math.PI);
          const slideScale = 1 + 0.03 * float;
          return (
            <SpeedBlur vx={slideVx} vy={0} amount={0.05} max={9} style={{ zIndex: 2 }}>
              <div
                style={{
                  position: 'absolute',
                  left: targetCard.x,
                  top: targetCard.y,
                  width: targetCard.w,
                  height: targetCard.h,
                  transform: `translate3d(${slideDx.toFixed(2)}px, ${slideDy.toFixed(2)}px, 0px) scale(${slideScale.toFixed(4)})`,
                  transformOrigin: 'center center',
                  boxShadow: `0 ${2 + 4 * float}px ${4 + 8 * float}px rgba(16,24,40,${(0.06 + 0.05 * float).toFixed(3)}), 0 ${6 + 18 * float}px ${16 + 26 * float}px -4px rgba(16,24,40,${(0.08 + 0.14 * float).toFixed(3)})`,
                  borderRadius: 10,
                  overflow: 'hidden',
                }}
              >
                <Img src={staticFile(`textures/live/${targetCard.file}`)} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }} />
              </div>
            </SpeedBlur>
          );
        })()}

        {/* 搜索框：纯白补丁盖住 placeholder（保留左侧放大镜图标和右侧按钮）+ 打字文字 + 钴蓝聚焦环 */}
        <div
          style={{
            position: 'absolute',
            left: SEARCH.x + 28,
            top: SEARCH.y + 3,
            width: SEARCH.w - 92,
            height: SEARCH.h - 6,
            background: '#ffffff',
            pointerEvents: 'none',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: SEARCH.x - 1,
            top: SEARCH.y - 1,
            width: SEARCH.w + 2,
            height: SEARCH.h + 2,
            borderRadius: 9,
            boxSizing: 'border-box',
            pointerEvents: 'none',
            opacity: focus,
            border: `1.5px solid ${accent}`,
            boxShadow: `0 0 0 3px rgba(${ACCENT_RGB},0.16)`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: SEARCH.x + 31,
            top: SEARCH.y,
            height: SEARCH.h,
            display: 'flex',
            alignItems: 'center',
            fontFamily: SIGHT.fontSans,
            fontSize: 13.5,
            fontWeight: 500,
            color: SIGHT.ink,
            pointerEvents: 'none',
          }}
        >
          <span>{chars.slice(0, typedCount).join('')}</span>
          {caretOn ? (
            <span style={{ display: 'inline-block', width: 1.5, height: 16, marginLeft: 1.5, borderRadius: 1, background: accent }} />
          ) : null}
        </div>

        {/* 双圈同心钴蓝 ripple 点击波纹 */}
        {[0, 1].map((r) => {
          const start = CLICK + r * 3;
          if (frame < start || frame > start + 12) return null;
          const t = interpolate(frame, [start, start + 12], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: Easing.out(Easing.cubic),
          });
          const rad = interpolate(t, [0, 1], [12, r === 0 ? 52 : 78]);
          return (
            <div
              key={`ripple-${r}`}
              style={{
                position: 'absolute',
                left: CLICK_C.x - rad,
                top: CLICK_C.y - rad,
                width: rad * 2,
                height: rad * 2,
                borderRadius: '50%',
                boxSizing: 'border-box',
                border: `${r === 0 ? 2 : 1.5}px solid ${accent}`,
                background: r === 0 ? `radial-gradient(circle, rgba(${ACCENT_RGB},0) 55%, rgba(${ACCENT_RGB},0.12) 100%)` : undefined,
                opacity: 1 - t,
                pointerEvents: 'none',
                zIndex: 5,
              }}
            />
          );
        })}

        {/* 点击选中同心钴蓝外描边 */}
        {frame >= CLICK + 2 ? (
          <div
            style={{
              position: 'absolute',
              left: TARGET_TO.x - 5,
              top: TARGET_TO.y - 5,
              width: targetCard.w + 10,
              height: targetCard.h + 10,
              borderRadius: 14,
              boxSizing: 'border-box',
              border: `3px solid ${accent}`,
              boxShadow: `0 0 0 4px rgba(${ACCENT_RGB},0.12), 0 8px 30px -6px rgba(${ACCENT_RGB},0.48)`,
              opacity: interpolate(frame, [CLICK + 2, CLICK + 5], [0.5, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }),
              transform: `scale(${interpolate(frame, [CLICK + 2, CLICK + 7], [1.02, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) })})`,
              pointerEvents: 'none',
              zIndex: 4,
            }}
          />
        ) : null}

        {/* macOS 箭头指针（按 zoom 反向缩放保持屏幕尺寸恒定） */}
        {ptrO > 0.001 ? (
          <svg
            width={28}
            height={28}
            viewBox="0 0 28 28"
            style={{
              position: 'absolute',
              left: ptr.x - 2,
              top: ptr.y - 1,
              zIndex: 6,
              opacity: ptrO,
              overflow: 'visible',
              transformOrigin: '2px 1px',
              transform: `scale(${(ptrScale * 1.6).toFixed(4)})`,
              filter: 'drop-shadow(0 1px 1px rgba(15,23,42,0.35)) drop-shadow(0 3px 6px rgba(15,23,42,0.25))',
            }}
          >
            <path d="M2 1 L2 23 L8 17.5 L11.5 25 L15.5 23.2 L12 15.8 L20 15 Z" fill="#17181c" stroke="#ffffff" strokeWidth={1.6} strokeLinejoin="round" />
          </svg>
        ) : null}
      </PageCam>
    </AbsoluteFill>
  );
};
