"""Capturas do portal em inglês e em português (seletor de idioma)."""
import pathlib

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
BASE = "http://central:8080"
with sync_playwright() as p:
    b = p.chromium.launch()
    for lang in ("en", "pt"):
        ctx = b.new_context(viewport={"width": 1440, "height": 1000})
        ctx.request.post(f"{BASE}/api/auth/password",
                         data={"username": "maya.chen", "password": (D / "maya_password.txt").read_text().strip()})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
        pg.add_init_script(f"localStorage.setItem('hangar_lang', '{lang}')")
        for r, name in (("#/", "home"), ("#/agents/renewal-coach", "agent"), ("#/agents/new", "new"), ("#/connect", "connect")):
            pg.goto(f"{BASE}/app/{r}")
            pg.wait_for_timeout(2200)
            pg.screenshot(path=str(D / "shots" / f"lang-{lang}-{name}.png"))
        print(lang, "html lang =", pg.evaluate("document.documentElement.lang"), "| erros:", errs)
        ctx.close()
    b.close()
