// Capturas do computer use na instalação: a tarefa (linha do tempo, aprovação, resultado) e os apps liberados.
// Playwright from this folder or from PLAYWRIGHT_FROM (a package.json of a project that has @playwright/test)
const { createRequire } = require('node:module')
const req = process.env.PLAYWRIGHT_FROM ? createRequire(process.env.PLAYWRIGHT_FROM) : require
const { chromium } = req('@playwright/test')
const [U, TASK, SLUG, OUT] = [process.env.HANGAR_URL, process.argv[2], process.argv[3], process.argv[4]]
;(async () => {
  const b = await chromium.launch({ channel: 'msedge' })
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 },
    extraHTTPHeaders: { Authorization: `Bearer ${process.env.HANGAR_TOKEN}` } })
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', (e) => errors.push(String(e)))
  await p.goto(`${U}/ui#/tasks/${TASK}`)
  await p.waitForTimeout(3500)
  await p.screenshot({ path: `${OUT}/task-top.png` })
  await p.screenshot({ path: `${OUT}/task-full.png`, fullPage: true })
  for (const [n, txt] of [['task-approval', 'Confirmar baixa'], ['task-secret', '[segredo]']]) {
    const el = p.getByText(txt).first()
    if (await el.count()) {
      await el.scrollIntoViewIfNeeded()
      await p.evaluate(() => window.scrollBy(0, -250))
      await p.waitForTimeout(500)
      await p.screenshot({ path: `${OUT}/${n}.png` })
    }
  }
  await p.goto(`${U}/ui#/employees/${SLUG}`)
  await p.waitForTimeout(3000)
  const tabs = await p.locator('.tabs a').allTextContents()
  console.log('tabs:', tabs.join(' | '))
  const cfg = p.locator('.tabs a', { hasText: /Configura|Ajustes|Settings/ }).first()
  if (await cfg.count()) {
    await cfg.click()
    await p.waitForTimeout(3000)
    const apps = p.locator('#pt-apps')
    if (await apps.count()) {
      await apps.scrollIntoViewIfNeeded()
      await p.evaluate(() => window.scrollBy(0, -300))
      await p.waitForTimeout(500)
      await p.screenshot({ path: `${OUT}/apps.png` })
    }
  }
  console.log('errors:', errors.length ? errors : 'none')
  await b.close()
})()
