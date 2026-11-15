r"""Build topic_place: where each fi + sv + en topic sits on the map (one row per located topic).

    .venv\Scripts\python -m db.build_topic_place

The Finnish article's own place (page_place, from Wikidata), else Kristian's article_geo (coordinates
in the Finnish wikitext), else the place its article links most today (page_origin 2026, "inferred":
Niinistö -> Salo). The same rule as the globe's language lines; materialised so the map and the
"most similar articles" query can join it cheaply. Rebuilt from those tables each run.
"""
from __future__ import annotations

import sys
import time

from common.db import connect

DDL = [
    "DROP TABLE IF EXISTS topic_place",
    """CREATE TABLE topic_place (
  wikidata_id  VARCHAR(20) NOT NULL PRIMARY KEY,
  lat          DOUBLE NOT NULL,
  lon          DOUBLE NOT NULL,
  located_by   ENUM('page_place', 'article_geo', 'inferred') NOT NULL,
  place        VARCHAR(255)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
]

FILL = """INSERT INTO topic_place (wikidata_id, lat, lon, located_by, place)
SELECT t.wikidata_id,
       COALESCE(p.lat, g.lat, op.lat), COALESCE(p.lon, g.lon, op.lon),
       CASE WHEN p.title IS NOT NULL THEN 'page_place' WHEN g.page_id IS NOT NULL THEN 'article_geo'
            ELSE 'inferred' END,
       COALESCE(p.title, IF(g.page_id IS NULL, op.title, NULL))
FROM lang_topic t
LEFT JOIN page_place pp ON pp.page_id = t.fi_page_id
LEFT JOIN place p ON p.title = pp.place_title
LEFT JOIN article_geo g ON g.page_id = t.fi_page_id
LEFT JOIN page_origin o ON o.page_id = t.fi_page_id AND o.year = 2026
LEFT JOIN place op ON op.title = o.place_title
WHERE p.title IS NOT NULL OR g.page_id IS NOT NULL OR op.title IS NOT NULL
GROUP BY t.wikidata_id"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    con = connect(autocommit=True)
    cur = con.cursor()
    for ddl in DDL:
        cur.execute(ddl)
    cur.execute(FILL)
    cur.execute("SELECT located_by, COUNT(*) AS n FROM topic_place GROUP BY located_by")
    by = {r["located_by"]: r["n"] for r in cur.fetchall()}
    print(f"topic_place: {sum(by.values()):,} of 2,919 topics located {by} ({time.time() - t0:.1f} s)")
    con.close()


if __name__ == "__main__":
    main()
