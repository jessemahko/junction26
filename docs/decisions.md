# Decisions

| When | Decision | Why |
|---|---|---|
| Fri 21:15 | MariaDB main challenge, SVT track | Team choice; SVT bonus |
| Fri 21:17 | Gemma + Verda side challenges | Coherent "open data, open DB, open model, EU compute" story |
| Fri 22:00 | "Contested History": sentence-level system versioning | Hits all three SVT examples in the brief |
| Fri 22:05 | 4 roles with frozen contracts | Parallel work from hour 1 |
| Fri 22:40 | **Data = dataset M** of `MariaDB/mariadb-wikipedia-datasets` | Only M has history: 862,076 versions of 19,742 History-of-Finland articles, 2003 – 1 Oct 2026, parquet, with editor, edit summary, sha1. S and L are current text only. |
| Fri 22:40 | **Dataset presets redefined** (plan said small/medium/large): `demo` = synthetic offline article; `small` = the 50 articles of MariaDB's time-machine demo (`ingest/lists/small.tsv`, incl. *Suomen sisällissota*, page 1150); `medium` = all articles in `versions-01..04`; `large` = all of M | Real files, real ids; L (current text of all fi-Wikipedia) is only useful for the Gemma throughput story |
| Fri 22:45 | **Historical time = option A** (`system_versioning_insert_history`) for bulk; option B (`SET @@timestamp` + plain DML) kept as `--mode replay` | Both confirmed working on `mariadb:lts` (12.3.3) and give identical results (`api/tests` run every test against both). A is one pass with multi-row inserts. |
| Fri 23:00 | `TIMESTAMP %s` always gets a full `YYYY-MM-DD HH:MM:SS.ffffff` | MariaDB refuses a bare date there (error 1525) |
| Fri 23:10 | **Schema additions** to the plan's §6.1: `article.sentence_order` (blob of hashes), `article.anonymous/minor/sha1/n_sentences`, `article_sentence.anonymous/prev_hash`, `load_log` | Order: a moved sentence must not get a new row (that would fake a "new life"), so per-revision order lives with the versioned article row. `prev_hash`: see next row. |
| Fri 23:30 | **Rewrite chains** (`prev_hash`): when a revision removes sentence P and adds a similar sentence S (word Jaccard ≥ 0.4, greedy), S records P | On real data exact returns are rare; rewording is the common fight. A recursive CTE over `FOR SYSTEM_TIME ALL` walks `prev_hash` + `row_end = row_start` (PK lookup) — V2 heat and the sentence genealogy panel. |
| Fri 23:30 | **Blanking vandalism filtered** at load: a span undone by an exact revert that contained a ≥ 50 % removal, or a ≥ 50 % removal restored ≥ 80 % within 7 days | One blank-and-revert otherwise gives *every* sentence a second life. 12 of 3,357 revisions of page 1150 dropped. |
| Fri 23:40 | Sentences need ≥ 3 words, ≥ 8 chars; normalisation unifies quotes, spaces, NBSP, soft hyphen | Link-only list items ("Talvisota") are not sentences; typographic edits are not content edits |
| Sat 00:10 | Drift queries are a **+1/−1 sweep with `SUM() OVER`**, not periods × lives | Monthly drift on page 1150 went from ~10 s to ~0.35 s; verified equal to AS OF snapshots (`test_sweep_matches_as_of_snapshots`) |
| Sat 00:10 | `as_of_article` adds a redundant `row_start <= ts ORDER BY row_start DESC LIMIT 1` | Lets the optimizer use `start_key` instead of walking the row_end-ordered history index (same finding as MariaDB's time-machine demo) |
| Sat 00:20 | Term matching via `LOCATE(term, CAST(LOWER(text) AS BINARY))` | 2× faster than `LIKE` under `utf8mb4_unicode_ci`, identical counts |
| Sat 00:20 | API served under `/api/...` (paths otherwise as §6.2) | Frontend and API share one origin on the Verda box (`web/dist` is served by FastAPI) |
| Sat 01:00 | **Globe** (react-globe.gl) as the landing view; articles placed by `{{coord}}`/`lat_deg`/`latd` in their latest wikitext, else via the place their infobox links (`paikka = [[Tampere]]`) | 2,629 of 19,742 articles have own coordinates, +131 events placed via their place. Not versioned: an article is placed where it is now. |
| Sat 01:00 | `article_geo.pt POINT` + `SPATIAL INDEX`; "nearby" = `MBRContains` box + `ST_Distance_Sphere` | Another MariaDB feature, used for something real (what else is near this place) |
| Sat 01:00 | Contested score on the globe = sentence returns + whole-article reverts; colour by percentile rank | A few huge articles would otherwise wash out the scale |
| Sat 01:30 | **Bitemporal (B5)** as a separate `sentence_event_time` table with `PERIOD FOR event_time`, filled from the years a sentence mentions (`ingest/event_time.py`), not an ALTER of `sentence_score` | Event time comes from the text, needs no model, and keeps working before Gemma runs; no ALTER on a loaded table. Query = `FOR SYSTEM_TIME AS OF` (when Wikipedia said it) × period overlap (when it happened). |
| Sat 01:30 | Parallel loader submits at most 2 pages per worker | `Executor.map` read every page of dataset M (12 GB of text) into memory up front |
| Sat 01:30 | Deploy = `docker compose --profile app up -d --build` (MariaDB + API/web image) | One command on a Verda CPU instance |
| Sat 00:30 | Scoring backends: `llm` (any OpenAI-compatible server, guided JSON) and `heuristic` (keyword baseline) | V4 works before the GPU is up; the baseline is what Gemma must beat in the eval |
