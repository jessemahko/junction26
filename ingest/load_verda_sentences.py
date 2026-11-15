r"""Load the GPU sentence embeddings from Verda (docs/contracts.md a) into lang_sentence.

    .venv\Scripts\python -m ingest.load_verda_sentences            # data/verda/sentences-{fi,sv,en}.parquet

The files hold every sentence of the 2,919 fi + sv + en topics, split with ingest.sentences.text_sentences
and embedded with bge-m3 (fp16 on an A100; cosine >= 0.99998 against our CPU vectors).

Safe swap, nothing is lost if a check fails:
  1. load into lang_sentence_new (no vector index yet: bulk insert first, index once afterwards)
  2. check: row counts per language equal the files; for every sentence that is also in the current
     lang_sentence (the CPU rows), the text is identical (same splitter, same numbering)
  3. add the VECTOR INDEX (M=16, cosine), as on lang_sentence
  4. RENAME lang_sentence -> lang_sentence_cpu, lang_sentence_new -> lang_sentence (one atomic statement)
lang_sentence_cpu is kept for rollback (RENAME back); drop it when not needed.
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pyarrow.parquet as pq

from common.db import ROOT, connect

VERDA = ROOT / "data" / "verda"
LANGS = ("fi", "sv", "en")
BATCH = 2000

DDL = """CREATE TABLE lang_sentence_new (
  lang         CHAR(2) NOT NULL,
  page_id      INT UNSIGNED NOT NULL,
  sent_no      INT UNSIGNED NOT NULL,
  wikidata_id  VARCHAR(20) NOT NULL,
  text         TEXT NOT NULL,
  model        VARCHAR(50) NOT NULL,
  embedding    VECTOR(1024) NOT NULL,
  PRIMARY KEY (lang, page_id, sent_no),
  KEY topic_key (wikidata_id, lang)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"""
INDEX = "ALTER TABLE lang_sentence_new ADD VECTOR INDEX embedding (embedding) M=16 DISTANCE=cosine"
INSERT = ("INSERT INTO lang_sentence_new (lang, page_id, sent_no, wikidata_id, text, model, embedding) "
          "VALUES (%s, %s, %s, %s, %s, %s, %s)")


def load(cur, con, lang: str) -> int:
    f = pq.ParquetFile(VERDA / f"sentences-{lang}.parquet")
    n = 0
    for batch in f.iter_batches(batch_size=BATCH):
        t = batch.to_pydict()
        emb = np.asarray(batch.column("embedding").flatten().to_numpy(zero_copy_only=False),
                         dtype="<f4").reshape(-1, 1024)
        rows = [(t["lang"][i], t["page_id"][i], t["sent_no"][i], t["wikidata_id"][i], t["text"][i],
                 t["model"][i], emb[i].tobytes()) for i in range(len(emb))]
        cur.executemany(INSERT, rows)
        con.commit()
        n += len(rows)
    return n


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    con = connect(read_timeout=None)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS lang_sentence_new")
    cur.execute(DDL)
    expected = {l: pq.ParquetFile(VERDA / f"sentences-{l}.parquet").metadata.num_rows for l in LANGS}

    t0 = time.time()
    for lang in LANGS:
        t = time.time()
        n = load(cur, con, lang)
        print(f"  {lang}: {n:,} rows in {time.time() - t:.0f} s", flush=True)
    t_rows = time.time() - t0

    cur.execute("SELECT lang, COUNT(*) AS n, COUNT(DISTINCT wikidata_id) AS topics FROM lang_sentence_new GROUP BY lang")
    got = {r["lang"]: (r["n"], r["topics"]) for r in cur.fetchall()}
    print("  counts:", {l: f"{got[l][0]:,} rows, {got[l][1]:,} topics" for l in LANGS})
    if any(got.get(l, (0,))[0] != expected[l] for l in LANGS):
        raise SystemExit(f"row counts differ from the files {expected}; lang_sentence untouched")
    cur.execute("""SELECT COUNT(*) AS shared, SUM(o.text <> n.text) AS differ,
       SUM(VEC_DISTANCE_COSINE(o.embedding, n.embedding)) / COUNT(*) AS mean_dist,
       MAX(VEC_DISTANCE_COSINE(o.embedding, n.embedding)) AS max_dist
FROM lang_sentence o JOIN lang_sentence_new n USING (lang, page_id, sent_no)""")
    r = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS n FROM lang_sentence")
    old = cur.fetchone()["n"]
    print(f"  against the CPU rows: {int(r['shared']):,} of {old:,} shared, {int(r['differ'] or 0)} texts differ, "
          f"vector cosine distance mean {float(r['mean_dist']):.2e}, max {float(r['max_dist']):.2e}")
    if int(r["shared"]) != old or int(r["differ"] or 0):
        raise SystemExit("the CPU sentences are not all reproduced exactly; lang_sentence untouched")

    t = time.time()
    cur.execute(INDEX)
    t_index = time.time() - t
    print(f"  vector index built in {t_index:.0f} s", flush=True)
    cur.execute("DROP TABLE IF EXISTS lang_sentence_cpu")
    cur.execute("RENAME TABLE lang_sentence TO lang_sentence_cpu, lang_sentence_new TO lang_sentence")
    # Fresh statistics: without them the optimiser picks PRIMARY (lang) over topic_key and every
    # per-topic query scans a whole language (19 s instead of 0.13 s for one topic in lang_match).
    cur.execute("ANALYZE TABLE lang_sentence")
    cur.fetchall()
    print(f"lang_sentence replaced: {sum(expected.values()):,} sentences; rows {t_rows:.0f} s + index "
          f"{t_index:.0f} s = {time.time() - t0:.0f} s. Old CPU rows kept as lang_sentence_cpu.")
    con.close()


if __name__ == "__main__":
    main()
