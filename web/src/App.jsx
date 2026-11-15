import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import FilterBar from './views/FilterBar.jsx'
import ArticleList from './views/ArticleList.jsx'
import ArticlePage from './views/ArticlePage.jsx'
import MapView from './views/MapView.jsx'

// The demo app: worklist -> article page -> map. Every view is a link:
//   #/list?q=sisällissota&mode=meaning&chip=civil-war    the worklist, narrowed
//   #/map?…same filter…                                  the map of the same articles
//   #/article/Q211855/languages | /edits                 one article: fi / sv / en, or its edit wars
// (#compare/Q… from older links opens the article page; #legacy is the pre-demo app.)
function parseHash() {
  const raw = decodeURIComponent(window.location.hash.replace(/^#\/?/, ''))
  const [path, qs = ''] = raw.split('?')
  const parts = path.split('/').filter(Boolean)
  const p = new URLSearchParams(qs)
  const filter = { q: p.get('q') || '', mode: p.get('mode') || 'meaning', chip: p.get('chip') || '' }
  if (parts[0] === 'article' && parts[1]) return { view: 'article', id: parts[1], tab: parts[2] || 'languages', filter }
  if (parts[0] === 'compare' && parts[1]) return { view: 'article', id: parts[1], tab: 'languages', filter }
  if (parts[0] === 'map') return { view: 'map', filter }
  return { view: 'list', filter }
}

function filterQs(f) {
  const p = new URLSearchParams()
  if (f.q) { p.set('q', f.q); if (f.mode !== 'meaning') p.set('mode', f.mode) }
  if (f.chip) p.set('chip', f.chip)
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function hrefFor(route, filter) {
  if (route.view === 'article') return `#/article/${route.id}/${route.tab || 'languages'}`
  return `#/${route.view}${filterQs(filter)}`
}

export default function App() {
  const [route, setRoute] = useState(parseHash)
  const [filter, setFilter] = useState(() => parseHash().filter)
  const [topics, setTopics] = useState(null)       // /api/topics answer for the current filter
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [chips, setChips] = useState(null)

  useEffect(() => {
    const on = () => { const r = parseHash(); setRoute(r); if (r.view !== 'article') setFilter(r.filter) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  useEffect(() => { api.chips().then(setChips).catch(() => setChips({ data: [] })) }, [])

  // One fetch per filter, shared by the list and the map.
  useEffect(() => {
    let live = true
    setLoading(true); setError(null)
    const t0 = performance.now()
    api.topics(filter).then((r) => {
      if (!live) return
      r.wall_ms = Math.round(performance.now() - t0)
      setTopics(r); setLoading(false)
    }).catch((e) => { if (live) { setError(e.message); setLoading(false) } })
    return () => { live = false }
  }, [filter.q, filter.mode, filter.chip])

  const go = useCallback((r, f = filter) => {
    const h = hrefFor(r, f)
    if (window.location.hash !== h) window.location.hash = h
    else setRoute(parseHash())
    window.scrollTo(0, 0)
  }, [filter])
  const applyFilter = (f) => {
    setFilter(f)
    const h = hrefFor({ view: route.view === 'map' ? 'map' : 'list' }, f)
    history.replaceState(null, '', h)
    if (route.view === 'article') setRoute({ view: 'list', filter: f })
  }
  const openArticle = (id, tab = 'languages') => go({ view: 'article', id, tab })

  const nav = route.view === 'article' ? 'list' : route.view
  return (
    <div className={`app app-${route.view}`}>
      <header className="top">
        <a className="brand" href={hrefFor({ view: 'list' }, filter)} title="Back to the worklist">
          <h1>AikaKone</h1>
        </a>
        <span className="tag">Finnish, Swedish and English Wikipedia on Finland's history: where the versions differ, and where editors fight</span>
        <nav className="mainnav">
          <a className={nav === 'list' ? 'on' : ''} href={hrefFor({ view: 'list' }, filter)}>Articles</a>
          <a className={nav === 'map' ? 'on' : ''} href={hrefFor({ view: 'map' }, filter)}>Map</a>
        </nav>
      </header>

      {route.view !== 'article' && (
        <FilterBar filter={filter} onChange={applyFilter} chips={chips?.data || []} loading={loading}
                   count={topics?.data?.length} notes={topics?.notes} />
      )}
      {error && <p className="err">API error: {error}. Is the server running (uvicorn api.main:app --port 8000)?</p>}

      {route.view === 'list' && <ArticleList res={topics} filter={filter} chips={chips} onOpen={openArticle} />}
      {route.view === 'map' && <MapView res={topics} filter={filter} onOpen={openArticle} />}
      {route.view === 'article' && (
        <ArticlePage id={route.id} tab={route.tab} filter={filter}
                     onTab={(t) => go({ view: 'article', id: route.id, tab: t })} />
      )}
    </div>
  )
}
