"""Folha de contato dos quadros-chave (revisão): python contact.py Launch 4 480"""
import pathlib
import sys

from PIL import Image, ImageDraw

name, cols, w = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
files = sorted(pathlib.Path("out/stills").glob(f"{name}-[0-9]*.png"))
first = Image.open(files[0])
h = round(w * first.height / first.width)
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w, rows * (h + 22)), (12, 16, 20))
d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    x, y = (i % cols) * w, (i // cols) * (h + 22)
    sheet.paste(Image.open(f).convert("RGB").resize((w, h)), (x, y + 22))
    d.text((x + 6, y + 4), f.stem.split("-")[-1], fill=(244, 180, 0))
sheet.save(f"out/stills/{name}-sheet.png")
print(f"out/stills/{name}-sheet.png")
