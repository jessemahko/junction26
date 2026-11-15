// API client: every call goes to the FastAPI server under /api (same origin; `npm run dev` proxies it).

async function get(path, params = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  const res = await fetch(`/api${path}${qs.toString() ? '?' + qs : ''}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  // Kristian's views of the Finnish article (system-versioned sentences)
  articles: (q = '') => get('/articles', { q }),
  asOf: (id, date) => get(`/articles/${id}/as-of`, { date }),
  diff: (id, from, to) => get(`/articles/${id}/diff`, { from, to }),
  contested: (id) => get(`/articles/${id}/contested`),
  editWars: (id, limit = 30) => get(`/articles/${id}/edit-wars`, { limit }),
  revisions: (id) => get(`/articles/${id}/revisions`),
  sentenceHistory: (id, hash) => get(`/articles/${id}/sentences/${hash}/history`),
  about: (id, date, from, to) => get(`/articles/${id}/about`, { date, from, to }),
  // fi / sv / en comparison (docs/contracts.md c)
  compare: (wikidataId) => get(`/compare/${encodeURIComponent(wikidataId)}`),
  // worklist, search, chips, map (api/explore.py)
  topics: ({ q = '', mode = 'meaning', chip = '' } = {}) => get('/topics', { q, mode: q ? mode : null, chip }),
  chips: () => get('/chips'),
  similar: (wikidataId, k = 10) => get(`/similar/${encodeURIComponent(wikidataId)}`, { k }),
  topicPlaces: () => get('/topic-places'),
  queryText: (name) => get(`/queries/${name}`),
}

export const fmtDate = (iso) => (iso ? iso.slice(0, 10) : 'now')
export const wikiRev = (revId) => `https://fi.wikipedia.org/?oldid=${revId}`
