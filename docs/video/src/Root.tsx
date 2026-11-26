import React from 'react';
import { Composition } from 'remotion';
import { FPS, HEIGHT, SIGHT_TOTAL, WIDTH } from './timeline';
import { SightMain } from './Main';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SightPromo"
    component={SightMain}
    durationInFrames={SIGHT_TOTAL}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
    defaultProps={{ bgm: true }}
  />
);
