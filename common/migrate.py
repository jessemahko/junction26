"""Bring an `article` table loaded before the merge (by the old load_parquet.py) to the unified
definition in db/schema.sql, without rewriting it.

    python -m common.migrate            # apply what is missing (safe to re-run)
    python -m common.migrate --check    # only report the differences

Every step is tried with ALGORITHM=INSTANT, so a 6 GB table is never rebuilt behind your back:
a step that MariaDB cannot do instantly is reported and skipped. Nothing is dropped.
"""
from __future__ import annotations

import argparse

import pymysql

from common.db import connect

# (what to look for in SHOW CREATE TABLE, the ALTER that provides it, why)
STEPS = [
    ("`editor`", "RENAME COLUMN `user` TO `editor`", "one name for 'who saved it' in article and article_sentence"),
    ("`content`", "RENAME COLUMN `text` TO `content`", "`text` is the sentence text in article_sentence"),
    ("`n_sentences`", "ADD COLUMN n_sentences INT UNSIGNED NOT NULL DEFAULT 0 AFTER `len`", "sentence views"),
    ("`sentence_order`", "ADD COLUMN sentence_order MEDIUMBLOB COMPRESSED NULL AFTER n_sentences", "sentence views"),
    ("`title` varchar(512)", "MODIFY COLUMN title VARCHAR(512) NOT NULL", "long titles"),
]
# Not instant: these build an index or rewrite the table. Run only with --slow.
SLOW = [
    ("KEY `rev_key`", "ADD KEY rev_key (rev_id)", "INPLACE", "/api/revisions/{rev_id}"),
    ("KEY `title_key`", "ADD KEY title_key (title)", "INPLACE", "article search"),
]
# Left as loaded (harmless; fixed for free if the table is ever reloaded):
KNOWN_DIFFERENCES = [
    "rev_id is INT UNSIGNED (schema: BIGINT UNSIGNED); fi.wikipedia revision ids are < 2^32",
    "sha1 is CHAR(31) (schema: CHAR(40)); Wikipedia's base-36 SHA-1 is 31 characters",
    "collation is utf8mb4_uca1400_ai_ci (schema: utf8mb4_unicode_ci)",
    "content is NOT NULL DEFAULT '' (schema: NULL allowed)",
]


def ddl(cur) -> str:
    cur.execute("SHOW CREATE TABLE article")
    return cur.fetchone()[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--slow", action="store_true", help="also add the two indexes (scans the table)")
    a = ap.parse_args()
    conn = connect(autocommit=True, dict_rows=False)
    cur = conn.cursor()
    cur.execute("SET system_versioning_alter_history = KEEP")   # ALTER of a versioned table keeps its history
    todo = [(alter, "INSTANT", why) for have, alter, why in STEPS if have not in ddl(cur)]
    todo += [(alter, algo, why) for have, alter, algo, why in SLOW if have not in ddl(cur) and (a.slow or a.check)]
    if not todo:
        print("article matches db/schema.sql (apart from the known differences below).")
    for alter, algo, why in todo:
        if a.check:
            print(f"missing: {alter}   -- {why}")
            continue
        try:
            cur.execute(f"ALTER TABLE article {alter}, ALGORITHM={algo}")
            print(f"ok ({algo.lower()}): {alter}")
        except pymysql.err.MySQLError as e:
            print(f"SKIPPED, not possible with ALGORITHM={algo}: {alter}\n         {e.args[-1]}")
    print("\nKnown differences left as loaded:")
    for d in KNOWN_DIFFERENCES:
        print(f"  - {d}")
    conn.close()


if __name__ == "__main__":
    main()
