// The demo path, end to end, against the running app (real API), with timings:
//   worklist -> search "sisällissota" -> list -> article (Languages, Edit wars) -> map -> click a dot
//   1. .venv\Scripts\python -m uvicorn api.main:app --port 8000
//   2. cd web; node scripts/demo-flow.mjs        -> docs/screenshots/demo-*.png, timings printed
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = process.env.BASE || 'http://127.0.0.1:8000'
const Q = process.env.QUERY || 'sisällissota'
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'screenshots')
mkdirSync(OUT, { recursive: true })
const timings = []
const time = async (label, fn) => {
  const t = performance.now()
  const r = await fn()
  const ms = Math.round(performance.now() - t)
  timings.push([label, ms])
  console.log(`${label.padEnd(44)} ${String(ms).padStart(6)} ms`)
  return r
}
const shot = async (page, name) => { await page.screenshot({ path: path.join(OUT, `demo-${name}.png`) }); console.log('  saved', `demo-${name}.png`) }
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }

const browser = await chromium.launch({ channel: process.env.CHANNEL || 'msedge' })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: 'light' })
page.on('pageerror', (e) => fail(`page error: ${e.message}`))

// 0. landing = the worklist
await time('landing: worklist rendered', async () => {
  await page.goto(`${BASE}/`)
  await page.waitForSelector('table.wl2 tbody tr')
})
if (!page.url().includes('/contested/')) fail(`/ did not redirect to the editor app: ${page.url()}`)
await shot(page, '1-worklist')

// 1. semantic search
await time(`semantic search "${Q}" -> list`, async () => {
  await page.fill('.search input', Q)
  await page.press('.search input', 'Enter')
  await page.waitForFunction(() => document.querySelector('.chiprow .status')?.innerText.includes('embedded'))
  await page.waitForSelector('.worklist2:not(.stale) table.wl2 tbody tr')
})
const top = await page.$$eval('table.wl2 tbody tr .art a', (as) => as.slice(0, 5).map((a) => a.innerText))
console.log('  top results:', top.join(' | '))
if (!top.includes('Suomen sisällissota')) fail('Suomen sisällissota not in the top 5')
await shot(page, '2-search')

// 1b. SQL drawer on the search
await page.click('.sqltoggle')
await page.waitForSelector('.sqlcontent pre')
await shot(page, '2b-search-sql')
await page.click('.sqltoggle')

// 1c. a topic chip (WITH RECURSIVE)
await time('topic chip "Civil War 1918"', async () => {
  await page.click('.search .clear')
  await page.waitForFunction(() => !document.querySelector('.search input').value)
  await page.click('.topic:has-text("Civil War 1918")')
  await page.waitForFunction(() => document.querySelector('.chiprow .status')?.innerText.match(/^\d+ article/))
})
await shot(page, '3-chip')

// 2. article page, Languages tab
await time('open article -> Languages tab', async () => {
  await page.click('table.wl2 tbody tr:has-text("Suomen sisällissota")')
  await page.waitForSelector('.cmprow .cell')
})
const agreed = await page.$$eval('.contras li', (li) => li.map((x) => x.classList.contains('agree')))
console.log(`  contradictions panel: ${agreed.length}, both models agree: ${agreed.filter(Boolean).length}`)
if (agreed.length && !agreed[0]) fail('"both models agree" not first')
await shot(page, '4-article-languages')
// click the first contradiction (both models agree): its row and the fix panel with "Edit in Wikipedia"
await page.click('.contras li')
await page.waitForSelector('.fix')
await page.evaluate(() => window.scrollBy(0, -70))
await page.waitForTimeout(300)
await shot(page, '4b-contradiction-fix')
await page.evaluate(() => window.scrollTo(0, 0))

// 3. Edit wars tab
await time('Edit wars tab', async () => {
  await page.click('.arttabs a:has-text("Edit wars")')
  await page.waitForSelector('.war')
})
await shot(page, '5-article-editwars')
await time('Edit wars -> Contested sentences', async () => {
  await page.click('.subtabs button:has-text("Contested sentences")')
  await page.waitForSelector('.prose .s')
})
await shot(page, '6-article-contested')
await time('Edit wars -> Article on a date', async () => {
  await page.click('.subtabs button:has-text("Article on a date")')
  await page.waitForSelector('.sliders input[type=range]')
})
await shot(page, '7-article-asof')

// 4-6. the map
for (const mode of ['2d']) {
  const tag = mode === '3d' ? '3D' : '2D'
  await time(`${tag} map for "${Q}"`, async () => {
    await page.goto(`${BASE}/contested/#/map?q=${encodeURIComponent(Q)}`)
    await page.reload()
    await page.waitForFunction(() => document.querySelector('.maplegend')?.innerText.match(/[1-9][\d,]* articles at/))
    await page.waitForSelector('.mapcanvas canvas')
  })
  await page.waitForTimeout(mode === '3d' ? 2500 : 900)      // camera flight / fit animation
  await shot(page, '8-map-search')

  // where the map drew the mark holding the civil war (alone, or in a blob), then a real hover and click
  const where = () => page.evaluate((m) => {
    const has = (k) => k.items.some((a) => a.id === 'Q211855')
    if (m === '2d') { const k = window.__map.marks.find(has); return k && { x: k.sx, y: k.sy, n: k.n } }
    const g = window.__globe, k = g.objectsData().find(has)
    return k && { ...g.getScreenCoords(k.lat, k.lon, 0.0064), n: k.n }
  }, mode)
  const box = await page.$eval('.mapcanvas', (c) => { const r = c.getBoundingClientRect(); return { x: r.left, y: r.top } })
  let found = null
  const p = await where()
  console.log(`  the civil war is ${p?.n > 1 ? `in a blob of ${p.n}` : 'a dot of its own'}`)
  await time(`${tag}: hover its mark`, async () => {
    if (!p) return
    for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1], [2, 2]]) {
      await page.mouse.move(box.x + p.x + dx, box.y + p.y + dy)
      const tip = await page.waitForSelector('.maptip b', { timeout: 1500 }).then((e) => e.innerText()).catch(() => null)
      if (tip && (tip === 'Suomen sisällissota' || (p.n > 1 && tip.includes(`${p.n} articles`)))) { found = { x: box.x + p.x + dx, y: box.y + p.y + dy }; break }
    }
  })
  await shot(page, '8b-map-hover')
  if (!found) { fail(`${tag}: the civil war's mark not found`); continue }
  if (p.n > 1) {
    await time(`${tag}: click the blob -> list of its articles`, async () => {
      await page.mouse.click(found.x, found.y)
      await page.waitForSelector('.mapcard .bloblist li')
    })
    await shot(page, '8c-map-blob')
  }
  await time(`${tag}: pick the civil war -> 10 similar articles + lines`, async () => {
    if (p.n > 1) await page.click('.bloblist button:has-text("Suomen sisällissota")')
    else await page.mouse.click(found.x, found.y)
    await page.waitForSelector('.mapcard .simlist li')
  })
  await page.waitForTimeout(mode === '3d' ? 1500 : 600)
  await shot(page, '9-map-pick')
  if (mode === '2d') console.log(`  2D frame time: ${await page.$eval('.maplegend', (e) => e.innerText.match(/frame ([\d.]+) ms/)?.[1])} ms`)
  else console.log(`  3D frames/s (software WebGL): ${await page.evaluate(() => new Promise((ok) => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 2000) requestAnimationFrame(f); else ok((n / 2).toFixed(0)) }; requestAnimationFrame(f) }))}`)
  await time(`${tag}: map card name -> article page`, async () => {
    await page.click('.mapcard .title')
    await page.waitForSelector('.cmprow .cell')
  })
  await time(`${tag}: map, all articles`, async () => {
    await page.goto(`${BASE}/contested/#/map`)
    // "2,682" or "2 682": the browser's locale decides the thousands separator
    await page.waitForFunction(() => document.querySelector('.maplegend')?.innerText.match(/\d[\d,\s]{3,} articles at/))
  })
  await page.waitForTimeout(mode === '3d' ? 2500 : 900)
  await shot(page, '10-map-all')
}

console.log('\ntimings (ms):', JSON.stringify(Object.fromEntries(timings)))
await browser.close()
