// Teste de estilo (STATES.md, "Style test"): 7 compassos, cortes secos na batida.
import React from 'react';
import {AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {at, BAR, BEAT, EASE_IN} from './beats';
import {C, F} from './brand';
import {Chip, Logo, Shot, Tarmac, Words} from './components';

const TOOLS = ['Claude', 'ChatGPT', 'Cursor', 'VS Code', 'Codex', 'n8n', 'Copilot', 'LibreChat', 'OpenCode', 'Slack'];
// posições soltas na metade direita (um "espalhado" com ordem: nada encosta na margem de 96 px)
const SPOT: [number, number][] = [[1080, 210], [1420, 300], [1180, 420], [1540, 520], [1000, 590],
  [1330, 650], [1110, 790], [1500, 800], [1580, 660], [1620, 410]];
const PAD = 120;

const Hook: React.FC = () => (
  <Tarmac>
    <div style={{position: 'absolute', left: PAD, top: 430}}>
      <Words text="Your company has AI agents." from={4} perWord={BEAT / 2} highlight="agents" />
    </div>
  </Tarmac>
);

const Scatter: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Tarmac>
      <div style={{position: 'absolute', left: PAD, top: 430, width: 760}}>
        <Words text="In ten different tools." from={0} perWord={BEAT / 2} />
      </div>
      {TOOLS.map((t, i) => {  // em pares, a cada colcheia, a partir da batida 2
        const start = BEAT + Math.floor(i / 2) * (BEAT / 2);
        const p = interpolate(frame, [start, start + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
          easing: EASE_IN});
        const [x, y] = SPOT[i];
        return <Chip key={t} label={t} style={{position: 'absolute', left: x, top: y,
          transform: `translateY(${(1 - p) * 40}px) rotate(${(i % 3 - 1) * 2}deg)`, opacity: p}} />;
      })}
    </Tarmac>
  );
};

const Home: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Tarmac>
      {TOOLS.map((t, i) => {  // as ferramentas entram pela porta do hangar no começo do estado
        const p = interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp', easing: EASE_IN});
        const [x0, y0] = SPOT[i];
        return <Chip key={t} label={t} style={{position: 'absolute', left: x0 + (960 - 80 - x0) * p,
          top: y0 + (470 - y0) * p, transform: `scale(${1 - 0.9 * p})`, opacity: 1 - p}} />;
      })}
      <div style={{position: 'absolute', left: 0, right: 0, top: 300, display: 'flex', flexDirection: 'column',
        alignItems: 'center', gap: 36}}>
        <Logo size={260} from={6} />
        <Words text="Agent Hangar" from={BEAT * 2} perWord={BEAT / 2} size={128} align="center" />
      </div>
    </Tarmac>
  );
};

const Proof: React.FC = () => (
  <Tarmac dashes={false}>
    <div style={{position: 'absolute', left: PAD, top: 330, width: 470}}>
      <Words text="It asks before it acts." from={BEAT} perWord={BEAT / 2} size={92} />
      <div style={{fontFamily: F.body, fontSize: 32, color: C.tarmacMute, marginTop: 34, lineHeight: 1.35}}>
        The exact e-mail waits for the manager.
      </div>
    </div>
    <div style={{position: 'absolute', left: 640, top: 150}}>
      <Shot src="shots/20-decision.png" from={0} dur={BAR * 2} width={1160} zoom={[1, 1.06]} focus={[0.3, 0.9]}
            crop={{x: 256, y: 222, w: 1184, h: 668}} boxes={[{x: 293, y: 817, w: 84, h: 38, at: BAR}]} />
    </div>
  </Tarmac>
);

const Close: React.FC = () => {
  const frame = useCurrentFrame();
  const url = 'github.com/valteresj2/agent-hangar';
  const typed = Math.round(interpolate(frame, [BEAT * 2, BEAT * 3.5], [0, url.length], {extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp'}));
  return (
    <Tarmac>
      <div style={{position: 'absolute', left: PAD, top: 300}}>
        <div style={{marginBottom: 40}}><Logo size={120} from={0} /></div>
        <Words text="One home for every AI agent." from={0} perWord={BEAT / 3} highlight="home" />
        <div style={{fontFamily: F.mono, fontSize: 44, color: C.tarmacInk, marginTop: 44}}>
          {url.slice(0, typed)}<span style={{color: C.mark, opacity: frame % 20 < 10 ? 1 : 0}}>▌</span>
        </div>
      </div>
    </Tarmac>
  );
};

export const Test: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: C.tarmac}}>
    <Audio src={staticFile('audio/test.wav')} />
    <Sequence from={at(1)} durationInFrames={BAR}><Hook /></Sequence>
    <Sequence from={at(2)} durationInFrames={BAR}><Scatter /></Sequence>
    <Sequence from={at(3)} durationInFrames={BAR * 2}><Home /></Sequence>
    <Sequence from={at(5)} durationInFrames={BAR * 2}><Proof /></Sequence>
    <Sequence from={at(7)} durationInFrames={BAR}><Close /></Sequence>
  </AbsoluteFill>
);
