import React, { createContext, useContext, useEffect, useState } from 'react'

// The SQL drawer: the MariaDB queries behind whatever is on screen, straight from the API responses.
// One drawer for the whole app (bottom left, "SQL"); each view says what it shows with
//   useSql([{ label, sql, ms }], [deps])
// The last view to call it wins; leaving the view clears it.
const SqlContext = createContext({ set: () => {}, queries: [] })

export function SqlProvider({ children }) {
  const [queries, set] = useState([])
  return <SqlContext.Provider value={{ queries, set }}>{children}</SqlContext.Provider>
}

export function useSql(queries, deps) {
  const { set } = useContext(SqlContext)
  useEffect(() => {
    set((queries || []).filter((q) => q && q.sql))
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => set([]), []) // eslint-disable-line react-hooks/exhaustive-deps
}

export default function SqlDrawer() {
  const { queries } = useContext(SqlContext)
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState(0)
  useEffect(() => { setTab(0) }, [queries.map((q) => q.label).join('|')])
  if (!queries.length) return null
  const cur = queries[Math.min(tab, queries.length - 1)]

  return (
    <section className={`sqldrawer${open ? ' open' : ''}`}>
      {open && (
        <div className="sqlcontent">
          <div className="sqltabs">
            {queries.map((q, i) => (
              <button key={q.label + i} className={i === tab ? 'on' : ''} onClick={() => setTab(i)}>
                {q.label}{q.ms != null && <small> {q.ms} ms</small>}
              </button>
            ))}
          </div>
          <pre>{highlight(cur.sql)}</pre>
        </div>
      )}
      <button className="btn sm sqltoggle" onClick={() => setOpen(!open)} title="The MariaDB queries behind this view">
        {open ? '✕ SQL' : `SQL${queries.length > 1 ? ` · ${queries.length}` : ''}`}
      </button>
    </section>
  )
}

const KW = /\b(WITH RECURSIVE|WITH|SELECT|FROM|WHERE|LEFT JOIN|JOIN|ON|AND|OR|NOT|AS|IN|UNION|ORDER BY|GROUP BY|HAVING|LIMIT|USING|DESC|ASC|SET|CASE|WHEN|THEN|ELSE|END|DISTINCT|FOR SYSTEM_TIME|AS OF|ALL|BETWEEN|VEC_DISTANCE_COSINE|VEC_DISTANCE|VEC_FromText)\b/g

function highlight(sql) {
  return sql.split('\n').map((line, i) => {
    const c = line.indexOf('--')
    const code = c >= 0 ? line.slice(0, c) : line
    const parts = []
    let last = 0
    for (const m of code.matchAll(KW)) {
      parts.push(code.slice(last, m.index))
      parts.push(<b key={m.index}>{m[0]}</b>)
      last = m.index + m[0].length
    }
    parts.push(code.slice(last))
    return <span key={i}>{parts}{c >= 0 && <span className="c">{line.slice(c)}</span>}{'\n'}</span>
  })
}
