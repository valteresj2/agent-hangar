"""Utilidades dos geradores: dados de gráficos/tabelas (inline ou via SQL), temas e nomes de arquivo."""
import math
import re
import unicodedata

THEMES = {
    "light": {"bg": "FFFFFF", "fg": "1F2937", "muted": "6B7280", "accent": "4F46E5", "card": "F3F4F6",
              "palette": ["4F46E5", "0EA5E9", "10B981", "F59E0B", "EF4444", "8B5CF6", "14B8A6", "F97316"]},
    "dark": {"bg": "0F172A", "fg": "E2E8F0", "muted": "94A3B8", "accent": "818CF8", "card": "1E293B",
             "palette": ["818CF8", "38BDF8", "34D399", "FBBF24", "F87171", "A78BFA", "2DD4BF", "FB923C"]},
    "corporate": {"bg": "FFFFFF", "fg": "0B1F3A", "muted": "5B6B82", "accent": "0B5CAD", "card": "EEF3F9",
                  "palette": ["0B5CAD", "2E8B57", "E07B39", "7A4EAB", "C0392B", "1F9BBD", "B8860B", "5D6D7E"]},
}


def theme(spec: dict) -> dict:
    t = dict(THEMES.get(spec.get("theme", "light"), THEMES["light"]))
    acc = (spec.get("accent") or "").lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", acc):
        t["accent"] = acc.upper()
        t["palette"] = [acc.upper()] + t["palette"][1:]
    return t


def filename(base: str, ext: str) -> str:
    # o LLM às vezes já manda "relatorio.pptx": remove a extensão antes de sanitizar (evita relatorio_pptx.pptx)
    base = re.sub(r"\.(pptx|html?|docx|md|xlsx|csv|pdf|png)$", "", base.strip(), flags=re.IGNORECASE)
    s = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\-]+", "_", s).strip("_").lower()[:60] or "arquivo"
    return s if s.endswith(ext) else f"{s}{ext}"


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def chart_data(ch: dict, query_df) -> tuple[list[str], list[dict]]:
    """{categories, series:[{name, values}]} inline, ou {sql, x, y} executado no DuckDB do workspace."""
    if ch.get("sql"):
        df = query_df(ch["sql"])
        if df.empty:
            return [], []
        x = ch.get("x") or df.columns[0]
        ys = ch.get("y") or [c for c in df.columns if c != x]
        ys = [ys] if isinstance(ys, str) else list(ys)
        cats = [str(v) for v in df[x].tolist()]
        return cats, [{"name": str(y), "values": [_num(v) for v in df[y].tolist()]} for y in ys]
    cats = [str(c) for c in ch.get("categories") or []]
    series = [{"name": str(s.get("name", f"Série {i+1}")), "values": [_num(v) for v in s.get("values", [])]}
              for i, s in enumerate(ch.get("series") or [])]
    return cats, series


def table_data(t: dict, query_df, limit: int = 500) -> tuple[list[str], list[list]]:
    if t.get("sql"):
        df = query_df(t["sql"]).head(limit)
        rows = [[("" if v is None or (isinstance(v, float) and math.isnan(v)) else v) for v in r]
                for r in df.itertuples(index=False)]
        return [str(c) for c in df.columns], rows
    return [str(c) for c in t.get("columns") or []], [list(r) for r in (t.get("rows") or [])[:limit]]


def fmt(v, spec_fmt: str | None = None) -> str:
    """Formata números no padrão pt-BR (1.234,5). spec_fmt: 'int' | 'pct' | 'brl' | 'usd' | 'dec'."""
    if isinstance(v, str) or v is None:
        return "" if v is None else v
    f = float(v)
    if spec_fmt == "pct":
        s = f"{f*100 if abs(f) <= 1 else f:,.1f}%"
    elif spec_fmt in ("brl", "usd"):
        s = f"{f:,.2f}"
        s = ("R$ " if spec_fmt == "brl" else "US$ ") + s
    elif spec_fmt == "int" or (spec_fmt is None and f.is_integer()):
        s = f"{f:,.0f}"
    else:
        s = f"{f:,.2f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def scalar(item: dict, query_df):
    if item.get("sql"):
        df = query_df(item["sql"])
        return None if df.empty else df.iat[0, 0]
    return item.get("value")
