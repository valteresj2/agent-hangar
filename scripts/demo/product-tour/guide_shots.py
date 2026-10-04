"""Capturas da aba Guia (PT e EN), como a Maya: um agente multiagente com memória e um agente simples."""
import pathlib

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
BASE = "http://central:8080"
AGENTS = ("renewal-coach", "account-memory")
with sync_playwright() as p:
    b = p.chromium.launch()
    for lang in ("pt", "en"):
        ctx = b.new_context(viewport={"width": 1440, "height": 1300})
        ctx.request.post(f"{BASE}/api/auth/password",
                         data={"username": "maya.chen", "password": (D / "maya_password.txt").read_text().strip()})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
        pg.add_init_script(f"localStorage.setItem('hangar_lang', '{lang}')")
        for slug in AGENTS:
            pg.goto(f"{BASE}/app/#/agents/{slug}/guide")
            pg.wait_for_selector(".guide-flow svg", timeout=20000)
            pg.wait_for_timeout(1200)
            tabs = pg.inner_text(".tabs").replace("\n", " | ")
            pg.screenshot(path=str(D / "shots" / f"guide-{lang}-{slug}.png"), full_page=True)
            print(lang, slug, "| abas:", tabs)
        print(lang, "erros de JS:", errs)
        ctx.close()
    b.close()
