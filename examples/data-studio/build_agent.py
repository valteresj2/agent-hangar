"""Cria o agente "Data Studio" usando SÓ o MCP da plataforma — o mesmo caminho do Claude/Codex/OpenCode.

    HANGAR_URL=http://localhost:8090 HANGAR_TOKEN=<admin> LLM_CONNECTION=<conexão openai> python build_agent.py

Pré-requisito: `docker compose --profile data-studio up -d` (o MCP server de ferramentas).
"""
import asyncio
import json
import os
import pathlib

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("HANGAR_URL", "http://localhost:8090").rstrip("/") + "/mcp"
TOKEN = os.environ["HANGAR_TOKEN"]
CONNECTION = os.environ.get("LLM_CONNECTION", "")
HERE = pathlib.Path(__file__).parent

INSTRUCTIONS = (HERE / "instructions.md").read_text(encoding="utf-8")
from agent_def import SKILLS, TESTS  # noqa: E402


async def main():
    async with streamablehttp_client(URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=900,
                                     sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(tool, **args):
                res = await s.call_tool(tool, args)
                text = "\n".join(getattr(c, "text", "") for c in res.content)
                shown = "(chave omitida)" if tool == "create_consumer_key" else text[:300]
                print(f"· {tool}: {shown}")
                if res.isError:
                    raise SystemExit(f"{tool} falhou: {text}")
                return text

            await call("register_mcp_server", name="data-studio", url="http://data-studio:8000/mcp",
                       description="Workspace por conversa + Python/DuckDB + PPTX, slides e dashboards HTML, DOCX, OCR")
            for name, (desc, fname) in SKILLS.items():
                await call("register_skill", name=name, description=desc,
                           content=(HERE / fname).read_text(encoding="utf-8"))
            try:
                reg = json.loads(await call("register_agent", name="Data Studio",
                                            objective="Analisar dados (planilhas, CSV, PDF, imagens) em profundidade "
                                                      "com Python e DuckDB, editar dados e produzir apresentações "
                                                      "PPTX/HTML, dashboards HTML e relatórios.",
                                            final_output="Resposta clara em markdown com números verificados e links "
                                                         "para os arquivos gerados (xlsx, pptx, html, docx, png).",
                                            owner="dados"))
                slug = reg["slug"]
            except SystemExit:
                slug = "data-studio"
            llm = {"model": None, "temperature": 0.2, "max_steps": 30, "vision": True}
            if CONNECTION:
                llm["connection"] = CONNECTION
            await call("design_agent", slug=slug, instructions=INSTRUCTIONS, llm=llm,
                       skills=list(SKILLS), mcps=["data-studio"],
                       tools=[{"type": "builtin", "name": "current_time"}], tests=TESTS,
                       channels=["librechat"])
            print(await call("ship_agent", slug=slug))
            key = json.loads(await call("create_consumer_key", name="librechat-data-studio", agents=[slug]))
            out = HERE / ".invoke_key"
            out.write_text(key["key"])
            print(f"\nAgente '{slug}' em produção. Chave de consumo gravada em {out} (não versionar).")


asyncio.run(main())
