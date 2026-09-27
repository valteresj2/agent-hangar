"""Baixa (no build da imagem) as bibliotecas JS usadas pelos HTMLs, para o modo offline=true."""
import pathlib
import sys
import urllib.request

LIBS = {
    "chart.umd.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js",
    "plotly.min.js": "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js",
}

out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name, url in LIBS.items():
    urllib.request.urlretrieve(url, out / name)
    print(name, (out / name).stat().st_size)
