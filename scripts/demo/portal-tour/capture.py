"""Captura o portal do usuário como a Ana (sessão temporária) + o quadro da conversa com o Claude."""
import pathlib

from playwright.sync_api import sync_playwright

D = pathlib.Path("/demo")
OUT = D / "shots"
OUT.mkdir(exist_ok=True)
BASE = "http://central:8080"
SESSION = (D / "ana_session.txt").read_text().strip()
W, H = 1440, 900
SLUG = "assistente-comercial"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, color_scheme="light", locale="pt-BR")
        # 1) conversa com o Claude (arquivo local)
        pg = ctx.new_page()
        pg.goto((D / "claude_chat.html").as_uri())
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / "01-claude.png"))
        pg.close()

        ctx.add_cookies([{"name": "hangar_session", "value": SESSION, "url": BASE},
                         {"name": "hangar_csrf", "value": "demo-csrf-token", "url": BASE}])
        pg = ctx.new_page()

        def go(hash_, name, wait="main h1", pause=1200, full=False):
            pg.goto(f"{BASE}/app/{hash_}")
            pg.wait_for_selector(wait, timeout=30000)
            pg.wait_for_timeout(pause)
            pg.screenshot(path=str(OUT / name), full_page=full)

        go("#/", "02-inicio.png", wait=".attn-card")
        go("#/agents", "03-meus-agentes.png", wait="#rows tr")
        go(f"#/agents/{SLUG}", "04-agente.png", wait=".tabs")
        # playground: pergunta de verdade
        pg.goto(f"{BASE}/app/#/agents/{SLUG}/playground")
        pg.wait_for_selector("#pmsg")
        pg.fill("#pmsg", "Quais clientes precisam de contato esta semana e por quê?")
        pg.click("#psend")
        pg.wait_for_selector(".msg.a.md", timeout=240000)
        pg.wait_for_timeout(800)
        pg.eval_on_selector(".chat", "c => { c.style.maxHeight = 'none'; }")
        pg.screenshot(path=str(OUT / "05-playground.png"))
        go(f"#/agents/{SLUG}/memory", "06-memoria.png", wait="table")
        pg.goto(f"{BASE}/app/#/agents/{SLUG}/schedules")
        pg.wait_for_selector(".sc-hist")
        pg.click(".sc-hist")
        pg.wait_for_selector(".run-out", timeout=30000)
        pg.wait_for_timeout(600)
        pg.eval_on_selector(".sc-runs", "r => r.scrollIntoView({block: 'start'})")
        pg.evaluate("window.scrollBy(0, -140)")
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(OUT / "07-resumo-agendado.png"))
        go(f"#/agents/{SLUG}/connect", "08-conectar.png", wait=".tabs", pause=1500)
        go("#/agents/catalog", "09-catalogo.png", wait="#rows tr")
        go("#/approvals", "10-pedidos.png", wait="main h1")
        b.close()
    print("ok", sorted(x.name for x in OUT.iterdir()))


main()
