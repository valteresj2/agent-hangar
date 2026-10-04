"""Gera o rascunho do guia de um agente pelo portal (como a Maya) e captura a aba Guia em PT e EN."""
import pathlib
import sys

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
BASE = "http://central:8080"
SLUG = sys.argv[1] if len(sys.argv) > 1 else "renewal-coach"
with sync_playwright() as p:
    b = p.chromium.launch()
    for lang in ("pt", "en"):
        ctx = b.new_context(viewport={"width": 1440, "height": 1300})
        ctx.request.post(f"{BASE}/api/auth/password",
                         data={"username": "maya.chen", "password": (D / "maya_password.txt").read_text().strip()})
        if lang == "pt":
            csrf = next(c["value"] for c in ctx.cookies() if c["name"] == "hangar_csrf")
            r = ctx.request.post(f"{BASE}/api/agents/{SLUG}/guide/generate", headers={"X-CSRF-Token": csrf}, timeout=180000)
            doc = r.json().get("doc") or {}
            print("gerar:", r.status, "| rascunho revisado?", doc.get("reviewed"), "| fonte:", doc.get("source"))
            print((doc.get("text") or r.text)[:1500])
        pg = ctx.new_page()
        pg.add_init_script(f"localStorage.setItem('hangar_lang', '{lang}')")
        pg.goto(f"{BASE}/app/#/agents/{SLUG}/guide")
        pg.wait_for_selector(".guide-md", timeout=20000)
        pg.wait_for_timeout(1200)
        pg.screenshot(path=str(D / "shots" / f"guide-draft-{lang}.png"), full_page=True)
        ctx.close()
    b.close()
