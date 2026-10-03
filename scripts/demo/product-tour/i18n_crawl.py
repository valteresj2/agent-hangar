"""Percorre o portal (como a Maya) e o console (como admin) em inglês e lista textos que sobraram em português."""
import json
import pathlib
import re

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
OUT = D / "shots"
OUT.mkdir(exist_ok=True)
BASE = "http://central:8080"
PT = re.compile(r"[ãõçáéíóúâêôàÁÉÍÓÚÇ]|\b(de|do|da|dos|das|para|com|sem|não|você|seu|sua|seus|suas|agente|agentes|chave|chaves|"
                r"nenhum|nenhuma|uso|custo|pedido|pedidos|criar|salvar|excluir|testar|conectar|entrar|novo|nova|todos|ainda|quando|"
                r"mais|ou|um|uma|em|na|nos|por|que|time|times|dias|chamadas|erros|execuções)\b", re.I)
JS = """() => {
  const out = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode())) {
    const el = n.parentElement; if (!el || el.closest('script,style,code,pre,textarea,.msg,.run-out,.chat,.md,[data-noi18n]')) continue;
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
    const t = n.nodeValue.trim(); if (t) out.add(t);
  }
  document.querySelectorAll('[placeholder],[title]').forEach(e => { for (const a of ['placeholder','title']) if (e.getAttribute(a)) out.add('@' + a + ': ' + e.getAttribute(a)); });
  return [...out];
}"""
PORTAL = ["#/", "#/agents", "#/agents/catalog", "#/agents/new", "#/approvals", "#/catalog", "#/connect", "#/keys", "#/teams",
          "#/templates", "#/usage"]
AGENT_TABS = ["", "/connect", "/playground", "/schedules", "/memory", "/tests", "/versions", "/usage", "/access", "/spec", "/deployments", "/logs"]
CONSOLE = ["#/", "#/agents", "#/approvals", "#/audit", "#/catalog", "#/connect", "#/deployments", "#/keys", "#/providers", "#/sso",
           "#/teams", "#/templates", "#/tests", "#/usage", "#/users"]
found, errors = {}, []


def crawl(ctx, prefix, routes, tag):
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(f"{tag}: {e}"))
    pg.add_init_script("localStorage.setItem('hangar_lang', 'en')")
    for r in routes:
        pg.goto(f"{BASE}{prefix}{r}")
        pg.wait_for_timeout(1800)
        for t in pg.evaluate(JS):
            if PT.search(t):
                found.setdefault(t, f"{tag} {r}")
    pg.screenshot(path=str(OUT / f"i18n-{tag}.png"))
    pg.goto(f"{BASE}{prefix}#/")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=str(OUT / f"i18n-{tag}-home.png"))
    pg.close()


with sync_playwright() as p:
    b = p.chromium.launch()
    maya = b.new_context(viewport={"width": 1440, "height": 1000})
    r = maya.request.post(f"{BASE}/api/auth/password",
                          data={"username": "maya.chen", "password": (D / "maya_password.txt").read_text().strip()})
    print("maya login:", r.status)
    crawl(maya, "/app/", PORTAL + [f"#/agents/renewal-coach{t}" for t in AGENT_TABS] + [f"#/agents/account-memory{t}" for t in ("", "/memory")],
          "portal")
    admin = b.new_context(viewport={"width": 1440, "height": 1000})
    pg = admin.new_page()
    r = pg.request.post(f"{BASE}/api/auth/token", data={"token": (D / "admin_token.txt").read_text().strip()})
    print("admin login:", r.status)
    pg.close()
    crawl(admin, "/ui/", CONSOLE + [f"#/agents/deal-desk{t}" for t in AGENT_TABS], "console")
    login = b.new_context(viewport={"width": 1440, "height": 1000})
    crawl(login, "/app/", ["#/login"], "login")
    b.close()
(D / "i18n_left.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(found), "textos em português")
print("erros de JS:", errors)
