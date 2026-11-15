r"""Build page_origin: where each Finnish article sits on the map (topic_place reads it).

    .venv\Scripts\python -m ingest.build_origin            # the current year (2026)
    .venv\Scripts\python -m ingest.build_origin --year 2018

An article's own place (page_place, from Wikidata) when it has one; otherwise "inferred": the
non-country place it linked most during the year (place_link FOR SYSTEM_TIME FROM … TO …; ties: the
oldest link). Rebuilds the table for the given year.
"""
from __future__ import annotations

import argparse
import sys
import time

from common.db import connect

DDL = """CREATE TABLE IF NOT EXISTS page_origin (year SMALLINT NOT NULL, page_id INT UNSIGNED NOT NULL,
  place_title VARCHAR(255) NOT NULL, inferred BOOL NOT NULL,
  PRIMARY KEY (year, page_id)) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"""

ORIGIN = [
    """INSERT INTO page_origin (year, page_id, place_title, inferred)
SELECT {year}, page_id, place_title, 0 FROM page_place""",
    """INSERT IGNORE INTO page_origin (year, page_id, place_title, inferred)
SELECT {year}, page_id, to_place, 1
FROM (SELECT l.page_id, l.to_place,
             ROW_NUMBER() OVER (PARTITION BY l.page_id
                                ORDER BY l.mentions DESC, l.row_start, l.to_place) AS rn
      FROM place_link FOR SYSTEM_TIME FROM TIMESTAMP'{y0}' TO TIMESTAMP'{y1}' l
      JOIN place p ON p.title = l.to_place
      WHERE p.is_country = 0) ranked
WHERE rn = 1""",
]


def for_year(sql: str, year: int) -> str:
    return sql.format(year=year, y0=f"{year}-01-01 00:00:00", y1=f"{year + 1}-01-01 00:00:00")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    year = ap.parse_args().year
    t = time.time()
    con = connect(dict_rows=False)
    cur = con.cursor()
    cur.execute(DDL)
    cur.execute("DELETE FROM page_origin WHERE year = %s", (year,))
    for sql in ORIGIN:
        cur.execute(for_year(sql, year))
    con.commit()
    cur.execute("SELECT COUNT(*), SUM(inferred) FROM page_origin WHERE year = %s", (year,))
    n, inferred = cur.fetchone()
    print(f"page_origin {year}: {n:,} articles, {int(inferred or 0):,} inferred ({time.time() - t:.1f} s)")
    con.close()


if __name__ == "__main__":
    main()
