# Motion studio rules (Agent Hangar launch videos)

Claude does not generate video here: it writes a Remotion program that renders to MP4. These rules decide the
quality. Read BRIEF.md and STATES.md before touching code. Every change ends with a review round (REVIEW.md).

## Never
- A title centered on a gradient. Backgrounds are flat brand surfaces (tarmac, ink or paper), at most with the runway
  line motif.
- Fade-only entrances. Text and panels enter with a mask reveal, a slide or a scale on a spring; opacity only helps.
- Invented UI. Every product screen is a real capture from `public/shots/` (taken from a running Hangar). Crop, zoom,
  pan and highlight it; never redraw, retouch or fake data in it.
- Third-party logos. Tools are named in text chips (Claude, ChatGPT, Cursor, VS Code…), never with their marks.
- Generic AI copy ("revolutionize", "unlock", "seamless", "supercharge", "game-changer"). Say what the product does.
- Motion off the grid. Every cut, entrance and highlight starts on a beat (`beats.ts`); nothing starts between beats.
- Text smaller than 44 px at 1080 px of height (32 px for small labels), or closer than 96 px to the frame edge
  (vertical: 80 px sides, 220 px top and bottom for platform UI).
- More than one idea per state. One sentence, at most 7 words, on screen at a time.

## Always
- Brand only (`src/brand.ts`): tarmac `#1C2530`, ink `#17212C`, runway yellow `#F4B400`, status green/amber/red/blue,
  paper `#ECEEF1`. Yellow marks the one thing to look at in each state; never two yellow things at once.
- Type: Barlow Semi Condensed 700 for display, IBM Plex Sans for body, IBM Plex Mono for code and data.
- Easing: in `Easing.bezier(0.22, 1, 0.36, 1)`, out `Easing.bezier(0.64, 0, 0.78, 0)`; springs with
  `{damping: 200}` for UI, `{damping: 14}` only for the logo hit.
- Reading time: a state stays at least `1 s + words / 3.5 s` after its text finishes entering.
- Camera moves on screenshots are slow (≤ 12 % scale change per bar) and end before the next cut.
- Sound is code (`audio/synth.py`) on the same grid: kick on beats, a tick on each highlight, a whoosh into each cut.
- Both formats come from the same scenes: 16:9 (1920×1080, 60 s) and 9:16 (1080×1920, 30 s cut).

## Review loop
1. Render stills at the key frame of every state (`npm run stills`), plus the MP4.
2. Score each state 1–5 on: legibility, rhythm (on the grid), brand, fidelity to the real product, one idea.
3. Anything below 4 gets a concrete fix; re-render and re-score. Ship only when every state is ≥ 4.
4. Log each round in REVIEW.md.
