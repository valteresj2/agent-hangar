# Motion studio (Remotion)

Launch videos for Agent Hangar, written as code. Read `CLAUDE.md` (studio rules), `BRIEF.md` (director brief) and
`STATES.md` (state list on the beat grid) first; `REVIEW.md` logs every review round.

Everything runs in Docker (no Node on the host); `node_modules` lives in a named volume, outside the repo:

```bash
python audio/synth.py test
docker run --rm -v "$PWD:/work" -v hangar_motion_node_modules:/work/node_modules -w /work \
  mcr.microsoft.com/playwright:v1.63.0-noble sh -c "npm install && npx remotion render src/index.ts Test out/test.mp4"
docker run --rm -v "$PWD:/work" -v hangar_motion_node_modules:/work/node_modules -w /work \
  mcr.microsoft.com/playwright:v1.63.0-noble node stills.mjs Test
```

`public/shots/` holds real captures of a running Hangar (the same ones as the interactive demo); people and customers
are fictional. Remotion is free for individuals and companies of up to three people; larger companies need a
Remotion company license.
