"""Capturas reais do portal (como a Maya, em inglês) em 2x, para o vídeo: nítidas mesmo com zoom de câmera.
Roda no container do Playwright, na rede do Hangar:
  docker run --rm --network hangar_agents -v "<product-tour>:/demo" -v "<motion>:/motion" \
    mcr.microsoft.com/playwright/python:v1.63.0-noble sh -c "pip install -q playwright==1.63.0 && python /motion/capture.py"
Telas que dependem de um momento que já passou (pedido de produção, e-mail esperando aprovação) ficam com a captura
original da demo (1x)."""
import pathlib

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
OUT = pathlib.Path("/motion/public/shots")
BASE = "http://central:8080"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="light",
                            locale="en-US")
        r = ctx.request.post(f"{BASE}/api/auth/password",
                             data={"username": "maya.chen", "password": (D / "maya_password.txt").read_text().strip()})
        assert r.ok, r.text()
        ctx.add_init_script("localStorage.setItem('hangar_lang', 'en')")
        pg = ctx.new_page()

        def shot(name):
            pg.screenshot(path=str(OUT / f"{name}.png"))
            print(name)

        def go(hash_, name, wait="main h1", pause=1500, scroll=None):
            pg.goto(f"{BASE}/app/{hash_}")
            pg.wait_for_selector(wait, timeout=30000)
            pg.wait_for_timeout(pause)
            if scroll:
                pg.eval_on_selector(scroll, "e => e.scrollIntoView({block: 'start'})")
                pg.evaluate("window.scrollBy(0, -20)")
                pg.wait_for_timeout(400)
            shot(name)

        pg.goto((D / "claude_chat.html").as_uri())
        pg.wait_for_timeout(1500)
        shot("01-claude")
        go("#/agents/account-memory/tests", "06-tests", wait=".tabs", pause=2500)
        go("#/agents/catalog", "10-catalog", wait="#rows tr")
        go("#/usage", "12-usage", pause=2500)
        go("#/agents/deal-desk/guide", "14-guide", wait=".guide-md")
        go("#/agents/account-memory/memory", "08-memory", wait="table")
        pg.goto(f"{BASE}/app/#/agents/deal-desk/connect")
        pg.wait_for_selector(".cn-go")
        pg.wait_for_timeout(1200)
        pg.eval_on_selector(".grid.g3", "g => g.scrollIntoView({block: 'start'})")
        pg.evaluate("window.scrollBy(0, -90)")
        pg.wait_for_timeout(400)
        shot("15-connect-tools")
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
        pg.eval_on_selector("#pl-out", "o => o.scrollIntoView({block: 'start'})")
        pg.evaluate("window.scrollBy(0, -260)")
        pg.wait_for_timeout(400)
        shot("17-reuse")
        go("#/employees/renewals-analyst/probation", "18-employee-probation", wait=".tabs")
        go("#/employees/renewals-analyst/authority", "21-authority", wait=".tabs", scroll=".tabs")
        go("#/employees/support-analyst/authority", "22-learn", wait=".sg", scroll=".tabs")
        b.close()


main()
