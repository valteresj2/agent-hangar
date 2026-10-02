"""Confere as telas do 'reusar antes de construir' no portal, como a Maya."""
import pathlib

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
OUT = D / "shots"
OUT.mkdir(exist_ok=True)
BASE = "http://central:8080"
SESSION = (D / "maya_session.txt").read_text().strip()
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_cookies([{"name": "hangar_session", "value": SESSION, "url": BASE},
                     {"name": "hangar_csrf", "value": "demo-csrf-token", "url": BASE}])
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(f"{BASE}/app/#/agents/new")
    pg.wait_for_selector("#pl-req")
    pg.fill("#pl-req", "A renewal assistant that remembers each customer's history, flags upcoming renewals and writes the renewal email")
    pg.fill("#pl-caps", "remember each customer's history\nflag upcoming renewals\nwrite the renewal proposal email")
    pg.click("#pl-go")
    pg.wait_for_selector("#pl-out table, #pl-out .warn-card", timeout=60000)
    pg.wait_for_timeout(800)
    pg.check(".pl-spec[value='account-memory']")
    pg.wait_for_timeout(300)
    print("botao:", pg.inner_text("#na-go"), "| linhas:", pg.locator("#pl-out tr").count(), "| modo:", pg.inner_text("#pl-mode"))
    pg.screenshot(path=str(OUT / "c1-plan.png"), full_page=True)
    for slug, name in (("renewal-coach", "c2-lineage"), ("account-memory", "c3-used-by")):
        pg.goto(f"{BASE}/app/#/agents/{slug}")
        pg.wait_for_selector("#lineage .card", timeout=30000)
        pg.wait_for_timeout(600)
        pg.eval_on_selector("#lineage", "e => e.scrollIntoView({block: 'start'})")
        pg.screenshot(path=str(OUT / f"{name}.png"))
        print(slug, "->", pg.inner_text("#lineage")[:300].replace("\n", " | "))
    print("erros de JS:", errors)
    b.close()
