"""MCP da plataforma: é por aqui que Claude/ChatGPT/Codex/OpenCode constroem agentes via chat."""
import asyncio

from mcp.server.fastmcp import Context, FastMCP
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

REUSAR ANTES DE CONSTRUIR (sempre, antes de criar qualquer agente)
- plan_agent(request, capabilities=[...]): passe o pedido e quebre-o em 2–6 capacidades curtas ("lembrar o histórico
  de cada cliente", "escrever o e-mail de follow-up"). O Hangar devolve, do catálogo da empresa: agentes parecidos
  (só os que a pessoa pode ver, em produção), skills, MCPs e templates, como cada um pode entrar no agente NOVO
  (specialist = chamado como está; base = cópia das instruções/skills/testes como ponto de partida; use_as_is = já
  faz o pedido) e as LACUNAS de habilidade, com perguntas.
- Mostre ao usuário o que encontrou e o porquê (campo why), e decida com ele. Se um agente já faz exatamente o
  pedido (use_as_is), ofereça usá-lo como está (connect_agent / request_agent_access) antes de construir outro.
- SKILLS: para cada lacuna, faça a pergunta do plano (no máximo 3 perguntas no total, e só se forem necessárias). Se
  o usuário descrever um procedimento/padrão, ele vira uma skill NOVA (new_skills em compose_agent, com um teste);
  se uma skill do catálogo servir, ofereça-a.
- compose_agent(...): cria o agente NOVO com as peças escolhidas — specialists, base, skills, new_skills, mcps — e
  escreva em `instructions` e `tests` SÓ o que é novo (as peças já trazem o resto: isso economiza tokens).
- REGRA: os agentes do catálogo são SÓ LEITURA. Nunca edite (design_agent/edit_agent) um agente existente para
  atender um pedido novo: monte um agente novo a partir dele. Agente de outro time como especialista exige acesso
  (access="request_access" no plano -> request_agent_access).
- Nada parecido no catálogo? Siga o fluxo abaixo (do zero), ou compose_agent sem peças.

FLUXO
1. Entenda o pedido. Se faltar algo essencial, PERGUNTE: nome, objetivo, saída final esperada,
   sistemas/dados que acessa, riscos (ações destrutivas, dados sensíveis).
2. plan_agent (acima). Se um template resolve o pedido, use apply_template (e ajuste com design_agent).
3. list_catalog -> conexões de LLM disponíveis. Sem conexão de LLM: pergunte ao usuário
   url, model_name e api key e registre com register_llm_connection (ou siga em mock/echo para testar).
4. compose_agent (com peças) ou register_agent(name, objective, final_output) -> devolve o slug.
5. design_agent(slug, ...) define o comportamento. É um JSON Merge Patch: objetos mesclam, listas e
   valores substituem, e null (ou o parâmetro `remove`) APAGA o campo. Ex.: trocar de conexão e voltar
   ao modelo padrão dela = llm={"connection": "x", "model": null}. Veja o formato completo em
   get_spec_schema. Inclua 2+ casos em `tests` ({name, input, expect_contains | expect_regex | judge});
   `judge` é uma rubrica avaliada por um LLM (use para respostas abertas).
   AGENTE DE CÓDIGO (vai editar projetos no VS Code/Cline/Continue): inclua 1+ casos com `workspace` — um mini-projeto
   real que o agente precisa resolver: {name, input: "<tarefa>", workspace: {files: {"calc.py": "...",
   "test_calc.py": "..."}, check: "python3 -m unittest" (ou "python3 -m pytest -q", "node --test"), protected:
   ["test_calc.py"]}}. Em stage, um sandbox efêmero dá ao agente ferramentas de arquivo e terminal; o caso só passa
   se o check sair com 0 e nenhum arquivo protegido mudar (sem "passar" editando o teste). Sandbox: Node 22,
   Python 3 com pytest e git.
   MEMÓRIA: se o agente precisa lembrar entre conversas (clientes, decisões, preferências, histórico), passe
   memory={"scope": "agent"|"team"|"org"} (team = compartilhada com o time; write=false = só leitura). Ele ganha
   memory__recall e memory__remember; diga nas instructions quando consultar e o que gravar. Só funciona se a
   instalação ligou a memória (docs/memory.md) — senão o deploy avisa.
6. Multiagente: crie os especialistas e depois o orquestrador com sub_agents=[slugs] (build_multi_agent).
7. ship_agent(slug): testa em stage, registra e só promove para produção se passar. Se falhar, leia os
   resultados, corrija com design_agent e rode de novo. Errou uma versão? rollback_agent.
8. Ao final informe: slug, versão, endpoints (OpenAI-compatible, A2A, ACP e MCP — todo agente é também um
   servidor MCP com 1 tool), resultado dos testes. Para o usuário plugar o agente numa ferramenta (Claude
   Code/Desktop, Codex, OpenCode, Cursor, VS Code, LibreChat, Open WebUI…), use connect_agent(slug, client,
   mode): "mcp" = o agente vira ferramenta (todas); "model" = vira modelo no chat (LibreChat, Open WebUI,
   OpenCode, SDK OpenAI). Ela gera uma chave só daquela ferramenta e devolve a configuração pronta — NUNCA
   entregue o token de admin. Para agente com harness, run_harness_job mostra resultado/diff.
9. EDITAR DEPOIS (esqueceu algo, quer ajustar um agente que já existe — em produção ou não):
   get_agent_spec(slug) mostra a spec atual e qual versão está em produção/stage. Depois
   edit_agent(slug, changes={...}, test=True) cria uma versão nova, sobe em STAGE e roda os testes — a produção
   continua na versão anterior. Mostre ao usuário o que mudou (changes) e o resultado. Se passou e ele quiser
   publicar: edit_agent(slug, promote=True) (ou promote_to_production). Com promote=True junto das mudanças, só
   publica se os testes passarem. Para revisar antes: diff_agent_versions(slug, from_version=<prod>). Nunca
   publique sem os testes aprovados; se reprovar, corrija com edit_agent e teste de novo.
10. AGENDAMENTO (o usuário quer que o agente rode sozinho: "toda segunda às 9h", "todo dia útil às 18h",
   "dia 5 às 8h", "amanhã às 14h"): depois de criar e testar, chame schedule_agent(slug, message, cron=... ou
   run_at=...). message = a tarefa exata que o agente recebe a cada disparo (escreva completa, como se o usuário
   pedisse no chat). cron tem 5 campos no fuso da empresa (whoami mostra org.timezone): "0 9 * * 1" = segunda
   9h; "0 18 * * 1-5" = dias úteis 18h; "0 8 5 * *" = dia 5 às 8h. Uma vez só: run_at="AAAA-MM-DDTHH:MM". Se o
   usuário citar outro fuso, passe timezone (ex.: "America/Sao_Paulo"). O agendamento só dispara com o agente em
   PRODUÇÃO — criado antes (ex.: aguardando aprovação), começa a valer quando ele subir. Pergunte se o resultado
   deve ir para algum lugar: notify_url = webhook do Slack/Teams (senão fica no histórico, aba Agendamentos).
   Confirme com o usuário o que foi agendado (o campo "when" e "next_run_local" da resposta). Para testar na
   hora: run_schedule_now.

ACESSO: cada agente pertence a um TIME. Você age com os papéis do usuário dono da credencial (veja whoami):
developer/maintainer criam e editam agentes do time (register_agent(team=...) quando a pessoa está em mais de um);
consumer só usa. Produção pode exigir aprovação: se ship_agent devolver status="approval_pending", diga ao
usuário que um mantenedor do time precisa aprovar (página Aprovações ou decide_approval) — não tente contornar.
Agentes de outros times aparecem em list_agents com access="viewer": para usar, request_agent_access.

Todo agente roda em container Docker isolado (harness: um container novo por execução, nunca ocioso).
Nunca coloque segredos em instructions/tools: chaves de LLM ficam criptografadas no catálogo da central.
""".strip()

mcp = FastMCP("agent-hangar", instructions=INSTRUCTIONS, host="0.0.0.0", port=8080,
              streamable_http_path="/mcp", stateless_http=True, json_response=True,
              # o Host varia (localhost, IP, domínio público); a autenticação é feita pelo AuthMiddleware
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


def _principal(ctx: Context) -> auth.Principal:
    """Quem chamou a tool: o AuthMiddleware autenticou o request HTTP e guardou o principal nele."""
    req = ctx.request_context.request if ctx and ctx.request_context else None
    p = req.scope.get("state", {}).get("principal") if req is not None else None
    if p is None:
        raise svc.PlatformError("não autenticado")
    return p


async def _run(ctx: Context, fn, *a, **kw):
    """Roda fn(db, acc, ...) numa thread — nunca no event loop. Essencial para jobs de harness: enquanto uma
    tool espera, o event loop precisa receber o callback do container do job. `acc` traz as permissões de
    quem chamou (services/access.py)."""
    p = _principal(ctx)

    def go():
        with SessionLocal() as db:
            return fn(db, svc.access.of(db, p), *a, **kw)
    return await asyncio.to_thread(go)


def _agent(db, acc, slug: str, action: str = "view"):
    a = svc.get_agent(db, slug)
    acc.require(action, a)
    return a


def _admin(acc):
    if not acc.p.is_admin:
        raise svc.access.Forbidden("só admins da plataforma alteram o catálogo")


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
async def whoami(ctx: Context) -> dict:
    """Quem você é na plataforma: papel na empresa, times e papel em cada um (onde pode criar agentes)."""
    return await _run(ctx, lambda db, acc: svc.org.me(db, acc))


@mcp.tool()
async def list_catalog(ctx: Context) -> dict:
    """Skills, MCP servers e conexões de LLM disponíveis para reutilizar (sem expor as api keys)."""
    def go(db, acc):
        return {"skills": [{"name": s.name, "description": s.description, "version": s.version, "has_test": bool(s.test)}
                           for s in db.scalars(select(Skill))],
                "mcp_servers": [{"name": m.name, "url": m.url, "description": m.description}
                                for m in db.scalars(select(McpServer))],
                "llm_connections": [svc.llm_connection_dict(c) for c in db.scalars(select(LlmConnection))],
                "builtin_tools": ["calculator", "current_time", "platform_dashboard"],
                "harnesses": svc.HARNESS_PROTOCOL,
                "fallback_sem_conexao": f"{config.DEFAULT_MODEL} (sem custo, sem chave — só para testar o fluxo)"}
    return await _run(ctx, go)


@mcp.tool()
async def register_llm_connection(ctx: Context, name: str, base_url: str, model_name: str, api_key: str,
                                  description: str = "", protocol: str = "openai",
                                  price_in_per_mtok: float | None = None,
                                  price_out_per_mtok: float | None = None) -> dict:
    """(Admin) Registra (ou atualiza) uma conexão de LLM: endpoint + model_name padrão + api key (idealmente
    virtual). protocol="openai" (chat, codex, hermes), "anthropic" (claude-code) ou "deepseek"
    (deepseek-harness). Preços por 1M tokens (US$) são opcionais e habilitam o cálculo de custo. A chave é
    guardada criptografada e nunca é devolvida."""
    def go(db, acc):
        _admin(acc)
        c = svc.upsert_llm_connection(db, name, base_url, model_name, api_key, description, acc.p.name, protocol,
                                      price_in_per_mtok, price_out_per_mtok)
        return {"registered": c.name, "base_url": c.base_url, "model_name": c.model_name, "protocol": c.protocol}
    return await _run(ctx, go)


@mcp.tool()
async def register_skill(ctx: Context, name: str, description: str, content: str, examples: str = "",
                         test: dict | None = None, team: str = "") -> dict:
    """Registra uma skill reutilizável (peça de montar agentes): procedimento/conhecimento em markdown, exemplos e um
    teste próprio ({name, input, judge|expect_contains}) que entra nos testes de quem a usar. Developers criam skills
    NOVAS para o time; só admins alteram uma existente (nova versão)."""
    def go(db, acc):
        if acc.p.is_admin:
            s = svc.upsert_skill(db, name, description, content, acc.p.name, examples, test)
        else:
            t = acc.team_for_new_agent(team or None)
            s = svc.upsert_skill(db, name, description, content, acc.p.name, examples, test, team_id=t.id,
                                 create_only=True)
        return {"registered": s.name, "version": s.version, "has_test": bool(s.test)}
    return await _run(ctx, go)


@mcp.tool()
async def register_mcp_server(ctx: Context, name: str, url: str, description: str = "") -> dict:
    """(Admin) Registra um MCP server (Streamable HTTP) no catálogo para os agentes usarem."""
    def go(db, acc):
        _admin(acc)
        m = svc.upsert_mcp(db, name, url, description, acc.p.name)
        return {"registered": m.name, "url": m.url}
    return await _run(ctx, go)


@mcp.tool()
async def list_templates() -> list:
    """Templates de agentes prontos (doc Q&A, triagem, revisor de PR, time de pesquisa…)."""
    return svc.list_templates()


@mcp.tool()
async def apply_template(ctx: Context, template_id: str, connection: str = "", harness_connection: str = "",
                         team: str = "") -> list:
    """Cria os agentes de um template no seu time (`team`: slug; opcional se você só está em um).
    `connection` (protocolo openai) alimenta os agentes de chat; `harness_connection` os agentes-com-harness.
    Sem conexões, nascem em mock. Depois: ship_agent."""
    return await _run(ctx, lambda db, acc: svc.apply_template(db, template_id, connection, harness_connection,
                                                              acc.p.name, acc, team or None))


@mcp.tool()
async def register_agent(ctx: Context, name: str, objective: str, final_output: str, owner: str = "",
                         team: str = "", visibility: str = "") -> dict:
    """Registra um agente: nome, objetivo e saída final. `team`: slug do time (opcional se você só é developer
    de um). `visibility`: private (só o time) | org (catálogo da empresa, uso sob pedido — padrão) | open
    (qualquer um da empresa usa). Devolve o slug para as próximas chamadas."""
    def go(db, acc):
        t = acc.team_for_new_agent(team or None)
        a = svc.create_agent(db, name, objective, final_output, owner=owner, actor=acc.p.name, team_id=t.id,
                             visibility=visibility or None)
        return {"slug": a.slug, "team": t.slug, "visibility": a.visibility, "status": a.status,
                "version": a.current_version, "next": "design_agent para definir instruções, skills, MCPs, tools e testes"}
    return await _run(ctx, go)


@mcp.tool()
async def design_agent(ctx: Context, slug: str, instructions: str | None = None, model: str | None = None,
                       skills: list | None = None, mcps: list | None = None, tools: list | None = None,
                       sub_agents: list | None = None, tests: list | None = None, channels: list | None = None,
                       llm: dict | None = None, harness: dict | None = None, judge: dict | None = None,
                       memory: dict | None = None, remove: list[str] | None = None) -> dict:
    """Atualiza a spec do agente (gera nova versão se mudar). JSON Merge Patch: passe só o que quer mudar;
    dentro de llm/harness/judge, um valor null apaga o campo. `remove` apaga campos inteiros (ex.:
    remove=["harness"] para voltar a ser agente de chat, ou remove=["llm"] antes de virar harness)."""
    patch = {k: v for k, v in (("instructions", instructions), ("skills", skills), ("mcps", mcps),
                               ("tools", tools), ("sub_agents", sub_agents), ("tests", tests),
                               ("channels", channels), ("llm", llm), ("harness", harness), ("judge", judge),
                               ("memory", memory))
             if v is not None}
    if model is not None:
        patch["llm"] = {**(patch.get("llm") or {}), "model": model or None}
    for k in remove or []:
        patch[k] = None

    def go(db, acc):
        _agent(db, acc, slug, "edit")
        a = svc.design_agent(db, slug, patch, acc.p.name, acc=acc)
        return {"slug": a.slug, "version": a.current_version, "status": a.status, "kind": a.kind,
                "next": "ship_agent (testa em stage e promove) ou run_tests"}
    return await _run(ctx, go)


@mcp.tool()
async def plan_agent(ctx: Context, request: str, capabilities: list[str] | None = None, limit: int = 5) -> dict:
    """Reusar antes de construir: procura no catálogo (só o que você pode ver; agentes só na versão em produção) os
    agentes, skills, MCPs e templates parecidos com o pedido; diz como cada agente pode entrar num agente NOVO
    (use_as_is | specialist | base), se você tem acesso, e quais habilidades faltam (gaps + questions, no máximo 3).
    `capabilities`: o pedido quebrado em 2–6 capacidades curtas (melhora muito a busca). Não altera nada."""
    return await _run(ctx, lambda db, acc: svc.composer.plan(db, acc, request, capabilities, max(1, min(limit, 10))))


@mcp.tool()
async def compose_agent(ctx: Context, name: str, objective: str, final_output: str, instructions: str = "",
                        specialists: list[str] | None = None, base: str = "", skills: list[str] | None = None,
                        new_skills: list[dict] | None = None, mcps: list[str] | None = None,
                        tools: list | None = None, tests: list[dict] | None = None,
                        copy_tests_from: list[str] | None = None, copy_base_tests: bool = True,
                        include_skill_tests: bool = True, llm: dict | None = None, memory: dict | None = None,
                        team: str = "", visibility: str = "", plan_id: str = "") -> dict:
    """Cria um agente NOVO montado a partir de peças do catálogo — os agentes de origem NUNCA são alterados.
    specialists: slugs (em produção) que o novo chama como estão (sub_agents, via A2A; outro time exige acesso).
    base: slug cujas instruções, skills, ferramentas e testes (versão em produção) são COPIADOS para o novo.
    skills: nomes do catálogo. new_skills: [{name, description, content, examples?, test?}] — skills novas do time.
    instructions/tests: SÓ o que é novo (o resto vem das peças). copy_tests_from: copia os testes de outros agentes.
    Os testes das skills entram automaticamente. Depois: ship_agent(slug)."""
    return await _run(ctx, lambda db, acc: svc.composer.compose(
        db, acc, name, objective, final_output, instructions, team, visibility, specialists, base, skills, new_skills,
        mcps, tools, tests, copy_tests_from, copy_base_tests, include_skill_tests, llm, memory, plan_id))


@mcp.tool()
async def agent_lineage(ctx: Context, slug: str) -> dict:
    """De quais agentes este foi montado (base e especialistas, e se eles ganharam versão nova desde então) e quem
    usa este agente como peça."""
    return await _run(ctx, lambda db, acc: svc.composer.lineage(db, acc, slug))


@mcp.tool()
async def rollback_agent(ctx: Context, slug: str, version: int) -> dict:
    """Restaura a spec de uma versão anterior como uma versão nova (o histórico nunca é reescrito)."""
    def go(db, acc):
        _agent(db, acc, slug, "edit")
        a = svc.rollback_agent(db, slug, version, acc.p.name)
        return {"slug": a.slug, "version": a.current_version, "status": a.status, "next": "ship_agent"}
    return await _run(ctx, go)


@mcp.tool()
async def build_multi_agent(ctx: Context, name: str, objective: str, final_output: str,
                            orchestrator_instructions: str, members: list, connection: str = "", model: str = "",
                            owner: str = "", team: str = "") -> dict:
    """Cria um multiagente de uma vez (todos no mesmo time). members: [{name, objective, final_output,
    instructions, skills?, mcps?, tools?, tests?}]. Cada membro vira um agente; o orquestrador delega a eles via
    A2A. `connection`/`model` valem para todos. Depois use ship_agent no orquestrador."""
    def go(db, acc):
        t = acc.team_for_new_agent(team or None)
        llm_patch = {k: v for k, v in (("connection", connection), ("model", model)) if v}
        slugs = []
        for m in members:
            a = svc.create_agent(db, m["name"], m["objective"], m["final_output"], owner=owner, actor=acc.p.name,
                                 team_id=t.id)
            patch = {k: m[k] for k in ("instructions", "skills", "mcps", "tools", "tests") if k in m}
            if llm_patch:
                patch["llm"] = llm_patch
            svc.design_agent(db, a.slug, patch, acc.p.name)
            slugs.append(a.slug)
        o = svc.create_agent(db, name, objective, final_output, owner=owner, actor=acc.p.name, team_id=t.id)
        patch = {"instructions": orchestrator_instructions, "sub_agents": slugs}
        if llm_patch:
            patch["llm"] = llm_patch
        svc.design_agent(db, o.slug, patch, acc.p.name)
        return {"orchestrator": o.slug, "members": slugs, "team": t.slug, "next": f"ship_agent('{o.slug}')"}
    return await _run(ctx, go)


@mcp.tool()
async def list_agents(ctx: Context) -> list:
    """Agentes que você pode ver: os dos seus times e os do catálogo da empresa (com o seu nível de acesso),
    status, versão, onde rodam e uso dos últimos 7 dias. `status`/`version` são da versão mais nova (pode ser um
    rascunho); `stage_version`/`prod_version` dizem qual versão está rodando em cada ambiente (null = parado)."""
    def go(db, acc):
        keep = ("slug", "name", "kind", "status", "version", "model", "requests_7d", "cost_7d", "visibility",
                "access")
        return [{k: a.get(k) for k in keep} | {"team": (a.get("team") or {}).get("slug"),
                                             "stage_version": (a["stage"] or {}).get("version"),
                                             "prod_version": (a["prod"] or {}).get("version")}
                for a in svc.list_agents(db, acc)]
    return await _run(ctx, go)


@mcp.tool()
async def get_agent(ctx: Context, slug: str) -> dict:
    """Detalhe: spec, versões, testes, deployments, jobs, endpoints e uso (conforme o seu acesso)."""
    def go(db, acc):
        a = _agent(db, acc, slug)
        svc.refresh_deployments(db, [a])
        return svc.agent_dict(db, a, detail=True, acc=acc)
    return await _run(ctx, go)


@mcp.tool()
async def run_tests(ctx: Context, slug: str) -> dict:
    """Deploy em stage (container isolado) + smoke (health, A2A, ACP, OpenAI, MCP) + casos da spec."""
    def go(db, acc):
        _agent(db, acc, slug, "edit")
        return svc.test_dict(svc.run_tests(db, slug, acc.p.name))
    return await _run(ctx, go)


@mcp.tool()
async def deploy_stage(ctx: Context, slug: str) -> dict:
    """Deploy no ambiente de stage."""
    def go(db, acc):
        _agent(db, acc, slug, "edit")
        return svc.dep_dict(svc.deploy_env(db, slug, "stage", acc.p.name))
    return await _run(ctx, go)


@mcp.tool()
async def promote_to_production(ctx: Context, slug: str, note: str = "") -> dict:
    """Promove para produção (só se a versão atual passou nos testes de stage). Se o seu papel não promove
    direto (developer, ou time com aprovação obrigatória), cria um pedido para um mantenedor aprovar e devolve
    status="approval_pending"."""
    return await _run(ctx, lambda db, acc: svc.org.promote(db, acc, slug, note))


@mcp.tool()
async def ship_agent(ctx: Context, slug: str, note: str = "") -> dict:
    """Atalho: (sub-agentes primeiro) testa em stage, registra e promove para produção se aprovado. Sem
    permissão de promover direto, termina com um pedido de aprovação (status="approval_pending") — avise o
    usuário que um mantenedor do time precisa aprovar em Aprovações."""
    return await _run(ctx, lambda db, acc: svc.org.ship(db, acc, slug, note))


@mcp.tool()
async def stop_agent(ctx: Context, slug: str, env: str = "prod") -> dict:
    """Para o container do agente (env: stage|prod). Produção: só mantenedores/admins."""
    def go(db, acc):
        _agent(db, acc, slug, "manage" if env == "prod" else "edit")
        svc.stop(db, slug, env, acc.p.name)
        return {"stopped": slug, "env": env}
    return await _run(ctx, go)


@mcp.tool()
async def chat_with_agent(ctx: Context, slug: str, message: str, env: str = "prod") -> dict:
    """Conversa com um agente deployado. Para agente-com-harness, dispara um job (prefira run_harness_job)."""
    def go(db, acc):
        _agent(db, acc, slug, "consume" if env == "prod" else "edit")
        return svc.chat(db, slug, message, env, "mcp", acc.p.name)
    return await _run(ctx, go)


@mcp.tool()
async def run_harness_job(ctx: Context, slug: str, task: str, env: str = "stage", timeout_s: int = 180,
                          wait: bool = True) -> dict:
    """Job de harness num container efêmero: executa a `task` e devolve resultado + diff + logs + tokens.
    wait=false devolve o job em fila na hora (acompanhe com get_job; cancele com cancel_job)."""
    def go(db, acc):
        _agent(db, acc, slug, "consume" if env == "prod" else "edit")
        if wait:
            return svc.job_dict(svc.run_harness_job(db, slug, task, env, timeout_s, acc.p.name, "mcp"))
        return svc.job_dict(svc.submit_job(db, slug, task, env, timeout_s, acc.p.name, "mcp"))
    return await _run(ctx, go)


def _job(db, acc, job_id: int) -> Job:
    job = db.get(Job, job_id)
    a = db.get(svc.Agent, job.agent_id) if job else None
    if not job or not a or not acc.can("usage", a):
        raise svc.PlatformError(f"job {job_id} não encontrado")
    return job


@mcp.tool()
async def get_job(ctx: Context, job_id: int) -> dict:
    """Estado atual de um job de harness."""
    return await _run(ctx, lambda db, acc: svc.job_dict(_job(db, acc, job_id)))


@mcp.tool()
async def cancel_job(ctx: Context, job_id: int) -> dict:
    """Cancela um job em fila ou rodando (o container é removido)."""
    def go(db, acc):
        _job(db, acc, job_id)
        return svc.job_dict(svc.cancel_job(db, job_id, acc.p.name))
    return await _run(ctx, go)


@mcp.tool()
async def create_consumer_key(ctx: Context, name: str, agents: list[str]) -> dict:
    """Gera uma chave de API que SÓ consegue invocar os agentes listados (escopo invoke) — é ela que vai
    para LibreChat, Slack, Claude Desktop etc. Os agentes precisam ser agentes que você pode usar; a chave é sua
    e morre se você perder o acesso. O valor aparece só nesta resposta."""
    def go(db, acc):
        if not agents:
            raise svc.PlatformError("informe os agentes")
        for s in agents:
            _agent(db, acc, s, "consume")
        row, raw = auth.create_api_key(db, name, ["invoke"], agents, acc.p.name,
                                       user_id=acc.p.user_id if acc.p.is_user else None)
        svc.audit(db, acc.p.name, "api_key.create", name, f"invoke {agents}")
        return {"key": raw, "agents": row.agents, "note": "guarde agora: não será exibida de novo"}
    return await _run(ctx, go)


@mcp.tool()
async def connect_agent(ctx: Context, slug: str, client: str, mode: str = "mcp") -> dict:
    """Conecta um agente em produção a uma ferramenta, plug and play: gera uma chave só para essa ferramenta e esse
    agente e devolve a configuração pronta para colar. client: claude-code | claude-desktop | codex | opencode |
    cursor | vscode | cline | continue | librechat | open-webui | openai-sdk | generic-mcp. mode: "mcp" (o agente
    vira uma ferramenta do cliente — todas as plataformas) ou "model" (o agente vira um modelo no chat — librechat,
    open-webui, opencode, openai-sdk; e, como AGENTE DE CÓDIGO que edita arquivos e usa o terminal do dev: vscode,
    cline, continue). Mostre ao usuário o conteúdo e os passos; a chave aparece só nesta resposta. Depois, confira
    com test_agent_connection."""
    def go(db, acc):
        _agent(db, acc, slug, "consume")
        return svc.connect.connect(db, slug, client, mode, acc.p.name,
                                   user_id=acc.p.user_id if acc.p.is_user else None)
    return await _run(ctx, go)


@mcp.tool()
async def test_agent_connection(ctx: Context, slug: str, env: str = "prod") -> dict:
    """Testa de ponta a ponta o modo agente de código (VS Code, Cline, Roo, Continue): manda uma ferramenta do
    cliente (hangar_ping), confere que o agente a chama pelo stream e que usa o resultado para responder. Use depois
    de connect_agent, ou para diagnosticar "o agente não edita meus arquivos". Mostre os passos ao usuário."""
    def go(db, acc):
        _agent(db, acc, slug, "consume" if env == "prod" else "edit")
        return svc.connect.probe(db, slug, env)
    return await _run(ctx, go)


@mcp.tool()
async def request_agent_access(ctx: Context, slug: str, reason: str = "") -> dict:
    """Pede acesso de uso a um agente de outro time (visibilidade "org"). Um mantenedor do time decide."""
    return await _run(ctx, lambda db, acc: svc.org.request_access(db, acc, slug, reason))


@mcp.tool()
async def list_approvals(ctx: Context) -> dict:
    """Pedidos que você pode decidir agora (promoções para produção e pedidos de acesso) e os seus pedidos."""
    return await _run(ctx, lambda db, acc: svc.org.approvals(db, acc))


@mcp.tool()
async def decide_approval(ctx: Context, kind: str, request_id: int, approve: bool, note: str = "") -> dict:
    """Aprova ou recusa um pedido. kind: "promotion" (promoção para produção — quem pediu não pode aprovar) ou
    "access" (uso de um agente do seu time). Confirme com o usuário antes de aprovar."""
    def go(db, acc):
        if kind == "promotion":
            return svc.org.decide_promotion(db, acc, request_id, approve, note)
        if kind == "access":
            return svc.org.decide_access(db, acc, request_id, approve)
        raise svc.PlatformError("kind deve ser promotion ou access")
    return await _run(ctx, go)


@mcp.tool()
async def get_agent_spec(ctx: Context, slug: str, version: int | None = None) -> dict:
    """Spec atual (ou de uma versão) + nome, objetivo, saída final, contato, time, visibilidade e qual versão está
    em produção e em stage. Use antes de editar um agente existente."""
    return await _run(ctx, lambda db, acc: svc.org.agent_spec(db, acc, slug, version))


@mcp.tool()
async def edit_agent(ctx: Context, slug: str, changes: dict | None = None, instructions: str | None = None,
                     name: str | None = None, objective: str | None = None, final_output: str | None = None,
                     owner: str | None = None, remove: list[str] | None = None, test: bool = True,
                     promote: bool = False, note: str = "") -> dict:
    """Edita um agente que já existe e, na mesma chamada, testa em stage e (opcional) publica.

    changes: JSON Merge Patch sobre a spec (formato de get_spec_schema) — ex.: {"tools": [...]},
    {"llm": {"model": "x"}}, {"tests": [...]}; objetos mesclam, listas substituem, null apaga. Atalhos:
    instructions, name, objective, final_output, owner. remove: campos da spec a apagar (ex.: ["harness"]).
    test=True (padrão): cria a versão nova, faz deploy em STAGE e roda os testes — produção segue na versão
    anterior. promote=True: se os testes passarem, publica em produção (ou cria o pedido de aprovação, se o seu
    papel/time exigir). Sem mudanças e com promote=True, publica a versão atual se ela já tiver teste aprovado.
    Devolve o que mudou (changes), o resultado dos testes e o estado de produção."""
    patch = dict(changes or {})
    for k, v in (("instructions", instructions), ("name", name), ("objective", objective),
                 ("final_output", final_output), ("owner", owner)):
        if v is not None:
            patch[k] = v
    for k in remove or []:
        patch[k] = None
    return await _run(ctx, lambda db, acc: svc.org.edit_agent(db, acc, slug, patch, test, promote, note))


@mcp.tool()
async def diff_agent_versions(ctx: Context, slug: str, from_version: int, to_version: int | None = None) -> dict:
    """O que mudou na spec entre duas versões (to_version padrão = atual). Útil para revisar antes de publicar:
    from_version = a versão que está em produção (get_agent_spec mostra qual é)."""
    def go(db, acc):
        _agent(db, acc, slug, "view_spec")
        return svc.registry.diff_versions(db, slug, from_version, to_version)
    return await _run(ctx, go)


@mcp.tool()
async def update_agent_access(ctx: Context, slug: str, visibility: str | None = None, expose_spec: bool | None = None,
                              team: str | None = None) -> dict:
    """(Mantenedor/admin) visibility: private | org | open; expose_spec: mostra instruções/spec (leitura) a quem é
    de fora do time; team: transfere o agente para outro time (slug)."""
    def go(db, acc):
        a = svc.org.set_agent_access(db, acc, slug, visibility, expose_spec, team)
        return {"slug": a.slug, "visibility": a.visibility, "expose_spec": a.expose_spec, "team_id": a.team_id}
    return await _run(ctx, go)


@mcp.tool()
async def schedule_agent(ctx: Context, slug: str, message: str, cron: str | None = None, run_at: str | None = None,
                         timezone: str | None = None, name: str = "", notify_url: str = "") -> dict:
    """Agenda o agente para disparar sozinho em produção. message: a tarefa enviada a cada disparo.
    cron (recorrente, 5 campos: minuto hora dia-do-mês mês dia-da-semana; ex.: "0 9 * * 1-5" = dias úteis 9h)
    OU run_at (uma vez: "2026-10-05T09:00"). timezone: padrão = fuso da empresa. notify_url: webhook
    (Slack/Teams/HTTP) que recebe o resultado. Só dispara com o agente em produção. Devolve "when" (em
    português) e "next_run_local" para confirmar com o usuário."""
    def go(db, acc):
        sch = svc.schedules.create(db, acc, slug, message, cron, run_at, timezone, name, notify_url)
        return svc.schedules.schedule_dict(db, sch)
    return await _run(ctx, go)


@mcp.tool()
async def list_schedules(ctx: Context, slug: str | None = None) -> dict:
    """Agendamentos (de um agente ou de todos os que você pode ver): quando, próximo disparo, último status."""
    return await _run(ctx, lambda db, acc: {"schedules": svc.schedules.list_for(db, acc, slug)})


@mcp.tool()
async def update_schedule(ctx: Context, schedule_id: int, message: str | None = None, cron: str | None = None,
                          run_at: str | None = None, timezone: str | None = None, name: str | None = None,
                          notify_url: str | None = None, enabled: bool | None = None) -> dict:
    """Altera um agendamento (horário, mensagem, webhook) ou pausa/retoma (enabled)."""
    fields = {k: v for k, v in (("message", message), ("cron", cron), ("run_at", run_at), ("timezone", timezone),
                                ("name", name), ("notify_url", notify_url), ("enabled", enabled)) if v is not None}
    return await _run(ctx, lambda db, acc: svc.schedules.schedule_dict(
        db, svc.schedules.update_schedule(db, acc, schedule_id, **fields)))


@mcp.tool()
async def delete_schedule(ctx: Context, schedule_id: int) -> dict:
    """Remove um agendamento (e o histórico dele)."""
    def go(db, acc):
        svc.schedules.delete(db, acc, schedule_id)
        return {"deleted": schedule_id}
    return await _run(ctx, go)


@mcp.tool()
async def run_schedule_now(ctx: Context, schedule_id: int) -> dict:
    """Dispara um agendamento agora (sem esperar o horário) e devolve o resultado — bom para testar."""
    return await _run(ctx, lambda db, acc: svc.schedules.run_now(db, acc, schedule_id))


@mcp.tool()
async def schedule_runs(ctx: Context, schedule_id: int, limit: int = 5) -> dict:
    """Últimas execuções de um agendamento: status, resposta do agente, tokens, custo e envio ao webhook."""
    return await _run(ctx, lambda db, acc: {"runs": svc.schedules.runs(db, acc, schedule_id, min(limit, 50))})
