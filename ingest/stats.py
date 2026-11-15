"""Per-article history summary (article_stats), for the globe.

The loader writes it for every page it loads. This backfills pages loaded before the table
existed, one article at a time (index lookups on page_id, no big temporary tables):

    python -m ingest.stats            # pages missing from article_stats
    python -m ingest.stats --all      # recompute every page
"""
from __future__ import annotations

import argparse
import sys
import time

from common.db import connect
from ingest.history import BuildResult

UPSERT = ("REPLACE INTO article_stats (page_id, revisions, reverts, lives, distinct_sentences, first_rev, "
          "last_rev, title, n_sentences) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")


def from_build(res: BuildResult) -> tuple:
    """Stats straight from the loader's in-memory result (no extra queries)."""
    seen: set = set()
    prev = None
    reverts = 0
    for pr in res.kept:
        s = pr.rev.sha1
        if s and s != prev and s in seen:
            reverts += 1
        if s:
            seen.add(s)
        prev = s
    distinct = len({row[1] for row in res.sentence_rows})
    return (res.page_id, len(res.kept), reverts, len(res.sentence_rows), distinct,
            res.kept[0].ts if res.kept else None, res.kept[-1].ts if res.kept else None,
            res.title, len(res.kept[-1].sents) if res.kept else 0)


def backfill(recompute_all: bool = False) -> int:
    conn = connect(autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT a.page_id FROM article a LEFT JOIN article_stats s USING (page_id)"
                    + ("" if recompute_all else " WHERE s.page_id IS NULL"))
        pages = [r["page_id"] for r in cur.fetchall()]
    t0 = time.time()
    with conn.cursor() as cur:
        for i, pid in enumerate(pages, 1):
            cur.execute("""SELECT COUNT(*) AS revisions, MIN(row_start) AS first_rev, MAX(row_start) AS last_rev,
                                  COALESCE(SUM(is_revert), 0) AS reverts
                           FROM (SELECT row_start,
                                        sha1 <> LAG(sha1) OVER (ORDER BY row_start)
                                          AND MIN(row_start) OVER (PARTITION BY sha1) < row_start AS is_revert
                                 FROM article FOR SYSTEM_TIME ALL WHERE page_id = %s) r""", (pid,))
            r = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS lives, COUNT(DISTINCT sent_hash) AS d "
                        "FROM article_sentence FOR SYSTEM_TIME ALL WHERE page_id = %s", (pid,))
            s = cur.fetchone()
            cur.execute("SELECT title, n_sentences FROM article WHERE page_id = %s", (pid,))
            a = cur.fetchone() or {"title": None, "n_sentences": 0}
            cur.execute(UPSERT, (pid, r["revisions"], int(r["reverts"]), s["lives"], s["d"], r["first_rev"],
                                 r["last_rev"], a["title"], a["n_sentences"]))
            if i % 1000 == 0:
                print(f"  {i:,}/{len(pages):,} articles ({time.time() - t0:.0f} s)", flush=True)
    print(f"article_stats: {len(pages):,} articles in {time.time() - t0:.0f} s")
    return len(pages)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    backfill(ap.parse_args().all)
