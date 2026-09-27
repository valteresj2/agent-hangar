"""Funções chamadas DENTRO do kernel da sessão (uid da sessão, cwd = workspace). Tudo que lê arquivos do usuário
ou executa SQL roda aqui, nunca no processo do servidor — assim uma sessão não alcança os dados de outra."""
from pathlib import Path

from . import inspect_files, sqltools

HERE = Path(".")


def inspect(path: str, max_rows: int = 10, pages: int = 5, ocr: bool = False, lang: str = "por+eng") -> str:
    p = HERE / path
    if not p.exists():
        raise FileNotFoundError(f"{path} não existe no workspace")
    text = inspect_files.inspect(p, max_rows=max_rows, pages=pages)
    if ocr:
        text += "\n\n## OCR\n" + inspect_files.ocr(p, lang=lang, pages=pages)
    return text


def sql(query: str, max_rows: int = 50, save_as: str | None = None) -> str:
    text, df = sqltools.run(HERE, query, max_rows=max_rows)
    if df is not None and save_as:
        sqltools.save(df, HERE / save_as)
        text += f"\n\nResultado completo salvo em {save_as}."
    return text


def tables() -> str:
    return sqltools.views_md(HERE)


def query_df(query: str):
    con, _ = sqltools.connect(HERE)
    return con.execute(query).df()


def presentation(spec: dict) -> list[str]:
    from .builders import html_slides, pptx_builder
    formats = spec.get("formats") or ["pptx", "html"]
    base = spec.get("filename") or spec.get("title") or "apresentacao"
    out = []
    if "pptx" in formats:
        out.append(pptx_builder.build(spec, HERE, base, query_df))
    if "html" in formats:
        out.append(html_slides.build(spec, HERE, base, query_df))
    return out


def dashboard(spec: dict) -> str:
    from .builders import dashboard as dash
    return dash.build(spec, HERE, query_df)


def document(spec: dict) -> str:
    from .builders import documents
    return documents.build(spec, HERE, query_df)


def preview(path: str, max_pages: int = 6, width: int = 1280) -> dict:
    """Renderiza PPTX/DOCX/XLSX/ODP (via LibreOffice → PDF) ou PDF em PNGs, uma imagem por página/slide."""
    import subprocess

    import pdfplumber
    src = HERE / path
    if not src.exists():
        raise FileNotFoundError(f"{path} não existe no workspace")
    tmp = HERE / ".preview"
    tmp.mkdir(exist_ok=True)
    if src.suffix.lower() == ".pdf":
        pdf = src
    else:
        # perfil do LibreOffice explícito: o uid da sessão não tem entrada em /etc/passwd e sem isso ele trava
        profile = (HERE / ".lo-profile").resolve().as_uri()
        r = subprocess.run(["soffice", f"-env:UserInstallation={profile}", "--headless", "--norestore",
                            "--convert-to", "pdf", "--outdir", str(tmp), str(src)],
                           capture_output=True, text=True, timeout=180)
        pdf = tmp / (src.stem + ".pdf")
        if not pdf.exists():
            raise RuntimeError(f"LibreOffice não converteu {path}: {(r.stderr or r.stdout)[-400:]}")
    out, blank = [], []
    with pdfplumber.open(pdf) as doc:
        total = len(doc.pages)
        for i, page in enumerate(doc.pages[:max_pages], 1):
            im = page.to_image(resolution=int(72 * width / max(page.width, 1))).original.convert("RGB")
            name = f"preview_{src.stem}_{i}.png"
            im.save(HERE / name)
            out.append(name)
            # página "em branco": praticamente sem variação de cor (render quebrado ou slide vazio)
            lo, hi = im.convert("L").getextrema()
            if hi - lo < 8:
                blank.append(i)
    return {"pages": total, "images": out, "blank_pages": blank}
