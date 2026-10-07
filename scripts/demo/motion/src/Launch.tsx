// Vídeo de lançamento (STATES.md): uma tabela de cenas na grade de batidas, nos dois formatos (16:9 e 9:16).
// Coordenadas das telas em px lógicos de 1440×900 (as capturas 2x usam a mesma grade).
import React from 'react';
import {AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {at, BAR, BEAT, EASE_IN} from './beats';
import {C, F} from './brand';
import {Chip, Crop, Logo, Shot, Tarmac, Words} from './components';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const TOOLS = ['Claude', 'ChatGPT', 'Cursor', 'VS Code', 'Codex', 'n8n', 'Copilot', 'LibreChat', 'OpenCode', 'Slack'];
const SPOT_H: [number, number][] = [[1080, 210], [1420, 300], [1180, 420], [1540, 520], [1000, 590],
  [1330, 650], [1110, 790], [1500, 800], [1580, 660], [1620, 410]];
const SPOT_V: [number, number][] = [[90, 900], [560, 960], [300, 1080], [700, 1150], [120, 1240],
  [480, 1300], [210, 1420], [640, 1460], [400, 1560], [130, 1620]];

const useV = () => {
  const {width, height} = useVideoConfig();
  return height > width;
};
const pad = (v: boolean) => (v ? 80 : 120);

// ------------------------------------------------------------------ cenas de tipografia
const Hook: React.FC = () => {
  const v = useV();
  return (
    <Tarmac>
      <div style={{position: 'absolute', left: pad(v), right: pad(v), top: v ? 760 : 430}}>
        <Words text="Your company has AI agents." from={4} perWord={BEAT / 2} highlight="agents" size={v ? 120 : 112} />
      </div>
    </Tarmac>
  );
};

const Scatter: React.FC = () => {
  const frame = useCurrentFrame();
  const v = useV();
  const spots = v ? SPOT_V : SPOT_H;
  return (
    <Tarmac>
      <div style={{position: 'absolute', left: pad(v), top: v ? 420 : 430, width: v ? 920 : 760}}>
        <Words text="In ten different tools." from={0} perWord={BEAT / 2} size={v ? 120 : 112} />
      </div>
      {TOOLS.map((t, i) => {
        const start = BEAT + Math.floor(i / 2) * (BEAT / 2);
        const p = interpolate(frame, [start, start + 10], [0, 1], {...clamp, easing: EASE_IN});
        const [x, y] = spots[i];
        return <Chip key={t} label={t} style={{position: 'absolute', left: x, top: y,
          transform: `translateY(${(1 - p) * 40}px) rotate(${(i % 3 - 1) * 2}deg)`, opacity: p}} />;
      })}
    </Tarmac>
  );
};

const Problem: React.FC = () => {
  const v = useV();
  return (
    <Tarmac>
      <div style={{position: 'absolute', left: pad(v), top: v ? 640 : 300, display: 'flex', flexDirection: 'column', gap: 18}}>
        <Words text="No tests." from={0} perWord={BEAT / 2} size={v ? 120 : 104} />
        <Words text="No owner." from={BEAT} perWord={BEAT / 2} size={v ? 120 : 104} />
        <Words text="No audit trail." from={BEAT * 2} perWord={BEAT / 2} size={v ? 120 : 104} />
      </div>
    </Tarmac>
  );
};

const Home: React.FC = () => {
  const frame = useCurrentFrame();
  const v = useV();
  const spots = v ? SPOT_V : SPOT_H;
  const {width} = useVideoConfig();
  return (
    <Tarmac>
      {TOOLS.map((t, i) => {  // as ferramentas entram pela porta do hangar
        const p = interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp', easing: EASE_IN});
        const [x0, y0] = spots[i];
        const tx = width / 2 - 80, ty = v ? 760 : 470;
        return <Chip key={t} label={t} style={{position: 'absolute', left: x0 + (tx - x0) * p, top: y0 + (ty - y0) * p,
          transform: `scale(${1 - 0.9 * p})`, opacity: 1 - p}} />;
      })}
      <div style={{position: 'absolute', left: pad(v), right: pad(v), top: v ? 560 : 230, display: 'flex',
        flexDirection: 'column', alignItems: 'center', gap: 34}}>
        <Logo size={v ? 300 : 240} from={6} />
        <Words text="Agent Hangar" from={BEAT * 2} perWord={BEAT / 2} size={v ? 140 : 128} align="center" />
        <div style={{marginTop: 10}}>
          <Words text="One home for every AI agent." from={BAR} perWord={BEAT / 3} size={v ? 64 : 64} weight={600}
                 color={C.tarmacInk} align="center" highlight="home" />
        </div>
      </div>
    </Tarmac>
  );
};

const Turn: React.FC = () => {
  const v = useV();
  return (
    <Tarmac dashes={false}>
      <div style={{position: 'absolute', left: pad(v), right: pad(v), top: v ? 700 : 400}}>
        <Words text="What if an agent had a job?" from={0} perWord={BEAT / 2} highlight="job" size={v ? 130 : 120} />
      </div>
    </Tarmac>
  );
};

// ------------------------------------------------------------------ cena com tela real
type Box = {x: number; y: number; w: number; h: number; bar: number; beat?: number};
type ShotDef = {src: string; crop: Crop; vcrop?: Crop; zoom?: [number, number]; focus?: [number, number];
  boxes?: Box[]; title: string; sub?: string; highlight?: string};

const ShotScene: React.FC<{def: ShotDef; start: number; bars: number}> = ({def, start, bars}) => {
  const v = useV();
  const crop = v && def.vcrop ? def.vcrop : def.crop;
  const maxW = v ? 920 : 1110, maxH = v ? 1080 : 900;
  const width = Math.round(Math.min(maxW, ((maxH - 44) * crop.w) / crop.h));
  const shotH = (width * crop.h) / crop.w + 44;
  const boxes = (def.boxes || []).map((b) => ({...b, at: at(b.bar, b.beat || 1) - start}));
  const shot = (
    <Shot src={def.src} from={0} dur={bars * BAR} width={width} zoom={def.zoom || [1, 1.06]} focus={def.focus || [0.5, 0.5]}
          crop={crop} boxes={boxes} />
  );
  const frame = useCurrentFrame();
  const caption = (
    <>
      <Words text={def.title} from={bars === 1 ? 0 : BEAT} perWord={bars === 1 ? BEAT / 3 : BEAT / 2} size={v ? 96 : 84}
             highlight={def.highlight} />
      {def.sub && (
        <div style={{fontFamily: F.body, fontSize: v ? 40 : 32, color: C.tarmacMute, marginTop: 28, lineHeight: 1.35,
          opacity: interpolate(frame, [BEAT * 3, BEAT * 3 + 10], [0, 1], clamp)}}>{def.sub}</div>
      )}
    </>
  );
  if (v) {
    return (
      <Tarmac dashes={false}>
        <div style={{position: 'absolute', left: 80, right: 80, top: 230}}>{caption}</div>
        <div style={{position: 'absolute', left: (1080 - width) / 2, top: 640 + (1080 - shotH) / 2}}>{shot}</div>
      </Tarmac>
    );
  }
  return (
    <Tarmac dashes={false}>
      <div style={{position: 'absolute', left: 120, top: 0, bottom: 0, width: 520, display: 'flex', flexDirection: 'column',
        justifyContent: 'center'}}>{caption}</div>
      <div style={{position: 'absolute', left: 690 + (1110 - width) / 2, top: (1080 - shotH) / 2}}>{shot}</div>
    </Tarmac>
  );
};

const MAIN: Crop = {x: 256, y: 0, w: 1184, h: 740};
const SHOTS: Record<string, ShotDef> = {
  build: {src: 'shots/01-claude.png', crop: {x: 225, y: 70, w: 975, h: 560}, zoom: [1, 1.04], focus: [0.02, 0.6],
    title: 'Built from the AI tool you already use.', sub: 'Claude, ChatGPT, Cursor or VS Code build it over MCP.'},
  reuse: {src: 'shots/17-reuse.png', crop: {x: 272, y: 250, w: 1130, h: 470}, focus: [0.2, 0.5],
    boxes: [{x: 300, y: 433, w: 236, h: 32, bar: 10}],
    title: 'Reuse before you build.', sub: 'It finds what the company already has, and calls it.'},
  tests: {src: 'shots/06-tests.png', crop: {x: 272, y: 305, w: 1140, h: 440}, focus: [0.2, 0.1],
    boxes: [{x: 293, y: 335, w: 312, h: 26, bar: 12}],
    title: 'Nothing reaches production untested.', sub: 'Smoke checks on every protocol, plus an LLM judge.'},
  eyes: {src: 'shots/01-claude.png', crop: {x: 225, y: 280, w: 975, h: 420}, zoom: [1, 1.04], focus: [0.02, 0.6],
    boxes: [{x: 250, y: 518, w: 939, h: 31, bar: 13, beat: 2}],
    title: 'Four eyes for production.'},
  anywhere: {src: 'shots/15-connect-tools.png', crop: {x: 262, y: 215, w: 1145, h: 580}, zoom: [1, 1.03], focus: [0.02, 0.2],
    title: 'Use it from any tool.', sub: 'As a tool over MCP, or as a model in the chat.'},
  hire: {src: 'shots/18-employee-probation.png', crop: {x: 280, y: 45, w: 1105, h: 700}, zoom: [1, 1.03], focus: [0.75, 0.3],
    boxes: [{x: 845, y: 234, w: 393, h: 54, bar: 18}],
    title: 'Hire it. It does a probation first.', sub: 'When a fact was missing, it asked instead of guessing.'},
  decision: {src: 'shots/20-decision.png', crop: {x: 256, y: 222, w: 1184, h: 668}, vcrop: {x: 260, y: 300, w: 700, h: 560},
    zoom: [1, 1.06], focus: [0.3, 0.9],
    boxes: [{x: 273, y: 368, w: 1156, h: 363, bar: 20}, {x: 293, y: 817, w: 84, h: 38, bar: 21}],
    title: 'It asks before it acts.', sub: 'The exact e-mail waits for the manager.'},
  authority: {src: 'shots/21-authority.png', crop: {x: 285, y: 70, w: 530, h: 830}, vcrop: {x: 285, y: 250, w: 530, h: 560},
    zoom: [1, 1.03], focus: [0.5, 0.6],
    boxes: [{x: 464, y: 441, w: 137, h: 25, bar: 22, beat: 3}, {x: 464, y: 700, w: 121, h: 25, bar: 23}],
    title: 'The platform holds the line.', sub: 'Not the prompt. Code jobs, money and deletes wait for people.'},
  learn: {src: 'shots/22-learn.png', crop: {x: 272, y: 75, w: 1140, h: 420}, vcrop: {x: 300, y: 180, w: 640, h: 330},
    focus: [0.2, 0.8], boxes: [{x: 314, y: 415, w: 132, h: 37, bar: 25}],
    title: 'It learns from your decisions.', sub: 'Repeated corrections become a lesson. You approve it.'},
};

// ------------------------------------------------------------------ faixa de prova e fechamento
const STRIP = [['shots/12-usage.png', 'Usage and cost'], ['shots/14-guide.png', 'A guide for every agent'],
  ['shots/10-catalog.png', 'Company catalog'], ['shots/08-memory.png', 'Team memory']];

const Strip: React.FC = () => {
  const v = useV();
  const w = v ? 440 : 390;
  return (
    <Tarmac dashes={false}>
      <div style={{position: 'absolute', left: pad(v), top: v ? 260 : 220}}>
        <Words text="And everything around it." from={0} perWord={BEAT / 3} size={v ? 96 : 80} />
      </div>
      <div style={{position: 'absolute', left: v ? 80 : 135, top: v ? 640 : 420, display: 'grid',
        gridTemplateColumns: `repeat(${v ? 2 : 4}, ${w}px)`, gap: v ? '70px 40px' : '30px 30px'}}>
        {STRIP.map(([src, label], i) => (
          <Sequence key={src} from={BEAT * (i + 1)} layout="none">
            <div>
              <Shot src={src} from={0} dur={BAR * 2} width={w} zoom={[1, 1.04]} crop={MAIN} />
              <div style={{fontFamily: F.body, fontSize: v ? 34 : 28, color: C.tarmacInk, marginTop: 14}}>{label}</div>
            </div>
          </Sequence>
        ))}
      </div>
    </Tarmac>
  );
};

const Close: React.FC = () => {
  const frame = useCurrentFrame();
  const v = useV();
  const url = 'github.com/valteresj2/agent-hangar';
  const typed = Math.round(interpolate(frame, [BAR + BEAT * 2, BAR + BEAT * 3.5], [0, url.length], clamp));
  return (
    <Tarmac>
      <div style={{position: 'absolute', left: pad(v), right: pad(v), top: v ? 560 : 250}}>
        <div style={{marginBottom: 40}}><Logo size={v ? 180 : 150} from={0} /></div>
        <Words text="One home for every AI agent." from={BEAT * 2} perWord={BEAT / 3} highlight="home" size={v ? 120 : 112} />
        <div style={{fontFamily: F.body, fontSize: v ? 48 : 44, color: C.tarmacInk, marginTop: 40,
          opacity: interpolate(frame, [BAR, BAR + 10], [0, 1], clamp)}}>Open source. One command to install.</div>
        <div style={{fontFamily: F.mono, fontSize: v ? 40 : 44, color: C.tarmacInk, marginTop: 26}}>
          {url.slice(0, typed)}<span style={{color: C.mark, opacity: frame % 20 < 10 && typed > 0 ? 1 : 0}}>▌</span>
        </div>
      </div>
    </Tarmac>
  );
};

// ------------------------------------------------------------------ as duas linhas do tempo
// [compasso, duração, cena]; uma tela é {shot, ref}: ref é o compasso da cena no 16:9, onde as deixas de destaque
// (boxes) foram marcadas — no 9:16 a cena começa em outro compasso e os destaques andam junto
type Item = [number, number, React.ReactNode | {shot: string; ref?: number}];

const WIDE: Item[] = [
  [1, 1, <Hook />], [2, 1, <Scatter />], [3, 1, <Problem />], [4, 2, <Home />],
  [6, 3, {shot: 'build'}], [9, 2, {shot: 'reuse'}], [11, 2, {shot: 'tests'}], [13, 1, {shot: 'eyes'}],
  [14, 2, {shot: 'anywhere'}], [16, 1, <Turn />], [17, 2, {shot: 'hire'}], [19, 3, {shot: 'decision'}],
  [22, 2, {shot: 'authority'}], [24, 2, {shot: 'learn'}], [26, 2, <Strip />], [28, 3, <Close />],
];
const VERT: Item[] = [
  [1, 1, <Hook />], [2, 1, <Scatter />], [3, 2, <Home />], [5, 1, <Turn />],
  [6, 3, {shot: 'decision', ref: 19}], [9, 2, {shot: 'authority', ref: 22}], [11, 2, {shot: 'learn', ref: 24}],
  [13, 3, <Close />],
];

const Timeline: React.FC<{items: Item[]; audio: string}> = ({items, audio}) => (
  <AbsoluteFill style={{backgroundColor: C.tarmac}}>
    <Audio src={staticFile(audio)} />
    {items.map(([bar, bars, node], i) => {
      const el = node && typeof node === 'object' && 'shot' in (node as object)
        ? <ShotScene def={SHOTS[(node as {shot: string}).shot]} start={at((node as {ref?: number}).ref || bar)} bars={bars} />
        : node as React.ReactNode;
      return <Sequence key={i} from={at(bar)} durationInFrames={bars * BAR}>{el}</Sequence>;
    })}
  </AbsoluteFill>
);

export const Launch: React.FC = () => <Timeline items={WIDE} audio="audio/launch.wav" />;
export const LaunchVertical: React.FC = () => <Timeline items={VERT} audio="audio/vertical.wav" />;
