import React, { useMemo, useState } from 'react'
import { useSql } from './SqlDrawer.jsx'

// Landing: "Articles that need an editor's attention". One row per topic that exists in Finnish,
// Swedish and English (GET /api/topics). Click a column to sort, a row to open the article page.
const PAGE = 50

const missShare = (r, l) => (r.sentences?.fi && r[`missing_${l}`] != null ? r[`missing_${l}`] / r.sentences.fi : null)

const COLS = [
  { key: 'similarity', label: 'Match', semantic: true,
    title: 'How close the article is to your search: cosine similarity of the bge-m3 vectors',
    value: (r) => r.similarity },
  { key: 'language', label: 'Language difference',
    title: 'How differently the Swedish and English versions tell it (whole-article bge-m3 distance to the Finnish one). Sorted by the length-adjusted distance',
    value: (r) => r.parts?.distance ?? (r.fi_sv + r.fi_en) / 2 },
  { key: 'missing', label: 'Missing content',
    title: 'Share of Finnish sentences with no counterpart (nothing closer than 0.418) in Swedish / English. Sorted by the length-adjusted share',
    value: (r) => r.parts?.missing ?? null },
  { key: 'contradictions', label: 'Possible contradictions',
    title: 'Sentence pairs Gemma judged to disagree on a fact (a number, date, name). “agree” = two models agree. Always check the sources',
    value: (r) => (r.contradictions == null ? null : r.contradictions + 1000 * (r.contradictions_agreed || 0)) },
  { key: 'edit_war', label: 'Edit wars',
    title: 'Edit-war activity in the Finnish history: reverts, and sentences that were removed and came back (0–1)',
    value: (r) => r.edit_war_score },
  { key: 'score', label: 'Score',
    title: 'How much the article needs an editor: 30 % language difference + 30 % missing content + 40 % edit wars (each as a percentile, length-adjusted)',
    value: (r) => r.score },
]

export default function ArticleList({ res, filter, onOpen }) {
  const semantic = !!(filter.q && filter.mode === 'meaning')
  const [sort, setSort] = useState(null)        // {key, dir}; null = the server's order
  const [shown, setShown] = useState(PAGE)
  useSql(res ? res.sql.map((s) => ({ ...s, ms: res.ms })) : [], [res])

  const cols = COLS.filter((c) => !c.semantic || semantic)
  const rows = useMemo(() => {
    const list = [...(res?.data || [])]
    if (!sort) return list
    const col = COLS.find((c) => c.key === sort.key)
    const val = sort.key === 'title' ? (r) => r.titles.fi : col.value
    return list.sort((a, b) => {
      const x = val(a), y = val(b)
      if (x == null && y == null) return 0
      if (x == null) return 1
      if (y == null) return -1
      return (typeof x === 'string' ? x.localeCompare(y, 'fi') : x - y) * sort.dir
    })
  }, [res, sort])

  if (!res) return <div className="panel muted">Loading the worklist…</div>
  // the answer for an earlier filter, while the new one is on its way
  const stale = res.filter && (res.filter.q !== filter.q || (res.filter.chip || '') !== filter.chip || (filter.q && res.filter.mode !== filter.mode))
  const head = (key, label, title) => {
    const on = sort?.key === key
    return (
      <th key={key} title={title} className={on ? 'sorted' : ''}
          onClick={() => setSort({ key, dir: on ? -sort.dir : key === 'title' ? 1 : -1 })}>
        {label}<span className="arrow">{on ? (sort.dir < 0 ? '▼' : '▲') : ''}</span>
      </th>
    )
  }

  return (
    <div className={`panel worklist2 ${stale ? 'stale' : ''}`}>
      <div className="listhead">
        <h2>Articles that need an editor's attention</h2>
        <p className="muted small">
          {semantic ? <>Closest to “{filter.q}” first. </> : <>Highest score first. </>}
          The Finnish, Swedish and English versions of each article compared sentence by sentence: how differently they
          tell it, what is missing, where Gemma found possible contradictions, and how much the Finnish article was fought
          over. Click an article to see the three versions side by side.
        </p>
      </div>
      {rows.length === 0 && <p className="muted">No articles match. Try another word, or search by {filter.mode === 'meaning' ? 'title' : 'meaning'}.</p>}
      {rows.length > 0 && (
        <table className="wl2">
          <thead>
            <tr>
              <th className="rank" title="Rank in the whole worklist">#</th>
              {head('title', 'Article', 'Finnish title, English title below')}
              {cols.map((c) => head(c.key, c.label, c.title))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, shown).map((r, i) => (
              <tr key={r.wikidata_id} onClick={() => onOpen(r.wikidata_id)} title={`Open “${r.titles.fi}”`}>
                <td className="rank">{r.rank ?? '—'}</td>
                <td className="art">
                  <a href={`#/article/${r.wikidata_id}/languages`} onClick={(e) => e.preventDefault()}>{r.titles.fi}</a>
                  <small>{r.titles.en}{r.titles.sv !== r.titles.fi && r.titles.sv !== r.titles.en ? ` · ${r.titles.sv}` : ''}</small>
                </td>
                {semantic && <td><Bar v={r.similarity} max={1} min={0.3} text={r.similarity?.toFixed(2)} tone="sim" /></td>}
                <td>
                  <Pair a={['sv', r.fi_sv]} b={['en', r.fi_en]} fmt={(v) => v.toFixed(2)} max={0.5} />
                </td>
                <td>
                  {missShare(r, 'en') == null ? <span className="muted">—</span> :
                    <Pair a={['sv', missShare(r, 'sv')]} b={['en', missShare(r, 'en')]} fmt={(v) => `${Math.round(v * 100)} %`} max={1}
                          title={`Finnish sentences missing: ${r.missing_sv} in Swedish, ${r.missing_en} in English (of ${r.sentences.fi})`} />}
                </td>
                <td className="contra">
                  {r.contradictions == null ? <span className="muted small" title="For the demo, Gemma (on Verda) judged the 301 most urgent articles. The rest can be judged the same way.">not judged in demo</span> : (
                    <>
                      <b className={r.contradictions ? 'n' : 'zero'} title={`Gemma judged ${r.judged_pairs} sentence pairs`}>{r.contradictions}</b>
                      {r.contradictions_agreed > 0 && <span className="agreebadge" title="Two models (Gemma 27B and 12B) agree on these">{r.contradictions_agreed} agree</span>}
                    </>
                  )}
                </td>
                <td><Bar v={r.edit_war_score} max={1} text={r.edit_war_score?.toFixed(2)} tone="war" /></td>
                <td><Bar v={r.score} max={1} text={r.score?.toFixed(2)} tone="score" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rows.length > shown && (
        <button className="btn block more" onClick={() => setShown(shown + PAGE * 2)}>
          Show more <small>{(rows.length - shown).toLocaleString()} more articles</small>
        </button>
      )}
    </div>
  )
}

function Bar({ v, max, min = 0, text, tone }) {
  if (v == null) return <span className="muted">—</span>
  const pct = Math.max(2, Math.min(100, ((v - min) / (max - min)) * 100))
  return (
    <span className={`bar2 ${tone || ''}`}>
      <span className="track"><span className="fill" style={{ width: `${pct}%` }} /></span>
      <span className="num">{text}</span>
    </span>
  )
}

function Pair({ a, b, fmt, max, title }) {
  return (
    <span className="pair" title={title}>
      {[a, b].map(([l, v]) => (
        <span key={l} className="pr">
          <span className="lang">{l}</span>
          <span className="track"><span className="fill" style={{ width: `${Math.min(100, (v / max) * 100)}%` }} /></span>
          <span className="num">{v == null ? '—' : fmt(v)}</span>
        </span>
      ))}
    </span>
  )
}
