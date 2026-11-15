import React, { useEffect, useState } from 'react'
import { api, fmtDate, wikiRev } from '../api.js'

// V3 — sentences that were removed and came back (A→B→A), ranked by number of lives.
// One GROUP BY ... HAVING COUNT(*) > 1 over FOR SYSTEM_TIME ALL.
export default function EditWars({ article, onJump }) {
  const [wars, setWars] = useState(null)
  const [open, setOpen] = useState(null)
  const [hideAnon, setHideAnon] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { api.editWars(article.page_id, 40).then(setWars).catch((e) => setError(e.message)) }, [article.page_id])
  if (!wars) return <div className="panel muted">{error || 'Loading…'}</div>

  const t0 = Date.parse(article.first_rev)
  const span = Date.now() - t0
  const pct = (iso) => (((iso ? Date.parse(iso) : Date.now()) - t0) / span) * 100

  // "Vandalism cleanup" = every removal was of an anonymous edit's sentence or by anonymous users.
  const isCleanup = (w) => w.periods.every((p) => p.anonymous || p.removed_by_anonymous || !p.to)
  const shown = hideAnon ? wars.filter((w) => !isCleanup(w)) : wars

  return (
    <div className="panel">
      <div className="legend" style={{ marginBottom: 8, justifyContent: 'space-between' }}>
        <span>{shown.length} sentences that left and came back · bar = when each life was in the article ({article.first_rev?.slice(0, 4)} → today)</span>
        <label><input type="checkbox" checked={hideAnon} onChange={(e) => setHideAnon(e.target.checked)} /> hide anonymous-only (vandalism cleanup)</label>
      </div>
      {shown.length === 0 && <p className="muted">No edit wars at sentence level.</p>}
      {shown.map((w) => (
        <div className="war" key={w.hash}>
          <div className="head" onClick={() => setOpen(open === w.hash ? null : w.hash)}>
            <div className="lives">{w.lives}<small>lives</small></div>
            <div className="text">{w.text}</div>
          </div>
          <div className="lifebar">
            {w.periods.map((p, i) => (
              <span key={i} style={{ left: `${pct(p.from)}%`, width: `${Math.max(0.3, pct(p.to) - pct(p.from))}%` }}
                    title={`${fmtDate(p.from)} → ${p.to ? fmtDate(p.to) : 'now'}`} />
            ))}
          </div>
          {open === w.hash && (
            <table className="periods">
              <thead><tr><th>In the article</th><th>Added by</th><th>Removed by</th><th>Edit summary</th><th /></tr></thead>
              <tbody>
                {w.periods.map((p, i) => (
                  <tr key={i}>
                    <td>{fmtDate(p.from)} → {p.to ? fmtDate(p.to) : 'now'}</td>
                    <td className={p.anonymous ? 'anon' : ''}><a href={wikiRev(p.rev_id)} target="_blank" rel="noreferrer">{p.editor || '—'}</a></td>
                    <td className={p.removed_by_anonymous ? 'anon' : ''}>{p.removed_rev ? <a href={wikiRev(p.removed_rev)} target="_blank" rel="noreferrer">{p.removed_by || '—'}</a> : '—'}</td>
                    <td className="muted">{p.removed_comment?.slice(0, 90)}</td>
                    <td>{p.to && <button className="btn sm" title="Open the article at this moment in the time slider, with this round of changes highlighted" onClick={() => onJump({ from: p.from, to: p.to })}>View →</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  )
}
