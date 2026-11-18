"""E2E do marketplace de Digital employees e da contratação por texto, contra um Agent Hangar rodando de verdade (modo
mock + LLM de mentira).

    HANGAR_URL=http://localhost:8090 HANGAR_TOKEN=<admin> ECHO_URL=http://e2e-echo:8080 python tests/e2e/market.py

Precisa do sistema de mentira (tests/e2e/echo_server.py) como `e2e-echo` na rede hangar_agents e, para a parte da
interface, de: pip install playwright httpx && playwright install chromium (sem o Playwright, só a API é exercitada, e
o script avisa). Cria dois times e quatro pessoas e exercita:
  - vitrine: só o admitido aparece; o cartão e a página não entregam tarefas, custo, lições nem o gestor;
  - quem é do time vê as instruções e copia com a base; quem só vê o agente copia o cargo, sem a spec;
  - "usar este agente": a cópia é pessoal, em modo sombra, com quem copiou de gestor; ela passa pela experiência em
    containers de verdade e é admitida; o original não muda e a cópia não vira oferta;
  - rascunho do cargo: por regras sem modelo e pelo modelo da empresa quando há conexão; não contrata nada;
  - contratação com o que a tela nova envia (agente pessoal, sem gestor nem time no pedido);
  - interface, com cliques de verdade: busca e filtro da vitrine, a página do agente, "Usar este agente" e a ficha
    preenchida pelo botão na tela de contratação.
Apaga tudo no fim. Sai com código != 0 na primeira falha.
"""
import json
import os
import sys
import time
import uuid

import httpx

URL = os.environ.get("HANGAR_URL", "http://localhost:8090").rstrip("/")
ECHO = os.environ.get("ECHO_URL", "http://e2e-echo:8080").rstrip("/")
RUN = uuid.uuid4().hex[:6]
admin = httpx.Client(base_url=URL, timeout=300, headers={"Authorization": f"Bearer {os.environ['HANGAR_TOKEN']}"})
passed = 0
created = {"agents": [], "users": [], "teams": [], "llm": []}
LOGIN: dict[str, tuple[str, str]] = {}
PRIVATE = ("lessons", "tasks", "cost_30d", "metrics", "probation", "rules", "manager", "owner", "open_decisions")
ASK = "Toda manhã, organize a caixa do Gmail e rascunhe respostas. Às segundas, revise o HubSpot. Nunca envie sem eu aprovar."


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL {name} {str(detail)[:500]}", flush=True)
        raise SystemExit(1)
    passed += 1
    print(f"ok   {name}", flush=True)


def ok(r: httpx.Response):
    if r.status_code >= 400:
        raise SystemExit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:400]}")
    return r.json()


def wait(fn, secs=300, every=2):
    t0 = time.time()
    while time.time() - t0 < secs:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def person(key: str, role: str, team: str) -> tuple[httpx.Client, str]:
    email, user, pw = f"e2e-{RUN}-{key}@example.com", f"e2e-{RUN}-{key}", f"pw-{uuid.uuid4().hex}"
    u = ok(admin.post("/api/users", json={"email": email, "name": f"E2E {key}", "username": user, "password": pw}))
    created["users"].append(u["id"])
    ok(admin.post(f"/api/teams/{team}/members", json={"email": email, "role": role}))
    LOGIN[key] = (user, pw)
    c = httpx.Client(base_url=URL, timeout=300)
    ok(c.post("/api/auth/password", json={"username": user, "password": pw}))
    c.headers["X-CSRF-Token"] = c.cookies.get("hangar_csrf") or ""
    return c, email


def slugs(c) -> list[str]:
    return [e["slug"] for e in ok(c.get("/api/market"))]


def activate(owner, approver, slug):
    """Experiência em containers de verdade, admissão por quem gerencia e, se o time pedir, a promoção pelo admin."""
    ok(owner.post(f"/api/employees/{slug}/probation"))
    done = wait(lambda: (lambda e: e if e["probation"] and all(t["status"] == "done" for t in e["probation"]) else None)(
        ok(owner.get(f"/api/employees/{slug}"))))
    check(f"{slug}: experiência concluída", done is not None, ok(owner.get(f"/api/employees/{slug}"))["probation"])
    adm = next((d for d in ok(approver.get("/api/decisions")) if d["kind"] == "admission" and d["employee"] == slug), None)
    check(f"{slug}: o gestor recebe o pedido de admissão", adm is not None)
    ok(approver.post(f"/api/decisions/{adm['id']}", json={"decision": "approve"}))
    promo = next((x for x in ok(admin.get("/api/approvals"))["to_decide"] if x["kind"] == "promotion" and x["agent"] == slug), None)
    if promo:
        ok(admin.post(f"/api/promotions/{promo['id']}/approve", json={}))
    check(f"{slug}: ativo", ok(owner.get(f"/api/employees/{slug}"))["status"] == "active")


def snapshot(slug: str) -> dict:
    a = ok(admin.get(f"/api/agents/{slug}"))
    e = ok(admin.get(f"/api/employees/{slug}"))
    return {"version": a.get("version"), "status": a.get("status"), "employee": e["status"],
            "title": e["title"], "responsibilities": e["responsibilities"], "shadow": e["shadow"]}


def scenario_market(dev, mgr, mgr_email, col, out, team) -> tuple[str, str]:
    job = {"name": f"Follow-up {RUN}", "title": "Sales follow-up", "mission": "No sales meeting is left without a next step.",
           "responsibilities": ["write the follow-up e-mail", "propose the CRM update", "flag stalled deals"],
           "manager": mgr_email, "team": team, "systems": ["CRM", "Gmail"], "llm": {"model": "mock/echo"},
           "channels": ["portal", "mcp"], "accept_default_authority": True,
           "probation_tasks": [{"title": f"Which deals are stalled {i}?", "body": f"answer {i}", "expected": f"answer {i}"}
                               for i in range(3)]}
    slug = ok(dev.post("/api/employees", json=job))["employee"]["slug"]
    created["agents"].append(slug)
    check("em contratação não é oferta", slug not in slugs(col))
    check("a página de quem não foi admitido é recusada", col.get(f"/api/market/{slug}").status_code == 403)
    activate(dev, mgr, slug)

    card = next((e for e in ok(col.get("/api/market")) if e["slug"] == slug), None)
    check("admitido aparece na vitrine", card is not None)
    check("o cartão traz cargo, time, sistemas e avatar", card["title"] == "Sales follow-up" and card["systems"] == ["CRM", "Gmail"]
          and card["team"].startswith("E2E market") and card["avatar_url"] and card["mine"] is False, card)
    check("quem gerencia vê que é dele", next(e for e in ok(mgr.get("/api/market")) if e["slug"] == slug)["mine"] is True)
    check("o cartão não entrega o trabalho", not [k for k in PRIVATE if k in card], card)

    d = ok(col.get(f"/api/market/{slug}"))
    check("a página não entrega o trabalho", not [k for k in PRIVATE if k in d], list(d))
    check("a página mostra o cargo e os pedidos de exemplo", d["responsibilities"] == job["responsibilities"]
          and d["examples"] == [t["title"] for t in job["probation_tasks"]], d)
    check("quem é do time vê as instruções e copia com a base", d["copy"] == {"allowed": True, "reason": "", "full": True}
          and "Sales follow-up" in (d["instructions"] or ""), d["copy"])
    before = snapshot(slug)

    r = ok(col.post(f"/api/market/{slug}/use"))
    check("usar este agente cria a cópia", r.get("created") is True, r)
    copy = r["employee"]
    created["agents"].append(copy["slug"])
    check("a cópia é pessoal, em modo sombra, com quem copiou de gestor", copy["slug"] != slug and copy["personal"] is True
          and copy["shadow"] is True and copy["status"] == "onboarding" and copy["can_manage"] is True, copy)
    check("a cópia leva o cargo e os pedidos de teste", copy["title"] == job["title"] and copy["mission"] == job["mission"]
          and [t["title"] for t in copy["probation"]] == [t["title"] for t in job["probation_tasks"]])
    lin = ok(admin.get(f"/api/agents/{copy['slug']}/lineage"))
    check("a linhagem aponta a base", ((lin.get("built_from") or {}).get("based_on") or {}).get("slug") == slug, lin)
    agent = ok(admin.get(f"/api/agents/{copy['slug']}"))
    text = next((v["spec"] for v in agent["versions"] if v["version"] == agent["version"]), {}).get("instructions", "")
    check("as instruções do cargo vêm uma vez só", text.count("Job title: Sales follow-up") == 1, text[:300])
    check("a cópia não vira oferta", copy["slug"] not in slugs(dev) and copy["slug"] not in slugs(col))
    check("quem é de fora não vê a cópia", out.get(f"/api/employees/{copy['slug']}").status_code in (403, 404))
    activate(col, col, copy["slug"])  # a cópia trabalha de verdade: experiência em containers e admissão por quem copiou
    check("admitida, a cópia continua fora da vitrine", copy["slug"] not in slugs(dev))
    check("o original não mudou", snapshot(slug) == before, (before, snapshot(slug)))

    if slug in slugs(out):  # o agente é visível na empresa: outro time copia o cargo, sem a spec
        d2 = ok(out.get(f"/api/market/{slug}"))
        check("outro time não lê as instruções", d2["instructions"] is None and d2["skills"] == [] and d2["apps"] == []
              and d2["copy"]["full"] is False, d2)
        r2 = ok(out.post(f"/api/market/{slug}/use"))
        check("outro time copia o cargo", r2.get("created") is True and r2["employee"]["personal"] is True, r2)
        created["agents"].append(r2["employee"]["slug"])
        lin2 = ok(admin.get(f"/api/agents/{r2['employee']['slug']}/lineage"))
        check("sem permissão de spec, nada do original é copiado", not (lin2.get("built_from") or {}).get("based_on"), lin2)
    else:
        check("fora do alcance, a página é recusada", out.get(f"/api/market/{slug}").status_code == 403)
        check("e a cópia também", out.post(f"/api/market/{slug}/use").status_code == 403)
    check("agente que não existe", col.get("/api/market/nao-existe").status_code in (400, 403, 404))
    return slug, copy["slug"]


def scenario_draft(col):
    n = len(ok(col.get("/api/employees")))
    check("rascunho pede uma frase de verdade", col.post("/api/employees/draft", json={"text": "oi"}).status_code == 400)
    check("rascunho pede uma pessoa", httpx.post(f"{URL}/api/employees/draft", json={"text": ASK}).status_code == 401)
    has_llm = any(c.get("protocol") == "openai" for c in ok(admin.get("/api/catalog"))["llm_connections"])
    d = ok(col.post("/api/employees/draft", json={"text": ASK}))
    check("o rascunho devolve só os campos da ficha", set(d["fields"]) == {"name", "title", "mission", "responsibilities",
                                                                             "systems", "probation_tasks"}, d)
    if not has_llm:
        f = d["fields"]
        check("sem modelo, as regras usam só o texto", d["source"] == "rules" and f["title"] == "" and f["probation_tasks"] == []
              and f["systems"] == ["Gmail", "HubSpot"] and len(f["responsibilities"]) == 3, d)
        conn = f"e2e-mk-{RUN}"
        ok(admin.post("/api/catalog/llm", json={"name": conn, "provider": "openrouter", "base_url": f"{ECHO}/llm/v1",
                                                "api_key": "e2e", "model_name": "e2e/plain"}))
        created["llm"].append(conn)
        # o LLM de mentira repete o pedido: um pedido com a ficha em JSON volta como a resposta do modelo
        sheet = {"name": "Iris", "title": "Inbox  assistant", "mission": "Keep the inbox in order.", "status": "active",
                 "responsibilities": ["sort the inbox", "draft replies", "never send without approval"], "systems": ["Gmail"],
                 "probation_tasks": [{"title": f"Draft reply {i}", "expected": "a draft, not sent"} for i in range(4)]}
        d = ok(col.post("/api/employees/draft", json={"text": "Draft this job sheet: " + json.dumps(sheet)}))
        f = d["fields"]
        check("com modelo, a ficha vem dele, limpa e limitada", d["source"] == "llm" and f["title"] == "Inbox assistant"
              and f["name"] == "Iris" and len(f["probation_tasks"]) == 3 and "status" not in f, d)
    check("rascunhar não contrata", len(ok(col.get("/api/employees"))) == n)


def scenario_form_hire(col):
    """O que a tela de contratação envia para um agente pessoal: sem gestor e sem time (o servidor usa os da pessoa)."""
    body = {"request": ASK, "name": f"Inbox {RUN}", "title": "Inbox assistant", "mission": "Keep the inbox in order.",
            "manager": "", "team": "", "responsibilities": ["sort the inbox", "draft replies", "never send without approval"],
            "systems": ["Gmail"], "specialists": [], "skills": [], "mcps": [], "backups": [], "autonomy_level": "intern",
            "channels": ["portal", "mcp"], "accept_default_authority": True, "shadow": True, "personal": True, "kpis": [],
            "report_webhook": "", "working_hours": "", "task_budget_usd": None, "task_time_limit_min": None, "report_hour": None,
            "probation_tasks": [{"title": f"Draft reply {i}", "body": f"Draft reply {i}", "expected": "a draft, not sent"}
                                for i in range(3)]}
    plan = ok(col.post("/api/employees/plan", json={**body, "manager": LOGIN["col"][0] + "@nope"}))
    check("a verificação aponta o gestor que não existe", any(m["field"] == "manager" for m in plan["missing"]), plan["missing"])
    r = ok(col.post("/api/employees", json=body))
    check("a ficha da tela contrata um agente pessoal", r.get("created") is True and r["employee"]["personal"] is True
          and r["employee"]["shadow"] is True and r["employee"]["can_manage"] is True, r)
    created["agents"].append(r["employee"]["slug"])
    short = ok(col.post("/api/employees", json={**body, "title": "", "probation_tasks": []}))
    check("ficha incompleta não contrata e diz o que falta", short.get("created") is False
          and {m["field"] for m in short["missing"]} >= {"title", "probation_tasks"}, short)


def scenario_ui(slug: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("AVISO: sem o Playwright, a interface não foi exercitada (pip install playwright && playwright install chromium)", flush=True)
        return False
    user, pw = LOGIN["ui"]
    api = httpx.Client(base_url=URL, timeout=120)
    ok(api.post("/api/auth/password", json={"username": user, "password": pw}))
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            ctx = b.new_context(viewport={"width": 1400, "height": 950}, locale="pt-BR")
            assert ctx.request.post(URL + "/api/auth/password", data={"username": user, "password": pw}).ok
            pg = ctx.new_page()
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.add_init_script("try { localStorage.setItem('hangar_lang', 'pt') } catch (e) {}")
            pg.goto(URL + "/app/#/market")
            pg.wait_for_selector(f"a.mk-card[href='#/market/{slug}']", timeout=20000)
            check("ui: o menu do portal leva ao marketplace", pg.locator("nav a[data-r='market']").count() == 1
                  and "on" in (pg.locator("nav a[data-r='market']").get_attribute("class") or ""))
            pg.fill("#mk-q", "zzz-nada")
            pg.wait_for_selector("#mk-clear")
            check("ui: busca sem resultado mostra o estado vazio", pg.locator("a.mk-card").count() == 0)
            pg.click("#mk-clear")
            pg.wait_for_selector(f"a.mk-card[href='#/market/{slug}']")
            pg.fill("#mk-q", "crm follow")
            check("ui: a busca acha por palavras soltas e mantém o foco", pg.locator(f"a.mk-card[href='#/market/{slug}']").count() == 1
                  and pg.evaluate("document.activeElement && document.activeElement.id") == "mk-q")
            pg.keyboard.press("Tab")  # o teclado chega ao cartão: é um link de verdade
            pg.click(f"a.mk-card[href='#/market/{slug}']")
            pg.wait_for_selector("#mk-use", timeout=20000)
            check("ui: a página mostra o que pedir, o que faz e o que a cópia leva",
                  pg.locator(".mk-asks li").count() == 3 and pg.locator(".mk-resp li").count() == 3
                  and pg.locator(".mk-takes li").count() == 5 and pg.locator(".mk-instr").count() == 1)
            pg.click("#mk-use")
            pg.wait_for_function("location.hash.startsWith('#/employees/')", timeout=60000)
            new = pg.evaluate("location.hash").split("/")[2].split("?")[0]
            created["agents"].append(new)
            e = ok(api.get(f"/api/employees/{new}"))
            check("ui: Usar este agente cria a cópia e abre a página dela", new != slug and e["personal"] is True and e["shadow"] is True, e["slug"])
            pg.wait_for_selector(".tabs a[aria-current='page']")
            check("ui: o nível aparece com o que ele significa", pg.locator("main .chip", has_text="pede aprovação").count() >= 1)
            pg.click(".tabs a[href$='/authority']")
            pg.wait_for_selector(".tab-hint")
            check("ui: a aba Alçada abre com a explicação", "sozinho" in pg.inner_text(".tab-hint"))

            pg.goto(URL + "/app/#/employees/new?personal=1")
            pg.wait_for_selector("#h-draft", timeout=20000)
            check("ui: a contratação abre em duas colunas, em Só eu", pg.locator(".hire-ask").count() == 1
                  and pg.locator("[data-who='me'][aria-pressed='true']").count() == 1 and pg.is_hidden("#h-team-box"))
            check("ui: os prontos do marketplace aparecem como ponto de partida", pg.locator(f".hire-ready a[href='#/market/{slug}']").count() == 1)
            pg.click(".hire-ex >> nth=0")
            check("ui: o exemplo preenche o pedido", len(pg.input_value("#h-ask")) > 20)
            pg.click("#h-draft")
            pg.wait_for_selector("#h-draft-out .card", timeout=60000)
            check("ui: Preencher a ficha escreve a missão e leva o foco à ficha", len(pg.input_value("#h-mission")) > 10
                  and pg.evaluate("document.activeElement && document.activeElement.id") == "hire-h-sheet")
            pg.click("[data-who='team']")
            check("ui: Meu time mostra time e gestor", pg.is_visible("#h-team-box") and "@" in pg.input_value("#h-manager"))
            pg.click("[data-who='me']")
            pg.fill("#h-name", f"UI {RUN}")
            pg.fill("#h-title", "Inbox assistant")
            pg.fill("#h-mission", "Keep the inbox in order.")
            pg.fill("#h-resp", "sort the inbox\ndraft replies\nnever send without approval")
            pg.fill("#h-systems", "Gmail")
            pg.click("#h-plan")
            pg.wait_for_selector("#h-out .warn-card", timeout=30000)
            check("ui: Verificar diz o que falta", pg.locator("#h-out li").count() >= 1)
            rows = pg.locator(".h-pt")
            for i in range(3):
                rows.nth(i).locator(".pt-title").fill(f"Draft reply {i}")
                rows.nth(i).locator(".pt-exp").fill("a draft, not sent")
            pg.click("#h-hire")
            pg.wait_for_function("location.hash.startsWith('#/employees/') && !location.hash.includes('/new')", timeout=60000)
            made = pg.evaluate("location.hash").split("/")[2].split("?")[0]
            created["agents"].append(made)
            e = ok(api.get(f"/api/employees/{made}"))
            check("ui: Criar agente contrata pela ficha", e["personal"] is True and e["title"] == "Inbox assistant" and e["status"] == "onboarding", e["slug"])

            pg.set_viewport_size({"width": 375, "height": 812})
            for page in ("market", f"market/{slug}", "employees/new?personal=1"):
                pg.goto(f"{URL}/app/#/{page}")
                pg.wait_for_timeout(1200)
                check(f"ui: {page} não rola para o lado no celular",
                      pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2"))
            check("ui: nenhuma página quebrou", not errors, errors)
        finally:
            b.close()
    return True


def cleanup():
    for s in reversed(created["agents"]):
        admin.delete(f"/api/agents/{s}")
    for u in created["users"]:
        admin.patch(f"/api/users/{u}", json={"active": False})
    for t in created["teams"]:
        admin.delete(f"/api/teams/{t}")
    for name in created["llm"]:
        admin.delete(f"/api/catalog/llm/{name}")


def main():
    check("health", ok(admin.get("/api/health"))["status"] == "ok")
    team = ok(admin.post("/api/teams", json={"name": f"E2E market {RUN}", "require_approval": False}))["slug"]
    other = ok(admin.post("/api/teams", json={"name": f"E2E market other {RUN}"}))["slug"]
    created["teams"] += [team, other]
    mgr, mgr_email = person("mgr", "maintainer", team)
    dev, _ = person("dev", "developer", team)
    col, _ = person("col", "developer", team)
    person("ui", "developer", team)
    out, _ = person("out", "developer", other)
    slug, _ = scenario_market(dev, mgr, mgr_email, col, out, team)
    scenario_draft(col)
    scenario_form_hire(col)
    ui = scenario_ui(slug)
    print(f"\n{passed} checks ok{'' if ui else ' (sem a interface)'}", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
        sys.stdout.flush()
