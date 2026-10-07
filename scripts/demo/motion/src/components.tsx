// Peças do estúdio: superfície (tarmac com a linha de pista), tipografia cinética, logo, chips e o quadro de tela real.
import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {BEAT, EASE_IN, EASE_OUT} from './beats';
import {C, F, LOGO_PATHS} from './brand';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** fundo da marca: tarmac liso com a linha central de pista correndo devagar (nada de degradê) */
export const Tarmac: React.FC<{children?: React.ReactNode; dashes?: boolean}> = ({children, dashes = true}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const vertical = height > width;
  const offset = (frame * 2) % 120;
  return (
    <AbsoluteFill style={{backgroundColor: C.tarmac}}>
      {dashes && (
        <svg width={width} height={height} style={{position: 'absolute', opacity: 0.18}}>
          {vertical ? (
            <line x1={width / 2} y1={-120 + offset} x2={width / 2} y2={height} stroke={C.mark} strokeWidth={6}
                  strokeDasharray="60 60" />
          ) : (
            <line x1={-120 + offset} y1={height - 140} x2={width} y2={height - 140} stroke={C.mark} strokeWidth={6}
                  strokeDasharray="60 60" />
          )}
        </svg>
      )}
      {children}
    </AbsoluteFill>
  );
};

/** uma linha de tipografia cinética: cada palavra sobe por máscara numa batida (from = quadro da 1ª palavra) */
export const Words: React.FC<{text: string; from: number; perWord?: number; size?: number; color?: string;
  highlight?: string; weight?: number; align?: 'left' | 'center'}> =
  ({text, from, perWord = BEAT / 2, size = 112, color = C.paper, highlight, weight = 700, align = 'left'}) => {
    const frame = useCurrentFrame();
    const words = text.split(' ');
    return (
      <div style={{fontFamily: F.display, fontWeight: weight, fontSize: size, lineHeight: 1.05, color, display: 'flex',
        flexWrap: 'wrap', gap: `0 ${size * 0.26}px`, justifyContent: align === 'center' ? 'center' : 'flex-start'}}>
        {words.map((w, i) => {
          const start = from + i * perWord;
          const p = interpolate(frame, [start, start + 12], [0, 1], {...clamp, easing: EASE_IN});
          const isMark = highlight && w.replace(/[.,]/g, '') === highlight;
          return (
            <span key={i} style={{overflow: 'hidden', display: 'inline-block', paddingBottom: size * 0.08}}>
              <span style={{display: 'inline-block', transform: `translateY(${(1 - p) * 110}%)`,
                color: isMark ? C.mark : color}}>{w}</span>
            </span>
          );
        })}
      </div>
    );
  };

/** sai empurrando para cima (usado no fim de um estado) */
export const exitUp = (frame: number, start: number) =>
  `translateY(${interpolate(frame, [start, start + 10], [0, -40], {...clamp, easing: EASE_OUT})}px)`;
export const exitOpacity = (frame: number, start: number) =>
  interpolate(frame, [start, start + 10], [1, 0], {...clamp, easing: EASE_OUT});

/** o hangar do logo, traçado (stroke) com "draw on" e a batida do logo */
export const Logo: React.FC<{size: number; from: number}> = ({size, from}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const draw = interpolate(frame, [from, from + 18], [0, 1], {...clamp, easing: EASE_IN});
  const hit = spring({frame: frame - from, fps, config: {damping: 14}});
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={C.mark} strokeWidth={2.2}
         strokeLinejoin="round" strokeLinecap="round" style={{transform: `scale(${0.85 + 0.15 * hit})`}}>
      {LOGO_PATHS.map((d, i) => (
        <path key={i} d={d} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
      ))}
    </svg>
  );
};

/** um chip com o nome de uma ferramenta (nunca o logo de terceiros) */
export const Chip: React.FC<{label: string; style?: React.CSSProperties}> = ({label, style}) => (
  <div style={{fontFamily: F.mono, fontSize: 34, color: C.tarmacInk, border: `2px solid ${C.tarmac2}`,
    background: '#212B37', borderRadius: 10, padding: '14px 26px', whiteSpace: 'nowrap', ...style}}>{label}</div>
);

/** uma tela real do produto dentro de uma janela, com movimento de câmera (zoom/pan) e destaques */
export type Crop = {x: number; y: number; w: number; h: number};
export const Shot: React.FC<{src: string; from: number; dur: number; zoom?: [number, number];
  focus?: [number, number]; width?: number; boxes?: {x: number; y: number; w: number; h: number; at: number}[];
  imgW?: number; imgH?: number; crop?: Crop}> =
  ({src, from, dur, zoom = [1, 1.1], focus = [0.5, 0.5], width = 1500, boxes = [], imgW = 1440, imgH = 900, crop}) => {
    const frame = useCurrentFrame();
    const {fps} = useVideoConfig();
    const enter = spring({frame: frame - from, fps, config: {damping: 200}});
    const z = interpolate(frame, [from, from + dur], zoom, {...clamp, easing: EASE_IN});
    const c = crop || {x: 0, y: 0, w: imgW, h: imgH};
    const k = width / c.w; // escala da imagem dentro da janela
    const h = c.h * k;
    const [fx, fy] = focus;
    return (
      <div style={{width, height: h + 44, borderRadius: 14, overflow: 'hidden', background: C.panel,
        boxShadow: '0 40px 120px rgba(0,0,0,.45)', transform: `translateY(${(1 - enter) * 80}px)`,
        opacity: interpolate(enter, [0, 1], [0, 1])}}>
        <div style={{height: 44, background: '#E3E7EC', display: 'flex', alignItems: 'center', gap: 10, padding: '0 18px'}}>
          {[C.stop, C.holdDark, C.goDark].map((c) => <div key={c} style={{width: 14, height: 14, borderRadius: 7, background: c}} />)}
        </div>
        <div style={{position: 'relative', width, height: h, overflow: 'hidden'}}>
          <div style={{position: 'absolute', inset: 0, transform: `scale(${z})`, transformOrigin: `${fx * 100}% ${fy * 100}%`}}>
            <Img src={staticFile(src)} style={{position: 'absolute', left: -c.x * k, top: -c.y * k, width: imgW * k,
              height: imgH * k, display: 'block'}} />
            {boxes.map((b, i) => {  // anel com folga: visível até sobre um botão amarelo
              const p = spring({frame: frame - b.at, fps, config: {damping: 200}});
              const pad = 12;
              return (
                <div key={i} style={{position: 'absolute', left: (b.x - c.x) * k - pad, top: (b.y - c.y) * k - pad,
                  width: b.w * k + pad * 2, height: b.h * k + pad * 2, border: `4px solid ${C.mark}`, borderRadius: 14,
                  boxShadow: `0 0 0 3px ${C.ink}, 0 0 ${30 * p}px rgba(244,180,0,.55)`, opacity: p,
                  transform: `scale(${1.15 - 0.15 * p})`}} />
              );
            })}
          </div>
        </div>
      </div>
    );
  };
