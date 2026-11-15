import React, { useEffect, useRef, useState } from 'react'

// Narrow the worklist (and the map): a search box that searches by meaning (bge-m3 + VEC_DISTANCE on
// the article vectors, so "prison camps" finds "vankileiri") or by title, and topic chips (a Finnish
// category and its subcategories, WITH RECURSIVE over the category tree).
export default function FilterBar({ filter, onChange, chips, loading, count, notes }) {
  const [text, setText] = useState(filter.q)
  const timer = useRef(null)
  useEffect(() => { setText(filter.q) }, [filter.q])

  const submit = (q, mode = filter.mode) => {
    clearTimeout(timer.current)
    if (q.trim() !== filter.q || mode !== filter.mode) onChange({ ...filter, q: q.trim(), mode })
  }
  const onType = (v) => {
    setText(v)
    clearTimeout(timer.current)
    // Title search is instant; a meaning search waits for a pause in typing.
    timer.current = setTimeout(() => submit(v), filter.mode === 'title' ? 250 : 700)
  }

  return (
    <div className="filterbar">
      <div className="searchrow">
        <div className={`search ${loading ? 'busy' : ''}`}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="M13 13l4.5 4.5" /></svg>
          <input value={text} onChange={(e) => onType(e.target.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') submit(text); if (e.key === 'Escape') { setText(''); submit('') } }}
                 placeholder={filter.mode === 'meaning' ? 'Search by meaning, in any language: “sisällissota”, “prison camps 1918”, “Swedish kings”…' : 'Search article titles (fi / sv / en)…'}
                 aria-label="Search articles" />
          {text && <button className="clear" onClick={() => { setText(''); submit('') }} title="Clear the search">✕</button>}
        </div>
        <div className="seg" role="group" aria-label="Search mode">
          <button className={filter.mode === 'meaning' ? 'on' : ''} onClick={() => submit(text, 'meaning')}
                  title="Semantic search: your words are embedded with bge-m3 and compared with every article's vector (VEC_DISTANCE_COSINE), so it also finds articles that never use the word">Meaning</button>
          <button className={filter.mode === 'title' ? 'on' : ''} onClick={() => submit(text, 'title')}
                  title="Plain title search (LIKE on the Finnish, Swedish and English titles)">Title</button>
        </div>
      </div>
      <div className="chiprow">
        <span className="muted small">Topics:</span>
        {chips.map((c) => (
          <button key={c.id} className={`topic ${filter.chip === c.id ? 'on' : ''}`}
                  onClick={() => onChange({ ...filter, chip: filter.chip === c.id ? '' : c.id })}
                  title={`Finnish category ${c.categories.map((x) => `“${x}”`).join(' + ')} and its subcategories (WITH RECURSIVE)${c.note ? ` — ${c.note}` : ''}`}>
            {c.label} <small>{c.topics}</small>
          </button>
        ))}
        <span className="status small muted">
          {loading ? 'Searching…' : count != null && (
            <>{count.toLocaleString()} article{count === 1 ? '' : 's'}{notes?.length ? ` · ${notes.join(' · ')}` : ''}</>
          )}
        </span>
      </div>
    </div>
  )
}
