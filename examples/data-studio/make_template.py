"""Gera templates/data-studio.yaml a partir de instructions.md e das skills desta pasta (fonte única do conteúdo).
    python examples/data-studio/make_template.py
"""
import pathlib

import yaml

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent.parent


def build() -> dict:
    from agent_def import SKILLS, TESTS  # mesma definição do caminho via MCP
    return {
        "id": "data-studio",
        "title": "Data Studio (análise de dados, dashboards e apresentações)",
        "description": "Analista de dados com Python e DuckDB num workspace por conversa: lê planilhas, CSV, PDF e "
                       "imagens (OCR), edita dados e entrega dashboards HTML, apresentações PPTX/HTML e relatórios. "
                       "Pensado para ser o motor do LibreChat (integrations/librechat).",
        "tags": ["chat", "data", "mcp", "librechat"],
        "needs": "Conexão de LLM (protocolo openai, de preferência com visão) e o MCP Data Studio no ar: "
                 "docker compose --profile data-studio up -d",
        "document": {
            "mcp_servers": [{"name": "data-studio", "url": "http://data-studio:8000/mcp",
                             "description": "Workspace por conversa + Python/DuckDB + PPTX, slides e dashboards HTML"}],
            "skills": [{"name": n, "description": d, "content": (HERE / f).read_text(encoding="utf-8")}
                       for n, (d, f) in SKILLS.items()],
            "agents": [{
                "name": "Data Studio", "slug": "data-studio", "owner": "dados",
                "objective": "Analisar dados (planilhas, CSV, PDF, imagens) em profundidade com Python e DuckDB, editar "
                             "dados e produzir apresentações PPTX/HTML, dashboards HTML e relatórios.",
                "final_output": "Resposta clara em markdown com números verificados e links para os arquivos gerados "
                                "(xlsx, pptx, html, docx, png).",
                "spec": {"instructions": (HERE / "instructions.md").read_text(encoding="utf-8"),
                         "llm": {"temperature": 0.2, "max_steps": 30},
                         "skills": list(SKILLS), "mcps": ["data-studio"],
                         "tools": [{"type": "builtin", "name": "current_time"}],
                         "channels": ["librechat"], "tests": TESTS},
            }],
        },
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE))
    out = ROOT / "templates" / "data-studio.yaml"
    out.write_text("# GERADO por examples/data-studio/make_template.py — edite os .md de lá, não este arquivo.\n"
                   + yaml.safe_dump(build(), sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    print(f"ok: {out}")
