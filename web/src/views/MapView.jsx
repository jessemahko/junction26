import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSql } from './SqlDrawer.jsx'
import Map2D from './map/Map2D.jsx'
import { usePlaces, useMarks, useClusters, useNeighbours, linesFor, color } from './map/shared.js'

// The map view: the articles of the current filter at their places, coloured by score (how much they need
// an editor); with a semantic search, size = similarity to the query. All the articles at one place (400 in
// Helsinki) are one blob, sized by the count: click it for the list. Pick an article (a dot, or a name in
// a blob's list): lines to its 10 most similar articles (VEC_DISTANCE on the article vectors), thicker =
// more similar; hovering a dot previews them. The name in the card opens the article page.
// The map itself is a 2D world map on one canvas (map/Map2D.jsx).
const where = (m) => (m.located === 'inferred' ? `${m.place} (the place the article links most)` : m.place || '')

export default function MapView({ res, filter, onOpen }) {
  const places = usePlaces()
  const semantic = !!(filter.q && filter.mode === 'meaning')
  const { marks: places1, unplaced } = useMarks(res, places, semantic)
  // the views report how big one article is on the ground at their zoom; marks that would overlap merge
  const [baseKm, setBaseKm] = useState(8)
  const { clusters: marks, markOf } = useClusters(places1, baseKm, semantic)
  const [hover, setHover] = useState(null)   // {mark, x, y}
  const [sel, setSel] = useState(null)       // {place: a place's key, id: article or null (a blob's list)}
  const [frame, setFrame] = useState(null)

  // the selection follows its place through re-clustering (zooming merges and splits blobs)
  const selMark = sel && (sel.id ? markOf.get(sel.id) : marks.find((m) => m.placeKeys.has(sel.place)))
  useEffect(() => { setHover(null) }, [marks])
  useEffect(() => { setSel(null) }, [places1])
  useEffect(() => {
    const id = setInterval(() => { const f = window.__map?.frameMs; if (f != null) setFrame(f) }, 1000)
    return () => clearInterval(id)
  }, [])

  // lines for the selected article, and a preview for a hovered single article
  const hoverId = hover && hover.mark.n === 1 ? hover.mark.items[0].id : null
  const sources = [sel?.id, hoverId !== sel?.id ? hoverId : null].filter(Boolean)
  const neigh = useNeighbours(sources)
  const lines = useMemo(() => linesFor(sources, neigh, markOf), [sources.join('|'), neigh, markOf])
  const focus = useMemo(() => {
    const f = new Set(lines.map((l) => l.to?.key).filter(Boolean))
    for (const m of [selMark, hover?.mark]) if (m) f.add(m.key)
    return f
  }, [lines, selMark, hover])
  const labels = useMemo(() => {
    if (!sel?.id || !selMark) return []
    const a = selMark.items.find((x) => x.id === sel.id)
    const out = [{ mark: selMark, text: a?.r.titles.fi || '', main: true }]
    for (const l of lines.filter((x) => x.src === sel.id).slice(0, 6)) out.push({ mark: l.to, lat: l.lat, lon: l.lon, text: l.title })
    return out
  }, [sel, selMark, lines])

  const onHover = useCallback((m, x, y) => setHover((h) => (m ? (h?.mark === m && Math.abs(h.x - x) < 2 && Math.abs(h.y - y) < 2 ? h : { mark: m, x, y }) : null)), [])
  const onPick = useCallback((m) => setSel(m ? { place: m.places[0].key, id: m.n === 1 ? m.items[0].id : null } : null), [])

  const shownSim = neigh[sel?.id] || neigh[hoverId]
  useSql([
    ...(res ? res.sql.map((s) => ({ ...s, ms: res.ms })) : []),
    ...(shownSim?.sql ? shownSim.sql.map((s) => ({ ...s, ms: shownSim.ms })) : []),
    ...(places ? places.sql.map((s) => ({ ...s, ms: places.ms })) : []),
  ], [res, places, shownSim])

  const view = { marks, fitKey: places1, fitMarks: places1, lines, focus, selKey: selMark?.key, hoverKey: hover?.mark.key, labels, semantic, onHover, onPick, onScale: setBaseKm }
  const article = sel?.id && selMark?.items.find((a) => a.id === sel.id)
  const cardSim = sel?.id && neigh[sel.id]
  const articles = places1.reduce((n, m) => n + m.n, 0)
  return (
    <div className="mapview">
      <div className="mapwrap">
        <Map2D {...view} />


        {hover && hover.mark.key !== selMark?.key && (
          <div className="maptip" style={{ left: Math.min(hover.x + 14, window.innerWidth - 290), top: hover.y + 14 }}>
            {hover.mark.n === 1 ? (
              <>
                <b>{hover.mark.items[0].r.titles.fi}</b>
                <span className="muted">{hover.mark.items[0].r.titles.en}</span>
                <Stats r={hover.mark.items[0].r} />
                <small className="muted">{where(hover.mark)} · click to pick</small>
              </>
            ) : (
              <>
                <b>{hover.mark.place}: {hover.mark.n} articles</b>
                <span className="muted small">most urgent: {hover.mark.items[0].r.titles.fi} ({hover.mark.items[0].r.score?.toFixed(2)})</span>
                <small className="muted">click to list them</small>
              </>
            )}
          </div>
        )}

        {selMark && !article && (
          <aside className="mapcard">
            <button className="x" onClick={() => setSel(null)} title="Close">✕</button>
            <span className="title static">{selMark.place}</span>
            <span className="muted">{selMark.n} articles here{selMark.located === 'inferred' ? ' (placed by the place they link most)' : ''}
              {semantic ? ', closest to your search first' : ', most urgent first'}</span>
            <ol className="bloblist">
              {selMark.items.map((a) => (
                <li key={a.id}>
                  <i style={{ background: color(a.r.score) }} title={`score ${a.r.score?.toFixed(2)}`} />
                  <button onClick={() => setSel({ place: selMark.places[0].key, id: a.id })} title="Pick: lines to its most similar articles">
                    {a.r.titles.fi}{selMark.places.length > 1 && <em> · {selMark.placeOf.get(a.id)}</em>}
                  </button>
                  <small>{semantic && a.r.similarity != null ? a.r.similarity.toFixed(2) : a.r.score?.toFixed(2)}</small>
                  <a href={`#/article/${a.id}/languages`} onClick={(e) => { e.preventDefault(); onOpen(a.id) }} title="Open the article page">→</a>
                </li>
              ))}
            </ol>
          </aside>
        )}
        {article && (
          <aside className="mapcard">
            <button className="x" onClick={() => setSel(null)} title="Close">✕</button>
            {selMark.n > 1 && <button className="back" onClick={() => setSel({ place: selMark.places[0].key, id: null })}>← all {selMark.n} articles: {selMark.place}</button>}
            <a className="title" href={`#/article/${article.id}/languages`} onClick={(e) => { e.preventDefault(); onOpen(article.id) }}
               title="Open the article page">{article.r.titles.fi} →</a>
            <span className="muted">{article.r.titles.en}</span>
            <Stats r={article.r} />
            <h4>Most similar articles</h4>
            {!cardSim?.data && <p className="muted small">Asking MariaDB…</p>}
            {cardSim?.data && (
              <ol className="simlist">
                {cardSim.data.map((n) => (
                  <li key={n.wikidata_id}>
                    <a href={`#/article/${n.wikidata_id}/languages`} onClick={(e) => { e.preventDefault(); onOpen(n.wikidata_id) }}>{n.titles.fi}</a>
                    <span className="simbar"><span style={{ width: `${Math.max(4, (n.similarity - 0.5) / 0.4 * 100)}%` }} /></span>
                    <small>{n.similarity.toFixed(2)}</small>
                  </li>
                ))}
              </ol>
            )}
            {cardSim?.data && <small className="muted">VEC_DISTANCE on the article vectors · {cardSim.ms} ms in MariaDB</small>}
          </aside>
        )}

        <div className="maplegend">
          <div className="ramp"><span>needs an editor less</span><i /><span>more</span></div>
          <div className="small">{semantic ? `dot size = how close to “${filter.q}”; ` : ''}a big blob = many articles at one place</div>
          <div className="small muted">
            {articles.toLocaleString()} articles at {places1.length.toLocaleString()} places{unplaced ? ` · ${unplaced} without a place` : ''}
            {frame != null && ` · frame ${frame.toFixed(1)} ms`}
          </div>
          <div className="small muted">drag to pan · scroll to zoom</div>
        </div>
      </div>
    </div>
  )
}

function Stats({ r }) {
  return (
    <span className="mapstats">
      <span title="Score: how much the article needs an editor"><i style={{ background: color(r.score) }} />score {r.score?.toFixed(2)}</span>
      <span title="Whole-article distance to the Finnish version">sv {r.fi_sv?.toFixed(2)} · en {r.fi_en?.toFixed(2)}</span>
      {r.contradictions != null && <span>{r.contradictions} possible contradiction{r.contradictions === 1 ? '' : 's'}{r.contradictions_agreed ? ` (${r.contradictions_agreed} agreed)` : ''}</span>}
      {r.similarity != null && <span>match {r.similarity.toFixed(2)}</span>}
    </span>
  )
}
