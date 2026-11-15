"""Scale numbers for the slides (plan B4): table sizes + query times per view.

    python -m db.benchmark                  # print a markdown report
    python -m db.benchmark --record         # also append it to docs/numbers.md

Times every view on the most-edited article (worst case) and on a random sample of articles
(typical case), 5 runs each, reporting median and p95. The point for the judges: every view is
per-article, so query time follows the article's own history, not the size of the database.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from datetime import datetime

from api import history as H
from common.db import ROOT, connect, settings


def _ms(fn, runs: int) -> list[float]:
    out = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def _p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs) + 0.999) - 1)]


def views(conn, page_id: int, first_rev: str) -> dict:
    mid = max("2012-06-01T00:00:00Z", first_rev)
    return {
        "as_of": lambda: H.as_of(conn, page_id, mid),
        "diff": lambda: H.diff(conn, page_id, first_rev, None),
        "contested": lambda: H.contested(conn, page_id),
        "edit_wars": lambda: H.edit_wars(conn, page_id, 20),
        "about 1917–1918": lambda: H.about(conn, page_id, None, 1917, 1918),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    conn = connect(autocommit=True)
    db = settings()["database"]
    out = [f"\n## Benchmark {datetime.now():%Y-%m-%d %H:%M} (`python -m db.benchmark`)\n"]

    with conn.cursor() as cur:
        cur.execute("SELECT VERSION() AS v")
        out.append(f"MariaDB {cur.fetchone()['v']}\n")
        c = H._rows(conn, "stats_counts", {})[0]
        cur.execute("SELECT COUNT(*) AS n FROM article_geo")
        geo = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM sentence_event_time")
        evt = cur.fetchone()["n"]
        out.append("| | |\n|---|---|")
        for k, v in [("articles", c["articles"]), ("revisions (article rows, all system time)", c["revisions"]),
                     ("sentence lives (article_sentence rows, all system time)", c["sentence_rows"]),
                     ("distinct sentences", c["distinct_sentences"]), ("current sentences", c["current_sentences"]),
                     ("sentences scored", c["scored_sentences"]), ("sentences with an event period (bitemporal)", evt),
                     ("articles on the globe", geo)]:
            out.append(f"| {k} | {int(v):,} |")
        cur.execute("""SELECT table_name AS t, ROUND((data_length + index_length) / 1e6) AS mb, table_rows AS r
                       FROM information_schema.tables WHERE table_schema = %s ORDER BY mb DESC""", (db,))
        out.append("\n| Table | MB on disk (data + indexes) |\n|---|---|")
        for r in cur.fetchall():
            out.append(f"| {r['t']} | {int(r['mb'] or 0):,} |")

    arts = H.articles(conn, "", 100000)
    arts = [x for x in arts if x["page_id"] < 900000000]
    top = arts[0]
    random.seed(2026)
    sample = random.sample(arts, min(a.sample, len(arts)))

    out.append(f"\n**Worst case**: *{top['title']}*, {top['revisions']:,} revisions. "
               f"**Typical**: {len(sample)} random articles (median {statistics.median(x['revisions'] for x in sample):.0f} revisions). "
               f"{a.runs} runs each, ms.\n")
    out.append("| View | worst median | worst p95 | typical median | typical p95 |\n|---|---|---|---|---|")
    worst = {k: _ms(f, a.runs) for k, f in views(conn, top["page_id"], top["first_rev"]).items()}
    typical: dict[str, list[float]] = {}
    for x in sample:
        for k, f in views(conn, x["page_id"], x["first_rev"]).items():
            typical.setdefault(k, []).extend(_ms(f, a.runs))
    for k in worst:
        out.append(f"| {k} | {statistics.median(worst[k]):.1f} | {_p95(worst[k]):.1f} | "
                   f"{statistics.median(typical[k]):.1f} | {_p95(typical[k]):.1f} |")
    for name, fn in [("globe: map (all articles)", lambda: H.map_points(conn)),
                     ("globe: nearby (spatial index)", lambda: H.near(conn, 60.17, 24.94, 1.0)),
                     ("bitemporal across all articles: 2012 about 1917–1918",
                      lambda: H.about_all(conn, "2012-01-01", 1917, 1918))]:
        t = _ms(fn, 3)
        out.append(f"| {name} | {statistics.median(t):.1f} | {_p95(t):.1f} | | |")

    report = "\n".join(out) + "\n"
    print(report)
    if a.record:
        with open(ROOT / "docs" / "numbers.md", "a", encoding="utf-8") as f:
            f.write(report)


if __name__ == "__main__":
    main()
