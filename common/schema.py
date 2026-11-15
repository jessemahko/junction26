"""Create the tables from db/schema.sql.

    python -m common.schema            # create missing tables (safe to re-run)
    python -m common.schema --reset    # drop and recreate everything (asks no questions!)
    python -m common.schema --db wiki_test
"""
from __future__ import annotations

import argparse
import os
import re

import pymysql

from common.db import ROOT, connect, settings

TABLES = ["sentence_score", "sentence_event_time", "article_sentence", "article", "article_geo",
          "article_stats", "load_log", "article_sentence_order",
          "article_list", "place", "page_place", "place_link", "revert", "page_origin"]
RESET_LIMIT = 100_000   # --reset refuses to drop an `article` with more versions than this


def apply(database: str | None = None, reset: bool = False) -> None:
    name = database or settings()["database"]
    server = connect(database="", autocommit=True)
    with server.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4")
    server.close()

    conn = connect(name, autocommit=True)
    with conn.cursor() as cur:
        if reset:
            # A real load is hours of work: only test and demo databases may be reset.
            try:
                cur.execute("SELECT COUNT(*) AS n FROM article FOR SYSTEM_TIME ALL")
                n = cur.fetchone()["n"]
            except pymysql.err.ProgrammingError:
                n = 0
            if n > RESET_LIMIT and os.environ.get("ALLOW_RESET") != "1":
                raise SystemExit(f"Refusing to reset `{name}`: article holds {n:,} versions. "
                                 "Set ALLOW_RESET=1 if you really mean it.")
            for t in TABLES:
                cur.execute(f"DROP TABLE IF EXISTS `{t}`")
        sql = re.sub(r"--[^\n]*", "", (ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        for statement in sql.split(";"):
            if statement.strip():
                cur.execute(statement)
        cur.execute("SHOW TABLES")
        tables = [next(iter(r.values())) for r in cur.fetchall()]
    conn.close()
    print(f"{name}: {', '.join(sorted(tables))}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None)
    p.add_argument("--reset", action="store_true")
    a = p.parse_args()
    try:
        apply(a.db, a.reset)
    except pymysql.err.OperationalError as e:
        raise SystemExit(f"Cannot reach MariaDB ({e}). Is it running? -> make db")
