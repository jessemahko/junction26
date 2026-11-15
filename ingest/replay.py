"""Load articles into MariaDB with Wikipedia's real edit times.  (owner: P2, schema by P1)

    python -m ingest.replay --dataset demo                 # synthetic article, offline
    python -m ingest.replay --dataset small --pages 1150   # just Suomen sisällissota
    python -m ingest.replay --dataset small                # the 50 articles
    python -m ingest.replay --dataset large --workers 8    # all of dataset M
    python -m ingest.replay --dataset large --workers 14 --sentences-only
                                          # `article` already holds every version (combined app):
                                          # write only the sentence tables + article_sentence_order

Two ways to put history into the system-versioned tables (same result, tested in api/tests):

  bulk   (default) SET system_versioning_insert_history = 1 and INSERT every life with explicit
         row_start/row_end. One pass, multi-row inserts: the scalable path.
  replay SET @@timestamp = <edit time> before each revision, then plain DELETE/INSERT/UPDATE:
         MariaDB itself moves removed sentences into history. Slow, but shows that the history
         is produced by ordinary DML.

Resumable: pages already in load_log are skipped. Throughput is printed and appended to
docs/numbers.md with --record.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, as_completed, wait
from datetime import datetime, timezone

from common.db import ROOT, connect
from common.schema import apply as apply_schema
from ingest.geo import load_index as load_geo_index
from ingest.geo import own_coordinates
from ingest.history import BuildResult, build
from ingest.stats import UPSERT as STATS_UPSERT
from ingest.stats import from_build as stats_from_build
from ingest.load_articles import Page, iter_pages

BATCH_BYTES = 8_000_000

A_COLS = "page_id, title, rev_id, editor, anonymous, comment, minor, sha1, n_sentences, sentence_order, content"
S_COLS = "page_id, sent_hash, position, text, rev_id, editor, anonymous, prev_hash"


def _batched_insert(cur, sql: str, rows: list[tuple], size_of) -> None:
    batch, size = [], 0
    for row in rows:
        s = size_of(row)
        if batch and size + s > BATCH_BYTES:
            cur.executemany(sql, batch)
            batch, size = [], 0
        batch.append(row)
        size += s
    if batch:
        cur.executemany(sql, batch)


def write_bulk(conn, res: BuildResult) -> None:
    with conn.cursor() as cur:
        cur.execute("SET system_versioning_insert_history = 1")
        hist_a = [r for r in res.article_rows if r[-1] is not None]
        cur_a = [r[:-1] for r in res.article_rows if r[-1] is None]
        size_a = lambda r: 200 + len(r[9] or b"") + 2 * len(r[10] or "") + len(r[5] or "")
        _batched_insert(cur, f"INSERT INTO article ({A_COLS}, row_start, row_end) VALUES "
                             f"(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", hist_a, size_a)
        _batched_insert(cur, f"INSERT INTO article ({A_COLS}, row_start) VALUES "
                             f"(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", cur_a, size_a)
        hist_s = [r for r in res.sentence_rows if r[-1] is not None]
        cur_s = [r[:-1] for r in res.sentence_rows if r[-1] is None]
        size_s = lambda r: 120 + 2 * len(r[3])
        _batched_insert(cur, f"INSERT INTO article_sentence ({S_COLS}, row_start, row_end) VALUES "
                             f"(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", hist_s, size_s)
        _batched_insert(cur, f"INSERT INTO article_sentence ({S_COLS}, row_start) VALUES "
                             f"(%s,%s,%s,%s,%s,%s,%s,%s,%s)", cur_s, size_s)
        cur.execute("SET system_versioning_insert_history = 0")


def write_sentences_only(conn, res: BuildResult) -> None:
    """The combined app: `article` already holds EVERY version (vandalism included) and is not
    rewritten. Write the sentence lives (built from the filtered revisions) and, per revision id,
    the sentence order into article_sentence_order. A revision dropped by the vandalism filter gets
    the order of the last kept revision before it, so a snapshot never shows the vandal's text."""
    with conn.cursor() as cur:
        cur.execute("SET system_versioning_insert_history = 1")
        hist_s = [r for r in res.sentence_rows if r[-1] is not None]
        cur_s = [r[:-1] for r in res.sentence_rows if r[-1] is None]
        size_s = lambda r: 120 + 2 * len(r[3])
        _batched_insert(cur, f"INSERT INTO article_sentence ({S_COLS}, row_start, row_end) VALUES "
                             f"(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", hist_s, size_s)
        _batched_insert(cur, f"INSERT INTO article_sentence ({S_COLS}, row_start) VALUES "
                             f"(%s,%s,%s,%s,%s,%s,%s,%s,%s)", cur_s, size_s)
        cur.execute("SET system_versioning_insert_history = 0")
        kept = {row[2]: (row[8], row[9]) for row in res.article_rows}     # rev_id -> (n, order)
        last, rows = (0, b""), []
        for rev_id in res.rev_ids:
            last = kept.get(rev_id, last)
            rows.append((rev_id, res.page_id, rev_id in kept, last[0], last[1]))
        _batched_insert(cur, "INSERT IGNORE INTO article_sentence_order (rev_id, page_id, kept, n_sentences, "
                             "sentence_order) VALUES (%s,%s,%s,%s,%s)", rows, lambda r: 60 + len(r[4]))


def write_replay(conn, res: BuildResult) -> None:
    """Option B: let MariaDB stamp the rows, with the session clock set to each edit time."""
    with conn.cursor() as cur:
        current: dict[bytes, None] = {}
        prev_of = {(row[1], row[8]): row[7] for row in res.sentence_rows}   # (hash, start) -> prev
        for i, pr in enumerate(res.kept):
            r = pr.rev
            epoch = pr.ts.replace(tzinfo=timezone.utc).timestamp()
            cur.execute(f"SET @@timestamp = {epoch:.6f}")      # a number; a quoted string is refused
            removed = [h for h in current if h not in pr.hashes]
            for k in range(0, len(removed), 500):
                chunk = removed[k:k + 500]
                cur.execute("DELETE FROM article_sentence WHERE page_id = %s AND sent_hash IN ("
                            + ",".join(["%s"] * len(chunk)) + ")", [res.page_id, *chunk])
            for h in removed:
                del current[h]
            added = [(res.page_id, h, pos, text, r.rev_id, r.user, r.anonymous, prev_of.get((h, pr.ts)))
                     for pos, (h, text) in enumerate(pr.sents) if h not in current]
            if added:
                cur.executemany(f"INSERT INTO article_sentence ({S_COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", added)
                for row in added:
                    current[row[1]] = None
            row = res.article_rows[i][:-2]
            if i == 0:
                cur.execute(f"INSERT INTO article ({A_COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
            else:
                cur.execute("UPDATE article SET title=%s, rev_id=%s, editor=%s, anonymous=%s, comment=%s, "
                            "minor=%s, sha1=%s, n_sentences=%s, sentence_order=%s, content=%s "
                            "WHERE page_id=%s", (*row[1:], res.page_id))
            conn.commit()
        cur.execute("SET @@timestamp = DEFAULT")


def save_geo(cur, res: BuildResult, geo_index: dict) -> None:
    """Place the article on the globe: geo index (own coordinates or linked place) first, else
    coordinates in its latest wikitext."""
    g = geo_index.get(res.page_id)
    if g:
        lat, lon, source = float(g["lat"]), float(g["lon"]), g["source"]
    else:
        c = own_coordinates(res.kept[-1].rev.text)
        if not c:
            return
        (lat, lon), source = c, "own"
    cur.execute("REPLACE INTO article_geo (page_id, lat, lon, pt, source) "
                "VALUES (%s, %s, %s, POINT(%s, %s), %s)", (res.page_id, lat, lon, lon, lat, source[:300]))


def _build(args) -> BuildResult:
    page, with_content, filt = args
    return build(page, with_content=with_content, filter_vandalism=filt)


def load(dataset: str, pages: set[int] | None = None, mode: str = "bulk", workers: int = 1,
         with_content: bool = False, filter_vandalism: bool = True, database: str | None = None,
         reset: bool = False, quiet: bool = False, sentences_only: bool = False) -> dict:
    apply_schema(database, reset=reset)
    conn = connect(database)
    with conn.cursor() as cur:
        cur.execute("SELECT page_id FROM load_log")
        done = {r["page_id"] for r in cur.fetchall()}
    stats = dict(articles=0, revisions=0, dropped=0, lives=0, seconds=0.0)
    t0 = time.time()
    geo_index = load_geo_index()

    def jobs():
        for page in iter_pages(dataset, pages, skip=done):
            if page.revisions:
                yield (page, with_content, filter_vandalism)

    def handle(res: BuildResult, t_page: float) -> None:
        if not res.kept or res.article_rows[-1][8] == 0:      # redirect / empty now: skip
            return
        tw = time.time()
        if sentences_only:
            write_sentences_only(conn, res)
        elif mode == "bulk":
            write_bulk(conn, res)
        else:
            write_replay(conn, res)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO load_log (page_id, dataset, revisions, lifetimes, seconds) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (res.page_id, dataset, len(res.kept), len(res.sentence_rows), time.time() - t_page))
            save_geo(cur, res, geo_index)
            cur.execute(STATS_UPSERT, stats_from_build(res))
        conn.commit()
        stats["articles"] += 1
        stats["revisions"] += len(res.kept)
        stats["dropped"] += res.dropped
        stats["lives"] += len(res.sentence_rows)
        if not quiet:
            el = time.time() - t0
            print(f"  {res.title[:50]:<50} {len(res.kept):>6} revs ({res.dropped} vandalism dropped) "
                  f"{len(res.sentence_rows):>7} lives  write {time.time() - tw:5.1f}s | "
                  f"total {stats['articles']} art, {stats['revisions'] / max(el, 1e-9):,.0f} revs/s",
                  flush=True)

    if workers > 1:
        # Bounded: Executor.map would submit (and read into memory) every page up front —
        # all 12 GB of dataset M. Keep at most 2 pages per worker in flight.
        with ProcessPoolExecutor(workers) as ex:
            pending: set = set()
            for job in jobs():
                pending.add(ex.submit(_build, job))
                if len(pending) >= workers * 2:
                    done_now, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for f in done_now:
                        handle(f.result(), time.time())
            for f in as_completed(pending):
                handle(f.result(), time.time())
    else:
        for job in jobs():
            tp = time.time()
            handle(_build(job), tp)
    conn.close()
    stats["seconds"] = round(time.time() - t0, 1)
    return stats


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="small", help="demo | small | medium | large | path.parquet | path.jsonl")
    ap.add_argument("--pages", help="comma-separated page ids (default: whole dataset)")
    ap.add_argument("--mode", choices=["bulk", "replay"], default="bulk")
    ap.add_argument("--workers", type=int, default=1, help="parallel parsing processes")
    ap.add_argument("--with-content", action="store_true", help="also store raw wikitext per revision")
    ap.add_argument("--keep-vandalism", action="store_true", help="do not drop blanking vandalism")
    ap.add_argument("--db", default=None, help="database name (default DB_NAME)")
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    ap.add_argument("--record", action="store_true", help="append the run to docs/numbers.md")
    ap.add_argument("--sentences-only", action="store_true",
                    help="article already loaded with every version: write only the sentence tables")
    a = ap.parse_args()
    pages = {int(x) for x in a.pages.split(",")} if a.pages else None
    stats = load(a.dataset, pages, a.mode, a.workers, a.with_content, not a.keep_vandalism, a.db, a.reset,
                 sentences_only=a.sentences_only)
    rate = stats["revisions"] / stats["seconds"] if stats["seconds"] else 0
    line = (f"| {datetime.now():%Y-%m-%d %H:%M} | {a.dataset}{' ' + a.pages if a.pages else ''} | {a.mode} "
            f"| {a.workers} | {stats['articles']:,} | {stats['revisions']:,} | {stats['dropped']:,} "
            f"| {stats['lives']:,} | {stats['seconds']:,} s | {rate:,.0f} |")
    print(f"\nLoaded {stats['articles']} articles, {stats['revisions']:,} revisions "
          f"({stats['dropped']:,} vandalism dropped), {stats['lives']:,} sentence lives in {stats['seconds']} s "
          f"({rate:,.0f} revisions/s)")
    if a.record:
        with open(ROOT / "docs" / "numbers.md", "a", encoding="utf-8") as f:
            f.write(line + "\n")


if __name__ == "__main__":
    main()
