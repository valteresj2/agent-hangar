import React from 'react';
import {Composition} from 'remotion';
import {BAR, FPS} from './beats';
import {Test} from './Test';

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Test" component={Test} durationInFrames={BAR * 7} fps={FPS} width={1920} height={1080} />
  </>
);
