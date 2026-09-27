"""SQL analítico com DuckDB sobre os arquivos do workspace: cada tabela vira uma view com nome derivado do arquivo."""
import re
from pathlib import Path

import duckdb
import pandas as pd

from .inspect_files import read_table

MAX_ROWS = 200


def view_name(stem: str, sheet: str | None = None) -> str:
    base = stem if not sheet or sheet == stem else f"{stem}_{sheet}"
    n = re.sub(r"\W+", "_", base.lower(), flags=re.UNICODE).strip("_") or "t"
    return f"t_{n}" if n[0].isdigit() else n


def connect(ws: Path) -> tuple[duckdb.DuckDBPyConnection, dict[str, str]]:
    con = duckdb.connect()
    views = {}
    for p in sorted(ws.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        s, q = p.suffix.lower(), str(p).replace("'", "''")
        try:
            if s in (".csv", ".tsv"):
                name = view_name(p.stem)
                con.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM read_csv_auto('{q}', sample_size=-1)")
            elif s == ".parquet":
                name = view_name(p.stem)
                con.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM read_parquet('{q}')")
            elif s in (".json", ".jsonl", ".ndjson"):
                name = view_name(p.stem)
                con.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM read_json_auto('{q}')")
            elif s in (".xlsx", ".xlsm", ".xls"):
                for sheet, df in read_table(p).items():
                    name = view_name(p.stem, sheet if len(pd.ExcelFile(p).sheet_names) > 1 else None)
                    con.register(f"_df_{name}", df)
                    con.execute(f"CREATE VIEW \"{name}\" AS SELECT * FROM \"_df_{name}\"")
                    views[name] = f"{p.name} [{sheet}]"
                continue
            else:
                continue
            views[name] = p.name
        except Exception as e:  # arquivo malformado não impede consultar os outros
            views[f"(erro) {p.name}"] = str(e)[:200]
    return con, views


def run(ws: Path, query: str, max_rows: int = 50, save_as: str | None = None) -> tuple[str, pd.DataFrame | None]:
    con, views = connect(ws)
    try:
        df = con.execute(query).df()
    except Exception as e:
        avail = "\n".join(f"- {k} ← {v}" for k, v in views.items()) or "(nenhuma tabela no workspace)"
        return f"Erro no SQL: {e}\n\nViews disponíveis:\n{avail}", None
    note = f"{len(df):,} linha(s) × {len(df.columns)} coluna(s)."
    shown = min(max_rows, MAX_ROWS)
    body = df.head(shown).to_markdown(index=False) if len(df.columns) else "(sem resultado)"
    if len(df) > shown:
        body += f"\n… mostrando {shown} de {len(df):,} linhas (use save_as para o resultado completo)."
    return f"{note}\n\n{body}", df


def views_md(ws: Path) -> str:
    con, views = connect(ws)
    lines = []
    for name, src in views.items():
        if name.startswith("(erro)"):
            lines.append(f"- {name}: {src}")
            continue
        cols = con.execute(f"DESCRIBE \"{name}\"").fetchall()
        n = con.execute(f"SELECT count(*) FROM \"{name}\"").fetchone()[0]
        lines.append(f"- **{name}** ← {src} — {n:,} linhas: " + ", ".join(f"{c[0]} {c[1]}" for c in cols[:40]))
    return "\n".join(lines) or "(nenhum arquivo tabular no workspace)"


def save(df: pd.DataFrame, path: Path):
    s = path.suffix.lower()
    if s == ".csv":
        df.to_csv(path, index=False)
    elif s == ".xlsx":
        df.to_excel(path, index=False)
    elif s == ".parquet":
        df.to_parquet(path, index=False)
    elif s == ".json":
        df.to_json(path, orient="records", force_ascii=False, indent=2)
    else:
        raise ValueError("save_as deve terminar em .csv, .xlsx, .parquet ou .json")
