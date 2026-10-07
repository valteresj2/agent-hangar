// Quadros-chave de cada estado para o ciclo de revisão (CLAUDE.md): node stills.mjs [composição] [quadro...]
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import path from 'node:path';

const [id = 'Test', ...frames] = process.argv.slice(2);
const KEY = {
  Test: [50, 112, 200, 268, 345, 410],
  Launch: [50, 112, 170, 280, 440, 580, 690, 760, 860, 950, 1050, 1170, 1230, 1350, 1470, 1590, 1770],
  LaunchVertical: [50, 112, 220, 290, 390, 450, 570, 690, 870],
};
const serveUrl = await bundle({entryPoint: path.resolve('src/index.ts')});
const composition = await selectComposition({serveUrl, id});
for (const frame of (frames.length ? frames.map(Number) : KEY[id] || [0])) {
  const output = `out/stills/${id}-${String(frame).padStart(4, '0')}.png`;
  await renderStill({serveUrl, composition, frame, output});
  console.log(output);
}
