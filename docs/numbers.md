# Numbers (for the slides)

Machine: Windows 11 laptop, MariaDB 12.3.3 (`mariadb:lts`) in Docker Desktop. Fill in the Verda
rows on the day.

## Hero article: *Suomen sisällissota* (page 1150)

| | |
|---|---|
| Versions in dataset M | 3,357 (2003-08-26 → 2026-09-12) |
| Loaded after vandalism filter | 3,345 (12 blanking revisions dropped) |
| Sentences in today's article | 1,008 |
| Sentence lives (system-versioned rows) | 8,089 |
| Distinct sentences ever | ~6,500 |
| Reverts (whole-text, sha1) | 338 |
| Most-fought sentence | the intro naming the war: 19 lives |
| Load time (parse + write, 1 process) | 79 s (≈ 60 s parsing wikitext, ≈ 12 s writing) |

## Query times on page 1150 (`GET /api/stats`, 5 runs)

| View | Query | median | p95 |
|---|---|---|---|
| V1 | `as_of` (AS OF article + AS OF sentences) | 75 ms | 81 ms |
| V1 | `diff` (two AS OF snapshots anti-joined) | 68 ms | 107 ms |
| V2 | `contested` (recursive rewrite chains + lives) | 142 ms | 154 ms |
| V3 | `edit_wars` (GROUP BY … HAVING COUNT(*) > 1 over ALL) | 41 ms | 45 ms |
| V4 | `drift` monthly, 280 periods (sweep + window) | 657 ms | 741 ms |
| V4 | `term_drift` monthly, 6 terms | 350 ms | 399 ms |

TODO (P1, Sat): same table on `medium` and `large`, on the Verda CPU instance.

## Scale

| Dataset | Articles | Versions | Sentence lives | Load time | Revisions/s |
|---|---|---|---|---|---|
| small | 50 | ~31,800 | | | |
| medium | | | | | |
| large | 19,742 | 862,076 | | | |

## Gemma eval (P3) — `python -m scoring.eval`

| Model | Tone acc. | Event-name acc. | Neutrality MAE | Valid JSON | Sentences/s | €/1k sentences |
|---|---|---|---|---|---|---|
| heuristic-v1 (baseline) | | | | 100 % | ~6,000 | 0 |
| Gemma (small) | | | | | | |
| Gemma (large) | | | | | | |

## Load runs (`python -m ingest.replay --record` appends here)

| When | Dataset | Mode | Workers | Articles | Revisions | Vandalism dropped | Lives | Time | Revisions/s |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-14 00:51 | geo | bulk | 6 | 300 | 72,800 | 444 | 89,521 | 136.0 s | 535 |
| 2026-11-14 01:27 | large | bulk | 4 | 19,294 | 781,332 | 3,546 | 1,295,537 | 1,519.8 s | 514 |

## Benchmark 2026-11-14 02:21 (`python -m db.benchmark`)

MariaDB 12.3.3-MariaDB-ubu2404

| | |
|---|---|
| articles | 19,597 |
| revisions (article rows, all system time) | 857,532 |
| sentence lives (article_sentence rows, all system time) | 1,393,198 |
| distinct sentences | 1,298,366 |
| current sentences | 586,324 |
| sentences scored | 1,266,901 |
| sentences with an event period (bitemporal) | 497,945 |
| articles on the globe | 2,761 |

| Table | MB on disk (data + indexes) |
|---|---|
| article | 2,779 |
| article_sentence | 688 |
| sentence_score | 222 |
| sentence_event_time | 93 |
| article_stats | 4 |
| load_log | 2 |
| article_geo | 0 |

**Worst case**: *Suomen sisällissota*, 3,345 revisions. **Typical**: 20 random articles (median 13 revisions). 5 runs each, ms.

| View | worst median | worst p95 | typical median | typical p95 |
|---|---|---|---|---|
| as_of | 71.1 | 73.3 | 9.9 | 16.1 |
| diff | 39.1 | 709.3 | 5.8 | 8.8 |
| contested | 614.6 | 639.5 | 12.1 | 23.7 |
| edit_wars | 41.7 | 46.0 | 5.9 | 14.5 |
| drift (month) | 787.8 | 879.2 | 26.6 | 58.5 |
| term_drift (month) | 329.1 | 387.8 | 24.5 | 34.0 |
| about 1917–1918 | 22.5 | 26.5 | 4.6 | 6.1 |
| globe: map (all articles) | 249.1 | 317.9 | | |
| globe: nearby (spatial index) | 6.8 | 10.8 | | |
| bitemporal across all articles: 2012 about 1917–1918 | 828.8 | 6440.0 | | |
