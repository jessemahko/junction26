import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useSql } from './SqlDrawer.jsx'

// Comparison view: fi | sv | en aligned sentence by sentence (GET /api/compare/{wikidata_id},
// docs/contracts.md c). Each sv / en cell is coloured by how it relates to the Finnish sentence:
// match, partial, framing, contradiction (Gemma's labels) or missing (no match above the threshold).
// Click a row to see what to fix and open that language's Wikipedia editor. A human makes the edit.
const LANGS = ['fi', 'sv', 'en']
const LANG_NAME = { fi: 'Finnish', sv: 'Swedish', en: 'English' }

export const STATUS = {
  match: { label: 'Match', help: 'Same claim in both languages' },
  partial: { label: 'Partial', help: 'One sentence says only part of what the other says' },
  framing: { label: 'Framing', help: 'Same fact, told with a different slant or tone' },
  contradiction: { label: 'Possible contradiction', help: 'Gemma thinks the two disagree on a fact (a number, date or name). Check the sources: about half of single-model flags are false alarms' },
  missing: { label: 'Missing', help: 'No sentence in this language matches (distance above the threshold)' },
}
const SEVERITY = ['contradiction', 'framing', 'missing', 'partial', 'match']

// The sv / en sentence shown for a Finnish sentence: its aligned partner, else the sentence that covers
// it (nearest within the threshold, not one-to-one: e.g. one English sentence saying what two Finnish do).
const cellOf = (row, lang) => row[lang] || (lang !== 'fi' && row.fi ? row.covered_by?.[lang] : null) || null
// Judgements of this cell's pair, one per model; the API sorts "both models agree" and the most
// serious label first.
const judgementsOf = (row, lang) => (row.judgements || []).filter((x) => x.lang === lang)

// The status of one cell. Finnish is the reference column, so it is coloured only when it is missing.
function cellStatus(row, lang) {
  if (lang === 'fi') return row.fi ? null : 'missing'
  if (!cellOf(row, lang)) return row.fi ? 'missing' : null // only_sv rows: the en cell is simply empty
  if (!row.fi) return null // the sentence that exists only here
  const j = judgementsOf(row, lang)[0]
  if (!j || j.label === 'same') return 'match'
  return STATUS[j.label] ? j.label : 'match'
}

function rowStatus(row) {
  const all = LANGS.map((l) => cellStatus(row, l)).filter(Boolean)
  return SEVERITY.find((s) => all.includes(s)) || 'match'
}

export default function Compare({ wikidataId, onBack, onHistory, embedded = false, preloaded = null }) {
  const [res, setRes] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all')
  const [sel, setSel] = useState(null)

  useEffect(() => {
    setSel(null)
    if (preloaded) { setRes(preloaded); return }       // the article page fetched it already
    setRes(null)
    api.compare(wikidataId).then(setRes).catch((e) => setError(e.message))
  }, [wikidataId, preloaded])

  const counts = useMemo(() => {
    const c = { all: 0, problems: 0 }
    for (const r of res?.rows || []) {
      const s = rowStatus(r)
      c.all++; c[s] = (c[s] || 0) + 1
      if (s !== 'match') c.problems++
    }
    return c
  }, [res])
  useSql(res ? [{ label: 'Compare fi / sv / en', sql: res.sql, ms: res.ms }] : [], [res])

  if (!res) return <div className="panel muted">{error ? `API error: ${error}` : 'Loading…'}</div>
  const { topic, scores, rows } = res
  const openRow = (i) => {
    setFilter('all'); setSel(i)
    setTimeout(() => document.getElementById(`row-${i}`)?.scrollIntoView({ block: 'start' }), 0)
  }
  const shown = rows.map((r, i) => ({ r, i })).filter(({ r }) => {
    const s = rowStatus(r)
    return filter === 'all' || (filter === 'problems' ? s !== 'match' : s === filter)
  })

  return (
    <div className="compare">
      {onBack && <button className="btn ghost back" onClick={onBack}>← Worklist</button>}

      <div className="panel cmphead">
        {!embedded && <div className="cmptitle">
          <h2>{topic.titles.fi}</h2>
          <span className="muted small">{topic.wikidata_id}</span>
          {onHistory && <button className="btn sm" onClick={() => onHistory(topic)} title="Kristian's views of the Finnish article: edit wars, contested sentences, any date">Finnish edit history →</button>}
        </div>}
        {!embedded && <div className="dists">
          {[['fi_sv', 'fi ↔ sv'], ['fi_en', 'fi ↔ en'], ['sv_en', 'sv ↔ en']].map(([k, l]) => (
            <span key={k} title="Whole-article cosine distance (bge-m3): 0 = same, higher = more different"><small>{l}</small><b>{scores?.[k] != null ? scores[k].toFixed(3) : '—'}</b></span>
          ))}
        </div>}
        <div className="filters">
          {[['all', 'All'], ['problems', 'Needs an editor'], ...SEVERITY.filter((s) => s !== 'match').map((s) => [s, STATUS[s].label]), ['match', 'Match']].map(([k, l]) => (
            <button key={k} className={`chip ${k} ${filter === k ? 'on' : ''}`} onClick={() => setFilter(k)} disabled={!counts[k]}>
              {l} <small>{counts[k] || 0}</small>
            </button>
          ))}
        </div>
      </div>

      <Contradictions items={res.contradictions || []} onOpen={openRow} />

      <div className="cmpgrid">
        <div className="cmprow cmpcols">
          <div className="stripe" />
          {LANGS.map((l) => (
            <div key={l} className="colhead">
              <div>
                <span className="lang">{l}</span>
                <a href={topic.urls[l]} target="_blank" rel="noreferrer">{topic.titles[l]}</a>
              </div>
              <a className="btn sm" href={topic.edit_urls[l]} target="_blank" rel="noreferrer"
                 title={`Open the ${LANG_NAME[l]} article in Wikipedia's editor. You make the edit.`}>Edit in Wikipedia ↗</a>
            </div>
          ))}
        </div>
        {shown.map(({ r, i }) => (
          <React.Fragment key={i}>
            <div id={`row-${i}`} className={`cmprow ${sel === i ? 'sel' : ''}`} onClick={() => setSel(sel === i ? null : i)}>
              <div className={`stripe ${rowStatus(r)}`} title={STATUS[rowStatus(r)].label} />
              {LANGS.map((l) => <Cell key={l} row={r} lang={l} />)}
            </div>
            {sel === i && <FixPanel row={r} topic={topic} />}
          </React.Fragment>
        ))}
        {shown.length === 0 && <p className="muted" style={{ padding: 12 }}>{res.note ? 'Sentence data is not computed for this article yet.' : 'No rows with this status.'}</p>}
      </div>

      <div className="legend cmplegend">
        {SEVERITY.slice().reverse().map((s) => <span key={s} title={STATUS[s].help}><i className={`sw ${s}`} />{STATUS[s].label}</span>)}
        <span>· hover a sentence for Gemma's reason · click a row to fix it</span>
      </div>
    </div>
  )
}

function Cell({ row, lang }) {
  const s = cellStatus(row, lang)
  const c = cellOf(row, lang)
  const covered = c && !row[lang]
  const js = lang !== 'fi' ? judgementsOf(row, lang) : []
  const j = js[0]

  if (!c) {
    if (!s) return <div className="cell empty" />
    const from = LANGS.filter((l) => l !== lang && cellOf(row, l)).join(' / ')
    return <div className="cell missing"><span className="gap">Missing in {LANG_NAME[lang]}{from ? ` (present in ${from})` : ''}</span></div>
  }
  return (
    <div className={`cell ${s || ''} ${covered ? 'covered' : ''}`}>
      <span className="txt">{c.text}</span>
      <span className="meta">
        {s && s !== 'match' && <span className={`stag ${s}`}>{STATUS[s].label}</span>}
        {j?.both_models_agree && <span className="stag agree" title={js.map((x) => x.model).join(' + ')}>both models agree</span>}
        {covered && <span title="Not a one-to-one pair: this is the nearest sentence, and it may also cover other Finnish sentences">covers it</span>}
        {c.distance != null && <span title="Cosine distance to the Finnish sentence">d {c.distance.toFixed(3)}</span>}
        {!row.fi && <span>no Finnish match</span>}
      </span>
      {lang !== 'fi' && row.fi && (
        <span className="tip">
          {js.length ? js.map((x) => (
            <React.Fragment key={x.model}>
              <b>{x.label === 'same' ? 'Same claim' : STATUS[x.label]?.label || x.label}</b> — {x.reason}<small>{x.model}</small>
            </React.Fragment>))
             : (<><b>Not judged in the demo</b> — matched by embedding only (distance {c.distance?.toFixed(3)}). For the demo, Gemma judged the 301 most urgent articles.</>)}
        </span>
      )}
    </div>
  )
}

// What an editor would do with this row: the sentences to compare and a link to the right editor.
function FixPanel({ row, topic }) {
  const tasks = []
  for (const l of LANGS) {
    const s = cellStatus(row, l)
    if (!s || s === 'match') continue
    const js = judgementsOf(row, l)
    const j = js[0]
    if (s === 'missing') {
      const src = LANGS.filter((o) => o !== l && cellOf(row, o))
      tasks.push({ key: l, kind: s, title: `${LANG_NAME[l]} does not have this`, edit: [l], refs: src.map((o) => [o, cellOf(row, o).text]) })
    } else {
      tasks.push({ key: l, kind: s, title: s === 'contradiction' ? (j?.note || `Possible contradiction, check the sources`) + ` (Finnish vs ${LANG_NAME[l]})` : `Finnish and ${LANG_NAME[l]} tell it differently`,
                   reason: j?.reason, model: js.map((x) => x.model).join(' + '), edit: ['fi', l], refs: [['fi', row.fi.text], [l, cellOf(row, l).text]] })
    }
  }
  if (!tasks.length) return <div className="fix"><p className="muted">All three versions agree here. Nothing to fix.</p></div>

  return (
    <div className="fix">
      {tasks.map((t) => (
        <div key={t.key} className={`task ${t.kind}`}>
          <h4><span className={`stag ${t.kind}`}>{STATUS[t.kind].label}</span> {t.title}</h4>
          {t.reason && <p className="reason">{t.reason} <small>explained by {t.model}</small></p>}
          <ul className="refs">
            {t.refs.map(([l, text]) => (
              <li key={l}><span className="lang">{l}</span><span className="txt">{text}</span>
                <button className="btn sm" onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(text) }} title="Copy, to quote or translate it yourself">Copy</button></li>
            ))}
          </ul>
          <div className="editbtns">
            {t.edit.map((l) => (
              <a key={l} className={`btn sm ${l === t.edit[t.edit.length - 1] ? 'primary' : ''}`} href={topic.edit_urls[l]} target="_blank" rel="noreferrer">
                Edit {LANG_NAME[l]} Wikipedia ↗
              </a>
            ))}
          </div>
        </div>
      ))}
      <p className="muted small">Opens Wikipedia's own editor. You write the edit and cite a source; this tool never edits Wikipedia.</p>
    </div>
  )
}

// Gemma's possible contradictions for this topic (top-level `contradictions` of /api/compare): the ones
// both models agree on first. Click one to jump to its row.
function Contradictions({ items, onOpen }) {
  if (!items.length) return null
  const agreed = items.filter((c) => c.both_models_agree).length
  return (
    <div className="panel contras">
      <h3>Possible contradictions <small className="muted">{items.length} · {agreed} where both models agree · check the sources before editing</small></h3>
      <ol>
        {items.map((c) => (
          <li key={`${c.row}-${c.lang}`} className={c.both_models_agree ? 'agree' : ''} onClick={() => onOpen(c.row)}>
            {c.both_models_agree && <span className="stag agree">both models agree</span>}
            <span className="lang">fi</span><span className="claim">{c.fi_claim || c.fi.text}</span>
            <span className="vs">vs</span>
            <span className="lang">{c.lang}</span><span className="claim">{c.other_claim || c.other.text}</span>
            <small className="muted">{c.models.map((m) => m.replace('google/', '')).join(' + ')}</small>
          </li>
        ))}
      </ol>
    </div>
  )
}
