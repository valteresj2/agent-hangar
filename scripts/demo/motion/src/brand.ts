// Tokens da marca, copiados de central/app/static/style.css (a fonte da verdade). Ver CLAUDE.md.
import {loadFont as loadBarlow} from '@remotion/google-fonts/BarlowSemiCondensed';
import {loadFont as loadPlexMono} from '@remotion/google-fonts/IBMPlexMono';
import {loadFont as loadPlexSans} from '@remotion/google-fonts/IBMPlexSans';

export const C = {
  tarmac: '#1C2530',
  tarmac2: '#26313E',
  tarmacInk: '#C9D1DB',
  tarmacMute: '#8793A1',
  ink: '#17212C',
  paper: '#ECEEF1',
  panel: '#FFFFFF',
  mark: '#F4B400',
  markSoft: '#FDF1CC',
  go: '#1E7F46',
  hold: '#9A5B00',
  stop: '#BD3326',
  info: '#2B5BA8',
  goDark: '#4CC784',
  holdDark: '#F0B454',
  stopDark: '#F07A6D',
};

export const F = {
  display: loadBarlow('normal', {weights: ['600', '700'], subsets: ['latin']}).fontFamily,
  body: loadPlexSans('normal', {weights: ['400', '500', '600'], subsets: ['latin']}).fontFamily,
  mono: loadPlexMono('normal', {weights: ['400', '500'], subsets: ['latin']}).fontFamily,
};

// o hangar do logo (icons.js), em coordenadas 24×24
export const LOGO_PATHS = ['M2.5 20.5V11L12 3.5 21.5 11v9.5', 'M6.5 20.5v-6h11v6', 'M9.5 14.5v6M14.5 14.5v6'];
