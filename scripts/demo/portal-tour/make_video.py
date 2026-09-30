"""Monta o tour do portal: GIF (README) e MP4, com legendas e transições suaves entre as capturas."""
import pathlib

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

D = pathlib.Path("/demo")
SH = D / "shots"
OUT = D / "out"
OUT.mkdir(exist_ok=True)
SLIDES = [
    ("01-claude.png", 5.5, "1 · Ana asks Claude for a Sales Assistant. Through the Hangar MCP, Claude builds it, tests it (9/9) and ships it"),
    ("02-inicio.png", 4.5, "2 · Her Início page: what needs attention, her agents, requests, budget and connections"),
    ("04-agente.png", 3.5, "3 · The agent Claude created: in production, owned by the Sales team"),
    ("05-playground.png", 5.0, "4 · A real question in the Playground. The answer comes from the team's memory"),
    ("06-memoria.png", 4.0, "5 · Team memory: dated facts that keep their history"),
    ("07-resumo-agendado.png", 5.5, "6 · The final result: the daily summary scheduled for weekdays at 8am"),
    ("08-conectar.png", 3.5, "7 · Plug it into Claude Code, Codex, Cursor, LibreChat… one revocable key per tool"),
    ("09-catalogo.png", 3.5, "8 · Company catalog: find other teams' agents and request access"),
]
W, H, BAR = 1440, 900, 64
FONT = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 25)


def slide(name: str, caption: str) -> Image.Image:
    img = Image.open(SH / name).convert("RGB").resize((W, H), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H + BAR), (28, 37, 48))
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, H, 10, H + BAR], fill=(244, 180, 0))
    d.text((32, H + BAR // 2), caption, font=FONT, fill=(255, 255, 255), anchor="lm")
    return canvas


frames = [(slide(n, c), secs) for n, secs, c in SLIDES]

# MP4 (1440x964, 30 fps, crossfade de 0,5 s)
FPS, FADE = 30, 15
writer = imageio_ffmpeg.write_frames(str(OUT / "portal-tour.mp4"), (W, H + BAR), fps=FPS, codec="libx264",
                                     pix_fmt_out="yuv420p", quality=8, macro_block_size=4)
writer.send(None)
arrs = [np.asarray(f) for f, _ in frames]
for i, (a, (_, secs)) in enumerate(zip(arrs, frames, strict=True)):
    for _ in range(int(secs * FPS)):
        writer.send(a.tobytes())
    if i + 1 < len(arrs):
        b = arrs[i + 1]
        for k in range(1, FADE + 1):
            t = k / (FADE + 1)
            writer.send((a * (1 - t) + b * t).astype(np.uint8).tobytes())
writer.close()

# GIF (1000 px, 2 quadros de transição entre slides, paleta de 160 cores)
GW = 1000
small = [(f.resize((GW, int((H + BAR) * GW / W)), Image.LANCZOS), secs) for f, secs in frames]
seq, durs = [], []
for i, (f, secs) in enumerate(small):
    seq.append(f)
    durs.append(int(secs * 1000))
    if i + 1 < len(small):
        for t in (0.33, 0.66):
            seq.append(Image.blend(f, small[i + 1][0], t))
            durs.append(90)
pal = [im.quantize(colors=160, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for im in seq]
pal[0].save(OUT / "portal-tour.gif", save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True)

# capturas individuais para o README (PNG otimizado, 1200 px)
for n in ("01-claude.png", "02-inicio.png", "05-playground.png", "06-memoria.png", "07-resumo-agendado.png"):
    im = Image.open(SH / n).convert("RGB")
    im = im.resize((1200, int(im.height * 1200 / im.width)), Image.LANCZOS)
    short = n.removesuffix(".png").split("-", 1)[1] + ".png"  # 02-inicio.png -> inicio.png
    im.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(OUT / short, optimize=True)

for f in sorted(OUT.iterdir()):
    print(f.name, round(f.stat().st_size / 1024), "KB")
