import React from 'react';
import {Composition} from 'remotion';
import {BAR, FPS} from './beats';
import {Launch, LaunchVertical} from './Launch';
import {Test} from './Test';

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Test" component={Test} durationInFrames={BAR * 7} fps={FPS} width={1920} height={1080} />
    <Composition id="Launch" component={Launch} durationInFrames={BAR * 30} fps={FPS} width={1920} height={1080} />
    <Composition id="LaunchVertical" component={LaunchVertical} durationInFrames={BAR * 15} fps={FPS} width={1080}
                 height={1920} />
  </>
);
