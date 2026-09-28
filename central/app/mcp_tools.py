"""MCP da plataforma: é por aqui que Claude/ChatGPT/Codex/OpenCode constroem agentes via chat."""
import asyncio

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select

from . import auth, config
from . import services as svc
from . import spec as specmod
from .db import SessionLocal
from .models import Job, LlmConnection, McpServer, Skill

INSTRUCTIONS = """
Você está conectado ao Agent Hangar da empresa. Sua missão: construir agentes (ou multiagentes)
conforme o pedido do usuário, testá-los em stage e deixá-los deployados e prontos para uso.

A plataforma NUNCA hospeda um LLM. Cada agente chama um LLM externo através de uma "Conexão de LLM"
do catálogo (nome + base_url + model_name + api key virtual — normalmente o gateway LiteLLM corporativo,
ou um provedor como OpenRouter/OpenAI/Anthropic). Sem conexão, o agente roda no modelo mock/echo (sem
custo, só para validar o fluxo).

Existem dois TIPOS de agente, e um agente pode ser single ou multi (orquestrador + sub-agentes):
- Agente de CHAT (padrão): um loop LLM + tools/MCP, sempre no ar, responde perguntas. Bom para
  Q&A, análise, redação, orquestração de sub-agentes.
- Agente com HARNESS (harness={"id":"claude-code"|"codex"|"hermes"|"deepseek-harness","connection":"<nome>"}):
  delega a tarefa a um harness completo que roda de verdade — edita arquivo, usa shell, git — dentro de
  UM CONTAINER EFÊMERO NOVO A CADA CHAMADA. Cada harness exige uma conexão do protocolo que ele fala:
    - "claude-code": protocol="anthropic" (API da Anthropic, ou gateway compatível com /v1/messages).
    - "codex" e "hermes": protocol="openai" (OpenAI, LiteLLM, OpenRouter…).
    - "deepseek-harness": protocol="deepseek" (só verificado contra a API oficial da DeepSeek).
  Sem indicação do usuário, prefira "claude-code". Um agente-com-harness NÃO pode ter sub_agents, mas PODE
  ser sub_agent de um orquestrador de chat.

A ESCOLHA DO TIPO É SUA, NÃO DO USUÁRIO — decida pelo OBJETIVO, sem perguntar "chat, harness ou
multiagente?" por padrão:
- Responder, analisar, redigir, classificar, consultar dados via MCP/tool, orquestrar -> CHAT.
- O objetivo decompõe em papéis especialistas distintos que se beneficiam de instruções e testes
  separados -> MULTIAGENTE (build_multi_agent). Tarefa coesa -> um agente só; não fragmente à toa.
- Exige EXECUÇÃO real (editar arquivo, rodar código, git, "corrija esse bug", "abra um PR") -> HARNESS.
Ao final, diga qual tipo escolheu e por quê, numa frase. Só pergunte se o objetivo for ambíguo, ou se for
usar HARNESS (avise que executa ações de verdade), a não ser que o usuário já tenha pedido explicitamente.

FLUXO
1. Entenda o pedido. Se faltar algo essencial, PERGUNTE: nome, objetivo, saída final esperada,
   sistemas/dados que acessa, riscos (ações destrutivas, dados sensíveis).
2. list_templates -> se um template já resolve o pedido, use apply_template (e ajuste com design_agent).
3. list_catalog -> REUTILIZE skills, MCPs e conexões de LLM. Sem conexão de LLM: pergunte ao usuário
   url, model_name e api key e registre com register_llm_connection (ou siga em mock/echo para testar).
4. register_agent(name, objective, final_output) -> devolve o slug.
5. design_agent(slug, ...) define o comportamento. É um JSON Merge Patch: objetos mesclam, listas e
   valores substituem, e null (ou o parâmetro `remove`) APAGA o campo. Ex.: trocar de conexão e voltar
   ao modelo padrão dela = llm={"connection": "x", "model": null}. Veja o formato completo em
   get_spec_schema. Inclua 2+ casos em `tests` ({name, input, expect_contains | expect_regex | judge});
   `judge` é uma rubrica avaliada por um LLM (use para respostas abertas).
6. Multiagente: crie os especialistas e depois o orquestrador com sub_agents=[slugs] (build_multi_agent).
7. ship_agent(slug): testa em stage, registra e só promove para produção se passar. Se falhar, leia os
   resultados, corrija com design_agent e rode de novo. Errou uma versão? rollback_agent.
8. Ao final informe: slug, versão, endpoints (OpenAI-compatible, A2A, ACP e MCP — todo agente é também um
   servidor MCP com 1 tool), resultado dos testes. Para o usuário plugar o agente numa ferramenta (Claude
   Code/Desktop, Codex, OpenCode, Cursor, VS Code, LibreChat, Open WebUI…), use connect_agent(slug, client,
   mode): "mcp" = o agente vira ferramenta (todas); "model" = vira modelo no chat (LibreChat, Open WebUI,
   OpenCode, SDK OpenAI). Ela gera uma chave só daquela ferramenta e devolve a configuração pronta — NUNCA
   entregue o token de admin. Para agente com harness, run_harness_job mostra resultado/diff.

Todo agente roda em container Docker isolado (harness: um container novo por execução, nunca ocioso).
Nunca coloque segredos em instructions/tools: chaves de LLM ficam criptografadas no catálogo da central.
""".strip()

mcp = FastMCP("agent-hangar", instructions=INSTRUCTIONS, host="0.0.0.0", port=8080,
              streamable_http_path="/mcp", stateless_http=True, json_response=True,
              # o Host varia (localhost, IP, domínio público); a autenticação é feita pelo AuthMiddleware
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


async def _run(fn, *a, **kw):
    """Roda a chamada (DB + Docker, bloqueante) numa thread — nunca no event loop. Essencial para jobs de
    harness: enquanto uma tool espera, o event loop precisa receber o callback do container do job."""
    def go():
        with SessionLocal() as db:
            return fn(db, *a, **kw)
    return await asyncio.to_thread(go)


ACTOR = "mcp"


@mcp.tool()
def platform_guide() -> str:
    """Leia primeiro: explica o fluxo e as regras da plataforma. O formato da spec está em get_spec_schema."""
    return INSTRUCTIONS


@mcp.tool()
def get_spec_schema() -> dict:
    """JSON Schema completo da spec de um agente (llm, harness, judge, instructions, skills, mcps, tools,
    sub_agents, tests, channels) — use para montar design_agent sem adivinhar campos."""
    return specmod.json_schema()


@mcp.tool()
async def list_catalog() -> dict:
    """Skills, MCP servers e conexões de LLM disponíveis para reutilizar (sem expor as api keys)."""
    def go(db):
        return {"skills": [{"name": s.name, "description": s.description} for s in db.scalars(select(Skill))],
                "mcp_servers": [{"name": m.name, "url": m.url, "description": m.description}
                                for m in db.scalars(select(McpServer))],
                "llm_connections": [svc.llm_connection_dict(c) for c in db.scalars(select(LlmConnection))],
                "builtin_tools": ["calculator", "current_time", "platform_dashboard"],
                "harnesses": svc.HARNESS_PROTOCOL,
                "fallback_sem_conexao": f"{config.DEFAULT_MODEL} (sem custo, sem chave — só para testar o fluxo)"}
    return await _run(go)


@mcp.tool()
async def register_llm_connection(name: str, base_url: str, model_name: str, api_key: str, description: str = "",
                                  protocol: str = "openai", price_in_per_mtok: float | None = None,
                                  price_out_per_mtok: float | None = None) -> dict:
    """Registra (ou atualiza) uma conexão de LLM: endpoint + model_name padrão + api key (idealmente virtual).
    protocol="openai" (chat, codex, hermes), "anthropic" (claude-code) ou "deepseek" (deepseek-harness).
    Preços por 1M tokens (US$) são opcionais e habilitam o cálculo de custo. A chave é guardada
    criptografada e nunca é devolvida."""
    c = await _run(svc.upsert_llm_connection, name, base_url, model_name, api_key, description, ACTOR, protocol,
                   price_in_per_mtok, price_out_per_mtok)
    return {"registered": c.name, "base_url": c.base_url, "model_name": c.model_name, "protocol": c.protocol}


@mcp.tool()
async def register_skill(name: str, description: str, content: str) -> dict:
    """Registra (ou atualiza) uma skill reutilizável: instruções/procedimento/conhecimento em markdown."""
    s = await _run(svc.upsert_skill, name, description, content, ACTOR)
    return {"registered": s.name}


@mcp.tool()
async def register_mcp_server(name: str, url: str, description: str = "") -> dict:
    """Registra um MCP server (Streamable HTTP) no catálogo para os agentes usarem."""
    m = await _run(svc.upsert_mcp, name, url, description, ACTOR)
    return {"registered": m.name, "url": m.url}


@mcp.tool()
async def list_templates() -> list:
    """Templates de agentes prontos (doc Q&A, triagem, revisor de PR, time de pesquisa…)."""
    return svc.list_templates()


@mcp.tool()
async def apply_template(template_id: str, connection: str = "", harness_connection: str = "") -> list:
    """Cria os agentes de um template. `connection` (protocolo openai) alimenta os agentes de chat;
    `harness_connection` os agentes-com-harness. Sem conexões, nascem em mock. Depois: ship_agent."""
    return await _run(svc.apply_template, template_id, connection, harness_connection, ACTOR)


@mcp.tool()
async def register_agent(name: str, objective: str, final_output: str, owner: str = "") -> dict:
    """Registra um agente: nome, objetivo e saída final. Devolve o slug para as próximas chamadas."""
    def go(db):
        a = svc.create_agent(db, name, objective, final_output, owner=owner, actor=ACTOR)
        return {"slug": a.slug, "status": a.status, "version": a.current_version,
                "next": "design_agent para definir instruções, skills, MCPs, tools e testes"}
    return await _run(go)


@mcp.tool()
async def design_agent(slug: str, instructions: str | None = None, model: str | None = None,
                       skills: list | None = None, mcps: list | None = None, tools: list | None = None,
                       sub_agents: list | None = None, tests: list | None = None, channels: list | None = None,
                       llm: dict | None = None, harness: dict | None = None, judge: dict | None = None,
                       remove: list[str] | None = None) -> dict:
    """Atualiza a spec do agente (gera nova versão se mudar). JSON Merge Patch: passe só o que quer mudar;
    dentro de llm/harness/judge, um valor null apaga o campo. `remove` apaga campos inteiros (ex.:
    remove=["harness"] para voltar a ser agente de chat, ou remove=["llm"] antes de virar harness)."""
    patch = {k: v for k, v in (("instructions", instructions), ("skills", skills), ("mcps", mcps),
                               ("tools", tools), ("sub_agents", sub_agents), ("tests", tests),
                               ("channels", channels), ("llm", llm), ("harness", harness), ("judge", judge))
             if v is not None}
    if model is not None:
        patch["llm"] = {**(patch.get("llm") or {}), "model": model or None}
    for k in remove or []:
        patch[k] = None
    a = await _run(svc.design_agent, slug, patch, ACTOR)
    return {"slug": a.slug, "version": a.current_version, "status": a.status, "kind": a.kind,
            "next": "ship_agent (testa em stage e promove) ou run_tests"}


@mcp.tool()
async def rollback_agent(slug: str, version: int) -> dict:
    """Restaura a spec de uma versão anterior como uma versão nova (o histórico nunca é reescrito)."""
    a = await _run(svc.rollback_agent, slug, version, ACTOR)
    return {"slug": a.slug, "version": a.current_version, "status": a.status, "next": "ship_agent"}


@mcp.tool()
async def build_multi_agent(name: str, objective: str, final_output: str, orchestrator_instructions: str,
                            members: list, connection: str = "", model: str = "", owner: str = "") -> dict:
    """Cria um multiagente de uma vez. members: [{name, objective, final_output, instructions, skills?, mcps?,
    tools?, tests?}]. Cada membro vira um agente; o orquestrador delega a eles via A2A. `connection`/`model`
    valem para todos. Depois use ship_agent no orquestrador."""
    def go(db):
        llm_patch = {k: v for k, v in (("connection", connection), ("model", model)) if v}
        slugs = []
        for m in members:
            a = svc.create_agent(db, m["name"], m["objective"], m["final_output"], owner=owner, actor=ACTOR)
            patch = {k: m[k] for k in ("instructions", "skills", "mcps", "tools", "tests") if k in m}
            if llm_patch:
                patch["llm"] = llm_patch
            svc.design_agent(db, a.slug, patch, ACTOR)
            slugs.append(a.slug)
        o = svc.create_agent(db, name, objective, final_output, owner=owner, actor=ACTOR)
        patch = {"instructions": orchestrator_instructions, "sub_agents": slugs}
        if llm_patch:
            patch["llm"] = llm_patch
        svc.design_agent(db, o.slug, patch, ACTOR)
        return {"orchestrator": o.slug, "members": slugs, "next": f"ship_agent('{o.slug}')"}
    return await _run(go)


@mcp.tool()
async def list_agents() -> list:
    """Agentes registrados com status, versão, onde rodam e uso dos últimos 7 dias."""
    def go(db):
        keep = ("slug", "name", "kind", "status", "version", "model", "requests_7d", "cost_7d")
        return [{k: a[k] for k in keep} | {"stage": bool(a["stage"]), "prod": bool(a["prod"])}
                for a in svc.list_agents(db)]
    return await _run(go)


@mcp.tool()
async def get_agent(slug: str) -> dict:
    """Detalhe completo: spec, versões, testes, deployments, jobs, endpoints e uso."""
    def go(db):
        a = svc.get_agent(db, slug)
        svc.refresh_deployments(db, [a])
        return svc.agent_dict(db, a, detail=True)
    return await _run(go)


@mcp.tool()
async def run_tests(slug: str) -> dict:
    """Deploy em stage (container isolado) + smoke (health, A2A, ACP, OpenAI, MCP) + casos da spec."""
    return svc.test_dict(await _run(svc.run_tests, slug, ACTOR))


@mcp.tool()
async def deploy_stage(slug: str) -> dict:
    """Deploy no ambiente de stage."""
    return svc.dep_dict(await _run(svc.deploy_env, slug, "stage", ACTOR))


@mcp.tool()
async def promote_to_production(slug: str) -> dict:
    """Promove para produção. Só funciona se a versão atual passou nos testes de stage."""
    return svc.dep_dict(await _run(svc.promote, slug, ACTOR))


@mcp.tool()
async def ship_agent(slug: str) -> list:
    """Atalho: (sub-agentes primeiro) testa em stage, registra e promove para produção se aprovado."""
    return await _run(svc.ship, slug, ACTOR)


@mcp.tool()
async def stop_agent(slug: str, env: str = "prod") -> dict:
    """Para o container do agente (env: stage|prod)."""
    await _run(svc.stop, slug, env, ACTOR)
    return {"stopped": slug, "env": env}


@mcp.tool()
async def chat_with_agent(slug: str, message: str, env: str = "prod") -> dict:
    """Conversa com um agente deployado. Para agente-com-harness, dispara um job (prefira run_harness_job)."""
    return await _run(svc.chat, slug, message, env, "mcp", ACTOR)


@mcp.tool()
async def run_harness_job(slug: str, task: str, env: str = "stage", timeout_s: int = 180, wait: bool = True) -> dict:
    """Job de harness num container efêmero: executa a `task` e devolve resultado + diff + logs + tokens.
    wait=false devolve o job em fila na hora (acompanhe com get_job; cancele com cancel_job)."""
    if wait:
        return svc.job_dict(await _run(svc.run_harness_job, slug, task, env, timeout_s, ACTOR, "mcp"))
    return svc.job_dict(await _run(svc.submit_job, slug, task, env, timeout_s, ACTOR, "mcp"))


@mcp.tool()
async def get_job(job_id: int) -> dict:
    """Estado atual de um job de harness."""
    def go(db):
        job = db.get(Job, job_id)
        if not job:
            raise svc.PlatformError(f"job {job_id} não encontrado")
        return svc.job_dict(job)
    return await _run(go)


@mcp.tool()
async def cancel_job(job_id: int) -> dict:
    """Cancela um job em fila ou rodando (o container é removido)."""
    return svc.job_dict(await _run(svc.cancel_job, job_id, ACTOR))


@mcp.tool()
async def create_consumer_key(name: str, agents: list[str]) -> dict:
    """Gera uma chave de API que SÓ consegue invocar os agentes listados (escopo invoke) — é ela que vai
    para LibreChat, Slack, Claude Desktop etc. O valor aparece só nesta resposta."""
    def go(db):
        for s in agents:
            svc.get_agent(db, s)
        row, raw = auth.create_api_key(db, name, ["invoke"], agents, ACTOR)
        svc.audit(db, ACTOR, "api_key.create", name, f"invoke {agents}")
        return {"key": raw, "agents": row.agents, "note": "guarde agora: não será exibida de novo"}
    return await _run(go)


@mcp.tool()
async def connect_agent(slug: str, client: str, mode: str = "mcp") -> dict:
    """Conecta um agente em produção a uma ferramenta, plug and play: gera uma chave só para essa ferramenta e esse
    agente e devolve a configuração pronta para colar. client: claude-code | claude-desktop | codex | opencode |
    cursor | vscode | librechat | open-webui | openai-sdk | generic-mcp. mode: "mcp" (o agente vira uma ferramenta
    do cliente — todas as plataformas) ou "model" (o agente vira um modelo no chat — librechat, open-webui,
    opencode, openai-sdk). Mostre ao usuário o conteúdo e os passos; a chave aparece só nesta resposta."""
    return await _run(svc.connect.connect, slug, client, mode, ACTOR)
