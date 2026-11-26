// Main.tsx — Sight B站开源宣传片总合成（支持 bgm inputProp 切换带 BGM / 无 BGM 双版渲染）
import React from 'react';
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { CAPTIONS, FLASH_CUTS, SIGHT_SHOTS, SIGHT_TOTAL, TITLE_CARDS } from './timeline';
import { SFX_CUES, sfxDuration } from './audio';
import { SIGHT, SightCaption, SightFlashCut } from './lib/SightBrand';
import { SceneMaskOpen } from './scenes/SceneMaskOpen';
import { SceneSpotlightHero } from './scenes/SceneSpotlightHero';
import { SightTitleCard } from './scenes/SightTitleCard';
import { SceneTypeFilter } from './scenes/SceneTypeFilter';
import { SceneGraphScan } from './scenes/SceneGraphScan';
import { SceneTimelineStack } from './scenes/SceneTimelineStack';
import { SceneAgentReveal } from './scenes/SceneAgentReveal';
import { SceneOutroLaunch } from './scenes/SceneOutroLaunch';

export type SightPromoProps = {
  bgm?: boolean;
};

export const SightMain: React.FC<SightPromoProps> = ({ bgm = true }) => {
  const frame = useCurrentFrame();

  // BGM 音量包络：前 12f 柔和淡入，正片留足空间给 SFX（0.30），末尾 24f 优雅淡出
  const bgmVol = interpolate(frame, [0, 12, SIGHT_TOTAL - 26, SIGHT_TOTAL], [0, 0.30, 0.30, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ backgroundColor: SIGHT.bg }}>
      {/* —— 10 个主镜头序列（全部锚定整拍） —— */}
      <Sequence from={SIGHT_SHOTS.maskOpen.from} durationInFrames={SIGHT_SHOTS.maskOpen.duration} name="S1-MaskOpen">
        <SceneMaskOpen />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.spotlight.from} durationInFrames={SIGHT_SHOTS.spotlight.duration} name="S2-SpotlightHero">
        <SceneSpotlightHero />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.card1.from} durationInFrames={SIGHT_SHOTS.card1.duration} name="C1-TitlePlatforms">
        <SightTitleCard
          text={TITLE_CARDS.card1.text}
          sub={TITLE_CARDS.card1.sub}
          subDigits={TITLE_CARDS.card1.subDigits}
          duration={SIGHT_SHOTS.card1.duration}
        />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.typeFilter.from} durationInFrames={SIGHT_SHOTS.typeFilter.duration} name="S3-TypeFilter">
        <SceneTypeFilter />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.graphScan.from} durationInFrames={SIGHT_SHOTS.graphScan.duration} name="S4-GraphScan">
        <SceneGraphScan />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.card2.from} durationInFrames={SIGHT_SHOTS.card2.duration} name="C2-TitleTimeline">
        <SightTitleCard
          text={TITLE_CARDS.card2.text}
          sub={TITLE_CARDS.card2.sub}
          duration={SIGHT_SHOTS.card2.duration}
        />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.timelineStack.from} durationInFrames={SIGHT_SHOTS.timelineStack.duration} name="S5-TimelineStack">
        <SceneTimelineStack />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.card3.from} durationInFrames={SIGHT_SHOTS.card3.duration} name="C3-TitleAgent">
        <SightTitleCard
          text={TITLE_CARDS.card3.text}
          sub={TITLE_CARDS.card3.sub}
          duration={SIGHT_SHOTS.card3.duration}
        />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.agentReveal.from} durationInFrames={SIGHT_SHOTS.agentReveal.duration} name="S6-AgentReveal">
        <SceneAgentReveal />
      </Sequence>

      <Sequence from={SIGHT_SHOTS.outro.from} durationInFrames={SIGHT_SHOTS.outro.duration} name="S7-OutroLaunch">
        <SceneOutroLaunch duration={SIGHT_SHOTS.outro.duration} />
      </Sequence>

      {/* —— 底部 56px 叙事主字幕层（Q11 达标） —— */}
      {CAPTIONS.map((c) => (
        <Sequence key={c.id} from={c.from} durationInFrames={c.duration} name={c.id}>
          <SightCaption text={c.text} duration={c.duration} />
        </Sequence>
      ))}

      {/* —— 钴白闪切转场层（位于字幕之上） —— */}
      {FLASH_CUTS.map((cut, i) => (
        <Sequence key={`flash-${i}`} from={cut - 5} durationInFrames={10} name={`FlashCut-${i + 1}`}>
          <SightFlashCut duration={10} />
        </Sequence>
      ))}

      {/* —— 音频层：BGM（受 bgm inputProp 控制，交付带/无 BGM 双版） + 中央 SFX 表 —— */}
      {bgm ? <Audio src={staticFile('audio/bgm.mp3')} volume={bgmVol} /> : null}

      {SFX_CUES.map((s, i) => (
        <Sequence key={`sfx-${i}`} from={s.from} durationInFrames={sfxDuration(s)} name={`SFX-${i + 1}`}>
          <Audio src={staticFile(`audio/${s.src}`)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
