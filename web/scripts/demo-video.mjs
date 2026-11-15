// Record the demo as a video (WebM, 1920×1080): the 3-minute path through AikaKone with a visible
// mouse pointer and short captions saying what is going on.
//   1. python start.py            (the app on :8000; let it warm up ~15 s for the search model)
//   2. cd web; node scripts/demo-video.mjs        -> data/aikakone-demo.webm
import { chromium } from 'playwright-core'
import { mkdirSync, copyFileSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = process.env.BASE || 'http://127.0.0.1:8000'
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const OUT = process.env.OUT || path.join(ROOT, 'data', 'aikakone-demo.webm')
const TMP = path.join(ROOT, 'data', 'video-tmp')
const W = 1920, H = 1080
mkdirSync(TMP, { recursive: true })

// A visible pointer, a click ring and a caption bar, added to every page load.
const OVERLAY = () => {
  const css = `
    #demo-cursor { position: fixed; left: 0; top: 0; width: 26px; height: 26px; z-index: 2147483647; pointer-events: none;
      transform: translate(-3px, -2px); transition: none; filter: drop-shadow(0 2px 3px rgba(0,0,0,.35)); }
    .demo-ring { position: fixed; width: 36px; height: 36px; margin: -18px 0 0 -18px; border-radius: 50%; z-index: 2147483646;
      border: 3px solid rgba(47,93,138,.85); pointer-events: none; animation: demo-ring .55s ease-out forwards; }
    @keyframes demo-ring { from { transform: scale(.4); opacity: 1 } to { transform: scale(1.4); opacity: 0 } }
    #demo-caption { position: fixed; left: 50%; bottom: 44px; transform: translateX(-50%); z-index: 2147483645; pointer-events: none;
      max-width: 1300px; padding: 14px 26px; border-radius: 14px; background: rgba(20,22,28,.86); color: #fff;
      font: 500 26px/1.35 Inter, system-ui, sans-serif; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,.25);
      opacity: 0; transition: opacity .35s ease; }
    #demo-caption.on { opacity: 1; }
    #demo-caption small { display: block; font-size: 19px; font-weight: 400; opacity: .8; margin-top: 3px; }`
  const add = () => {
    if (document.getElementById('demo-cursor')) return
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st)
    const c = document.createElement('div'); c.id = 'demo-cursor'
    c.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.5 19 2.6-7.7L21 10.7z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>'
    document.body.appendChild(c)
    const cap = document.createElement('div'); cap.id = 'demo-caption'; document.body.appendChild(cap)
    const pos = window.__demoPos || [W / 2, H / 2]
    c.style.left = pos[0] + 'px'; c.style.top = pos[1] + 'px'
    document.addEventListener('mousemove', (e) => { window.__demoPos = [e.clientX, e.clientY]; c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px' }, true)
    document.addEventListener('mousedown', (e) => {
      const r = document.createElement('div'); r.className = 'demo-ring'
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'
      document.body.appendChild(r); setTimeout(() => r.remove(), 600)
    }, true)
    window.__caption = (html) => {
      cap.classList.remove('on')
      setTimeout(() => { cap.innerHTML = html || ''; if (html) cap.classList.add('on') }, html && cap.innerHTML ? 350 : 0)
    }
  }
  const W = 1920, H = 1080
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add()
}

const browser = await chromium.launch({ channel: process.env.CHANNEL || 'msedge' })
const context = await browser.newContext({ viewport: { width: W, height: H }, colorScheme: 'light',
  recordVideo: { dir: TMP, size: { width: W, height: H } } })
await context.addInitScript(OVERLAY)
const page = await context.newPage()
page.on('pageerror', (e) => console.log('page error:', e.message))

const wait = (ms) => page.waitForTimeout(ms)
const caption = async (title, sub = '', hold = 0) => {
  await page.evaluate(([t, s]) => window.__caption?.(t ? `${t}${s ? `<small>${s}</small>` : ''}` : ''), [title, sub])
  if (hold) await wait(hold)
}
let mouse = [W / 2, H / 2]
async function moveTo(x, y, ms = 700) {
  const steps = Math.max(8, Math.round(ms / 16))
  await page.mouse.move(x, y, { steps })
  mouse = [x, y]
}
async function moveToEl(selector, { dx = 0, dy = 0, ms = 700 } = {}) {
  const el = page.locator(selector).first()
  await el.scrollIntoViewIfNeeded()
  const b = await el.boundingBox()
  await moveTo(b.x + b.width / 2 + dx, b.y + b.height / 2 + dy, ms)
  return b
}
async function click(selector, opts = {}) {
  await moveToEl(selector, opts)
  await wait(250)
  await page.mouse.down(); await wait(80); await page.mouse.up()
}
async function type(selector, text) {
  await click(selector)
  await page.keyboard.type(text, { delay: 85 })
}
const scrollBy = (y) => page.evaluate((dy) => window.scrollBy({ top: dy, behavior: 'smooth' }), y)
const scrollTop = () => page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))

// ------------------------------------------------------------------ the demo
await page.goto(`${BASE}/`)
await page.waitForSelector('table.wl2 tbody tr')
await wait(800)
await caption('AikaKone', 'Finnish, Swedish and English Wikipedia on Finland’s history: where the versions differ, and where editors fight', 4200)

await caption('The worklist: 2,909 articles that exist in all three languages',
  'ranked by language difference, missing content, Gemma’s possible contradictions and edit wars', 1500)
await moveToEl('table.wl2 thead th:has-text("Language difference")', { ms: 900 }); await wait(900)
await moveToEl('table.wl2 thead th:has-text("Missing content")', { ms: 600 }); await wait(900)
await moveToEl('table.wl2 thead th:has-text("Possible contradictions")', { ms: 600 }); await wait(900)
await moveToEl('table.wl2 thead th:has-text("Edit wars")', { ms: 600 }); await wait(1400)

await caption('Semantic search, in any language', 'bge-m3 embeds the query; MariaDB ranks the articles by VEC_DISTANCE', 600)
await type('.search input', 'prison camps 1918')
await page.keyboard.press('Enter')
await page.waitForFunction(() => document.querySelector('.chiprow .status')?.innerText.includes('embedded'))
await page.waitForSelector('.worklist2:not(.stale) table.wl2 tbody tr')
await caption('An English query finds the Finnish prison-camp articles', 'Suomenlinnan, Tampereen and Tammisaaren vankileiri never use those words', 500)
await moveToEl('table.wl2 tbody tr:nth-child(1) .art a', { ms: 800 }); await wait(3200)

await caption('Every view shows its MariaDB SQL', '', 300)
await click('.sqltoggle'); await wait(4200)
await click('.sqltoggle'); await wait(400)

await caption('Topic chips: a Finnish category and all its subcategories', 'WITH RECURSIVE over Wikipedia’s category tree', 300)
await click('.search .clear'); await wait(700)
await click('.topic:has-text("Civil War 1918")')
await page.waitForFunction(() => /^\d+ article/.test(document.querySelector('.chiprow .status')?.innerText || ''))
await wait(2200)

await caption('Open an article: the Finnish Civil War', '', 300)
await click('table.wl2 tbody tr:has-text("Suomen sisällissota") .art a')
await page.waitForSelector('.cmprow .cell'); await wait(900)
await caption('Finnish, Swedish and English side by side, sentence by sentence',
  'bge-m3 sentence vectors; mutual best matches in MariaDB; colour = how the sentence relates to the Finnish one', 3800)
await caption('Gemma’s possible contradictions, the ones both models agree on first', 'Gemma 27B + 12B, self-hosted on a Verda GPU', 600)
await moveToEl('.contras li:nth-child(1)', { ms: 800 }); await wait(2200)
await moveToEl('.contras li:has-text("Mannerheim")', { ms: 600 }); await wait(1800)
await click('.contras li:has-text("Mannerheim")')
await page.waitForSelector('.fix'); await wait(500)
await page.evaluate(() => window.scrollBy(0, -80)); await wait(600)
await caption('Mannerheim’s order: 25 or 27 January? Check the sources', 'the two sentences, Gemma’s reason, and the editor links', 3200)
await caption('A human makes the edit', '“Edit in Wikipedia” opens Wikipedia’s own editor; the tool never edits Wikipedia', 600)
await moveToEl('.fix .editbtns a.primary', { ms: 800 }); await wait(3000)

await scrollTop(); await wait(900)
await caption('Edit wars in the Finnish history', 'system-versioned sentences: removed and restored, again and again (FOR SYSTEM_TIME ALL)', 300)
await click('.arttabs a:has-text("Edit wars")')
await page.waitForSelector('.war'); await wait(1500)
await moveToEl('.war .lives', { ms: 700 }); await wait(2600)
await caption('The article on any date', 'FOR SYSTEM_TIME AS OF: drag the slider through 23 years of history', 300)
await click('.subtabs button:has-text("Article on a date")')
await page.waitForSelector('.sliders input[type=range]'); await wait(1000)
{
  const b = await page.locator('.sliders input[type=range]').first().boundingBox()
  await moveTo(b.x + b.width - 6, b.y + b.height / 2, 800); await wait(300)
  await page.mouse.down()
  await moveTo(b.x + b.width * 0.62, b.y + b.height / 2, 1600); await wait(500)
  await moveTo(b.x + b.width * 0.3, b.y + b.height / 2, 1600)
  await page.mouse.up(); await wait(2500)
}

await caption('The map: every article at its place', 'crowded places merge into one blob; zoom in and they split', 300)
await scrollTop(); await wait(400)
await click('.mainnav a:has-text("Map")')
await page.waitForSelector('.mapcanvas canvas'); await wait(800)
if (await page.locator('.topic.on').count()) { await click('.topic.on'); }
await page.waitForFunction(() => /\d[\d,\s]{3,} articles at/.test(document.querySelector('.maplegend')?.innerText || ''))
await wait(1800)
{
  const box = await page.locator('.mapcanvas').boundingBox()
  const big = await page.evaluate(() => { const m = [...window.__map.marks].sort((a, b) => b.n - a.n)[0]; return { x: m.sx, y: m.sy } })
  await moveTo(box.x + big.x, box.y + big.y, 900); await wait(600)
  for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, -260); await wait(260) }
  await wait(2200)
  for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, 260); await wait(200) }
  await wait(1200)
}

await caption('Search on the map', 'dot size = how close each article is to the search', 300)
await type('.search input', 'sisällissota')
await page.keyboard.press('Enter')
await page.waitForFunction(() => /^60 articles/.test(document.querySelector('.maplegend .small.muted')?.innerText || ''))
await wait(2200)
{
  const box = await page.locator('.mapcanvas').boundingBox()
  const p = await page.evaluate(() => { const k = window.__map.marks.find((m) => m.items.some((a) => a.id === 'Q211855')); return { x: k.sx, y: k.sy } })
  await caption('Click a blob to list its articles', '', 300)
  await moveTo(box.x + p.x, box.y + p.y, 900); await wait(900)
  await page.mouse.down(); await wait(80); await page.mouse.up()
  await page.waitForSelector('.bloblist li'); await wait(1800)
}
await caption('Pick one: lines to its 10 most similar articles', 'VEC_DISTANCE on the article vectors, ~30 ms in MariaDB', 300)
await click('.bloblist button:has-text("Suomen sisällissota")')
await page.waitForSelector('.simlist li'); await wait(4200)
await moveToEl('.simlist li:nth-child(1) a', { ms: 700 }); await wait(1200)
await moveToEl('.mapcard .title', { ms: 700 }); await wait(800)
await caption('The name opens the article page', '', 300)
await click('.mapcard .title')
await page.waitForSelector('.cmprow .cell'); await wait(1800)

await caption('AikaKone', 'MariaDB vector search + system-versioned tables · Gemma and bge-m3 on Verda · Junction 2026', 4500)
await caption('')
await wait(600)

const video = page.video()
await context.close()
await browser.close()
copyFileSync(await video.path(), OUT)
rmSync(TMP, { recursive: true, force: true })
console.log('saved', OUT)
