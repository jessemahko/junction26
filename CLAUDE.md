# Junction 2026 — a Wikipedia editor tool: language differences + edit wars

Main challenge: **MariaDB "Wikipedia Through Time"**, **both tracks** (vector search + system-versioned
tables). Side challenges: **Best Use of Gemma** and **Verda Compute Track**.

Team: Jussi + Kristian (Kristian's laptop broke; his code is merged in). Branch: **`combined`**.

## The product (decided Sat 17:15 after talking to MariaDB)

A tool that helps **Wikipedia editors** find and fix problems in articles about Finland's history:

1. **Worklist of questionable articles**, ranked by:
   - how much the **Finnish, Swedish and English** versions differ
   - content **missing** in a language
   - **contradictions** between languages (numbers, dates, names)
   - **edit-war** activity in the Finnish history
2. **Comparison view:** fi / sv / en side by side, aligned sentence by sentence, colour-coded:
   matching · missing · contradicting · different framing/tone. Next to it, Kristian's views of the
   Finnish article: edit wars, contested sentences, the article as of any date.
3. **Then edit:** "Open in Wikipedia's editor" for the chosen language, with the missing or conflicting
   sentence (and the language it comes from) shown for reference. **A human makes the edit.** Never
   auto-write edits; Wikipedia is strict about AI-written text.
4. **Globe as the entry point:** each article at its place (Niinistö → Helsinki). Lines from the article
   to one fixed point per language (sv → Stockholm, en → London), labelled, **coloured green → red by how
   much that language version differs**. Click → comparison view. Fallback if lines are unclear: colour the
   article's dot by difference.

Hero articles: **Sauli Niinistö** (fi page 1137) and **Suomen sisällissota** (fi page 1150).

## Judging (MariaDB, 20 % each)

Effective and creative use of MariaDB (vectors and/or SVT) · implementation and scale across the datasets
· usefulness for readers/editors · design and demo quality · originality. Bonus: SVT, or **both tracks**.
Gemma: most innovative, impactful use of Gemma. Verda: ambition (compute you couldn't do on a laptop),
fit of Verda products, working prototype + **documented process**, path to scale.

Every view must be backed by real MariaDB queries, and **show the SQL** (the SQL drawer convention).

## The algorithm: three levels

1. **Whole article:** `VEC_DISTANCE` between the fi / sv / en versions, using dataset S's ready-made
   bge-m3 vectors. Cheap and coarse; normalise for length differences.
2. **Sentence matching:** split each version into sentences, embed with **bge-m3** (same model as the
   dataset vectors, multilingual), match every sentence to its nearest neighbours in the other languages
   with MariaDB `VECTOR(1024)` + vector index + `VEC_DISTANCE`. **No match above the threshold = content
   missing** in that language. Record the threshold and why.
3. **Gemma judges matched pairs:** same claim / **contradiction** (numbers, dates, names) / **different
   framing or tone** (sentiment), with a one-line reason. Store it with the model name.

Bridge between the tracks: compare the **Finnish article as of a past date** (`FOR SYSTEM_TIME AS OF`) with
today's English/Swedish, e.g. "did the Finnish article catch up with the English one, and when?".

## Data

- **Dataset M** (loaded): 19,742 Finnish articles, **862,076 versions** 2003–2026, system-versioned with
  real Wikipedia times. Only Finnish has history.
- **Dataset S** (to load): **current** text in **fi 19,285 / sv 4,921 / en 5,254** + bge-m3 vectors,
  one per article. **2,919 topics in all three languages** (same `wikidata_id`). Snapshot August 2025.
  Release `s-2026-10` of MariaDB/mariadb-wikipedia-datasets.
- **No Russian** in the provided data. Use fi / sv / en.
- Reference repos in `reference/`: `mariadb-vector-wikipedia-rag` (vector loader, index settings, query
  shapes; **use its findings**: `M=16`, `mhnsw_ef_search=80`; put the vector search in a subquery so the
  index is used), `mariadb-system-versioning-wikipedia`, `mariadb-wikipedia-datasets`.

## Environment

- **Windows PC**, PowerShell. MariaDB 13.0 as a Windows service on **port 3307** (MySQL 8 is on 3306,
  don't mix them up). Database `wiki`. Settings in `.env` (gitignored).
- Python venv `.venv` (`.venv\Scripts\python`). Run scripts as modules: `python -m ingest.…`.
- One server: `.venv\Scripts\python -m uvicorn api.main:app --port 8000`.
  `/` redirects to `/contested/` = the React app (`web/`): worklist → article page → 2D map.

## Code layout (after the 2026-11-15 cleanup)

- `api/` FastAPI: `explore.py` (worklist search, chips, map), `editor.py` (fi / sv / en compare),
  `main.py` (Kristian's history routes for the Finnish article), `db.py` (one pool, SQL helpers;
  a missing table answers 503 with the command that loads it).
- `common/` connection + schema. `db/schema.sql` = one schema. `db/queries/*.sql` one file per view.
- `ingest/` loaders (dataset M, dataset S, sentences, Verda sentences + judgements, categories, places, geo, event time).
- `scoring/` Gemma: pair judging on Verda (`judge_pairs.py`, `eval_pairs.py`) and sentence scoring (`score.py`).
- `web/` the React app (Vite): `src/views/` (ArticleList, ArticlePage, Compare, MapView + `map/`, Kristian's
  EditWars / ContestedMap / TimeSlider). `web/scripts/demo-flow.mjs` = the Playwright demo run.
- Docs: `NOTES.md` (log), `docs/contracts.md`, `docs/decisions.md`, `docs/numbers.md`,
  `docs/process-log.md` (Verda). Demo screenshots: `docs/screenshots/` (`web/scripts/demo-flow.mjs`).

## Existing tables (don't break them)

- `article` — **system-versioned**, every version, columns from both builds (`editor`, `content`,
  `sentence_order` …).
- Kristian: `article_sentence` (system-versioned sentence lives), `sentence_score`,
  `sentence_event_time` (`PERIOD FOR event_time`), `article_geo` (`POINT` + `SPATIAL INDEX`), `article_stats`.
- Jussi: `place`, `page_place`, `place_link` (system-versioned), `revert`, `heat_year`, `page_origin`,
  `arc_year`, `year_caption`.

## New tables (names must not clash: the RAG repo also calls its table `article`)

```sql
lang_article        (lang, page_id, wikidata_id, title, content, …)        -- dataset S, current text
lang_article_vector (lang, page_id, embedding VECTOR(1024), VECTOR INDEX) -- dataset S vectors
lang_topic          (wikidata_id, fi_page_id, sv_page_id, en_page_id)      -- the 2,919 shared topics
lang_sentence       (lang, page_id, sent_no, text, embedding VECTOR(1024), VECTOR INDEX)
lang_pair           (wikidata_id, fi_sent, other_lang, other_sent, distance) -- best matches
pair_judgement      (pair id, label: same|contradiction|framing|missing, reason, tone, model)
article_divergence  (wikidata_id, fi_sv, fi_en, sv_en, missing_en, missing_sv, contradictions,
                     edit_war_score, rank)                                  -- the worklist
```

## Build stages (stop and show results after each one)

1. **Proof (small):** load dataset S under the new names; whole-article distances for the 2,919 topics
   (10 most / least similar, distribution, effect of length); sentence matching for Niinistö (1137) and the
   1918 war (1150) only, embedding on CPU (sentence-transformers or Ollama). Report missing sentences,
   the threshold and why, the 5 clearest "missing in English" examples, pairs with differing numbers/dates.
2. **Embeddings on Verda:** all sentences of the 2,919 topics with bge-m3 on a GPU (batch job), loaded
   into `lang_sentence` with a vector index; then `lang_pair` for all topics. Log GPU, time, cost.
3. **Gemma on Verda:** judge matched pairs (vLLM serving Gemma, structured JSON). Hero articles first,
   then the top of the worklist. Measure quality on a small hand-labelled set; log model, speed, cost.
4. **Worklist + comparison view** in the React app, with "Open in Wikipedia's editor" links and the SQL
   drawer. Link Kristian's edit-war views for the Finnish article.
5. **Globe lines** from each article to sv / en, coloured by difference; click → comparison view.
6. **Polish:** landing page, README, one start command, demo script, Verda write-up, screenshots.

## Working rules

- Commit and push to **`combined`**. **No Co-Authored-By or "Generated with Claude Code" lines.**
  Never force-push.
- Never drop, truncate or reload `article` or the other loaded tables without asking. New work goes into
  new tables.
- Keep `NOTES.md` up to date: decisions, measured times, row counts, problems. It becomes the README and
  the Verda write-up (`docs/process-log.md`).
- Don't commit `data/` or `.env`.
- Ask before downloading anything over 1 GB or starting paid cloud resources.
- Prefer simple, working, demoable over complete. The demo is 3 minutes.
- Be honest in findings: report what the data shows, not what we hoped.