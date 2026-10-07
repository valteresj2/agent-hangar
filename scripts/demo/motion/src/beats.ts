// A grade de batidas: tudo começa numa batida (CLAUDE.md). 120 BPM a 30 fps.
import {Easing} from 'remotion';

export const FPS = 30;
export const BPM = 120;
export const BEAT = (60 / BPM) * FPS; // 15 quadros
export const BAR = BEAT * 4; // 60 quadros = 2 s

/** quadro de uma batida: bar e beat começam em 1, como na partitura */
export const at = (bar: number, beat = 1) => (bar - 1) * BAR + (beat - 1) * BEAT;
export const bars = (n: number) => n * BAR;

export const EASE_IN = Easing.bezier(0.22, 1, 0.36, 1);
export const EASE_OUT = Easing.bezier(0.64, 0, 0.78, 0);
