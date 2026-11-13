"""Vídeo do README: computer use governado (o Digital employee opera um ERP de desktop olhando a tela).
Capturas reais: /demo/frames (a tela do desktop durante a tarefa, 1 por segundo) e /demo/ui (o console)."""
import pathlib

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

D = pathlib.Path("/demo")
FR, UI, OUT = D / "frames", D / "ui", D / "out"
OUT.mkdir(exist_ok=True)
W, H, BAR = 1280, 800, 60
NAVY, AMBER, WHITE, MUTE, DESK = (28, 37, 48), (244, 180, 0), (255, 255, 255), (170, 182, 196), (22, 30, 44)
F = "/usr/share/fonts/truetype/liberation/LiberationSans-"


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(F + ("Bold" if bold else "Regular") + ".ttf", size)


def card(kicker: str, title: str, lines: list[str], foot: str = "") -> Image.Image:
    im = Image.new("RGB", (W, H + BAR), NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 14, H + BAR], fill=AMBER)
    y = 110
    if kicker:
        d.text((110, y), kicker.upper(), font=font(24), fill=AMBER)
        y += 52
    for t in title.split("\n"):
        d.text((110, y), t, font=font(52), fill=WHITE)
        y += 68
    y += 24
    for ln in lines:
        if ln.startswith("•"):
            d.ellipse([112, y + 12, 124, y + 24], fill=AMBER)
            d.text((146, y), ln[1:].strip(), font=font(28, False), fill=WHITE)
            y += 50
        elif ln.startswith("$"):
            d.rounded_rectangle([110, y - 4, 1170, y + 40], 8, fill=(15, 21, 29))
            d.text((128, y + 2), ln, font=ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf", 26),
                   fill=(230, 230, 230))
            y += 62
        else:
            d.text((110, y), ln, font=font(28, False), fill=MUTE)
            y += 46
    if foot:
        d.text((110, H + BAR - 90), foot, font=font(24, False), fill=MUTE)
    return im


def caption(im: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGB", (W, H + BAR), NAVY)
    canvas.paste(im, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, H, 10, H + BAR], fill=AMBER)
    d.text((30, H + BAR // 2), text, font=font(23), fill=WHITE, anchor="lm")
    return canvas


def fit(img: Image.Image, bg=NAVY) -> Image.Image:
    """Cabe a imagem em W×H mantendo a proporção, centralizada."""
    img = img.convert("RGB")
    s = min(W / img.width, H / img.height)
    img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    out = Image.new("RGB", (W, H), bg)
    out.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
    return out


def slide(name: str, text: str, crop=None) -> Image.Image:
    img = Image.open(UI / f"{name}.png").convert("RGB")
    if crop:
        img = img.crop(crop)
    return caption(fit(img), text)


# a janela do ERP dentro do desktop: a caixa do que não é fundo, no quadro do formulário preenchido
ref = Image.open(FR / "f0040.png").convert("RGB")
bg = Image.new("RGB", ref.size, ref.getpixel((ref.width // 2, ref.height - 120)))
box = ImageChops.difference(ref.crop((0, 40, ref.width, ref.height - 90)), bg.crop((0, 40, ref.width, ref.height - 90))).getbbox()
x0, y0, x1, y1 = box[0] - 16, box[1] + 40 - 16, box[2] + 16, box[3] + 40 + 16


def desk(i: int, text: str) -> Image.Image:
    im = Image.open(FR / f"f{i:04d}.png").convert("RGB").crop((x0, y0, x1, y1))
    return caption(fit(im, DESK), text)


SEQ = [
    (card("Agent Hangar v0.58", "Computer use,\ngoverned",
          ["A Digital employee operates desktop apps that have no API",
           "and no web page, by looking at the screen, with an approval",
           "before any click that confirms something."]), 6.0),
    (card("Why it matters", "What it brings",
          ["• Legacy ERPs, spreadsheets and installed systems join the work",
           "• The model sees the window: screenshot plus accessible elements",
           "• Saving, posting or paying waits for a person, with the screenshot",
           "• Passwords come from the vault (secret://); the model never sees them",
           "• An isolated Linux desktop with no internet, only the allowed apps",
           "• Every step on the task's timeline, screenshots kept as evidence"]), 10.0),
    (card("Turn it on", "One profile, then pick the apps",
          ["$ docker compose --profile desktop up -d desktop",
           "• Digital employee → Configurações: the apps it may open",
           "• Your own apps: add them to mcp-servers/desktop/Dockerfile",
           "• Built on Cua; the token never leaves the desktop container"]), 8.0),
    (slide("apps", "Admin · the governed desktop tools and the apps this employee may open"), 5.0),
    (slide("task-top", "The request, in plain words: log in, post the payment of invoice 102, confirm",
           (272, 0, 1440, 270)), 5.0),
]
LIVE = [(22, "It opens the ERP (a Tk app with no accessibility: vision only)", 1.2),
        (24, "User 'ana'…", 0.8), (26, "…and the password, typed from the vault: the model never sees it", 1.6),
        (29, "Entrar", 0.9), (31, "Logged in: 'Bem-vindo, ana'", 1.2),
        (34, "Invoice 102…", 0.9), (37, "…found: Gama Comércio ME, R$ 12.000,00 open", 1.6),
        (39, "The date, in the format the screen asks for", 1.2), (42, "The amount paid", 1.2),
        (46, "Confirmar baixa: this click changes the system, so it waits for the manager", 1.8),
        (47, "Approved: the system asks 'Confirma a baixa?', covered by the same approval", 1.8),
        (49, "Sim → 'Baixa registrada: fatura 102, pago R$ 12000,00 em 05/10/2026'", 2.6)]
SEQ += [(desk(i, t), s) for i, t, s in LIVE]
SEQ += [
    (caption(fit(Image.open(UI / "evidence.png")), "The approval request carried this screenshot: what the person approved is what got clicked"), 5.0),
    (slide("task-top", "The result, with the system's own receipt: approved in decision #692 and done once",
           (272, 280, 1440, 900)), 6.0),
    (slide("task-approval", "Screenshots kept as the task's evidence; the judge scored the result 5/5", (272, 300, 1440, 900)), 5.0),
    (card("Tested", "With a real model, end to end",
          ["DeepSeek through OpenRouter, on a regular install: 8 of 8 cases",
           "• Login with a vault password · a date typed in another format",
           "• A nonexistent invoice: nothing written, the employee says so",
           "• A confirmation dialog through the authority · menus and scrolling",
           "• Gnumeric: a formula saved with 'Save as' · reading a CSV",
           "• Two payments in one task, without duplicates"]), 9.0),
    (card("Get started", "Governed desktop in Agent Hangar",
          ["• Guide: valteresj2.github.io/agent-hangar/docs/analyst/",
           "• Platform: github.com/valteresj2/agent-hangar"],
          "Recorded on a real install with a real model; the ERP is a sample app."), 5.0),
]

FPS, FADE = 24, 8
path = OUT / "computer-use.mp4"
writer = imageio_ffmpeg.write_frames(str(path), (W, H + BAR), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                     bitrate="500k", macro_block_size=4,
                                     output_params=["-tune", "stillimage", "-movflags", "+faststart"])
writer.send(None)
arrs = [np.asarray(im) for im, _ in SEQ]
for i, (a, (_, secs)) in enumerate(zip(arrs, SEQ, strict=True)):
    for _ in range(int(secs * FPS)):
        writer.send(a.tobytes())
    if i + 1 < len(arrs):
        b = arrs[i + 1]
        n = 4 if (i >= 5 and i < 5 + len(LIVE)) else FADE  # na sequência ao vivo, cortes rápidos
        for k in range(1, n + 1):
            t = k / (n + 1)
            writer.send((a * (1 - t) + b * t).astype(np.uint8).tobytes())
writer.close()

for n, im in (("live-confirm", desk(47, "")), ("live-done", desk(49, ""))):
    im.crop((0, 0, W, H)).save(OUT / f"{n}.png")
print("total", round(sum(s for _, s in SEQ), 1), "s")
for f in sorted(OUT.iterdir()):
    print(f.name, round(f.stat().st_size / 1024), "KB")
