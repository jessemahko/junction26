r"""Stage 1: embed the sentences of a few topics with bge-m3 on this PC's CPU, into lang_sentence.

    .venv\Scripts\python -m ingest.embed_cpu --topics Q29207,Q211855 --null 12

--null N also embeds N random other topics (fixed seed), the "unrelated articles" that
db/lang_match.py uses to calibrate the match threshold.
--extreme P also embeds every topic whose whole-article fi–sv or fi–en distance is above the
P-th percentile: the "different subject" candidates (db/build_divergence.py).
Rows already embedded are skipped.
Stage 2 replaces this with the Verda batch job (docs/contracts.md a).
"""
from __future__ import annotations

import argparse
import random
import re
import struct
import sys
import time

from common.db import ROOT, connect
from ingest.sentences import text_sentences

MODEL = "bge-m3"
LANGS = ("fi", "sv", "en")


def create_tables(cur) -> None:
    sql = re.sub(r"--[^\n]*", "", (ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    for stmt in sql.split(";"):
        if "TABLE IF NOT EXISTS lang_sentence " in stmt or "TABLE IF NOT EXISTS lang_pair " in stmt:
            cur.execute(stmt)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", default="Q29207,Q211855")
    ap.add_argument("--null", type=int, default=0, help="also embed N random other topics")
    ap.add_argument("--seed", type=int, default=1918)
    ap.add_argument("--extreme", type=float, default=0, help="also embed topics above this distance percentile")
    a = ap.parse_args()
    con = connect(dict_rows=False)
    cur = con.cursor()
    create_tables(cur)
    topics = a.topics.split(",")
    if a.null:
        cur.execute("SELECT wikidata_id FROM lang_topic ORDER BY wikidata_id")
        others = [q for (q,) in cur.fetchall() if q not in topics]
        nulls = random.Random(a.seed).sample(others, a.null)
        print("null topics:", ",".join(nulls))
        topics += nulls
    if a.extreme:
        import numpy as np
        from db.lang_distance import SQL as DIST_SQL
        from common.db import connect as dconnect
        dc = dconnect()
        with dc.cursor() as c2:
            c2.execute(DIST_SQL)
            rows = c2.fetchall()
        dc.close()
        cut = {p: np.percentile([float(r[p]) for r in rows], a.extreme) for p in ("fi_sv", "fi_en")}
        extreme = [r["wikidata_id"] for r in rows
                   if float(r["fi_sv"]) > cut["fi_sv"] or float(r["fi_en"]) > cut["fi_en"]]
        print(f"extreme topics (> p{a.extreme:g}: fi_sv {cut['fi_sv']:.3f}, fi_en {cut['fi_en']:.3f}): {len(extreme)}")
        topics += [q for q in extreme if q not in topics]
    cur.execute("SELECT DISTINCT lang, page_id FROM lang_sentence")
    done = set(cur.fetchall())

    from sentence_transformers import SentenceTransformer     # slow import: only when needed
    t0 = time.time()
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    print(f"model loaded in {time.time() - t0:.0f} s", flush=True)
    n_total, t_embed = 0, 0.0
    for q in topics:
        cur.execute("SELECT lang, page_id, title, content FROM lang_article WHERE wikidata_id = %s "
                    "AND lang IN ('fi','sv','en')", (q,))
        for lang, page_id, title, content in cur.fetchall():
            if (lang, page_id) in done:
                continue
            sents = [s for _, s in text_sentences(content)]
            if not sents:
                continue
            t = time.time()
            vecs = model.encode(sents, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
            t_embed += time.time() - t
            rows = [(lang, page_id, i, q, s, MODEL, struct.pack("<1024f", *v.tolist()))
                    for i, (s, v) in enumerate(zip(sents, vecs))]
            cur.executemany("INSERT INTO lang_sentence (lang, page_id, sent_no, wikidata_id, text, model, "
                            "embedding) VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)
            con.commit()
            n_total += len(sents)
            print(f"  {q} {lang} {title[:40]:<40} {len(sents):5} sentences  {time.time() - t:5.1f} s", flush=True)
    rate = n_total / t_embed if t_embed else 0
    print(f"embedded {n_total:,} sentences in {t_embed:.0f} s on CPU ({rate:.1f} sentences/s)")
    con.close()


if __name__ == "__main__":
    main()
