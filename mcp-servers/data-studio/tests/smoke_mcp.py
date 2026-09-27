"""Smoke do Data Studio via protocolo MCP (rode dentro da rede dos agentes):
    docker run --rm --network hangar_agents -v "$PWD/mcp-servers/data-studio/tests:/t" \
        agent-hangar/mcp-data-studio python /t/smoke_mcp.py
"""
import asyncio
import base64
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("MCP_URL", "http://data-studio:8000/mcp")
FILES = os.environ.get("FILES_URL", "http://data-studio:8001")
CSV = "regiao,produto,mes,vendas,custo\n" + "\n".join(
    f"{r},{p},2026-{m:02d},{v},{v * 0.6:.1f}" for r in ("Sul", "Norte", "Sudeste") for p in ("A", "B")
    for m, v in zip(range(1, 7), (100, 120, 90, 150, 170, 160), strict=True))
ok = 0


def check(name, cond, detail=""):
    global ok
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  -> {str(detail)[:600]}"))
    if not cond:
        sys.exit(1)
    ok += 1


async def call(session_id, tool, **args):
    async with streamablehttp_client(URL, headers={"X-Session-Id": session_id}, timeout=600) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args)
            text = "\n".join(getattr(c, "text", "") for c in res.content)
            return res.isError, text


async def main():
    run = os.urandom(3).hex()
    A, B = f"conversa-A-{run}", f"conversa-B-{run}"
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
    check("tools listadas", {"run_python", "run_sql", "create_presentation", "create_dashboard", "ingest_file",
                             "inspect_file", "create_document", "fetch_url"} <= names, names)

    err, t = await call(A, "ingest_file", filename="vendas 2026.csv", data_base64=base64.b64encode(CSV.encode()).decode())
    check("ingest", not err and json.loads(t)["path"] == "vendas_2026.csv", t)
    err, t2 = await call(A, "ingest_file", filename="outra.csv", data_base64=base64.b64encode(CSV.encode()).decode())
    check("ingest deduplica conteúdo repetido", json.loads(t2)["new"] is False, t2)
    err, t = await call(A, "inspect_file", path="vendas_2026.csv")
    check("inspect (perfil)", not err and "36 linhas" in t, t)
    err, t = await call(A, "list_tables")
    check("list_tables", not err and "vendas_2026" in t, t)
    err, t = await call(A, "run_sql", query="SELECT regiao, sum(vendas) total FROM vendas_2026 GROUP BY 1 ORDER BY 2 DESC",
                        save_as="totais.xlsx")
    check("run_sql + save_as xlsx", not err and "Sul" in t and "totais.xlsx" in t, t)
    err, t = await call(A, "run_python", code="df = pd.read_csv('vendas_2026.csv')\nprint(df.vendas.sum())")
    check("python", not err and "4740" in t, t)
    err, t = await call(A, "run_python", code="print(len(df))\ndf.groupby('mes').vendas.sum().plot(title='x'); plt.show()")
    check("python com estado + figura", not err and "36" in t and "figura_1.png" in t, t)
    err, t = await call(A, "create_presentation", title="Vendas 2026", slides=[
        {"type": "kpis", "title": "Resumo", "items": [{"label": "Vendas", "sql": "select sum(vendas) from vendas_2026"},
                                                      {"label": "Margem", "value": 0.4, "format": "pct"}]},
        {"type": "chart", "title": "Por mês", "chart": {"kind": "line", "sql": "select mes, sum(vendas) v from vendas_2026 group by 1 order by 1", "x": "mes", "y": ["v"]}},
        {"type": "chart", "title": "Mix", "chart": {"kind": "pie", "categories": ["A", "B"], "series": [{"name": "s", "values": [60, 40]}]}},
        {"type": "table", "title": "Top", "table": {"sql": "select regiao, sum(vendas) v from vendas_2026 group by 1"}},
        {"type": "image", "title": "Figura", "path": "figura_1.png"},
        {"type": "bullets", "title": "Próximos passos", "bullets": ["Expandir Norte", "  priorizar produto B"]}])
    files = json.loads(t)["files"] if not err else []
    check("pptx + html", not err and {f["file"] for f in files} == {"vendas_2026.pptx", "vendas_2026.html"}, t)
    err, t = await call(A, "create_dashboard", title="Painel de Vendas", kpis=[{"label": "Total", "sql": "select sum(vendas) from vendas_2026", "format": "int"}],
                        charts=[{"title": "Região", "kind": "column", "sql": "select regiao, sum(vendas) v from vendas_2026 group by 1", "x": "regiao", "y": ["v"]}],
                        tables=[{"title": "Base", "sql": "select * from vendas_2026"}], insights=["Sul lidera"])
    check("dashboard", not err and json.loads(t)["file"] == "painel_de_vendas.html", t)
    dash_url = json.loads(t)["url"]
    err, t = await call(A, "create_document", title="Relatório", format="docx",
                        markdown="## Resumo\n- **Sul** lidera\n\n[[table: select regiao, sum(vendas) v from vendas_2026 group by 1]]\n\n[[image: figura_1.png]]")
    check("docx", not err and json.loads(t)["file"] == "relatorio.docx", t)

    err, t = await call(A, "preview_file", path="vendas_2026.pptx")
    pv = json.loads(t) if not err else {}
    check("preview_file (LibreOffice -> PNG, sem pagina em branco)",
          not err and pv["pages"] >= 6 and not pv["blank_pages"] and len(pv["files"]) >= 6, t)
    err, t = await call(A, "create_dashboard", title="Offline", offline=True,
                        charts=[{"title": "x", "kind": "column", "categories": ["a"],
                                 "series": [{"name": "s", "values": [1]}]}])
    off_url = json.loads(t)["url"]
    r = httpx.get(off_url.replace(off_url.split("/f/")[0], FILES))
    check("dashboard offline embute o Plotly", "cdn.jsdelivr" not in r.text and len(r.text) > 1_000_000, len(r.text))

    internal = dash_url.replace(dash_url.split("/f/")[0], FILES)
    r = httpx.get(internal)
    check("download assinado (html inline)", r.status_code == 200 and "Plotly" in r.text, r.status_code)
    bad = internal.replace("/f/", "/f/").rsplit("/", 2)
    r = httpx.get(f"{bad[0]}/{'0' * 24}/{bad[2]}")
    check("token inválido recusado", r.status_code == 404, r.status_code)

    # isolamento: a conversa B não vê nem alcança os arquivos da A
    err, t = await call(B, "list_files")
    check("B não lista arquivos de A", "vendas" not in t, t)
    err, t = await call(B, "run_python", code="import glob; print(glob.glob('/data/sessions/*/*'))\n"
                                             "print(open('/data/.files_secret').read())")
    # modo process: a pasta existe mas é de outro uid; modo container: o sandbox nem enxerga /data
    check("B não lê workspace nem segredo de A",
          "vendas" not in t and ("Permission denied" in t or "No such file" in t), t)
    err, t = await call(B, "run_sql", query="select * from read_csv_auto('/data/sessions/*/vendas_2026.csv')")
    check("SQL de B não lê arquivos de A", "vendas" not in t.split("Erro")[0] or "Erro" in t, t)
    print(f"\n{ok} checks ok")


asyncio.run(main())
