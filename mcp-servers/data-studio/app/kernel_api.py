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
