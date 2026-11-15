"""The API's database access: one connection pool and one error policy for both routers.

A missing table is not a crash: the combined database is loaded in stages (places first, sentences
later), so an endpoint whose tables are not there yet answers 503 and says which loader fills them.
"""
from __future__ import annotations

import time
import os
import re

import pymysql
from fastapi import HTTPException

from common.db import Pool

pool = Pool(size=int(os.environ.get("DB_POOL", 8)))

LOADERS = {   # table -> the command that creates and fills it
    **dict.fromkeys(["article_sentence", "article_stats", "load_log"], "python -m ingest.replay --dataset small"),
    "sentence_score": "python -m scoring.score",
    "sentence_event_time": "python -m ingest.event_time",
    "article_geo": "python -m ingest.geo, then python -m ingest.replay",
    **dict.fromkeys(["place", "page_place"], "python -m ingest.places"),
    "place_link": "python -m ingest.place_links",
    "page_origin": "python -m ingest.build_origin",
    "topic_place": "python -m db.build_topic_place",
    **dict.fromkeys(["category_link", "article_category"], "python -m ingest.load_categories"),
    "article": "python -m ingest.load_parquet",
    **dict.fromkeys(["lang_article", "lang_article_vector", "lang_topic"], "python -m ingest.load_lang"),
    "lang_sentence": "python -m ingest.load_verda_sentences (or python -m ingest.embed_cpu on a CPU)",
    "lang_pair": "python -m db.lang_match",
    "article_divergence": "python -m db.build_divergence",
    "pair_judgement": "python -m ingest.load_judgements",
    "article_sentence_order": "python -m ingest.replay --dataset large --sentences-only",
}


def db_error(e: Exception) -> HTTPException:
    """Turn a database error into an HTTP answer a person can act on."""
    code = e.args[0] if e.args else None
    text = str(e.args[-1]) if e.args else str(e)
    if isinstance(e, pymysql.err.ProgrammingError) and code == 1146:          # table doesn't exist
        m = re.search(r"'[^.']*\.([^']+)'", text)
        table = m.group(1) if m else "?"
        how = LOADERS.get(table)
        return HTTPException(503, f"Not loaded yet: table `{table}` does not exist in this database."
                                  + (f" Load it with: {how}" if how else ""))
    if isinstance(e, pymysql.err.OperationalError) and code == 1054:           # unknown column
        return HTTPException(503, f"Schema is out of date ({text}). Run: python -m common.migrate")
    if isinstance(e, pymysql.err.OperationalError):
        # Timeout or lost connection: say so instead of hanging (e.g. MariaDB stalled on a full disk).
        return HTTPException(503, f"Database not responding ({text}). "
                                  "Check that MariaDB is running and its disk is not full.")
    return HTTPException(500, f"Database error: {text}")


DB_ERRORS = (pymysql.err.OperationalError, pymysql.err.ProgrammingError)

def render(sql, params):
    """SQL with ? replaced by the values, for display in the SQL drawer (execution uses params)."""
    out, it = [], iter(params)
    for part in sql.split("?"):
        out.append(part)
        try:
            v = next(it)
        except StopIteration:
            continue
        out.append(str(v) if isinstance(v, (int, float)) else "'" + str(v).replace("'", "''") + "'")
    return "".join(out).strip()


def query(sql, params=()):
    """Run one query on a pooled connection; returns (rows as dicts, ms).
    SQL is written with ? placeholders (that is what the SQL drawer shows); pymysql wants %s."""
    try:
        with pool.connection() as con, con.cursor() as cur:
            t = time.perf_counter()
            cur.execute(sql.replace("?", "%s") if params else sql, params or None)
            rows = list(cur.fetchall())
            return rows, round((time.perf_counter() - t) * 1000, 2)
    except DB_ERRORS as e:
        raise db_error(e)
