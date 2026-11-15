r"""Load dataset S's Finnish category tree into category_link and article_category.

    .venv\Scripts\python -m ingest.load_categories

Files (from the dataset repo; identical copies in reference/mariadb-vector-wikipedia-rag/data/):
  s-category-links-fi.tsv     parent, child   child = a subcategory OR an article title
  s-article-categories-fi.tsv page_id, category  an article's own categories (Finnish page ids)

The worklist's topic chips walk this tree with WITH RECURSIVE (api/explore.py). Re-runnable: both
tables are rebuilt from the files (they hold nothing else).
"""
from __future__ import annotations

import csv
import sys
import time

from common.db import ROOT, connect

LISTS = ROOT / "reference" / "mariadb-wikipedia-datasets" / "lists"
FALLBACK = ROOT / "reference" / "mariadb-vector-wikipedia-rag" / "data"

DDL = [
    "DROP TABLE IF EXISTS category_link",
    """CREATE TABLE category_link (
  parent  VARCHAR(255) NOT NULL,
  child   VARCHAR(255) NOT NULL,        -- a subcategory, or an article title
  PRIMARY KEY (parent, child),
  KEY child (child)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
    "DROP TABLE IF EXISTS article_category",
    """CREATE TABLE article_category (
  page_id   INT UNSIGNED NOT NULL,      -- Finnish page id (lang_article.page_id, lang = 'fi')
  category  VARCHAR(255) NOT NULL,
  PRIMARY KEY (page_id, category),
  KEY category (category)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
]


def read(name: str) -> list[dict]:
    path = LISTS / f"s-{name}" if (LISTS / f"s-{name}").exists() else FALLBACK / name
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    links = read("category-links-fi.tsv")
    cats = read("article-categories-fi.tsv")
    con = connect(autocommit=True)
    cur = con.cursor()
    for ddl in DDL:
        cur.execute(ddl)
    cur.executemany("INSERT IGNORE INTO category_link (parent, child) VALUES (%s, %s)",
                    [(r["parent"], r["child"]) for r in links])
    cur.executemany("INSERT IGNORE INTO article_category (page_id, category) VALUES (%s, %s)",
                    [(int(r["page_id"]), r["category"]) for r in cats])
    cur.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT parent) AS parents FROM category_link")
    a = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT category) AS c, COUNT(DISTINCT page_id) AS p FROM article_category")
    b = cur.fetchone()
    cur.execute("""SELECT COUNT(DISTINCT t.wikidata_id) AS n FROM lang_topic t
JOIN article_category c ON c.page_id = t.fi_page_id""")
    covered = cur.fetchone()["n"]
    print(f"category_link: {a['n']:,} links under {a['parents']:,} parent categories; "
          f"article_category: {b['n']:,} rows, {b['c']:,} categories, {b['p']:,} pages; "
          f"{covered:,} of the 2,919 fi+sv+en topics have a category ({time.time() - t0:.1f} s)")
    con.close()


if __name__ == "__main__":
    main()
