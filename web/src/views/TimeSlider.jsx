import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtDate, wikiRev } from '../api.js'

// V1 — the article as it was at any moment, and what changed since an earlier moment.
// Powered by FOR SYSTEM_TIME AS OF (as-of) and two AS OF snapshots anti-joined (diff).
export default function TimeSlider({ article, focus }) {
  const [revs, setRevs] = useState([])
  const [toIdx, setToIdx] = useState(null)
  const [fromIdx, setFromIdx] = useState(null)
  const [snap, setSnap] = useState(null)
  const [diff, setDiff] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.revisions(article.page_id).then((r) => {
      setRevs(r)
      setToIdx(r.length - 1)
    }).catch((e) => setError(e.message))
  }, [article.page_id])

  // Hero moment: another view hands over a {from, to} range.
  useEffect(() => {
    if (!focus || !revs.length) return
    const idxAt = (iso) => {
      let i = 0
      while (i + 1 < revs.length && revs[i + 1].timestamp <= iso) i++
      return i
    }
    setToIdx(idxAt(focus.to))
    setFromIdx(focus.from ? idxAt(focus.from) : null)
  }, [focus, revs])

  const toRev = revs[toIdx]
  const fromRev = fromIdx != null ? revs[fromIdx] : null

  // `stale` guards: a slow older response (e.g. today's 1,000-sentence article) must not
  // overwrite a newer one when the slider moves quickly or another view jumps here.
  useEffect(() => {
    if (!toRev) return
    let stale = false
    setError(null)
    api.asOf(article.page_id, toRev.timestamp)
      .then((s) => !stale && setSnap(s)).catch((e) => !stale && setError(e.message))
    return () => { stale = true }
  }, [article.page_id, toRev?.timestamp])

  useEffect(() => {
    if (!toRev || !fromRev) { setDiff(null); return }
    let stale = false
    api.diff(article.page_id, fromRev.timestamp, toRev.timestamp)
      .then((d) => !stale && setDiff(d)).catch((e) => !stale && setError(e.message))
    return () => { stale = true }
  }, [article.page_id, toRev?.timestamp, fromRev?.timestamp])

  const added = useMemo(() => new Set((diff?.added || []).map((s) => s.hash)), [diff])

  // Bitemporal filter: sentences about events in years [yFrom, yTo] (application time),
  // as the article stood at the slider's moment (system time).
  const [yFrom, setYFrom] = useState('')
  const [yTo, setYTo] = useState('')
  const [about, setAbout] = useState(null)
  useEffect(() => {
    const a = parseInt(yFrom, 10), b = parseInt(yTo || yFrom, 10)
    if (!toRev || !(a >= 1000) || !(b >= a)) { setAbout(null); return }
    let stale = false
    api.about(article.page_id, toRev.timestamp, a, b)
      .then((r) => !stale && setAbout(new Set(r.map((s) => s.hash)))).catch(() => !stale && setAbout(null))
    return () => { stale = true }
  }, [article.page_id, toRev?.timestamp, yFrom, yTo])

  if (!revs.length) return <div className="panel muted">{error || 'Loading revisions…'}</div>

  return (
    <div className="grid2">
      <div className="panel">
        <Activity revs={revs} toIdx={toIdx} fromIdx={fromIdx} onPick={setToIdx} />
        <div className="sliders">
          <label>
            <span>Show as of</span>
            <input type="range" min={0} max={revs.length - 1} value={toIdx ?? 0}
                   onChange={(e) => setToIdx(+e.target.value)} />
            <b>{fmtDate(toRev?.timestamp)}</b>
          </label>
          <label>
            <span>
              <input type="checkbox" checked={fromIdx != null}
                     onChange={(e) => setFromIdx(e.target.checked ? Math.max(0, (toIdx ?? 0) - 1) : null)} />
              {' '}Compare with
            </span>
            <input type="range" min={0} max={revs.length - 1} value={fromIdx ?? 0} disabled={fromIdx == null}
                   onChange={(e) => setFromIdx(+e.target.value)} />
            <b>{fromRev ? fmtDate(fromRev.timestamp) : '—'}</b>
          </label>
          <label>
            <span>About events in</span>
            <span className="years">
              <input type="number" placeholder="1917" value={yFrom} onChange={(e) => setYFrom(e.target.value)} />
              –
              <input type="number" placeholder="1918" value={yTo} onChange={(e) => setYTo(e.target.value)} />
            </span>
            <b>{about ? `${about.size} sentences` : ''}</b>
          </label>
        </div>
        {snap && (
          <div className="revmeta">
            <span>Revision <a href={wikiRev(snap.rev_id)} target="_blank" rel="noreferrer">{snap.rev_id}</a></span>
            <span>by <b className={snap.anonymous ? 'anon' : ''}>{snap.editor || '—'}</b></span>
            {snap.comment && <span>“{snap.comment.slice(0, 120)}”</span>}
            <span>{snap.sentences.length} sentences</span>
            {diff && <span><b style={{ color: 'var(--add-ink)' }}>+{diff.added.length}</b> / <b style={{ color: 'var(--del-ink)' }}>−{diff.removed.length}</b> / {diff.kept} kept</span>}
          </div>
        )}
        {error && <p className="err">{error}</p>}
        <div className="prose">
          {snap?.sentences.map((s) => (
            <span key={s.hash} className={`s ${added.has(s.hash) ? 'add' : ''} ${about && !about.has(s.hash) ? 'dim' : ''}`}
                  title={`since ${fmtDate(s.since)} · ${s.editor || ''}`}>{s.text} </span>
          ))}
        </div>
      </div>
      <div className="panel">
        <h3>Removed since {fromRev ? fmtDate(fromRev.timestamp) : '…'}</h3>
        {!diff && <p className="muted small">Tick “Compare with” to see what was added (green) and removed (red) between two moments.</p>}
        {diff && diff.removed.length === 0 && <p className="muted small">Nothing removed.</p>}
        {diff && (
          <div className="removed"><ul>{diff.removed.map((s) => <li key={s.hash}>{s.text}</li>)}</ul></div>
        )}
      </div>
    </div>
  )
}

// Edits per month (bars) with reverts (red), the shown moment as a line. Click = jump there.
function Activity({ revs, toIdx, fromIdx, onPick }) {
  const { months, max, first, span } = useMemo(() => {
    const m = new Map()
    for (const r of revs) {
      const k = r.timestamp.slice(0, 7)
      const e = m.get(k) || { edits: 0, reverts: 0 }
      e.edits++; if (r.is_revert) e.reverts++
      m.set(k, e)
    }
    const t0 = Date.parse(revs[0].timestamp)
    const t1 = Date.now()
    return { months: [...m.entries()], max: Math.max(...[...m.values()].map((e) => e.edits)), first: t0, span: t1 - t0 }
  }, [revs])
  const x = (iso) => ((Date.parse(iso) - first) / span) * 1000
  const W = 1000, H = 54
  const pick = (e) => {
    const box = e.currentTarget.getBoundingClientRect()
    const t = first + ((e.clientX - box.left) / box.width) * span
    let i = 0
    while (i + 1 < revs.length && Date.parse(revs[i + 1].timestamp) <= t) i++
    onPick(i)
  }
  return (
    <>
      <svg className="activity" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" onClick={pick}>
        {months.map(([k, e]) => {
          const h = (Math.sqrt(e.edits) / Math.sqrt(max)) * (H - 6)
          const hr = (Math.sqrt(e.reverts) / Math.sqrt(max)) * (H - 6)
          return (
            <g key={k}>
              <rect x={x(k + '-01')} y={H - h} width={3} height={h} fill="var(--muted)" opacity={0.45} />
              {e.reverts > 0 && <rect x={x(k + '-01')} y={H - hr} width={3} height={hr} fill="var(--del-ink)" />}
            </g>
          )
        })}
        {fromIdx != null && revs[fromIdx] && <line x1={x(revs[fromIdx].timestamp)} x2={x(revs[fromIdx].timestamp)} y1={0} y2={H} stroke="var(--muted)" strokeDasharray="3 3" strokeWidth={2} />}
        {revs[toIdx] && <line x1={x(revs[toIdx].timestamp)} x2={x(revs[toIdx].timestamp)} y1={0} y2={H} stroke="var(--accent)" strokeWidth={3} />}
      </svg>
      <div className="legend" style={{ marginBottom: 12 }}>
        <span><i style={{ background: 'var(--muted)', opacity: 0.45 }} />edits per month</span>
        <span><i style={{ background: 'var(--del-ink)' }} />reverts</span>
        <span>{revs[0].timestamp.slice(0, 4)} → today · click to jump</span>
      </div>
    </>
  )
}
