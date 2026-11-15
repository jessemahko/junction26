# Rewritten — working notes

## Morning summary (2026-11-14)

### What works
The whole pipeline runs at full scale (19,742 articles, 862,076 versions). The globe app runs
from one server: landing overlay, year slider with play, four metrics, green/red link arcs, a caption
per year, the 1918 story, side panel with the article as it stood on the date, and the SQL drawer.

**Start it** (PowerShell, from the project folder; MariaDB service must be running):
```powershell
cd web; npm install; npm run build; cd ..          # only after a fresh clone or frontend changes
.venv\Scripts\python -m uvicorn api:app --port 8000
# open http://127.0.0.1:8000
```

**Rebuild the data** (all steps are safe to rerun; none calls an API except labels for new places):
```powershell
.venv\Scripts\python places.py --all --no-lookup   # place, page_place from data/places.tsv  (2.7 min)
.venv\Scripts\python labels_en.py                  # English labels, cached                  (seconds)
.venv\Scripts\python place_links.py --all          # place_link, system-versioned            (3.8 min)
.venv\Scripts\python build_heat.py --all           # revert, heat_year, page_origin, arc_year, year_caption (4.3 min)
.venv\Scripts\python check_api.py                  # times every endpoint (server must run)
cd web; npm run screenshots                        # docs/screenshots/ (server must run)
```

### Full-scale numbers
| | |
|---|---|
| `article` (system-versioned) | 19,742 articles, 862,076 versions, 5.9 GB |
| link targets / with coordinates / kept as places | 169,720 / 22,168 / **11,428** |
| articles with their own location | 4,621 (4,142 own coordinates, 479 via event location) |
| `place_link` (system-versioned) | **133,491 rows**, 113,891 current |
| noise filter | 46,049 reverts found, 52,919 versions skipped (6.1 %) |
| `heat_year` / `arc_year` / `page_origin` | 169,973 / 145,803 / 286,473 rows |
| Wikidata lookups (one-off) | 161,655 titles, 6,077 requests, 70 min |
| rebuild from cache | places 163 s · place links 229 s · heat + arcs 258 s |
| API, warm | every endpoint 1.5–38 ms; "return everything" calls 149–184 ms; **none over 300 ms** |

Sanity: page 1150 links 4 / 65 / 107 / 112 places as of 2005 / 2010 / 2018 / now (same sets as the
50-article run); the 2014-02-11 edit still swaps Tampere + Suomenlinna for five prison camps.

### Pitch findings (`docs/findings.md`, each with its SQL)
1. **Helsinki is the most rewritten place:** 4,426 links added, 392 removed. (With countries: Suomi
   leads, 4,992 / 1,282.)
2. **2007 was the busiest year:** 11,276 links added, 1,559 removed. 45 % of the added links came
   from new articles; 2007 is also the peak for edits, new articles and reverts.
3. **Tarja Halonen is the most reverted article** (971 reverts). January 2006, the election month,
   has her most edits and reverts, but the revert share was normal; it was busier, not more contested.
4. **Links moved to the state of the period:** Venäjä → Venäjän keisarikunta is the most common swap
   (48 edits); links to the Russian Empire grew ×7.4 from 2008 to 2026, Russia ×2.9.
5. **No naming shift for the 1918 war:** "sisällissota" has led "vapaussota" about 5–6 to 1 since
   2009. The 2009 jump in "vapaussota" is a medal name in biographies.

### Screenshots (`docs/screenshots/`, 1600×900, headless Edge)
`landing` · `2005` · `2014` · `2018` · `2018-all-links` · `2007-where-editors-fought` ·
`2013-what-was-rewritten` · `story-1918-2014` · `place-tampere-2018` · `sql-drawer`

### Half done / not checked
- **Never tested by hand:** play/pause, hover tooltips, story autoplay and the "Explore freely"
  button were only exercised through URL parameters and screenshots. Click through once before
  the demo.
- **Arc origins are guesses for most articles:** only 4,621 of 19,742 articles have a location of
  their own. The default view shows only those; "Show all links" adds the guessed ones.
- **Labels:** "Ahvenanmaan maakunta" can be half hidden behind Helsinki; region centroids
  ("Eurooppa", "Pohjoismaat") sometimes get labels.
- **`article` load time** was never recorded (the full load ran outside these notes).
- **Findings caveat:** the war-name counts are word counts per article; "sisällissota" also covers
  other countries' civil wars.
- **Nothing blocked.** Two failures overnight, both fixed: the lookup run crashed at its very end on a
  write conflict (no lookups lost), then a duplicate key from accent-insensitive collation
  (place tables now `utf8mb4_bin`).

### Next steps
1. **Gemma on Verda (stage 7).** The UI is ready for it: the caption has an empty
   "explained by Gemma" slot, filled when `/api/captions` finds a `change_reason (page_id, rev_id,
   reason, label)` table. Start with the 23 caption edits and the 1150 story edits, then reverts and
   link changes in bulk.
2. Click through the demo by hand and fix anything the screenshots missed.
3. Add the arc tooltips' Gemma reason (same `change_reason` table, keyed by the arc's articles).
4. Record the `article` load time for the README (one rerun of `load_parquet.py --list all` on an
   empty table; ask first, it rewrites 5.9 GB).

## Night run, task 5: pitch findings (2026-11-14)

`docs/findings.md`; queries in `findings.py` (10 min, mostly the yearly text scans) and
`findings_extra.py`. Decisions:
- Headline place excludes countries (Helsinki); Suomi is a footnote.
- War names: "vapaussota" counted with and without medal-only articles (`Vapaussodan
  muistomitali`). The data shows no shift, and the finding says so.
- Halonen: monthly series July 2005 – June 2007 against the 15 / 29 January 2006 election rounds.

---

## Stage 1: setup (2026-11-14) — done

### Result
| step | time |
|---|---|
| `create_tables.py` (database + 6 tables) | 0.16 s |
| `load_parquet.py`: 50 articles, **31,848 versions**, 2,050 MB of wikitext | **82 s** |
| `article` table on disk (COMPRESSED text + indexes) | **921 MB** |

Proof (`check_stage1.py`):
```sql
SELECT rev_id, title, row_start, row_end, len, LEFT(text, 120)
FROM article FOR SYSTEM_TIME AS OF TIMESTAMP'2010-01-01 00:00:00'
WHERE page_id = 1150
```
→ rev_id **7791638** *Suomen sisällissota*, saved 2009-12-29 10:37:52, current until 2010-01-24
16:42:21, 146,453 bytes (https://fi.wikipedia.org/?oldid=7791638). It is the newest version saved
before the date (checked against `FOR SYSTEM_TIME ALL`). Page 1150 has 3,357 versions, the whole set
spans 2003-03-29 … 2026-09-29.

AS OF query times for page 1150 (warm cache): 2004-06-01 0.14 ms (7,358 bytes then!), 2010-01-01
0.33 ms, 2018-01-01 0.19 ms, 2026-01-01 0.07 ms. `COUNT(*) … AS OF '2010-01-01'` over the whole table:
40 articles existed, 4.4 ms.

Login issue on the way: the first `.env` password was rejected by MariaDB (`1045 Access denied`);
fixed by updating `.env`.

### Environment found
- **MariaDB 13.0** runs as the Windows service `MariaDB` on **port 3307** (from its `my.ini`).
  **MySQL 8.0** (`MySQL80`) also runs on this machine, on 3306. Don't mix them up.
- Python 3.14.3 in `.venv`: mariadb 1.1.15, pyarrow 26.0.1, duckdb 2.0.0, fastapi, uvicorn.

### Files
- `common.py`: reads `.env` (handles BOM/CRLF/quotes), `connect()` always sets `time_zone='+00:00'`.
- `schema.sql`: all five tables from CLAUDE.md. `article` is the reference schema plus `parent_id` and
  `anonymous` (both in dataset M).
- `create_tables.py`: `CREATE DATABASE IF NOT EXISTS wiki`, then runs `schema.sql`.
- `load_parquet.py`: loads the 50 dev articles by default; `--list all` loads all 19,742.
- `check_stage1.py`: the `AS OF '2010-01-01'` proof for page 1150.

### Decisions
- **Real times** work like the reference `load.py`: `system_versioning_insert_history = 1`, explicit
  `row_start`/`row_end` (end = the next version's start), and the newest version is inserted without
  `row_end` so it stays current. Edits in the same second are shifted 1 µs apart to keep their order.
- **No `PARTITION BY SYSTEM_TIME`.** The reference measured no speed-up and 25% more disk. Kept
  `KEY start_key (page_id, row_start)`, which gave the reference its speed-up for old dates.
- **Batches are sized by bytes** (8 MB of text per `executemany`), well under the 16 MB packet limit.
- **Streaming parquet read.** Every article sits entirely in one parquet file (checked: 0 of 19,742 are
  split), and page_id ranges are sorted across files. The loader reads one row group at a time, skips
  row groups whose page_id stats hold no wanted article, and writes each article when the next one
  begins, so the full load won't need GBs of RAM.
- **Timestamps:** parquet holds `timestamp[ms, tz=UTC]`. Casting to naive `timestamp[us]` keeps the
  same instant (checked) and avoids needing the tz database, which pyarrow lacks on Windows.

### Data facts (50 dev articles)
- 31,848 versions; all 50 articles found. This matches the reference repo's count from the XML dumps.
- Reading them from parquet with a pyarrow `isin` filter takes 1.3 s.
- sha1 is always 31 chars; 8 versions have a null sha1 (likely deleted revisions).
- A duckdb glob query over all 16 files with `count(DISTINCT …)` hung for more than 2 min; pyarrow
  was instant. Use pyarrow for parquet.
- Load speed: about 390 versions/s, or 25 MB of wikitext/s. At that rate the full dataset M
  (862k versions) would take about 35–40 min, if it scales linearly (to measure in stage 6).

> Note: by the time of stage 2 the `article` table held **all 19,742 articles / 862,076 versions**
> (a full load ran outside these notes, so its time is not recorded). `article_list` still holds the 50
> dev articles, and stage 2 scripts default to that list.

## Stage 2: places (2026-11-14) — done

Run: `.venv\Scripts\python places.py` (50 dev articles; `--all` for every article). Total **488 s**:
link extraction from all 31,848 versions **24 s**, Wikidata/Wikipedia lookups **462 s** (547 API
requests, 12,747 titles). Reruns read `data/places.tsv` and make no lookups.

### Results
| | count |
|---|---|
| distinct link targets (all versions of the 50 articles) | **12,734** |
| … that are existing fi.wikipedia pages (after redirects) | 11,159 |
| … with a Wikidata item | 11,131 |
| … with coordinates (P625, Earth) | **1,701** |
| `place` rows (distinct places after merging redirects) | **1,526** |
| articles with their own location (`page_place`) | **19 of 50**: 9 own P625, 10 via P276 |

Own location via P276: Jatkosota, Talvisota and **Suomen sisällissota → Suomi** (the country, i.e.
Finland's centroid); Lapin sota → Lapin maakunta, Mäntsälän kapina → Mäntsälä, Pariisin rauhansopimus
(1947) → Pariisi, Pähkinäsaaren rauha → Pähkinäsaaren linna, Siirtoväki → Karjalankannas,
Tarton rauha → Tartto, YYA-sopimus → Moskova.
Own P625: Ahvenanmaan kysymys, Anjalan liitto, Isoviha, Mannerheim-linja, Moskovan rauhansopimus
(1940), Porkkalan vuokra-alue, Suomen sota, Suomen suuriruhtinaskunta, Turun palo.
No location (31): mostly decade/election/politics articles (Suomi 1960-luvulla, Eduskuntavaalit 2011 …).

Top 30 places by linking articles, ever / in the current version:
Suomi 38/32 · Helsinki 30/25 · Neuvostoliitto 28/24 · Ruotsi 25/21 · Venäjä 21/6 · Pietari 20/19 ·
Kansallinen Kokoomus 19/18 · Yhdistynyt kuningaskunta 19/15 · Turku 18/15 · Ahvenanmaan maakunta 17/14 ·
Tampere 17/12 · Saksa 17/9 · Ranska 16/12 · Viipuri 16/12 · Venäjän keisarikunta 15/15 ·
Suomen suuriruhtinaskunta 15/14 · Oulu 15/12 · Ruotsin kieli 14/7 · Suomen Pankki 13/12 ·
Karjalankannas 13/11 · Tukholma 13/11 · Puola 13/7 · Petsamo 12/12 · Yhdysvallat 12/10 · Viro 12/9 ·
Natsi-Saksa 11/11 · Neuvosto-Venäjä 11/11 · Karjala 11/8 · Lahti 11/8 · Moskova 11/8.
(Venäjä 21 → 6: links to "Venäjä" were later rewritten to more precise targets such as
Venäjän keisarikunta / Neuvosto-Venäjä — already a "rewritten" story.)

Most common kinds in `place`: municipality of Finland 171, town 75, battle 60, sovereign state 57,
former municipality 42, city 37, village 32, river 28, historical country 23, shopping center 22.

### Decisions
- **Redirects are resolved on fi.wikipedia, not Wikidata.** `wbgetentities&sites=fiwiki&redirects=yes`
  reported redirect titles ("Helsingin kaupunki", "Lapuan liike") as missing. Instead: step 1
  fi.wikipedia `action=query&redirects=1&prop=pageprops` (title → resolved title + QID), step 2
  `wbgetentities&ids=` for P625/P31/P276, step 3 P31 labels for `kind`. All 50 per request, serial.
- **`place.title` is the resolved title.** `data/places.tsv` keeps the title *as linked* plus
  `resolved`, so stage 3 maps link text → place via the cache ("Helsingin kaupunki" counts as Helsinki).
  Extra columns vs CLAUDE.md: `resolved`, `p276`.
- `kind` = English label of the first P31. Coordinates on other globes (Moon …) are ignored.
- **maxlag:** Wikidata kept answering `maxlag` with a steady ~11 s reported lag, so `maxlag=5` stalled
  the run (first attempt crashed after 6 retries). Read-only requests now use `maxlag=30`, honour
  `Retry-After`, back off up to ~15 min, and log every wait.
- The first run accidentally scanned **all 862k versions** (169,720 distinct targets → would have been
  ~7,000 API requests); stopped after <10 requests. Scripts now default to `article_list`.

### Problems / open questions for stage 3
- **Non-places with coordinates:** P625 also exists on parties (Kansallinen Kokoomus — its HQ),
  languages (Ruotsin kieli), banks (Suomen Pankki), shopping centers (22). They would make
  misleading hotspots. Proposal: drop by `kind` (organisations, languages, buildings …) or keep
  only geographic/event kinds.
- **Country-level locations:** the demo article *Suomen sisällissota* sits at "Suomi" (centroid) via
  P276; the arcs from it will start in central Finland. Fine for the globe, but Tampere will only
  flare through linking articles, not as the article's own location.
- Full scale (stage 6): 169,720 targets ≈ 7,000 serial requests ≈ 1.5–2 h at the measured rate.

## Stage 2b: place kinds, is_country, resumable --all (2026-11-14)

- **`kinds` column in `data/places.tsv`:** all P31 labels (|-separated), not just the first. The first
  label alone was too narrow for a whitelist (Rooma = "border city", Moskova = "capital of Russia",
  Pariisi = "commune of France"). The old cache was migrated in place: 49 requests backfilled the
  1,705 cached places with coordinates.
- **Whitelist (`kinds.py`)**: a place is kept when any P31 label matches a group (tried in order):
  country, battle (battle/siege), treaty (treaty/armistice), fortress (fortress/castle/fort/
  fortification/stronghold/kremlin/defence line), settlement (municipality/town/city/village/
  settlement/posyolok/urban area/… minus "city hall", "city fire", "old town", districts,
  neighbourhoods), region (region/province/county/oblast/governorate/län/territory/isthmus/
  peninsula/federal subjects…), island (island/archipelago), water (river/lake).
  `python kinds.py` prints what is included and excluded.
- **`place` columns added:** `category` and `is_country` (category = country: sovereign and historical
  countries, empires, kingdoms; drawn as polygons later).
  `ALTER TABLE place ADD category, is_country` was run by hand; schema.sql is updated.
- Articles' own locations that fail the whitelist (Turun palo, Isoviha, Anjalan liitto, Porkkalan
  vuokra-alue, Ahvenanmaan kysymys) stay in `place` with `category='own_location'`, so their arcs
  have an origin. They are not used as link targets.

Result (50 dev articles): 1,527 distinct places with coordinates → **923 in `place`**:
settlement 525 · country 123 · region 116 · battle 65 · water 45 · fortress 19 · island 15 ·
treaty 10 · own_location 5. **604 excluded** (293 kinds), largest: shopping center 22,
neighborhood 17, church building 16, building 11, railway station 11, street 10, Helsinki
neighbourhood 9, university 8+6, museum 8, prisoner-of-war camp 7, sculpture 7, memorial 7.
Bugs fixed on the way: "governorate of the Russian Empire" matched *empire* → country (now region);
"provinces of Sweden" (plural) was excluded.

**Resumable `places.py --all`:** titles already in places.tsv are skipped; results are appended every
250 titles; a half-written last line from a killed run is dropped on start (tested). Estimate for all
19,742 articles: about 157k new titles at about 1,000 titles / 36 s ≈ **1.5–2.5 h** plus lag waits;
link extraction over 862k versions adds about 2.5 min per start.

Overnight command (PowerShell, from the project folder; `cmd /c` keeps the log UTF-8 — PowerShell 5.1
`>` would write UTF-16):
```powershell
cmd /c ".venv\Scripts\python -u places.py --all >> data\places_all.log 2>&1"
```
If it stops, run the same command again. It rewrites `place` and `page_place` for all articles at
the end, so rerun `place_links.py` afterwards.

## Stage 3: place links (2026-11-14) — 50 dev articles

Run: `.venv\Scripts\python place_links.py` (`--all` for every article). Drops and recreates
`place_link` each run (a plain DELETE would leave the history rows). **54 s** for 31,848 versions.

- **Lifetimes:** a row (page, place) lives from the first kept version that links the place to the
  first later kept version that doesn't; times are Wikipedia's (`system_versioning_insert_history`).
  Links still in the current version are current rows. `mentions` = the most times the place was
  linked in one version during that lifetime (a new row per mention change would count as "added").
- **Noise filter:** a revert = version j with the same sha1 as an earlier version k ≠ j−1. It undid
  k+1 … j−1; if j came within 48 h of k+1, those versions are skipped. Slower reverts are kept (real
  disputes). Skipped versions are listed in `data/noise_skipped.tsv`.
- **3,035 reverts** detected; the filter skipped **3,756 versions (11.8 %)**.
- `place_link`: **2,487 rows** (history + current), 1,790 current; 918 target places.

Links added / removed per year (added in brackets: by an article's first version, i.e. article creation):

| year | added | (new article) | removed |
|---|---|---|---|
| 2003 | 12 | 7 | 0 |
| 2004 | 119 | 34 | 15 |
| 2005 | 228 | 22 | 43 |
| 2006 | 205 | 1 | 43 |
| 2007 | 233 | 0 | 44 |
| 2008 | 145 | 1 | 49 |
| 2009 | 82 | 3 | 80 |
| 2010 | 80 | 0 | 15 |
| 2011 | 160 | 7 | 79 |
| 2012 | 90 | 0 | 35 |
| 2013 | 30 | 0 | 10 |
| 2014 | 109 | 47 | 28 |
| 2015 | 50 | 0 | 52 |
| 2016 | 65 | 0 | 28 |
| 2017 | 64 | 11 | 7 |
| 2018 | 179 | 5 | 4 |
| 2019 | 39 | 0 | 6 |
| 2020 | 113 | 12 | 51 |
| 2021 | 114 | 0 | 10 |
| 2022 | 46 | 0 | 18 |
| 2023 | 101 | 0 | 10 |
| 2024 | 47 | 0 | 21 |
| 2025 | 110 | 0 | 19 |
| 2026 | 66 | 0 | 30 |

**Sanity check, Suomen sisällissota (page 1150)**, places linked `FOR SYSTEM_TIME AS OF`:
- **2005-01-01: 4** — Helsinki, Tampereen taistelu, Vaasa, Neuvosto-Venäjä (the article was ~7 KB).
- **2010-01-01: 64** — +60, e.g. Brest-Litovskin rauha, Saksan keisarikunta, Viipuri, Lahti,
  Tampere, Suomenlinna, Vilppula, Viipurin taistelu, Antrean taistelut.
- **2018-01-01: 100** — +40 (Kämärän taistelu, Varkauden taistelu, Syrjäntaan taistelu, Oulu, Pori,
  Ukraina, Neuvostoliitto …), −4 (Tampere, Suomenlinna, Pihkova, Antrean taistelut).
- **now: 104** — +4 (Weimarin tasavalta, Japanin keisarikunta, Pohjoismaat, Venäjän SFNT).

Demo find: *Tampere* and *Suomenlinna* were unlinked on **2014-02-11** by the edit "Linkit
vankileireihin" (links to the prison camps). The links most likely moved to the prison-camp articles,
which the kind whitelist currently excludes ("prisoner-of-war camp", "concentration camp").

### Open
- Add prison camps to the whitelist? They are central to the 1918 story (Hennalan, Tampereen,
  Suomenlinnan vankileiri …), and without them the globe shows the 2014 rewrite only as a removal.
- Self-links (an article linking its own location, e.g. sisällissota → Suomi) are kept in
  `place_link`; filter `from = to` in the arcs API.

## Stage 3b: camps (2026-11-14)

- New whitelist category **camp** (prison / prisoner-of-war / concentration / internment / labour camp)
  in `kinds.py`: 8 places — Hennalan, Tampereen, Suomenlinnan, Hämeenlinnan, Riihimäen,
  Lappeenrannan, Tammisaaren vankileiri, Fellmanin pelto. `place` now 931 rows; `place_link`
  2,496 rows (1,799 current), built in 35 s.
- `places.py --no-lookup`: refills `place`/`page_place` from `data/places.tsv` **read-only** (no API
  calls, never writes the cache), so it is safe while the `--all` lookup run appends to the cache.
  ⚠ The `--all` run imported the old `kinds.py` at start; when it finishes it rewrites `place`
  without camps → afterwards run `places.py --all --no-lookup`, then `place_links.py`.
- **Confirmed:** the 2014-02-11 edit on page 1150 ("Linkit vankileireihin", rev 13858503) now shows
  as **5 links added** (Hämeenlinnan, Hennalan, Riihimäen, Suomenlinnan, Tampereen vankileiri) and
  **2 removed** (Tampere, Suomenlinna) — the links moved from the towns to their camps.

## Stage 4: heat table + API (2026-11-14) — 50 dev articles

### heat_year (`build_heat.py`, 7.9 s total)
Every metric is an `INSERT … SELECT` over SVT queries, one per year 2004–2026 (`heat_sql.py`; the API
shows the build query in `built_from`):
- **knowledge** = `place_link FOR SYSTEM_TIME AS OF '<year>-01-01'` rows pointing to the place,
  plus length in KB of articles located there (`article FOR SYSTEM_TIME AS OF` ⋈ `page_place`).
  KB rather than bytes so one article doesn't drown out the link counts.
- **activity** = versions saved that year (`article FOR SYSTEM_TIME ALL`, row_start in year) of the
  articles located at the place or linking it at any moment of the year
  (`place_link FOR SYSTEM_TIME FROM '<y>-01-01' TO '<y+1>-01-01'`). 7.4 s of the 7.9 s.
- **controversy** = reverts that year, same articles. Reverts go in a plain table `revert`, built
  from `article FOR SYSTEM_TIME ALL` with the reference repo's window-function definition
  (`sha1 <> LAG(sha1) AND MIN(row_start) OVER (PARTITION BY page_id, sha1) < row_start`):
  **3,033 reverts** (Python found 3,035; the difference is versions with a NULL sha1).
- **rewritten** = `place_link FOR SYSTEM_TIME ALL` rows to the place with row_start or row_end in
  the year (added + removed; this includes links added by a new article).
- Result: **12,294 rows, 917 places**. Top 2018: knowledge Suomi 368, Suomen suuriruhtinaskunta 142;
  activity Suomi 1,330, Neuvostoliitto 1,244; controversy Suomi 97; rewritten Tampere 5.

### API (`api.py`, FastAPI)
Run: `.venv\Scripts\python -m uvicorn api:app --port 8000`. Each request opens its own connection
(time_zone UTC). Every response has `sql` (the SQL that ran, with values filled in for reading;
execution uses bound parameters or int-validated literals) and `ms` (database time).
CORS open for GET (local frontend).

| endpoint | sample | HTTP | curl total (warm) | DB ms | size |
|---|---|---|---|---|---|
| `/api/years` | | 200 | 4 ms | 1.3 | 0.2 KB |
| `/api/heat` | year=2018, knowledge (580 places) | 200 | 9 ms | 2.2 | 80 KB |
| `/api/heat` | year=2007, activity | 200 | 7 ms | | 50 KB |
| `/api/heat` | year=2007, controversy | 200 | 6 ms | | 44 KB |
| `/api/heat` | year=2014, rewritten | 200 | 4 ms | | 18 KB |
| `/api/arcs` | year=2014, limit=200 | 200 | 12 ms | 5.8 | 34 KB |
| `/api/arcs` | year=2018, limit=5000 (643 arcs) | 200 | 18 ms | 7.4 | 110 KB |
| `/api/place/Tampere` | date=2010-01-01 | 200 | 5 ms | 1.8 | 1.7 KB |
| `/api/place/Hennalan vankileiri` | date=2015-01-01 | 200 | 4 ms | | 1.1 KB |
| `/api/article/1150` | date=2010-01-01 | 200 | 36 ms | 11.5 | 127 KB |
| `/api/article/1150` | now | 200 | 35 ms | 6.2 | 146 KB |
| errors | bad metric / unknown place / article before it existed | 400 / 404 / 404 | 2–3 ms | | |

The article endpoint is the slowest because of cleaning about 150 KB of wikitext in Python, not the SQL.
Sample responses are saved in `data/api_samples/*.json`.

Sample responses (trimmed):
```json
GET /api/heat?year=2018&metric=knowledge
{"sql": "SELECT h.place_title AS title, p.lat, p.lon, h.knowledge AS value, ... WHERE h.year = 2018 AND h.knowledge > 0 ...",
 "ms": 2.17, "built_from": "INSERT INTO heat_year ... FROM place_link FOR SYSTEM_TIME AS OF TIMESTAMP'2018-01-01 00:00:00' ...",
 "data": [{"title": "Suomi", "lat": 65.0, "lon": 27.0, "value": 368, "kind": "sovereign state",
           "category": "country", "is_country": true}, ...]}

GET /api/arcs?year=2014
{"sql": "SELECT f.title AS from_title, ... FROM place_link FOR SYSTEM_TIME ALL WHERE row_start >= TIMESTAMP'2014-01-01 00:00:00' ...",
 "ms": 5.82,
 "data": [{"from": {"title": "Suomi", "lat": 65.0, "lon": 27.0},
           "to": {"title": "Latvia", "lat": 57.0, "lon": 25.0},
           "weight": 1, "status": "added", "pages": [1150]}, ...]}

GET /api/place/Tampere?date=2010-01-01
{"sql": "...FROM place_link FOR SYSTEM_TIME AS OF TIMESTAMP '2010-01-01 00:00:00' l ...", "ms": 1.75,
 "place": {"title": "Tampere", "qid": "Q40840", "category": "settlement", ...},
 "data": [{"page_id": 1150, "title": "Suomen sisällissota", "rev_id": 7791638, "relation": "links here",
           "mentions": 1, "oldid_url": "https://fi.wikipedia.org/?oldid=7791638"}, ... 4 articles]}

GET /api/article/1150?date=2010-01-01
{"sql": "SELECT ... FROM article FOR SYSTEM_TIME AS OF TIMESTAMP '2010-01-01 00:00:00' WHERE page_id = 1150; ...",
 "ms": 11.51, "title": "Suomen sisällissota", "rev_id": 7791638,
 "oldid_url": "https://fi.wikipedia.org/?oldid=7791638", "saved": "2009-12-29 10:37:52",
 "until": "2010-01-24 16:42:21", "edits_to_date": 2213, "reverts_to_date": 147,
 "blocks": [{"kind": "p", "text": "Suomen sisällissota käytiin Suomen senaatin eli hallituksen ..."}, ... 314 blocks]}
```

### Arcs: decisions and limits
- status per year: **added** = row_start in the year, **removed** = row_end in the year, **same** =
  `AS OF '<y+1>-01-01'` with row_start before 1 Jan (the same row survived the whole year). A link
  added and removed within one year shows as both. Ordered added → removed → same, then weight.
- **weight = distinct articles** (`COUNT(DISTINCT page_id)`); first version used `COUNT(*)` and
  double-counted links that flapped twice in a year (1150 → Latvia in 2014).
- Origin = `page_place`; **self-links filtered** (`f.title <> t.title`). `pages` lists the page_ids
  behind each arc (for tooltips / Gemma reasons later).
- **Limit:** only 19 of the 50 dev articles have an origin, so most link changes have no arc
  (2018: 19 added, 0 removed). The heatmap still counts them. Worth a fallback origin later
  (e.g. the article's most-linked place).
- 1150 sits at Suomi's centroid (65 N, 27 E), so all its arcs fan out from central Finland.

## Stage 4b: fallback arc origins + page filter (2026-11-14)

- New plain table **`page_origin (year, page_id, place_title, inferred)`**, built in `build_heat.py`
  (0.1 s). Own location from `page_place` (inferred = 0); otherwise the **non-country place the
  article linked most at any moment of the year** (`place_link FOR SYSTEM_TIME FROM … TO …`,
  `ROW_NUMBER() … ORDER BY mentions DESC, row_start`; ties go to the oldest link). 921 rows, 484
  inferred; **49 of 50 articles** now have an origin (was 19).
- `/api/arcs` joins `page_origin` and returns **`origin_inferred`** and `articles: [{page_id, title}]`
  (was `pages`). New optional **`page=`** filter (arcs of one article). `/api/heat` now returns `qid`.
- 2018, limit 500: 164 added (145 inferred), 4 removed, 332 unchanged; 14 ms.
  `/api/arcs?year=2014&page=1150`: 31 added, 7 removed, 97 unchanged; 9 ms.
- Some inferred origins are odd (Mannerheim → Lausanne, Kekkonen → Pielavesi, Suomi 1980-luvulla →
  Oulu): "most-linked" is often a birthplace or a tie. They are drawn dimmer for that reason.

## Stage 5: globe frontend (2026-11-14)

**Run everything with one command** (after building the frontend once):
```powershell
cd web; npm install; npm run build; cd ..
.venv\Scripts\python -m uvicorn api:app --port 8000     # then open http://127.0.0.1:8000
```
`api.py` serves `web/dist` itself. For frontend work: `cd web; npm run dev` (proxies `/api` to :8000).
`web/dist/` is gitignored, so a fresh clone needs the build step.

- **Stack:** Vite + globe.gl, plain JS, no framework. `web/src/main.js` (logic), `style.css`,
  `historical.js` (lookup table). Textures are copied from the three-globe package into `web/public`,
  so the demo needs no internet.
- **Countries as polygons:** Natural Earth 110m (177 countries, trimmed to 175 KB in
  `web/public/countries.geojson`), matched by `WIKIDATAID` = `place.qid`. 47 historical countries map
  to a modern polygon in `historical.js` (Neuvostoliitto / Venäjän keisarikunta / Neuvosto-Venäjä →
  Russia, Natsi-Saksa / Weimarin tasavalta → Germany, Suomen suuriruhtinaskunta → Finland …).
  A polygon's heat is the **max** of its places, not the sum: the same articles link several eras, and
  the sum made Russia swamp the globe. Countries with no polygon at 110m (Malta, Kap Verde) are points.
- **Heat points, not `heatmapsData`:** globe.gl's heatmap layer needs a bandwidth of degrees, which
  smears Finnish towns into one blob, and it isn't clickable. Places are flat discs, size and colour on
  a **sqrt scale against the metric's maximum over all years**, so years are comparable and growth is
  visible during playback. Top 1,500 points only (for full scale).
- **Arcs:** green = added, red = removed (slower, shorter dashes), faint grey = unchanged; inferred
  origins dimmer and thinner. Limit 500 per year (changes first). Hover = tooltip with article titles;
  click = the article.
- **Place names** are DOM labels (three.js text lacked ä/ö), strongest first, decluttered by distance,
  recomputed after zoom.
- **Side panel:** click a place → fly-to + its articles as of 31 Dec of the slider year (2026 = today);
  click an article → text on that day, edits and reverts so far, `?oldid=` link. Clicking a country
  opens its top place, with chips for the other eras.
- **Story: 1918** button: arcs filtered to page 1150, steps 2005 → 2010 → 2014 → 2018 → now every 6 s,
  with a caption, live counts, the article in the panel, and labels on the places whose links changed
  (removed first).
- **SQL drawer:** tabs Heat (the read query + the SVT query that built that year), Arcs, Panel;
  `FOR SYSTEM_TIME …` highlighted; shows DB ms.
- **Preload:** all 23 years of heat for the metric and of arcs are fetched in the background (6 at a
  time, thin progress line on the slider), so playback doesn't wait on the network.
- **URL parameters** for demo and tests: `?year=2014&metric=rewritten`, `&sql=1`, `&place=Tampere`,
  `?story=1&year=2014` (`&autoplay=1`).

### Checked with Playwright
`cd web; npm run screenshots` (uses the installed Edge via `playwright-core`, no browser download; app
must be running). Saved in `docs/screenshots/`: `2005-knowledge`, `2014-rewritten`, `2018-knowledge`,
`2007-controversy-sql`, `place-tampere-2018`, `story-1918-2005/2014/2018`.
Fixed after looking at the first round:
- arcs were far too thick when zoomed in and flew off the globe → thinner strokes, lower altitude;
- place names overlapped and showed "H?meenlinna" → DOM labels with declutter;
- Russia's polygon swamped activity/controversy → max instead of sum, calmer blue ramp;
- side panel ran under the timeline → timeline, metric toggle and story card make room;
- heat points were barely visible at the overview zoom → larger minimum size;
- story labels hid the removed places (Tampere, Suomenlinna) → removed first.

### Known limits
- Not tested by hand in a real browser: play/pause, hover tooltips and the story autoplay were only
  exercised through URL parameters and screenshots (headless Edge, software rendering).
- In 2005 knowledge points are tiny by design (scale is against the all-years maximum).
- 1150's own location is Suomi's centroid, so story arcs fan out from central Finland.
- JS bundle is 1.95 MB (three.js); fine locally.
- When `places.py --all` finishes it rewrites `place`/`page_place` for all articles without the camp
  category; rerun `places.py --all --no-lookup`, `place_links.py`, `build_heat.py` afterwards.

## Night run, task 1: the overnight lookup (2026-11-14)

- `places.py --all` **finished every lookup**: 161,655 new titles, 6,077 API requests, 4,206 s (70 min).
  It then crashed while writing `place` (`Record has changed since last read in table 'place'`): a
  transaction conflict with the Stage 3b refill of `place` that ran while it was looking up. No lookup
  was lost; `data/places.tsv` holds 174,407 titles.
- Rerun from the cache (0 lookups, 1 request, 163 s, of which 161 s is link extraction over 862,076
  versions). First rerun failed with `Duplicate entry 'Salla' for key 'PRIMARY'`: the default
  collation (`utf8mb4_uca1400_ai_ci`) ignores accents and case, so two different places collided.
  **Decision:** `place`, `page_place`, `place_link`, `heat_year`, `page_origin` now use
  `utf8mb4_bin` (schema.sql updated; existing tables converted with `ALTER TABLE … CONVERT TO`).
- This rerun used the current `kinds.py` (with camps), so it also covers "places.py --all --no-lookup".

Totals, all 19,742 articles:

| | count |
|---|---|
| distinct link targets | **169,720** |
| existing fi.wikipedia pages | 111,829 |
| with a Wikidata item | 111,575 |
| with coordinates | **22,168** (18,671 distinct after merging redirects) |
| kept in `place` by the kind whitelist | **11,428** (7,243 excluded) |
| articles with their own location (`page_place`) | **4,621**: 4,142 own P625, 479 via P276 |

`place` by category: settlement 5,475 · own_location 2,641 · water 1,361 · region 634 · island 510 ·
country 412 · battle 222 · fortress 117 · camp 29 · treaty 27. (own_location = articles with their own
coordinates whose kind is not whitelisted, e.g. buildings; kept as arc origins only.)
Top places by linking articles (ever / now): Suomi 4,728 / 3,710 · Helsinki 4,300 / 4,034 ·
Venäjä 1,815 / 1,454 · Turku 1,708 / 1,557 · Neuvostoliitto 1,707 / 1,558 · Ruotsi 1,665 / 1,470 ·
Pietari 1,528 / 1,446 · Tampere 1,329 / 1,208 · Viipuri 1,306 / 1,227 · Oulu 991 / 908.

## Night run, task 2: Stage 6, full scale (2026-11-14)

All 19,742 articles / 862,076 versions. `article` is 5.9 GB on disk (its load time was not recorded;
it ran outside these notes).

| step | command | time | result |
|---|---|---|---|
| places | `places.py --all` (from cache) | **163 s** | `place` 11,428, `page_place` 4,621 |
| English labels | `labels_en.py` | 188 s (229 requests, once) | 9,951 places with an `en_label` |
| place links | `place_links.py --all` | **229 s** | `place_link` **133,491** rows (113,891 current), 8,787 target places |
| heat + arcs | `build_heat.py --all` | **258 s** | see below |

No step came near 45 min, so nothing needed optimising for time.

- **Noise filter at full scale:** 46,049 reverts detected, **52,919 versions skipped (6.1 %)**.
- `build_heat.py --all` breakdown: `revert` 45,668 rows 13.9 s · knowledge 5.6 s · **activity 191.8 s** ·
  controversy 25.5 s · rewritten 1.4 s · `page_origin` 286,473 rows (17,487 articles have an origin in
  some year; 180,190 inferred) 4.8 s · `arc_year` 145,803 rows 12.1 s · `year_caption` 1.8 s.
  `heat_year`: **169,973 rows, 11,400 places**.
- Link changes per year peak in **2007: 11,276 added, 1,559 removed** (full table in
  `data/place_links_all.log`).

### What changed for scale
- **`arc_year`** (new plain table): the 1,500 strongest arcs per year × status × origin type, built
  from the same `FOR SYSTEM_TIME ALL / AS OF` query the API used to run live. Live, that query grouped
  every link of the year. `/api/arcs` reads `arc_year` and returns the SVT query as `built_from`.
  `/api/arcs?page=` (one article) still runs live on `place_link`.
- **`/api/arcs` defaults changed:** only added + removed arcs with a known origin, `limit` strongest
  per group (default 150). `all=1` adds unchanged and inferred-origin arcs.
- **`/api/heat`** has `limit` (default 1,500): countries first (drawn as polygons), then the strongest
  places. Returns `en_label`.
- **`/api/place`** returns the 200 articles that link the place most (`limit`), plus `linking_total`.
- **`/api/captions`** (new) + `year_caption` table: per year, links added/removed and the single edit
  that changed the most place links (an article's first version doesn't count). Includes
  `reason`/`label` from a `change_reason (page_id, rev_id, reason, label)` table when it exists
  (Gemma, stage 7); null until then.
- Index `page_place (place_title)`; `revert (page_id, row_start)`.
- `check_api.py` times every endpoint against the running server.

### API response times at full scale (warm, best of 3; `data/check_api_full.txt`)
| endpoint | total ms | DB ms | rows | KB |
|---|---|---|---|---|
| `/api/years` | 1.5 | 0.1 | 23 | 0.2 |
| `/api/captions` | 2.3 | 0.1 | 23 | 8.9 |
| `/api/heat?year=2018&metric=knowledge` | 37.8 | 21.8 | 1,500 | 272 |
| `/api/heat?year=2007&metric=activity` | 22.7 | 7.6 | 1,500 | 269 |
| `/api/heat?year=2007&metric=controversy` | 31.0 | 5.5 | 1,500 | 266 |
| `/api/heat?year=2013&metric=rewritten` | 29.0 | 13.7 | 1,500 | 269 |
| `/api/heat?year=2026&metric=knowledge&limit=20000` (everything) | 148.5 | 44.0 | 10,881 | 1,963 |
| `/api/arcs?year=2014` | 8.9 | 1.7 | 300 | 92 |
| `/api/arcs?year=2007&all=1` | 27.2 | 5.5 | 900 | 314 |
| `/api/arcs?year=2018&all=1&limit=1500` (everything stored) | 183.5 | 31.2 | 6,508 | 2,233 |
| `/api/arcs?year=2014&page=1150` | 5.0 | 1.0 | 140 | 39 |
| `/api/place/Tampere?date=2010-01-01` | 18.9 | 14.5 | 202 | 40 |
| `/api/place/Helsinki` | 26.8 | 21.9 | 232 | 48 |
| `/api/place/Suomi?date=2018-12-31` | 33.7 | 28.9 | 216 | 44 |
| `/api/article/1150?date=2010-01-01` | 34.9 | 12.0 | 314 | 127 |
| `/api/article/1150` | 34.1 | 6.4 | 364 | 146 |

**Nothing is over 300 ms.**

### Sanity checks at full scale
- **Page 1150** links 4 / 65 / 107 / 112 places as of 2005 / 2010 / 2018 / now. The place sets are
  **identical** to the 50-article run with camps (compared name by name). The older 64 / 100 / 104 in
  Stage 3 were measured before the camp category existed.
- **2014-02-11 edit on 1150:** still 5 camps added (Hennalan, Hämeenlinnan, Riihimäen, Suomenlinnan,
  Tampereen vankileiri) and Tampere + Suomenlinna removed.

## Night run, task 3: Stage 5b, readable in 5 seconds (2026-11-14)

1. **Legend, always visible** ("How to read the map"): dot sizes (text follows the metric: "bigger =
   more written about it"), country shading, green / red dashed / grey arcs, and the toggle.
2. **Caption per year**, from `/api/captions` (`year_caption`, built from `place_link FOR SYSTEM_TIME
   ALL`): "**2014** · articles added 6,457 links to places and removed 630", then "Biggest single edit:
   *Lapinkylä*, 93 added — editor's note: …" (click opens the article). Below it an empty slot,
   `#caption-reason`, shown only when the API returns `reason`: it renders as an "explained by Gemma"
   pill + one sentence. Stage 7 only needs to create `change_reason (page_id, rev_id, reason, label)`.
   **Decision:** "biggest change" = the single edit that added + removed the most place links that
   year, not counting an article's first version.
3. **Default arcs = added + removed with a known origin** (220 per year, green and red in the year's
   real proportion so red doesn't look as common as green). "Show all links" adds kept links and
   arcs whose origin is inferred (90 per group).
4. **Opens on Finland + the Baltic** (lat 61.2, lon 23.5, altitude 0.62).
5. **Metric names:** How much is written / How much was edited / Where editors fought / What was
   rewritten. The one-line explanation of the selected metric is always shown under the toggle
   (a hover-only tooltip would be missed in a demo).
6. **Landing overlay** with the title, one explanatory sentence, "▶ Watch: the 1918 civil war" (starts
   the story) and "Explore freely" (**decision:** starts at 2004 and presses play, because a static 2004
   is nearly empty). Deep links (`?year=`, `?story=`, `?place=`) skip the overlay.
7. **English labels:** `labels_en.py` fetched the `en` label for all 11,428 places once (229 requests,
   cached in `data/place_labels.tsv`), stored in `place.en_label`; 5,643 differ from the Finnish title.
   Shown in tooltips, the place panel and, when short, on the globe ("Viipuri Vyborg").
   `places.py` refills `en_label` from the cache.
8. **Full scale:** 700 strongest places as dots (+ countries as polygons), 220 arcs by default; marks
   are sized in degrees, so dot radius and arc width now shrink when the camera zooms in. Place names
   are decluttered with label width taken into account. Place panel lists the 200 articles that
   mention the place most, largest first, with the true total ("903 articles link here").
   Story captions updated to the full-scale numbers (65 / 107 / 112 places).

## Night run, task 4: screenshots (2026-11-14)

`cd web; npm run screenshots` → `docs/screenshots/` (headless Edge, 1600×900):
`landing`, `2005`, `2014`, `2018`, `2018-all-links`, `2007-where-editors-fought`,
`2013-what-was-rewritten`, `story-1918-2014`, `place-tampere-2018`, `sql-drawer`.

Fixed after looking at them:
- place names were things like "Kirjasalon tasavalta" and "Färsaaret": the API returns countries first,
  so the label list wasn't ordered by value → sorted by value in the frontend;
- red arcs looked as common as green (150 of each) → proportional to the year's totals;
- arcs and dots were huge after flying to a place → sizes scale with camera altitude;
- legend lines wrapped → shorter wording, wider box;
- top bar ran over the title when the side panel was open → subtitle hides, bar re-centres;
- landing text was hard to read over the globe labels → darker backdrop;
- place panel started with 1 KB stubs (ordered by mentions) → largest articles first.

Still imperfect: "Ahvenanmaan maakunta" can be half covered by the Helsinki label; centroid dots for
continents/regions ("Eurooppa", "Pohjoismaat") get labels in some metrics; play/pause, hover tooltips
and autoplay are still only checked through screenshots, not by hand.

## Combined app, stage 1: plan + backend (2026-11-14)

Branch `combined` (from `Jussi`) + `git merge origin/Kristian --allow-unrelated-histories`: both
histories kept. Plan, layout and every conflict: **`docs/merge-plan.md`**.

What was done:
- `web/` (globe) moved to `web/globe/` in its own commit before the merge, so the two frontends
  did not collide; the merge itself conflicted only in `.gitignore` (union).
- My scripts moved into Kristian's packages (`git mv`, history kept): `api.py → api/places.py`
  (an `APIRouter`), `ingest/{load_parquet,links,kinds,places,labels_en,place_links,build_heat,
  check_stage1}.py`, `db/{heat_sql,findings,findings_extra}.py`. `common.py` and
  `create_tables.py` removed in favour of `common/db.py` and `common/schema.py`.
  Run them as modules now: `.venv\Scripts\python -m ingest.place_links --all`.
- All my scripts ported from the `mariadb` connector to pymysql (`%s` placeholders). The place
  router still *shows* `?` SQL in the drawer and converts when it runs it.
- One schema, `db/schema.sql`: Kristian's tables + the place tables; `article` has both sets of
  columns. **Live table migrated without a reload** by `python -m common.migrate`: 5 instant ALTERs
  (`user→editor`, `text→content`, `+n_sentences`, `+sentence_order`, `title VARCHAR(512)`) in
  0.3 s, then `+rev_key`, `+title_key` (inplace). History kept (`system_versioning_alter_history=KEEP`).
- One API: `uvicorn api.main:app` = Kristian's sentence routes + my place router. `api/db.py`: one
  pool, and a missing table answers **503 "Not loaded yet: table X … Load it with: …"**, never a 500.
- Both old frontends served: `/` = globe (`web/globe/dist`), `/contested/` = React
  (`web/dist`, Vite `base: '/contested/'`; Kristian's catch-all SPA route replaced by the mount).
- `common.schema --reset` now refuses on a database whose `article` has > 100,000 versions
  (`ALLOW_RESET=1` to override): Kristian's tests reset `wiki_test`, which stays fine.
- `.env.example`: port 3307, database `wiki`. `dev.py places` / `places-dev` run the place pipeline.

### Checks
- **Place pipeline rerun from the new packages, all 19,742 articles:** places 157 s, place links
  204 s, heat + arcs 127 s (activity 67 s, was 192 s: the new `article` indexes). Every count equals
  the pre-merge build: `place` 11,428 · own locations 4,621 · `place_link` 133,491 (113,891 current)
  · 52,919 versions skipped by the noise filter · `revert` 45,668 · `heat_year` 169,973 ·
  `page_origin` 286,473 · `arc_year` 145,803.
- **Page 1150:** 4 / 65 / 107 / 112 places as of 2005 / 2010 / 2018 / now ✔.
  **2014-02-11 edit:** + Hennalan, Hämeenlinnan, Riihimäen, Suomenlinnan, Tampereen vankileiri,
  − Tampere, Suomenlinna ✔.
- **Tests: 64 passed** (`.venv\Scripts\python -m pytest`): Kristian's 33 (`test_history.py` builds its
  own `wiki_test`, both load modes; `test_sentences.py`) + 31 new in `api/tests/test_places.py`
  (the 1150 numbers, the camp edit, every place route, errors, every sentence route never 500s).
- **Kristian's routes on our database:** health, `/api/articles/1150/revisions` and
  `/api/revisions/{rev_id}` already answer 200 (they only need `article`); as-of, diff, contested,
  edit wars, drift, term drift, about, map, near, articles, stats answer 503 naming the missing table
  and its loader. The React app at `/contested/` loads and shows those messages.
- **API timings unchanged** (`python -m api.check_api`): every place endpoint 1–40 ms, the two
  "everything" calls 167 / 187 ms, none over 300 ms.

Problem hit: the first rerun used `places.py --all --no-lookup` and gave 4,618 own locations, not
4,621. One event location (Q2994644, used by 3 articles) was fetched live by the original run but is
not in `data/places.tsv`, and `--no-lookup` never calls the API. Rerun without the flag: 1 request,
numbers equal. `--no-lookup` is only for when another run is appending to the cache.

## Editor tool, stage 1: the proof (2026-11-14, branch `jussi-editor`)

New plan in CLAUDE.md: an editor tool (fi / sv / en differences + edit wars). Contracts with Kristian
(Verda, Gemma, React) in **`docs/contracts.md`**, mocks in `web/mocks/worklist.json`, `compare.json`.
(The earlier "combined stage 2" sentence load into `article` was not started; superseded by this plan.)

### Dataset S loaded (`python -m ingest.load_lang`, 163 s)
`lang_article` 29,460 rows (fi 19,285 · sv 4,921 · en 5,254), 69 MB · `lang_article_vector` 29,460
bge-m3 vectors, `VECTOR INDEX M=16 DISTANCE=cosine`, 250 MB · `lang_topic` **2,919** topics in all
three languages. No existing table touched. 162 topics have at least one truncated vector.

### Level 1: whole-article distance (`python -m db.lang_distance` → `data/lang_distance.txt`)
One `VEC_DISTANCE_COSINE` query over the 2,919 topics, **43 ms**.

| pair | median | p10 | p90 | max | R² explained by length |
|---|---|---|---|---|---|
| fi–sv | 0.244 | 0.164 | 0.355 | 0.585 | 25 % |
| fi–en | 0.235 | 0.162 | 0.337 | 0.605 | 23 % |
| sv–en | 0.204 | 0.130 | 0.310 | 0.603 | 28 % |

- **Most similar:** short biographies written alike (Bayard Taylor fi–sv 0.070, Arthur Hjelt fi–en 0.064).
- **Least similar: mostly not "different stories" but different subjects under one Wikidata id**:
  Renki / Farmworker (fi–en 0.605), Kirvu (former Finnish municipality) / Svobodnoye, Leningrad Oblast,
  Lauri Olavinpoika Björnram / Lasse Olsson (240 vs 41,642 chars), Punakaarti 69,580 vs Röda gardet 335 chars.
- **Length:** the bigger the length ratio, the larger the distance (r ≈ +0.5); length explains about
  a quarter of the variance. The residual after a length fit is the better ranking signal.
- **Heroes:** Niinistö fi–sv 0.242 (median), fi–en 0.149 (among the 7 % most similar).
  Suomen sisällissota fi–sv **0.350 (rank 320 of 2,919)**, fi–en 0.217.

### Level 2: sentence matching, Niinistö + 1918 war (`ingest.embed_cpu`, `db.lang_match` → `data/lang_match.txt`)
- Split with the new shared **`ingest.sentences.text_sentences()`** (S text is Markdown: drops `#`
  headings and `|` tables, strips `- `). Sentences: Niinistö fi 242 / sv 45 / en 169;
  1918 war fi 870 / sv 261 / en 558.
- Embedded with **bge-m3 on CPU** (sentence-transformers 6.3, torch 2.15 CPU, 16 threads):
  4,548 sentences (heroes + 20 random calibration topics) in 331 s = **13.7 sentences/s**.
  Model download 2.3 GB. → `lang_sentence` (53 MB, vector index M=16).
- Matching in MariaDB: exact best match per sentence within the topic
  (`VEC_DISTANCE_COSINE` + `ROW_NUMBER() OVER`), both directions → `lang_pair` 3,257 rows, **3.3 s**.
  Exact, not the vector index: a per-topic search with a `WHERE` would have the index filter after the
  ANN step. The index is for the "search all sentences" queries of stage 2.

**Threshold = 0.418 (cosine distance).** How: each Finnish sentence's best match in *unrelated* articles
of the other language (random topics, pool as large as the real article) is a "match by chance".
0.418 is the 5th percentile of those chance distances (sv 0.423, en 0.413 separately), so a closer
match happens by chance for only 5 % of sentences. The random topics are also Finnish history, so this
is conservative. **Caveat:** for the 1918 war the real and chance distributions overlap a lot
(median real fi→en 0.398 vs chance 0.495; real fi→sv 0.452 vs chance 0.503): much of a long article
is only loosely covered in the other language, and a single threshold is a blunt cut.

| topic | lang | fi sentences | matched | **missing** | lang sentences | only in lang |
|---|---|---|---|---|---|---|
| Sauli Niinistö | sv | 242 | 84 | **158** | 45 | 11 |
| Sauli Niinistö | en | 242 | 160 | **82** | 169 | 42 |
| Suomen sisällissota | sv | 870 | 241 | **629** | 261 | 146 |
| Suomen sisällissota | en | 870 | 547 | **323** | 558 | 140 |

(The Swedish Niinistö article is 4,277 characters against 29,153 in Finnish, so "missing in sv" is
mostly "the Swedish article is short".)

**5 clearest "missing in English"** (no en sentence closer than 0.418; distance to nearest en):
1. 1918 war fi#864 (0.610): *Heikki Kujanpään vuonna 2018 ohjaama Suomen hauskin mies on
   punavankileirille sijoittuva … draama* — the 2018 prison-camp film is not in the English film list.
2. 1918 war fi#666 (0.571): *"Lahdessa naisia eivät kuitenkaan teloittaneet saksalaiset, vaan
   suomalaiset"* — who executed women at Lahti; English only mentions the camp's rape stories.
3. 1918 war fi#843 (0.556): Uuno Pekka Kekäläinen's Hennala prison-camp diary (1973).
4. 1918 war fi#828 (0.548): the last White Army veteran, Lennart Rönnback, died in 2007.
5. Niinistö fi#205 (0.547): founded the Tukikummit foundation with Hjallis Harkimo.

**Numbers / dates:** 348 of 1,032 matched pairs have different numbers; 238 where *each* side has a
number the other lacks. Read the top ones: **none is a clear contradiction.** They are omissions or
different scope (fi "Helsinki 12–13 April, Hyvinkää 21 April …" vs en "Hyvinkää and Riihimäki 21–22
April"), approximations (about 400 White Guard units vs 375 on 26 Jan 1918), or a match on a
neighbouring claim (phase 1 ended 14 March vs the war ended 15 May). Number-diffing finds candidates;
deciding contradiction needs Gemma (stage 3). Footnote markers (`[130]`) are ignored.

### Problems
- `lang_topic` / `lang_pair` got the server default collation (uca1400) and failed to join
  `lang_sentence` (unicode_ci): all `lang_*` tables are now `utf8mb4_unicode_ci`.
- The first heading-and-list-blind split kept Markdown headings as sentences → `text_sentences()`.

## Editor tool, stage 1b: real data for Kristian's views (2026-11-14)

### Matching quality: mutual best matches (`db/lang_match.py`)
A pair is **matched** when the fi and sv / en sentence are each other's best match **and** closer
than 0.418 (`lang_pair.mutual`, `lang_pair.matched`). Stricter than stage 1: a sentence that only
points at a partner whose own best match is another sentence no longer counts (typically one English
sentence covering two Finnish ones: the second is now "missing").

| hero | lang | fi sentences | matched (stage 1, best only) | matched (mutual) | **missing (mutual)** | best-only, not mutual |
|---|---|---|---|---|---|---|
| Sauli Niinistö | sv | 242 | 84 | 26 | **216** | 58 |
| Sauli Niinistö | en | 242 | 160 | 84 | **158** | 76 |
| Suomen sisällissota | sv | 870 | 241 | 79 | **791** | 159 |
| Suomen sisällissota | en | 870 | 547 | 241 | **629** | 306 |

So "missing in English" is 158 (was 82) for Niinistö and 629 (was 323) for the 1918 war. The
best-only column is the price of mutuality: those sentences have a close English sentence that is
shared with another Finnish sentence.

### "Different subject" topics (`db/build_divergence.py`)
Flag = whole-article distance above the **97th percentile** (fi–sv > 0.413 or fi–en > 0.393: 153
topics) **and** under **10 %** of the shorter version's sentences matched, **and** that shorter
version has at least **5 sentences**. The last rule was added after looking at the data: stubs are not
different subjects (the 4-sentence Swedish *Röda gardet (Finland)* matches none of *Punakaarti*'s 474).
To decide, the 153 candidates were embedded on CPU (`ingest.embed_cpu --extreme 97`: 23,140
sentences, **23 min 27 s**, 18.4 sentences/s) and matched (175 topics, 14.6 s).

**10 topics flagged** (left out of the worklist, `?include_flagged=1` shows them), e.g.:
- *Lääninhallitus* (Finnish provincial office) | *County administrative boards of Sweden* — 0 % match
- *Teollisuuspatruuna* | *Ironmaster* — 0 %
- *Renki* (Finnish farmhand) | *Dräng* / *Farmworker* — 0 %
- *Tykkimyssy* | *French hood* — 6 %
- *Lapinkylä* (Sámi village) | *Siida* — 4 %
Also Vouti / Fogde, Koulukoti / Approved school, Käräjäkunta / Tithing, the list of Finland's wars.
**One looks wrong:** *Maunu Eerikinpojan maanlaki* | *Magnus Erikssons landslag* is the same law;
the Finnish and Swedish texts just share no sentence closely enough.

### Kristian's sentence tables loaded (all of dataset M, `article` not reloaded)
`python -m ingest.replay --dataset large --workers 14 --sentences-only` → **8 min 44 s**
(1,629 versions/s), after page 1150 alone (11 s).
- New mode `--sentences-only`: `article` already holds all 862,076 versions and its history rows can't
  be updated, so the per-version sentence order goes to a new table **`article_sentence_order`**
  (rev_id → n_sentences, sentence_order, kept). A version dropped by his blanking-vandalism filter gets
  the order of the last kept version, so a snapshot never shows vandal text. His queries
  (`as_of_article`, `map`, `revision`, `revisions`) read it first, then `article`'s own columns
  (so his `wiki_test` tests still pass).
- 19,595 articles (147 are redirects / empty today: no sentences; their 597 versions have no order row).
  Kept versions 857,477, dropped 4,002 → 857,477 + 4,002 + 597 = 862,076 ✔.
- `article_sentence` **1,393,147 lives** (723 MB) · `article_sentence_order` 3.1 GB (the hash blobs) ·
  `article_stats` 19,595 · `article_geo` 2,760 (geo index `python -m ingest.geo`: 7 s) ·
  `sentence_event_time` 497,939 sentences with a year (`ingest.event_time`, 19 s).
- **Checks:** 1150 keeps **3,345 versions** after his filter (12 dropped), 8,089 lives, the opening sentence
  has **19 lives**, 338 reverts, 1,008 current sentences — all equal to his numbers. Niinistö's opening
  sentence has had **83 lives**.
- All his routes answer 200 on real data: as-of 17 ms, edit wars 15 ms, contested 168 ms, diff 21 ms,
  term drift 107 ms, bitemporal about 288 ms, map 7 ms. **Drift is empty**: it needs `sentence_score`
  (`python -m scoring.score`), which was not run.

### Worklist + compare API (`api/editor.py`, format of `docs/contracts.md`)
- `article_divergence` (`python -m db.build_divergence`, 0.2 s): 2,919 topics, 175 with sentence data,
  all with an edit-war score. **Score = 0.6 · language difference + 0.4 · edit war** (percentile ranks).
  *Decision:* "missing" is shown but not scored yet. With weight 0.2 it ranked exactly the topics that
  happen to have sentence data first. It goes into the score when every topic has sentences (Verda).
- Top of the worklist: Muinaissukset, Hämäläiset, Talonpoika, Perussuomalaiset Nuoret, Uhtua,
  Suomen kansanvaltuuskunta … Suomen sisällissota rank 233, Niinistö 1,070.
- `GET /api/worklist` 7 ms (50) / 79 ms (all 2,909); `GET /api/compare/{id}` 13 ms (Niinistö),
  29 ms (1918 war, 1,369 rows) after adding `lang_pair.other_key`; without it 1.8 s.
  Topics without sentences answer `rows: []` + `note` (recorded in contracts.md).
- `tzdata` added to requirements (pyarrow needs it on Windows to read dataset M's times).
- Tests: **69 passed** (new `api/tests/test_editor.py` checks both routes field by field against the mocks).

## Editor tool: globe language lines + top-40 comparisons (2026-11-14)

### A. "Language differences" on the globe (`web/globe`, `GET /api/lang-lines`)
- Fifth button next to the metrics. Each topic in fi + sv + en is a dot at its place; lines go from it
  to **Stockholm (sv)** and **London (en)**, labelled at the ends "SV Swedish Wikipedia" / "EN English
  Wikipedia". Year slider and caption are hidden (dataset S is one snapshot, Aug 2025).
  Clicking a dot or a line opens `/contested/#compare/<wikidata_id>` (Kristian's React route).
  Legend entry + SQL drawer show the query. `/api/lang-lines`: 2,682 topics, 88 ms.
- **Where a topic is:** page_place (Wikidata, 860), else article_geo (Finnish wikitext coordinates, 7),
  else **inferred** = the place its Finnish article links most today (`page_origin` 2026, 1,815; drawn
  as a smaller dot, the tooltip says so). *Decision:* without the inferred places only 867 topics had a
  place and Niinistö was missing. **Niinistö lands at Salo** (his birthplace, his article's most-linked
  place), not Helsinki as CLAUDE.md's example says: the data's answer, kept.
- **Colour:** percentile of the distance within each language (green = closer to the Finnish article
  than most, red = among the most different), not the raw distance: raw values cluster around the
  median and everything looked orange. **Only the 15 % most different lines per language are drawn
  clearly**; the rest are a faint haze. Two earlier versions (all lines equally visible; then a cubic
  fade) were a red hairball at 2,682 × 2 lines. Dot colour = mean of the two percentiles.
- Different-subject topics are hidden. Screenshots: `docs/screenshots/language-differences.png`
  (Europe view, the default for this mode) and `language-differences-finland.png` (`?view=home`).
- Still dense over Finland: most topics are Finnish places. The bright lines and the labels (most
  different first) carry the message; zooming in helps.

### B. Real comparison rows for the top 40 of the worklist
`ingest.embed_cpu --topics <top 40 by rank, different-subject excluded>` (list in `data/top40.txt`):
18 were already embedded as extreme candidates; the other 22 = **5,366 sentences in 6 min 58 s** (15.0
sentences/s), then `db.lang_match` (40 topics, 2.9 s) and `db.build_divergence`.
**197 topics now have sentence data** (heroes + 20 calibration + 153 candidates + 22). `/api/compare`
returns real rows for all of the top 40 (e.g. Muinaissukset: 10 ms).
Honest caveat: the top of the worklist is dominated by topics where the Finnish article is far longer
(Muinaissukset: 706 Finnish sentences, 696 missing in English). That is real missing content, but it
means "most different" ≈ "Finnish is much longer" for many topics.

### C. Checks
Tests **70 passed** (+ `test_lang_lines_for_the_globe`). Screenshots of the normal modes re-taken
(2014, landing, story) and unchanged apart from the new button.

## Editor tool, stage 1c: a worklist editors can use (2026-11-14)

### 1. "Missing" = nothing within the threshold
`missing_sv` / `missing_en` = Finnish sentences whose **nearest** sv / en sentence (mutual or not) is
not closer than 0.418. Alignment in `/api/compare` stays mutual; a Finnish row that is not aligned but
has a close sentence gets it in **`covered_by`** and counts as present in `status`.

| hero | fi sentences | missing sv | missing en | sv sentences missing in fi | en sentences missing in fi |
|---|---|---|---|---|---|
| Sauli Niinistö | 242 | **158** | **82** | 11 of 45 | 42 of 169 |
| Suomen sisällissota | 870 | **632** | **323** | 146 of 261 | 141 of 558 |

(Stage 1b, mutual-only: Niinistö en 158, 1918 war en 629.) In compare, Niinistö has 76 rows covered in
English and the 1918 war 306. **Caveat:** coverage within 0.418 can be topical, not factual: Niinistö's
"the euro was adopted during his ministry" is "covered" by "he became vice president of the European
Investment Bank" (0.388). Gemma (stage 3) must judge covered pairs too.

### 2. Score = length-adjusted difference + edit war
- For each pair, a least-squares fit over all 2,919 topics:
  `distance ≈ a + b·|ln(len_fi / len_other)| + c·ln(min(len_fi, len_other))` (lengths in characters, +1).
  fi–sv: `0.179 + 0.042·|ln ratio| + 0.0030·ln(shorter)`, R² 25 %; fi–en: `0.220 + 0.037·|ln ratio|
  − 0.0027·ln(shorter)`, R² 23 %. The **residual** (`fi_sv_resid`, `fi_en_resid`) is what length does
  not explain; positive = the versions say different things, not just more or less.
- `score = 0.6 · mean(percentile of fi_sv_resid, percentile of fi_en_resid) + 0.4 · edit-war percentile`.
- New **`missing_in_fi`** (`{sv, en}`): sv / en sentences with no Finnish sentence within 0.418, for the
  197 topics with sentence data. Shown, not scored (only 197 of 2,919 have it; see stage 1b).
- Effect: Suomen sisällissota rises from rank 233 to **79**; Niinistö 1,070 → 1,240.

**New top 10, and why** (residual percentile fi–sv / fi–en, edit-war percentile; lengths fi / sv / en):
1. **Sortovuodet** | Förtrycksperioderna i Finland | Russification of Finland — p95 / p97, war p95. The
   Finnish article is the *shortest* (3.6k vs 8.4k / 7.8k chars) yet far from both: it frames the period
   as "the years of oppression, a name given afterwards"; English frames it as a *policy* of the Russian
   Empire. Not a length artefact.
2. **Talonpoika** | Allmoge | Peasant — p99 / p99, war p91. Three different concepts: the Finnish
   land-owning farmer of the estate society, a Swedish stub on *allmoge* as a social group (432 chars),
   the feudal peasant in English. Close to a "different subject"; not flagged because the Swedish
   version is under 5 sentences. **Candidate for the override list.**
3. **Korjausliike** | De Blåa | Finnish Reform Movement — p99 / p93, war p95 (465 revisions). A party with
   three names; the Finnish article is detailed (10.7k), Swedish a stub (0.6k).
4. **Hämäläiset** | Tavaster | Tavastians — p97 / p99. Finnish: the people of Häme, present tense ("are");
   Swedish and English: an ancient tribe, past tense ("were"). A real framing difference.
5. **Uhtua** | Kalevala (stad) | Kalevala, Russia — p99 / p95. Finnish uses the Karelian/Finnish name
   and history; Swedish and English describe a Russian urban locality and its census figures.
6. **Suomen kansanvaltuuskunta** | Finska folkdelegationen | Finnish People's Delegation — p96 / p92, war
   p95. The Reds' government of 1918; Finnish 40.9k chars vs 5k / 7.8k: much more, and differently
   weighted, even after the length fit.
7. **Kalastajasaarento** | Fiskarhalvön | Rybachy Peninsula — p94 / p97. Same peninsula; Finnish tells it
   as part of Petsamo's (Finnish) history, English as "the northernmost part of continental European Russia".
8. **Pähkinälinna** | Nöteborg | Shlisselburg — p97 / p95. The Finnish title is the fortress name, the
   article (and the others) are about the town; different emphasis and name history.
9. **Vatja** | Votiska | Votic language — p99 / p98. The language; Swedish is a 702-character stub,
   English (13k) covers the speakers and revival in depth.
10. **Viipurin linna** | Viborgs slott | Vyborg Castle — p92 / p94, war p94 (239 revisions, 54 reverts).
    Finnish starts from the Karelian trading post the castle replaced; Swedish from its founding by the
    Swedish regent Torgils Knutsson in 1293; English "built by the Swedes". Whose castle it was is told
    differently.
*Honest note:* the reasons come from the scores plus reading the three openings; the sentence-level
evidence is in `/api/compare/<id>` (all ten have sentence data except Viipurin linna).

### 3. Different-subject overrides
`db/subject_overrides.tsv` (wikidata_id, same|different, note) wins over the rule. First entry:
**Q339275 Maunu Eerikinpojan maanlaki = same subject** (the same law). Now **9** topics flagged.

### 4. Contract + mocks
`docs/contracts.md`: missing = nothing within 0.418; worklist `missing_in_fi: {sv, en}`; compare rows
`covered_by: {sv, en}` (cell or null), `status` counts covered as present; an sv / en sentence that is
close but not aligned is not a row of its own. `web/mocks/worklist.json` and `compare.json` updated
(compare: Niinistö fi#4 is now covered in Swedish).

### 5. Checks
Tests **72 passed** (new: worklist and compare agree on missing counts; the override holds).
`/api/compare` 49 ms (1918 war) / 140 ms cold (Niinistö).

## Editor tool: Gemma 27B judgements imported (2026-11-14 evening)

Jesse's Verda run (Gemma 3 27B, `google/gemma-3-27b-it`) arrived as `judgements.parquet`,
`judgements-detail.csv` and `sentences-{fi,sv,en}.parquet`; copied to `data/verda/` (gitignored).
There was no `judgements-v2-12b.parquet` yet, so "both models agree" is built and tested, but no real
pair has it.

### 1. Import: `python -m ingest.load_judgements`
- **Numbering check:** Jesse's sentences equal our `lang_sentence` exactly on the hero topics:
  - fi 1,112 (242 + 870), sv 306, en 727
  - same `sent_no`, same text, 0 differences
  - All **430** judged pairs are our mutual matches, and the detail CSV's texts agree too.
- **Table:** `pair_judgement` gains `fi_claim`, `other_claim`, `same_specific_fact`, `source_file` and
  `imported_at`. The table already existed (empty), so the new columns are added with
  `ADD COLUMN IF NOT EXISTS`.
- **Re-runnable:** a model's rows for the topics in a file are replaced, and other models' rows are
  kept. The second run reported "replaced 430". A file whose sentence numbers are not in
  `lang_sentence`, or whose sentence texts differ, is refused before anything is written (tested).
- **Import time:** 0.2 s for 430 rows.

| topic | judged pairs | same | partial | framing | contradiction |
|---|---|---|---|---|---|
| Sauli Niinistö | 110 | 37 | 71 | 2 | 0 |
| Suomen sisällissota | 320 | 59 | 202 | 44 | 15 |
| **all** | **430** | 96 | 273 | 46 | 15 |

**Honest check of the 15 contradictions (all in the civil war), read by hand:**
- **7 are real differences in a date or number for the same thing:**
  - Mannerheim's resignation: 27 vs 25 May
  - Vaasa senate back in Helsinki: 2 vs 4 May
  - Reds at Viipuri: 7,000 vs 15,000
  - the March manifesto: 20 vs 15 March
  - the armistice: 15 vs 6 December
  - Mannerheim's disarmament order: 25 vs 27 January
  - each side's strength: 80,000 vs about 100,000
- **8 compare different scopes or events:**
  - combat deaths vs all deaths
  - prisoners taken vs prisoners in camps at the end
  - 1921 vs 1919 prisoner counts
  - the Tokoi senate: Gemma took the 1916 election year for the senate's year
  - and similar
- `same_specific_fact` was true for all 15, so it does not filter these out.

So precision is about 50 %. That is why the UI says **"Possible contradiction, check the sources"**,
never "contradiction". A second model (the 12B run) agreeing should raise precision; that is what
`both_models_agree` is for.

### 2. `/api/compare`
- Each row's judgements carry `label`, `reason`, `model`, tones, `fi_claim`, `other_claim`,
  `same_specific_fact`, `note` and `both_models_agree`.
- They are attached only when they judge that row's own aligned (or covered) pair. All 430 land
  (110 + 320).
- New top-level `contradictions`: one entry per contradiction pair, "both models agree" first, then in
  text order. `row` points into `rows`; rows themselves stay in text order, since alignment needs that.
- Time: 1918 war compare ~20 ms.

### 3. `/api/worklist`
- New fields: `contradictions`, `framing` and `judged_pairs`, live from `pair_judgement` for the
  primary model (`judged_by: google/gemma-3-27b-it`), and `null` for unjudged topics.
- Not in the score yet. `article_divergence.contradictions` uses the same model.

### 4. Override
- **Talonpoika (Q838811) is now a different subject.** fi = the land-holding farmer of the estate
  society; sv = *Allmoge*, the common people of a district; en = the feudal peasant in general.
- 10 topics are flagged now, and the worklist moves up one:
  1. Sortovuodet
  2. Korjausliike
  3. Hämäläiset
  4. Uhtua
  5. Suomen kansanvaltuuskunta
  6. Kalastajasaarento
  7. Pähkinälinna
  8. Vatja
  9. Viipurin linna
  10. Suomen pääministeri (new)
- Civil war is rank 78, Niinistö 1,239.

### 5. Contract, mocks and checks
- `docs/contracts.md` b and c, plus both mocks, are updated (the compare mock shows a 12B second opinion
  agreeing on one pair).
- Tests: **76 passed**. New tests:
  - judgement counts agree between the worklist, compare and the table
  - agreement and sort order (pure function)
  - the import refuses unknown sentence numbers
  - Talonpoika is flagged

### 6. Second model: Gemma 3 12B (`judgements-v2-12b.parquet`)
Imported next to the 27B with `python -m ingest.load_judgements data/verda/judgements-v2-12b.parquet`:
- 430 rows, on the same 430 pairs; numbering verified; took 0.2 s.
- `judgements-v2-27b.parquet` is byte-identical to `judgements.parquet`, so it was not imported again.
- 12B labels: 222 same, 190 partial, 12 framing, 6 contradiction.
- The 12B is clearly more lenient: it calls 108 of the 27B's "partial" pairs and 23 of its "framing"
  pairs "same".

Agreement: the same label on **260 / 430 pairs (60 %)**.

| 27B \ 12B | same | partial | framing | contradiction |
|---|---|---|---|---|
| same | 88 | 8 | 0 | 0 |
| partial | 108 | 160 | 3 | 2 |
| framing | 23 | 15 | 8 | 0 |
| contradiction | 3 | 7 | 1 | 4 |

**Contradictions both models agree on: 4. Of these, 3 are real:**
- the armistice: 15 vs 6 December
- the Vaasa senate: 2 vs 4 May
- Mannerheim's disarmament order: 25 vs 27 January
- The fourth is "nearly equal combat deaths" vs "five times more Reds killed", which compares different
  scopes.

**Precision:** about 75 % when both models agree, against 7 / 15 ≈ 47 % for the 27B alone. The price is
recall: of the 27B's 7 real ones, 4 are missed by the 12B (Mannerheim's resignation, Viipuri, the March
manifesto, 80k vs 100k). So the UI shows both, with "both models agree" first.

**The 12B's own 2 contradictions (Niinistö):**
- 37 % vs 62.7 %: the first round vs the second round, a false alarm.
- The Order of the Seraphim collar, 2014 vs 2016: a **real** difference the 27B called partial.

`/api/compare/Q211855` now lists the 4 agreed contradictions first ("Possible contradiction, check the
sources (both models agree)"), then the 11 that only the 27B flags. The worklist counts stay on the
27B. Tests: 76 passed.

## Combined: jussi-editor + jesse-editor merged (2026-11-14 night)

**Merge** (`combined`):
- `origin/jussi-editor` merged as a fast-forward.
- `origin/jesse-editor` (worklist and compare React views, Verda embedding script, Gemma judge and eval,
  process log) merged with one conflict, in `docs/contracts.md` b: both sides added `fi_claim`,
  `other_claim` and `same_specific_fact`. Resolution:
  - Jesse's sharper column definitions and label rules.
  - My import paragraph.
  - Both change-log entries.
- NOTES.md, process-log and mocks merged cleanly.

**Real API in the build:** `web/.env.production` sets `VITE_EDITOR_MOCKS=0`, so `npm run build` (served
under `/contested/`) uses `/api/worklist` and `/api/compare`. `npm run dev:mock` still uses the mocks.

**Wiring Jesse's views to the real responses** (small changes to `web/src/views/Compare.jsx`):
- `covered_by`: a covered sentence is shown in grey with "covers it", instead of "Missing".
- All models' judgements per cell: the tooltip lists each model's reason; the fix panel says which models.
- Wording: "Possible contradiction"; the fix panel uses the API's `note` ("… check the sources (both
  models agree)").
- New "Possible contradictions" panel above the grid (`contradictions` from the API): the 4 where both
  models agree come first; a click jumps to the row and opens its fix panel.
- Worklist: a "Framing" column next to "Possible contradictions".

**Globe:** new `?topic=Q…` parameter for language mode: only that article's dot and two lines.
- Why it was needed: 9 topics sit at Finland's centre point (65 N, 27 E: their `page_place` is "Suomi",
  the 1918 war among them), and their lines to London overlap exactly. Hovering there showed another
  article, and a click opened another topic (Q1255927).

**Playwright check** (`cd web/globe; npm run editor-flow`, real API):
- globe → hover the 1918 war's English line → click → `/contested/#compare/Q211855`
- No mock note; 1,157 rows; 271 label tags; 15 possible contradictions, **the 4 "both models agree"
  first**; click one → its row and fix panel.
- Screenshots: `docs/screenshots/editor-flow-{0-globe-language,1-globe-line-hover,2-compare,3-contradiction-row,4-gemma-reasons}.png`.

Tests: 76 passed.

## Demo app: worklist -> article page -> map (2026-11-15)

The app is simplified for the 3-minute demo. Everything not listed below is hidden, not deleted:
- `/` redirects to the worklist at `/contested/`.
- The old React app (globe tab, time slider, narrative drift…) is at `/contested/#legacy`.
- The old place globe (year slider, heat metrics, arcs, the 1918 story, the language lines) is at `/globe/`.
- Old `#compare/Q…` links open the new article page.

**Data added:**
- `ingest/load_categories.py`: dataset S's Finnish category tree in `category_link` (1,760 parent→child
  links, child = subcategory or article) and `article_category` (25,720 rows). All 2,919 topics have a
  category.
- `db/build_topic_place.py`: `topic_place`, the map position of each topic, by the globe's rule
  (`page_place` → `article_geo` → inferred most-linked place). 2,688 of 2,919 topics have one
  (860 page_place, 7 article_geo, 1,821 inferred).
- `scripts/make_nordic_map.py`: `web/public/nordic.json`, built from Natural Earth 1:10m (public domain)
  countries and lakes. It is clipped to lon −30…75 / lat 40…82 and simplified at 0.012°, giving 60
  countries, 288 lakes and 41k points in 652 kB. The globe's file had 40 points for all of Finland.

**API (`api/explore.py`); every answer carries its SQL and ms:**
- **`/api/topics?q=&mode=meaning|title&chip=`:** the worklist.
  - Semantic search embeds the query with bge-m3 on CPU (`common/embed.py`): loaded once in a
    background thread at server start (~10 s), local Hugging Face cache only, ~45 ms per query after
    that.
  - It ranks topics by `VEC_DISTANCE_COSINE` against dataset S's article vectors in fi, sv and en: the
    nearest 300 vectors, using the vector index with `mhnsw_ef_search=80` and the search in a subquery,
    as the RAG repo found, then MIN distance per topic, top 60.
  - So "civil war prison camps" (English) finds *Suomenlinnan / Tammisaaren / Tampereen vankileiri*.
  - Title search is `LIKE` on the three titles.
  - The chips are a recursive CTE, `WITH RECURSIVE cat` over `category_link` (category + 2 levels),
    then `article_category`.
- **Topic chips:**

  | chip | category root | topics |
  |---|---|---|
  | Civil War 1918 | Suomen sisällissota | 9 |
  | Presidents | Suomen presidentit | 7 |
  | Winter and Continuation Wars | Talvisota + Jatkosota | 17 |
  | Swedish era | Ruotsin vallan aika Suomessa | 105 |
  | Russian era | **Suomen suuriruhtinaskunta** | 208 |

  The tree has no "Venäjän vallan aika", so the Russian era uses the Grand Duchy, its nearest category.
  Civil War has only 9 topics: of the 79 Finnish articles in that category, only 9 exist in all three
  languages.
- **`/api/similar/{id}`:**
  - `SET @v = (the article's fi vector)`, then the 200 nearest Finnish article vectors (index), kept
    when they are mapped topics, top 10.
  - The vector index there: 12–20 ms warm, recall 60/60 against the exact scan on a test query.
  - The exact scan of 29k vectors is 43 ms; the index matters for the 358k sentence vectors, not for
    these.
- **`/api/topic-places`, `/api/chips`, `/api/queries/{name}`:** the last gives the text of
  `db/queries/*.sql`, for the SQL drawer of Kristian's views.
- **`/api/compare`:** gains `topic.page_ids` (contract updated).

**Frontend (`web/src`):**
- `App.jsx`: hash routes `#/list?q=…&chip=…`, `#/map?…`, `#/article/Q…/languages|edits`. The filter is
  shared by the list and the map.
- `FilterBar`: search box with Meaning / Title toggle, topic chips, the count and the embed time.
- `ArticleList` ("Articles that need an editor's attention"), sortable columns:
  - title (fi + en)
  - language difference (sv / en distance)
  - missing content (% of Finnish sentences missing in sv / en)
  - possible contradictions (with "N agree")
  - edit wars
  - score
- `ArticlePage`: breadcrumb back to the (filtered) worklist.
  - Tab "Languages": the compare view, possible contradictions on top, both-models-agree first.
  - Tab "Edit wars": Kristian's edit wars / contested sentences / article on a date for the Finnish
    article, each with its SQL.
- `MapView`, 2D canvas:
  - **Projection and layers:** Lambert azimuthal equal-area centred on Finland. Land and lakes are
    `Path2D`s built once and cached on an offscreen layer per view, so a hover redraws only dots and
    lines.
  - **Dots:** coloured by score; with a semantic search, size = similarity.
  - **Stacking:** articles at the same place (Helsinki has 400, Turku 51, St Petersburg 40) fan out in a
    sunflower spaced ~3.5 km on the map, so a city is a dense cluster from afar and opens up when you
    zoom in.
  - **Lines:** hover or click → lines to the 10 most similar articles (bent, drawn in, thicker = more
    similar), at most 20 on screen (hover + pin).
  - **Card:** clicking the name opens the article page.
  - **View:** fit to the filter (Finland always in view), wheel zoom and drag pan, never zoomed out past
    the data.
- **SQL drawer:** one for the whole app (`useSql`), tabbed by query, with the ms of each.

**Speed** (Playwright `web/scripts/demo-flow.mjs`, Edge, 1440×900, real API):

| step | ms |
|---|---|
| landing → worklist rendered (2,909 rows) | 490 |
| semantic search "sisällissota" → list | 313 |
| chip "Civil War 1918" | 157 |
| open article → Languages tab | 345 |
| Edit wars tab / Contested / Article on a date | 229 / 230 / 221 |
| map for "sisällissota" | 79 |
| click a dot → 10 similar + lines | 17 |
| map card name → article page | 243 |
| map, all 2,616 dots on the map | 195 |

A map frame takes 0.4 ms with 60 dots and 1.9 ms with all 2,616, plus the cached base layer.

Screenshots: `docs/screenshots/demo-{1-worklist,2-search,2b-search-sql,3-chip,4-article-languages,5-article-editwars,6-article-contested,7-article-asof,8-map-search,8b-map-hover,9-map-dot,10-map-all}.png`.

Honest notes:
- **Placement:** 1,821 of the 2,688 places are inferred (the place the article links most). The 1918
  war sits at Finland's centre point (its `page_place` is "Suomi").
- **Similarities:** semantic search scores are low and close (0.45–0.53), because a 2–5 word query
  against a whole article is a weak signal. The ranking is still right for the demo queries.
- **Map scope:** 66 mapped topics lie outside the map's area (the Americas, Asia…); the legend says so.
- **Judgements:** `judgements-27b-top300.parquet` (Jesse's 7,399-pair run) has not arrived. Only its run
  log `judge_run-27b-top300.json` and `judgements-12b-contra.parquet` are in Downloads. Until then, only
  the two hero topics have Gemma labels.

## GPU sentences for all 2,919 topics, rematch, missing content in the score (2026-11-15)

### 1. Load: `python -m ingest.load_verda_sentences`
- **Source:** Jesse's Verda run, `data/verda/sentences-{fi,sv,en}.parquet` (bge-m3 fp16, the shared
  splitter).
- **Method:**
  - Loaded into `lang_sentence_new` without a vector index, checked, then indexed.
  - Swapped in with one `RENAME`; the CPU rows are kept as `lang_sentence_cpu` for rollback.
- **Counts:** fi **167,278**, sv **72,023**, en **119,252** (358,553), every topic in all three
  languages, equal to the files and to the requested numbers.
- **Against the 33,054 CPU sentences:**
  - All present, all texts identical.
  - Vector cosine distance mean 1.2e-6, **max 9.0e-4**: a few sentences differ more than the 2e-5 Jesse
    measured on his sample. Harmless at a threshold of 0.418.
- **Time:** rows 86 s (fi 20 s, sv 24 s, en 42 s); `ADD VECTOR INDEX` (M=16, cosine) **7,032 s**
  (1 h 57 min, single-threaded HNSW inserts while the ALTER copies). Total 7,129 s.
- **Stale statistics:**
  - After the `RENAME` the optimiser estimated 1 row and used `PRIMARY (lang, …)` instead of
    `topic_key (wikidata_id, lang)`. Every per-topic match query scanned a whole language: 19 s instead
    of 0.13 s for Niinistö.
  - `ANALYZE TABLE lang_sentence` fixed it; the loader and `lang_match` now run it.

### 2. Rematch: `python -m db.lang_match --workers 8`
- **Result:** all **2,919** topics; `lang_pair` 525,831 rows, 143,484 mutual, 125,968 matched
  (mutual and < 0.418).
- **Wall time 889 s, misleadingly:**
  - The first ~515 topics ran on stale statistics (~840 s).
  - After the `ANALYZE` the other ~2,400 took **~50 s**.
  - A clean run is about a minute on 8 connections.
- **Missing counts:** `missing_*` and `missing_in_fi_*` are now computed for all 2,919 topics
  (`db.build_divergence`, 1.8 s).

### 3. Score with missing content
- **Formula:** `score = 0.3 · distance + 0.3 · missing + 0.4 · edit_war`, each a percentile.
- **Missing part:** the mean percentile of the length-adjusted *unaligned share* for sv and en:
  - `unaligned_l = (missing_l + missing_in_fi_l) / (fi_sentences + l_sentences)`: the share of both
    versions' sentences with no counterpart closer than 0.418, in either direction.
  - Length-corrected like the distance: least squares over all 2,919 topics,
    `share ≈ a + b·|ln(n_fi/n_l)| + c·ln(min(n_fi, n_l))` (sentence counts), residual ranked.
  - Fits: sv `0.377 + 0.165·|ln ratio| + 0.0125·ln(shorter)`, R² **41 %**; en
    `0.384 + 0.184·|ln ratio| − 0.0048·ln(shorter)`, R² **43 %**. Length explains even more of the
    missing share than of the distance (23–25 %), so the correction matters.
- **Stored per topic:** `p_distance`, `p_missing`, `p_edit_war`, which explain a rank.

**New top 10** (all at p86–99 on both language parts and p82–98 on edit wars):

| # | fi / sv / en | why |
|---|---|---|
| 1 | Sortovuodet / Förtrycksperioderna / Russification of Finland | Finnish is the shortest (25 sentences vs 79 sv, 47 en) and frames it as "years of oppression"; 71 Swedish and 39 English sentences have no Finnish counterpart |
| 2 | Uhtua / Kalevala (stad) / Kalevala, Russia | the Finnish article is the Finnish history of the village; sv / en describe today's Russian town (census, economy); 25 / 23 of 26 Finnish sentences missing |
| 3 | Kalastajasaarento / Fiskarhalvön / Rybachy Peninsula | Finnish tells it as part of Petsamo's Finnish history, en as "the northernmost part of continental European Russia" |
| 4 | Hämäläiset / Tavaster / Tavastians | Finnish "are a people" (56 sentences); Swedish a 3-sentence stub, English 13 sentences: "were a tribe" |
| 5 | Viipurin linna / Viborgs slott / Vyborg Castle | Finnish starts from the Karelian trading post, sv / en from the Swedish founding (1293); 34 English sentences have no Finnish counterpart |
| 6 | Karjalankannas / Karelska näset / Karelian Isthmus | English (176 sentences) is today's Russian geography, administration and towns; Finnish centres on Finnish history and lists the 1939 Finnish municipalities; Swedish 14 sentences; edit war p98 |
| 7 | Pähkinälinna / Nöteborg / Shlisselburg | the Finnish title is the fortress, all three are about the town; Finnish is the short one (25 vs 57 / 77) |
| 8 | Karjaa / Karis / Karis | Finnish and Swedish are both full local articles but cover different things (fi: villages, dialect, food culture; sv: election results 1976–2004, business); English a 9-sentence stub; 1 possible contradiction |
| 9 | Vatja / Votiska / Votic language | Swedish a 734-character stub; English (101 sentences) covers speakers and revival in depth; 2 possible contradictions |
| 10 | Heimosodat / Frändefolkskrigen / Heimosodat | the same wars told differently: fi by expedition (Vienan retket, Aunus, Petsamo, memorial crosses), sv by region with background and the Tartu peace; fi "about 9,000 volunteers" vs sv "about 10,000" |

Sortovuodet, Uhtua, Kalastajasaarento, Hämäläiset, Viipurin linna, Pähkinälinna and Vatja were already
in the stage-1c top 10 (distance + edit war only). The missing-content part brings in Karjalankannas,
Karjaa and Heimosodat.

**Heroes:**
- **Civil war:** rank **78 → 226**. Distance p77, edit war p100, but missing **p42**: its unaligned
  share is high in raw terms, yet the Finnish article is 870 sentences against 261 / 558, and the length
  fit explains most of it.
- **Niinistö:** rank 1,239 → 1,216.

### 4. Hero numbers unchanged
Compared with a snapshot taken before the reload:
- **Unchanged:** sentence counts, missing_sv / missing_en and missing_in_fi_sv / _en for Niinistö
  (242 / 45 / 169; 158 / 82; 11 / 42) and the civil war (870 / 261 / 558; 632 / 323; 146 / 141).
- **Pair level:**
  - 5 of 3,257 best matches changed partner, all near-ties: the two candidates were 0.0001 apart, e.g.
    0.4106 vs 0.4107.
  - 4 mutual flags changed.
  - On unchanged pairs, no distance moved more than 0.00065.

### 5. Judgements imported: `python -m ingest.load_judgements`
- **Files and order:** `judgements.parquet` (27B, heroes), `judgements-v2-12b.parquet`, **`judgements-27b-top300.parquet`** (7,399
  pairs, 300 topics), **`judgements-12b-contra.parquet`** (269 pairs, the 12B on the 27B's
  contradictions).
- **Newest wins:** each file replaces its model's rows for its topics. The default order is now
  oldest-first by file time, so the newest run of a model wins: the civil war uses the top-300 run,
  Niinistö keeps the hero run.
- **Totals:** 27B 7,509 rows / 301 topics (269 contradictions in the top 300); 12B 379 rows / 140 topics.
- **"Both models agree": 47 contradictions in 38 topics.**
- **Pairs no longer mutual:** 12 judged pairs in the top-300 run (and 2 + 2 in the hero files) are no
  longer mutual matches after the GPU rematch (near-ties). They are kept, but do not attach to a row.
- **Civil war on its article page:** 16 possible contradictions, **5** where both models agree, first.

### 6. Checks
- Tests: **83 passed, 1 skipped** ("compare without sentence data" has no topic left to test).
- The judgement test now allows for flipped near-ties.
- Demo flow (`web/scripts/demo-flow.mjs`) passes with the new data, same timings: every step under
  ~330 ms; the map click is 11 ms.
- **Map bug fixed:** hovering a dot whose neighbours were still loading could throw
  (`shownSim.sql` undefined).

## Map: 3D globe by default, 2D world map as the light option (2026-11-15)
- **3D (default):** `web/src/views/map/Map3D.jsx`, globe.gl (lazy-loaded), styled like the original
  globe:
  - **Base:** the dark earth texture with relief, the dark sky, the blue atmosphere, country outlines
    (`web/public/world3d.json`), Finland highlighted.
  - **Dots:** coloured by score, sized by similarity in a semantic search. A dot's size is a distance on
    the ground, so dots shrink as you zoom in. Stacked articles (Helsinki has 400) spread at least 1.8
    dot radii apart, recomputed after each zoom.
  - **Arcs:** hover or click → gold arcs to the 10 most similar articles, with flowing dashes and name
    labels. The camera sits a little south of the filter, so the arcs show their curve.
- **2D (toggle, remembered in the browser):** `Map2D.jsx`, now the **whole world** in the Equal Earth
  projection, from `web/public/world.json` (Natural Earth 1:10m; detailed in Northern Europe, simplified
  elsewhere, big lakes everywhere; 78k points, 1.3 MB; `scripts/make_world_map.py`, which replaces
  `make_nordic_map.py`). Zoom out to the whole world; city names appear when you are close.
- **Shared code:** data, dots, neighbours and colours are in `map/shared.js`; the card, tooltip, legend
  and SQL are in `MapView.jsx`. Without WebGL, the map starts in 2D.
- **Playwright** (`web/scripts/demo-flow.mjs`) checks both modes: hover the civil war's dot → click → 10
  similar articles → card name → article page.
  - **2D:** click 9–14 ms, frame 0.2–0.4 ms.
  - **3D:** timings measured with software WebGL (SwiftShader, ~3 frames/s in headless Edge), so they say
    nothing about a laptop GPU; check the 3D globe on the demo machine.

### Map: blobs for crowded places, the same lines in 3D and 2D (2026-11-15)
- **Blobs:** all the articles at one place are now one **blob** on both maps. This replaces the
  sunflower spreading.
  - **Size:** grows with the log of the count.
  - **Colour:** the blob's most urgent article.
  - **Count:** written inside big blobs (3D: 20+).
  - **Hover:** shows the place, the count and the most urgent article.
  - **Click:** lists the articles (most urgent, or closest to the search, first). A name selects that
    article (lines, card), and → opens its article page.
  - **Scale:** 2,682 placed articles sit at 1,244 places. The civil war shares "Suomi" (Finland's centre
    point) with the Winter War, the Continuation War and Isoviha, a blob of 4.
- **Lines:** the 3D lines now follow the 2D map: solid (no flowing dashes), low over the surface,
  thicker and brighter = more similar, drawn in once. They are light blue on the dark globe and dark
  blue on the light 2D map. `linesFor()` in `map/shared.js` builds them for both.
- **Demo flow:** hover the blob → click → list → pick the civil war → 10 similar + lines → card →
  article. Passes in 3D and 2D; in 2D the blob click takes 6 ms and the pick 56 ms.

### Map: flat 3D dots like the 2D map, no overlapping marks (2026-11-15)
- **3D marks:** flat discs with a white outline lying on the surface (globe.gl's object layer:
  `CircleGeometry` + `RingGeometry`, `objectFacesSurface`). They replace the cylinder points, so the
  globe's dots look like the 2D map's.
  - **Size:** `sizeOf()` in `map/shared.js`, the same rule on both maps. The size on screen stays about
    3–4 px whatever the zoom (0.2 × camera altitude, in degrees).
  - **Colours:** parsed as sRGB, the same as 2D; `new Color(r, g, b)` had treated them as linear and
    washed them out.
- **No overlaps:** zoom-dependent clustering (`useClusters()`). Each view reports how big one article is
  on the ground at its zoom (2D: px → km; 3D: degrees → km). Marks whose circles would touch merge into
  one blob, biggest first, repeated until nothing touches; zooming in splits them back into places.
  - **List and selection:** a merged blob is titled "Helsinki and 6 places near it", and its list shows
    each article's place. The selection follows its place through re-clustering.
  - **Fitting:** the camera fits to the places, not the clusters. Fitting to clusters had flown the 3D
    camera to 35° S, because after heavy merging most of the remaining marks are scattered singles.
- **Demo flow** passes in both modes (the civil war is in a blob of 4–7 depending on the zoom; picked
  from the list).

## Cleanup (2026-11-15)
- **3D globe removed.** The map is the 2D world map only: the component, `world3d.json`, the earth
  texture, and globe.gl / three.js from `web/package.json`.
- **Deleted, because the demo app no longer reaches it** (all still in git history):
  - **Old frontends:** the old place globe (`web/globe/`, the `/globe/` route), the pre-demo React app
    (`LegacyApp`, `GlobeView`, `NarrativeDrift`, `Stats`, the old `Worklist`), their images and the
    react-globe.gl / recharts packages.
  - **Mock mode:** `web/.env.mock`, `.env.production`, `dev:mock`, 19 of 21 mocks; kept: `worklist.json`
    and `compare.json`, the contract examples the tests check against.
  - **API:** the place routes (`api/places.py`; its two SQL helpers moved to `api/db.py`),
    `/api/lang-lines`, and the history routes only the deleted views used (drift, term-drift, about-all,
    revision, map, near, stats), with their models, `db/queries/*.sql` and tests.
  - **Tools:** `api/dump_mocks.py`, `api/check_api.py` (the Playwright demo flow times the real path).
  - **Screenshots:** the old screenshots (`docs/screenshots` except `demo-*`, `web/screenshots`).
  - **Stray repo:** a nested git repo `Junction26/` holding only a photo, which had been committed by
    accident; untracked, the folder is left on disk and in `.gitignore`.
  - **Styles:** 48 CSS rules of the deleted views.
- **Kept on purpose:**
  - **Data pipeline:** every loader and builder of a table the app reads. The place pipeline stays
    (`ingest/places.py`, `build_heat.py`, `db/heat_sql.py`…), because `topic_place` comes from
    `page_place` / `article_geo` / `page_origin`.
  - **Kristian's history routes:** the ones his three views use, plus `ingest/synthetic.py` and
    `event_time.py` (tests, the "about" filter).
  - **Scoring:** `scoring/` (judging, and `sentence_score` feeds the contested-sentence history) and
    `scripts/verda/`.
- **Checks:** tests 43 passed, 1 skipped (the others belonged to deleted code); demo flow passes; the web
  build went from ~4 s / 2 MB JS to 0.45 s.

## AikaKone (2026-11-15)
- **Rename:** the app is now **AikaKone** (header, page title, API title, package names, README). The
  README is rewritten for the editor tool: what it does, how to run it, the data pipeline.
- **Docs deleted:**
  - `docs/findings.md` (the old globe's place-link findings) and `db/findings.py` /
    `findings_extra.py` behind it.
  - `docs/merge-plan.md` (the merge is done).
  - **Kept:** `decisions.md`, `numbers.md`, `process-log.md` (Verda), `contracts.md`. `db/benchmark.py`
    is still used by the process log; its two drift timings went with the drift queries.
- **Demo screenshots:** regenerated by `web/scripts/demo-flow.mjs`, 1440×900 at 2× (2880×1800), in
  `docs/screenshots/demo-*.png`, 14 shots:
  - worklist, semantic search, its SQL, topic chip
  - article Languages, a contradiction with its fix panel and the "Edit in Wikipedia" buttons
  - edit wars, contested sentences, the article on a date
  - map for the search, hover, blob list, picked article with its 10 similar, all articles
- **Timings** in the same run: worklist 344 ms, search 298 ms, chip 206 ms, article 377 ms, edit-war
  tabs 109–224 ms, map 225–420 ms, map click 8–66 ms.

### Cleanup 2: one start command, old globe tables dropped (2026-11-15)
- **`python start.py`** replaces `dev.py`, `Makefile`, `Dockerfile`, `.dockerignore`,
  `docker-compose.yml` and the root `package.json`, which described old workflows. It does three
  things: checks the `.env` database settings and that MariaDB answers (with the worklist size); builds
  `web/dist` when it is missing or older than `web/src`; runs the API, which serves the app (`/` →
  `/contested/`). Options: `--port`, `--host`, `--rebuild`. Tested on :8001.
- **Dropped from MariaDB:** `heat_year`, `arc_year`, `year_caption`. Only the deleted globe read them.
- **Kept `place_link`:** it is the system-versioned history of place links that the map's *inferred*
  locations come from (1,821 of the 2,688 placed topics).
- **Builder:** `ingest/build_heat.py` and `db/heat_sql.py` are replaced by **`ingest/build_origin.py`**,
  which rebuilds only `page_origin` for one year (default 2026, the map's). Rebuilt and checked:
  17,362 articles; `topic_place` again 2,688 (860 page_place, 7 article_geo, 1,821 inferred).
- **Schema and hints:** `db/schema.sql`, `common/schema.py` and the 503 "load it with…" hints in
  `api/db.py` are updated.
- **Not dropped:** `revert` (45,048 rows) is also unused now; it was not on the agreed list.
- `docs/process-log.md` and `docs/decisions.md` still mention Docker and `dev.py`: they record what was
  done then.
- Tests: 43 passed, 1 skipped.

### "0" vs "—" in Possible contradictions (2026-11-15)
- **What they mean:** "—" = Gemma never judged the topic; "0" = judged, no contradiction. The data
  matches this:
  - **Judged:** 27B judgements for 301 topics (the 300 of `top_topics.txt` + Niinistö). Each was judged
    for 97–110 % of its current matched pairs; 13 of 7,509 judged pairs are no longer matched after the
    GPU rematch. 162 judged topics have 0 contradictions, 139 have some.
  - **Not judged:** the other 2,608 topics.
- **Gap:** the judging list was the top 300 of the *old* score. With missing content in the score,
  today's top 50 is fully judged, but the top 100 has 4 unjudged and the top 300 has 83 (first at rank
  54, *Suomenlinna*).
  - **List:** `data/verda/topics_to_judge.txt` (83 topics, 2,239 matched pairs).
  - **Estimate:** about 11 min and €0.40 on Verda at the last run's rate (7,401 pairs in 37 min, €1.34).
- **UI:** the worklist now says "not judged" instead of "—"; hovering a number shows how many pairs Gemma
  judged.
