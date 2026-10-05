"""Capturas da demo interativa (Product Hunt) como a Maya, com o portal em inglês. Uso: python capture.py <grupo>
grupos: approval (antes de aprovar), main (depois de publicado e com memória/uso), extra (Guia e Conectar),
reuse (reusar antes de construir), employee (Digital employee), claude (conversa renderizada)."""
import pathlib
import sys

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
OUT = D / "shots"
OUT.mkdir(exist_ok=True)
BASE = "http://central:8080"
PASSWORD = (D / "maya_password.txt").read_text().strip()  # conta local de demonstração (arquivo fora do git)
W, H = 1440, 900


def run(group: str):
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, color_scheme="light", locale="en-US")
        if group == "claude":
            pg = ctx.new_page()
            pg.goto((D / "claude_chat.html").as_uri())
            pg.wait_for_timeout(1500)
            pg.screenshot(path=str(OUT / "01-claude.png"), full_page=False)
            b.close()
            return
        r = ctx.request.post(f"{BASE}/api/auth/password", data={"username": "maya.chen", "password": PASSWORD})
        assert r.ok, r.text()
        ctx.add_init_script("localStorage.setItem('hangar_lang', 'en')")  # o portal tem PT e EN; a demo é em inglês
        pg = ctx.new_page()

        def go(hash_, name, wait="main h1", pause=1500, before=None):
            pg.goto(f"{BASE}/app/{hash_}")
            pg.wait_for_selector(wait, timeout=30000)
            pg.wait_for_timeout(pause)
            if before:
                before()
            pg.screenshot(path=str(OUT / name))

        if group == "approval":
            go("#/approvals", "03-approval.png")
        elif group == "main":
            go("#/", "02-home.png", wait=".attn-card")
            go("#/agents", "04-my-agents.png", wait="#rows tr")
            go("#/agents/deal-desk", "05-deal-desk.png", wait=".tabs")
            go("#/agents/account-memory/tests", "06-tests.png", wait=".tabs", pause=2500)
            # playground do Deal Desk: pergunta real, resposta real
            pg.goto(f"{BASE}/app/#/agents/deal-desk/playground")
            pg.wait_for_selector("#pmsg")
            pg.fill("#pmsg", "Prepare me for my call with Northwind Logistics tomorrow.")
            pg.click("#psend")
            pg.wait_for_selector(".msg.a.md", timeout=300000)
            pg.wait_for_timeout(1000)
            pg.eval_on_selector(".chat", "c => { c.style.maxHeight = 'none'; }")
            pg.screenshot(path=str(OUT / "07-playground.png"))
            pg.screenshot(path=str(OUT / "07-playground-full.png"), full_page=True)
            go("#/agents/account-memory/memory", "08-memory.png", wait="table")
            go("#/agents/deal-desk/connect", "09-connect.png", wait=".tabs", pause=2000)
            go("#/agents/catalog", "10-catalog.png", wait="#rows tr")
            pg.goto(f"{BASE}/app/#/agents/deal-desk/schedules")
            pg.wait_for_selector(".sc-hist")
            pg.click(".sc-hist")
            pg.wait_for_selector(".run-out", timeout=30000)
            pg.wait_for_timeout(800)
            pg.eval_on_selector(".sc-runs", "r => r.scrollIntoView({block: 'start'})")
            pg.evaluate("window.scrollBy(0, -160)")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / "11-schedule.png"))
            go("#/usage", "12-usage.png", pause=2500)
            go("#/agents/deal-desk/versions", "13-versions.png", wait=".tabs", pause=1500)
        elif group == "extra":
            go("#/agents/deal-desk/guide", "14-guide.png", wait=".guide-md", pause=1500)
            pg.goto(f"{BASE}/app/#/agents/deal-desk/connect")
            pg.wait_for_selector(".cn-go")
            pg.wait_for_timeout(1200)
            pg.eval_on_selector(".grid.g3", "g => g.scrollIntoView({block: 'start'})")
            pg.evaluate("window.scrollBy(0, -90)")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / "15-connect-tools.png"))
            # conecta o Cursor (modo MCP): a configuração pronta aparece; a chave é mascarada e revogada em seguida
            pg.click(".cn-go[data-c='cursor'][data-m='mcp']")
            pg.wait_for_function("document.querySelector('#cn-out') && document.querySelector('#cn-out').innerText.length > 40", timeout=30000)
            pg.wait_for_timeout(800)
            pg.evaluate("""() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let n; while ((n = w.nextNode())) n.nodeValue = n.nodeValue.replace(/ah_[A-Za-z0-9_-]{8,}/g, 'ah_••••••••••••');
                document.querySelectorAll('input,textarea').forEach(i => { i.value = i.value.replace(/ah_[A-Za-z0-9_-]{8,}/g, 'ah_••••••••••••'); }); }""")
            pg.eval_on_selector("#cn-out", "o => o.scrollIntoView({block: 'start'})")
            pg.evaluate("window.scrollBy(0, -200)")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / "16-connect-cursor.png"))
            csrf = next(c["value"] for c in ctx.cookies() if c["name"] == "hangar_csrf")
            conns = pg.request.get(f"{BASE}/api/agents/deal-desk/connections").json()
            for k in conns:
                r = pg.request.delete(f"{BASE}/api/keys/{k['id']}", headers={"X-CSRF-Token": csrf})
                print("revogada", k["client_label"], r.status)
        elif group == "employee":
            # Digital employee (v0.16): contratado pelo MCP (employee_live.py); a tarefa espera a aprovação de um e-mail
            go("#/employees/renewals-analyst/probation", "18-employee-probation.png", wait=".tabs", pause=1500)
            go("#/employees/renewals-analyst/overview", "19-employee.png", wait=".tabs", pause=1500)
            pg.goto(f"{BASE}/app/#/decisions")
            pg.wait_for_selector(".dc button.dc-go[data-d='approve']", timeout=30000)
            pg.wait_for_timeout(1200)
            pg.eval_on_selector(".dc:has(.dc-edit-open)", "c => c.scrollIntoView({block: 'start'})")
            pg.evaluate("window.scrollBy(0, -120)")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / "20-decision.png"))
            pg.goto(f"{BASE}/app/#/employees/renewals-analyst/authority")
            pg.wait_for_selector(".tabs")
            pg.wait_for_timeout(1500)
            pg.eval_on_selector(".tabs", "t => t.scrollIntoView({block: 'start'})")  # a tabela inteira, com o piso da empresa
            pg.evaluate("window.scrollBy(0, -20)")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / "21-authority.png"))
        elif group == "reuse":
            # reusar antes de construir: o hangar procura no catálogo agentes e skills parecidos com o pedido
            pg.goto(f"{BASE}/app/#/agents/new")
            pg.wait_for_selector("#pl-req")
            pg.fill("#pl-req", "A renewal assistant that remembers each customer's history, flags upcoming renewals and "
                               "writes the renewal email")
            pg.fill("#pl-caps", "remember each customer's history\nflag upcoming renewals\nwrite the renewal proposal email")
            pg.click("#pl-go")
            pg.wait_for_selector("#pl-out table, #pl-out .warn-card", timeout=60000)
            pg.wait_for_timeout(800)
            spec = pg.locator(".pl-spec[value='account-memory']")
            if spec.count():
                spec.first.check()
            pg.wait_for_timeout(400)
            pg.eval_on_selector("#pl-out", "o => o.scrollIntoView({block: 'start'})")
            pg.evaluate("window.scrollBy(0, -260)")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / "17-reuse.png"))
        b.close()
    print("ok", sorted(x.name for x in OUT.iterdir()))


run(sys.argv[1] if len(sys.argv) > 1 else "main")
