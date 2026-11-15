r"""Load dataset S (current fi / sv / en text + bge-m3 article vectors) into lang_article,
lang_article_vector and lang_topic. Touches no other table.

    .venv\Scripts\python -m ingest.load_lang            # from data/s/*.parquet

Safe to rerun: rows already loaded are kept (INSERT IGNORE); lang_topic is rebuilt.
"""
from __future__ import annotations

import re
import struct
import sys
import time

import pyarrow.parquet as pq

from common.db import ROOT, connect

S = ROOT / "data" / "s"
LANGS = ("fi", "sv", "en")
BATCH_BYTES = 8_000_000
TABLES = ("lang_article", "lang_article_vector", "lang_topic")


def create_tables(cur) -> None:
    sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)
    for stmt in sql.split(";"):
        if any(f"TABLE IF NOT EXISTS {t} " in stmt for t in TABLES):
            cur.execute(stmt)


def batched(cur, sql: str, rows: list[tuple], size_of) -> None:
    batch, size = [], 0
    for row in rows:
        if batch and size + size_of(row) > BATCH_BYTES:
            cur.executemany(sql, batch)
            batch, size = [], 0
        batch.append(row)
        size += size_of(row)
    if batch:
        cur.executemany(sql, batch)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    con = connect(dict_rows=False)
    cur = con.cursor()
    create_tables(cur)
    t_all = time.time()
    for lang in LANGS:
        t = time.time()
        rows = [(r["lang"], r["page_id"], r["rev_id"], r["wikidata_id"], r["title"], r["url"],
                 (r["date_modified"] or "").replace("T", " ").replace("Z", "") or None,
                 r["text"] or "", len(r["text"] or ""))
                for r in pq.read_table(S / f"articles-{lang}.parquet").to_pylist()]
        batched(cur, "INSERT IGNORE INTO lang_article (lang, page_id, rev_id, wikidata_id, title, url, "
                     "date_modified, content, len) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                rows, lambda r: 300 + 3 * len(r[7]))
        con.commit()
        t_text = time.time() - t
        t = time.time()
        # MariaDB takes a VECTOR as raw bytes: 1024 float32, little-endian.
        vecs = [(r["lang"], r["page_id"], r["model"], r["truncated"],
                 struct.pack(f"<{len(r['embedding'])}f", *r["embedding"]))
                for r in pq.read_table(S / f"vectors-bge-m3-{lang}.parquet").to_pylist()]
        batched(cur, "INSERT IGNORE INTO lang_article_vector (lang, page_id, model, truncated, embedding) "
                     "VALUES (%s,%s,%s,%s,%s)", vecs, lambda r: 4200)
        con.commit()
        print(f"{lang}: {len(rows):,} articles ({t_text:.0f} s), {len(vecs):,} vectors ({time.time() - t:.0f} s)",
              flush=True)
    cur.execute("DELETE FROM lang_topic")
    cur.execute("""INSERT INTO lang_topic (wikidata_id, fi_page_id, sv_page_id, en_page_id)
                   SELECT fi.wikidata_id, fi.page_id, sv.page_id, en.page_id
                   FROM lang_article fi
                   JOIN lang_article sv ON sv.lang = 'sv' AND sv.wikidata_id = fi.wikidata_id
                   JOIN lang_article en ON en.lang = 'en' AND en.wikidata_id = fi.wikidata_id
                   WHERE fi.lang = 'fi' AND fi.wikidata_id IS NOT NULL""")
    con.commit()
    for t in TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"{t}: {cur.fetchone()[0]:,} rows")
    cur.execute("""SELECT table_name, ROUND((data_length + index_length) / 1e6) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name LIKE 'lang!_%%' ESCAPE '!'""")
    print("MB on disk:", dict(cur.fetchall()))
    print(f"Total {time.time() - t_all:.0f} s")
    con.close()


if __name__ == "__main__":
    main()
