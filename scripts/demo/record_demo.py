"""Grava a demo do README: LibreChat + Data Studio (anexos → análise → dashboard e slides).

Pré-requisitos: stack no ar (Agent Hangar com --profile data-studio, agente data-studio em produção e
integrations/librechat) e `pip install playwright pillow && playwright install chromium`.

    python scripts/demo/record_demo.py            # gera docs/assets/demo.gif e as capturas PNG

Credenciais: LIBRECHAT_EMAIL / LIBRECHAT_PASSWORD, ou TEST_USER_* de integrations/librechat/.env.
"""
import io
import os
import pathlib
import re
import time

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "assets"
SAMPLES = ROOT / "examples" / "data-studio" / "samples"
URL = os.environ.get("LIBRECHAT_URL", "http://localhost:3090")
PROMPT = ("Analyze the H1 sales spreadsheet together with the supplier report (PDF) and the stock photo. "
          "Give me the top 5 findings, an interactive dashboard and a short presentation.")
W, H = 1440, 900


def creds() -> tuple[str, str]:
    env = {}
    f = ROOT / "integrations" / "librechat" / ".env"
    if f.exists():
        env = dict(line.split("=", 1) for line in f.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return (os.environ.get("LIBRECHAT_EMAIL") or env.get("TEST_USER_EMAIL", ""),
            os.environ.get("LIBRECHAT_PASSWORD") or env.get("TEST_USER_PASSWORD", ""))


class Recorder:
    def __init__(self, page):
        self.page, self.frames = page, []

    def snap(self, hold: int = 1):
        img = Image.open(io.BytesIO(self.page.screenshot())).convert("RGB")
        if self.frames and list(self.frames[-1][0].getdata())[::997] == list(img.getdata())[::997]:
            self.frames[-1][1] += hold  # quadro repetido: só estica a duração
        else:
            self.frames.append([img, hold])

    def gif(self, path: pathlib.Path, width: int = 1000, base_ms: int = 700):
        imgs = [f.resize((width, int(f.height * width / f.width)), Image.LANCZOS) for f, _ in self.frames]
        pal = [i.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for i in imgs]
        pal[0].save(path, save_all=True, append_images=pal[1:], loop=0, optimize=True,
                    duration=[min(h, 6) * base_ms for _, h in self.frames])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    email, password = creds()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, locale="en-US", color_scheme="light")
        page = ctx.new_page()
        rec = Recorder(page)

        page.goto(f"{URL}/login")
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_url(re.compile(r"/c/"), timeout=20000)
        page.goto(f"{URL}/c/new")
        page.wait_for_selector("textarea", timeout=20000)
        time.sleep(1.5)
        rec.snap(2)

        # anexos: menu de anexo → primeira opção ("upload to provider") → seletor de arquivos real
        page.click('[aria-label="Attach File Options"]')
        with page.expect_file_chooser() as fc:
            items = page.locator('[role="menuitem"]:visible')
            items.filter(has_not_text=re.compile("text|texto", re.I)).first.click()
        fc.value.set_files([str(SAMPLES / n) for n in ("vendas_2026.xlsx", "relatorio_fornecedores.pdf",
                                                        "quadro_estoque.png")])
        time.sleep(4)
        page.fill("textarea", PROMPT)
        rec.snap(3)
        page.keyboard.press("Enter")

        # enquanto o agente trabalha: abre o bloco de progresso ("Thoughts") e captura as ferramentas rodando
        opened, t0 = False, time.time()
        while time.time() - t0 < 420:
            time.sleep(2.5)
            if not opened:
                toggle = page.get_by_role("button", name=re.compile("Thinking|Thoughts|Reasoning", re.I))
                if toggle.count():
                    toggle.first.click()
                    opened = True
            rec.snap(1)
            links = page.locator('a[href*=":8095/f/"]')
            busy = page.locator('[aria-label*="Stop"], [data-testid="stop-generation-button"]').count()
            if links.count() >= 2 and not busy:
                break
        time.sleep(2)
        # resposta final: rola pelo texto para mostrar achados e links
        for _ in range(4):
            rec.snap(3)
            page.mouse.wheel(0, 500)
            time.sleep(0.8)
        rec.snap(4)
        page.screenshot(path=OUT / "librechat-answer.png")

        hrefs = [a.get_attribute("href") for a in page.locator('a[href*=":8095/f/"]').all()]
        dash = next((h for h in hrefs if "dashboard" in h and h.endswith(".html")), None) or \
            next((h for h in hrefs if h.endswith(".html")), None)
        deck = next((h for h in hrefs if h.endswith(".html") and h != dash), None)
        if dash:
            d = ctx.new_page()
            d.goto(dash)
            time.sleep(4)
            d.screenshot(path=OUT / "dashboard.png")
            rec.page = d
            rec.snap(5)
            d.mouse.wheel(0, 700)
            time.sleep(1.5)
            rec.snap(4)
        if deck:
            s = ctx.new_page()
            s.goto(deck + "#3")
            time.sleep(3)
            s.screenshot(path=OUT / "slides.png")
            rec.page = s
            rec.snap(5)
        rec.gif(OUT / "demo.gif")
        browser.close()
    print("ok:", *(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
