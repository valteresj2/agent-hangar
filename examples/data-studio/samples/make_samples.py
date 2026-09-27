"""Gera os arquivos de exemplo usados no teste do Data Studio (dados fictícios):
    docker run --rm -v "$PWD/examples/data-studio/samples:/out" -w /out agent-hangar/mcp-data-studio python make_samples.py
"""
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image, ImageDraw, ImageFont

rng = np.random.default_rng(42)

# ---------- planilha de vendas (com sujeira proposital) ----------
lojas = {"Loja Centro": "Sudeste", "Loja Paulista": "Sudeste", "Loja Moinhos": "Sul", "Loja Batel": "Sul",
         "Loja Boa Viagem": "Nordeste", "Loja Pituba": "Nordeste", "Loja Asa Sul": "Centro-Oeste"}
produtos = {"Notebook Pro": ("Informática", 7200), "Monitor 27": ("Informática", 1900), "Mouse sem fio": ("Acessórios", 150),
            "Teclado mecânico": ("Acessórios", 480), "Headset": ("Áudio", 650), "Caixa de som": ("Áudio", 900),
            "Webcam 4K": ("Acessórios", 820), "Tablet 11": ("Mobile", 3100)}
rows = []
dates = pd.date_range("2026-01-01", "2026-06-30", freq="D")
for _ in range(1000):
    d = dates[rng.integers(len(dates))]
    loja = rng.choice(list(lojas))
    prod = rng.choice(list(produtos))
    cat, preco = produtos[prod]
    sazonal = 1 + 0.25 * (d.month >= 5)
    qtd = int(max(1, rng.poisson(3 * sazonal)))
    desconto = float(rng.choice([0, 0, 0, 0.05, 0.1]))
    receita = round(qtd * preco * (1 - desconto), 2)
    regiao = lojas[loja]
    if rng.random() < 0.04:  # sujeira: região escrita de outras formas
        regiao = rng.choice([regiao.lower(), regiao + " ", regiao.upper()])
    rows.append({"data": d.date(), "loja": loja, "regiao": regiao, "produto": prod, "categoria": cat, "quantidade": qtd,
                 "preco_unitario": preco if rng.random() > 0.02 else None, "desconto": desconto,
                 "receita": receita, "custo": round(receita * rng.uniform(0.55, 0.7), 2)})
vendas = pd.DataFrame(rows).sort_values("data")
metas = pd.DataFrame({"regiao": ["Sudeste", "Sul", "Nordeste", "Centro-Oeste"],
                      "meta_mensal": [220000, 140000, 130000, 60000]})
with pd.ExcelWriter("vendas_2026.xlsx") as xw:
    vendas.to_excel(xw, sheet_name="Vendas", index=False)
    metas.to_excel(xw, sheet_name="Metas", index=False)

# ---------- PDF com tabela de fornecedores ----------
forn = pd.DataFrame({
    "Fornecedor": ["TechDistrib", "Alfa Import", "MegaParts", "SoundWave", "VisionCam"],
    "Categoria": ["Informática", "Mobile", "Acessórios", "Áudio", "Acessórios"],
    "Prazo (dias)": [12, 25, 7, 15, 20], "Custo frete (R$)": [850, 1400, 300, 520, 610],
    "Nota qualidade": [4.6, 3.8, 4.2, 4.9, 3.5]})
with PdfPages("relatorio_fornecedores.pdf") as pdf:
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.08, 0.93, "Relatório de Fornecedores – 1º semestre 2026", fontsize=16, weight="bold")
    fig.text(0.08, 0.89, "Avaliação de prazo de entrega, frete e qualidade dos principais fornecedores.", fontsize=10)
    ax = fig.add_axes([0.08, 0.55, 0.84, 0.3])
    ax.axis("off")
    tb = ax.table(cellText=forn.values, colLabels=forn.columns, loc="center")
    tb.scale(1, 1.6)
    fig.text(0.08, 0.5, "Observações: a Alfa Import teve 3 atrasos acima de 30 dias em abril.\n"
                        "Recomenda-se renegociar o frete da Alfa Import e ampliar o volume com a MegaParts.",
             fontsize=10)
    pdf.savefig(fig)
    plt.close(fig)

# ---------- imagem: quadro de estoque ----------
img = Image.new("RGB", (900, 420), "white")
dr = ImageDraw.Draw(img)
try:
    f = ImageFont.truetype("DejaVuSans.ttf", 26)
    fb = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
except OSError:
    f = fb = ImageFont.load_default()
dr.text((30, 20), "Estoque atual – 30/06/2026", font=fb, fill="black")
estoque = [("Produto", "Unidades", "Mínimo"), ("Notebook Pro", "18", "25"), ("Monitor 27", "64", "30"),
           ("Tablet 11", "9", "20"), ("Headset", "120", "40"), ("Webcam 4K", "33", "15")]
for i, (a, b, c) in enumerate(estoque):
    y = 80 + i * 52
    font = fb if i == 0 else f
    dr.text((40, y), a, font=font, fill="black")
    dr.text((460, y), b, font=font, fill="black")
    dr.text((680, y), c, font=font, fill="black")
    dr.line((30, y + 44, 870, y + 44), fill="#cccccc", width=2)
img.save("quadro_estoque.png")
print("ok:", len(vendas), "vendas")
