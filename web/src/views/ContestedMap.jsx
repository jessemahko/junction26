import React, { useEffect, useState } from 'react'
import { api, fmtDate } from '../api.js'

// V2 — today's article, every sentence heat-coloured by how contested it has been:
// rewrites (length of its rewrite chain, recursive CTE over history) + returns (lives - 1).
// Click a sentence: its genealogy, every earlier wording it replaced.
export const heat = (s) => s.rewrites + 2 * (s.lives - 1)
const LEVELS = [0, 1, 3, 6, 12, 25]
const level = (h) => LEVELS.filter((l) => h >= l).length - 1

export default function ContestedMap({ article }) {
  const [rows, setRows] = useState(null)
  const [sel, setSel] = useState(null)
  const [chain, setChain] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { api.contested(article.page_id).then(setRows).catch((e) => setError(e.message)) }, [article.page_id])
  useEffect(() => {
    if (!sel) return
    setChain(null)
    api.sentenceHistory(article.page_id, sel.hash).then(setChain).catch((e) => setError(e.message))
  }, [sel?.hash])

  if (!rows) return <div className="panel muted">{error || 'Loading…'}</div>
  const top = [...rows].sort((a, b) => heat(b) - heat(a)).slice(0, 5)

  return (
    <div className="grid2">
      <div className="panel">
        <div className="legend" style={{ marginBottom: 12 }}>
          <span>How fought-over:</span>
          {LEVELS.map((l, i) => (
            <span key={l}><i style={{ background: `var(--heat-${i})`, border: '1px solid var(--line)' }} />{i === 0 ? 'never' : `≥${l}`}</span>
          ))}
          <span>· score = rewrites + 2 × returns</span>
        </div>
        <div className="prose">
          {rows.map((s) => (
            <span key={s.hash} className={`s click ${sel?.hash === s.hash ? 'sel' : ''}`}
                  style={{ background: `var(--heat-${level(heat(s))})` }}
                  title={`${s.rewrites} rewrites · ${s.lives} lives · since ${fmtDate(s.since)}`}
                  onClick={() => setSel(s)}>{s.text} </span>
          ))}
        </div>
      </div>
      <div className="panel">
        {!sel && (
          <>
            <h3>Most contested sentences</h3>
            <ol className="chain">
              {top.map((s) => (
                <li key={s.hash} onClick={() => setSel(s)} style={{ cursor: 'pointer' }}>
                  {s.text.slice(0, 140)}{s.text.length > 140 ? '…' : ''}
                  <span className="when">{s.rewrites} rewrites · {s.lives} lives</span>
                </li>
              ))}
            </ol>
            <p className="muted small">Click any sentence to see every earlier version of it.</p>
          </>
        )}
        {sel && (
          <>
            <h3>How this sentence was written</h3>
            <p className="small muted">{sel.rewrites} rewrites · {sel.lives} lives · first seen {fmtDate(sel.first_seen)}</p>
            {!chain && <p className="muted">Loading…</p>}
            {chain && (
              <ol className="chain">
                {chain.map((c, i) => (
                  <li key={i}>
                    <span className="when">
                      {fmtDate(c.from)} → {c.to ? fmtDate(c.to) : 'now'} · <span className={c.anonymous ? 'anon' : ''}>{c.editor}</span>
                      {c.tone && c.tone !== 'neutral' && <span className={`pill ${c.tone}`}>{c.tone}</span>}
                      {c.event_name && <span className="pill">{c.event_name}</span>}
                    </span>
                    {c.text}
                  </li>
                ))}
              </ol>
            )}
            <button className="btn ghost back" onClick={() => setSel(null)} title="Back to the most contested sentences">← All sentences</button>
          </>
        )}
      </div>
    </div>
  )
}
