import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useSql } from './SqlDrawer.jsx'
import Compare from './Compare.jsx'
import EditWars from './EditWars.jsx'
import ContestedMap from './ContestedMap.jsx'
import TimeSlider from './TimeSlider.jsx'

// One article: "Languages" = Finnish, Swedish and English side by side (possible contradictions on top,
// the ones both models agree on first); "Edit wars" = Kristian's views of the Finnish article's history
// (system-versioned sentences): sentences that were fought over, how contested each sentence is, and
// the article as of any date.
const TABS = [
  { id: 'languages', label: 'Languages', help: 'Finnish, Swedish and English, sentence by sentence' },
  { id: 'edits', label: 'Edit wars', help: 'The Finnish article’s history: what editors fought over' },
]
const HISTORY = [
  { id: 'wars', label: 'Edit wars', queries: ['edit_wars'],
    help: 'Sentences that were removed and came back, most-fought first. Click one for each round: who added it, who removed it and why.' },
  { id: 'contested', label: 'Contested sentences', queries: ['contested', 'sentence_history'],
    help: 'Today’s text, each sentence coloured by how often it was rewritten or removed and restored. Click a sentence for its earlier wordings.' },
  { id: 'asof', label: 'Article on a date', queries: ['as_of_sentences', 'diff', 'revisions'],
    help: 'The article as it was on any date (FOR SYSTEM_TIME AS OF); tick “Compare with” to see what changed between two dates.' },
]

export default function ArticlePage({ id, tab, filter, onTab }) {
  const [cmp, setCmp] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    setCmp(null); setError(null)
    api.compare(id).then(setCmp).catch((e) => setError(e.message))
  }, [id])

  const back = `#/list${filter.q || filter.chip ? `?${new URLSearchParams({ ...(filter.q && { q: filter.q }), ...(filter.q && filter.mode !== 'meaning' && { mode: filter.mode }), ...(filter.chip && { chip: filter.chip }) })}` : ''}`
  const t = cmp?.topic
  return (
    <div className="articlepage">
      <nav className="crumbs">
        <a href={back}>Articles{filter.q ? ` · “${filter.q}”` : ''}</a>
        <span>›</span>
        <b>{t ? t.titles.fi : id}</b>
      </nav>
      {error && <p className="err">API error: {error}</p>}
      {t && (
        <header className="arthead">
          <div>
            <h2>{t.titles.fi}</h2>
            <div className="alt">
              <span><i className="lang">sv</i> {t.titles.sv}</span>
              <span><i className="lang">en</i> {t.titles.en}</span>
              <span className="muted">{t.wikidata_id}</span>
            </div>
          </div>
          <div className="dists">
            {[['fi_sv', 'fi ↔ sv'], ['fi_en', 'fi ↔ en'], ['sv_en', 'sv ↔ en']].map(([k, l]) => (
              <span key={k} title="Whole-article cosine distance (bge-m3): 0 = the same, higher = more different">
                <small>{l}</small><b>{cmp.scores?.[k] != null ? cmp.scores[k].toFixed(3) : '—'}</b>
              </span>
            ))}
          </div>
        </header>
      )}
      <nav className="arttabs">
        {TABS.map((x) => (
          <a key={x.id} href={`#/article/${id}/${x.id}`} className={tab === x.id ? 'on' : ''} title={x.help}
             onClick={(e) => { e.preventDefault(); onTab(x.id) }}>{x.label}</a>
        ))}
      </nav>
      {tab === 'languages' && cmp && <Compare wikidataId={id} preloaded={cmp} embedded onHistory={() => onTab('edits')} />}
      {tab === 'languages' && !cmp && !error && <div className="panel muted">Loading the three versions…</div>}
      {tab === 'edits' && t && <History topic={t} />}
    </div>
  )
}

function History({ topic }) {
  const [article, setArticle] = useState(null)
  const [missing, setMissing] = useState(false)
  const [sub, setSub] = useState('wars')
  const [focus, setFocus] = useState(null)
  const [sql, setSql] = useState({})
  const view = HISTORY.find((h) => h.id === sub)

  useEffect(() => {
    const pid = topic.page_ids?.fi
    api.articles(topic.titles.fi).then((list) => {
      const a = list.find((x) => x.page_id === pid) || list.find((x) => x.title === topic.titles.fi)
      if (a) setArticle(a); else setMissing(true)
    }).catch(() => setMissing(true))
  }, [topic.wikidata_id])
  useEffect(() => {
    for (const name of view.queries) {
      if (!sql[name]) api.queryText(name).then((r) => setSql((s) => ({ ...s, [name]: r.sql }))).catch(() => {})
    }
  }, [sub])
  useSql(view.queries.map((name) => ({ label: name.replace(/_/g, ' '), sql: sql[name] })), [sub, sql])

  if (missing) return <div className="panel muted">No Finnish edit history for “{topic.titles.fi}” in dataset M.</div>
  if (!article) return <div className="panel muted">Loading the Finnish history…</div>
  return (
    <div className="history">
      <div className="subtabs">
        {HISTORY.map((h) => (
          <button key={h.id} className={sub === h.id ? 'on' : ''} onClick={() => { setSub(h.id); setFocus(null) }} title={h.help}>{h.label}</button>
        ))}
        <span className="muted small">{article.revisions.toLocaleString()} versions of the Finnish article, {article.first_rev?.slice(0, 4)}–{article.last_rev?.slice(0, 4)}</span>
      </div>
      <p className="viewhelp">{view.help}</p>
      {sub === 'wars' && <EditWars key={article.page_id} article={article} onJump={(r) => { setFocus(r); setSub('asof') }} />}
      {sub === 'contested' && <ContestedMap key={article.page_id} article={article} />}
      {sub === 'asof' && <TimeSlider key={article.page_id} article={article} focus={focus} />}
    </div>
  )
}
