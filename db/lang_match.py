r"""Sentence matching between the fi / sv / en versions of a topic (level 2), all in MariaDB.

    .venv\Scripts\python -m db.lang_match                       # every topic with sentences in lang_sentence
    .venv\Scripts\python -m db.lang_match --topics Q29207,Q211855
    .venv\Scripts\python -m db.lang_match --report > data\lang_match.txt   # heroes: counts + examples
    .venv\Scripts\python -m db.lang_match --calibrate           # recompute the threshold (stage 1)

For each sentence, its nearest sentence in the other language of the same topic, both directions
(VEC_DISTANCE_COSINE, exact within the topic) -> lang_pair. A pair is **mutual** when each sentence
is the other's best match, and **matched** when it is mutual and closer than THRESHOLD.
A Finnish sentence without a matched pair is "missing" in that language; an sv / en sentence without
one is "only_sv" / "only_en".

THRESHOLD (stage 1, `--calibrate`): for each Finnish sentence of the hero articles, its nearest
sentence among UNRELATED articles of the other language (random topics, a pool as large as the real
article) is a "match by chance"; 0.418 is the 5th percentile of those chance distances.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import numpy as np

from common.db import connect

THRESHOLD = 0.418
CHANCE_PERCENTILE = 5
HEROES = {"Q29207": "Sauli Niinistö", "Q211855": "Suomen sisällissota"}

PAIR_SQL = """
INSERT INTO lang_pair (wikidata_id, other_lang, direction, fi_sent, other_sent, distance)
SELECT %(q)s, %(lang)s, %(direction)s, fi_sent, other_sent, distance
FROM (SELECT f.sent_no AS fi_sent, o.sent_no AS other_sent,
             VEC_DISTANCE_COSINE(f.embedding, o.embedding) AS distance,
             ROW_NUMBER() OVER (PARTITION BY {side}.sent_no
                                ORDER BY VEC_DISTANCE_COSINE(f.embedding, o.embedding)) AS rn
      FROM lang_sentence f
      JOIN lang_sentence o ON o.wikidata_id = f.wikidata_id AND o.lang = %(lang)s
      WHERE f.wikidata_id = %(q)s AND f.lang = 'fi') best
WHERE rn = 1"""

# A pair is mutual when the same (fi_sent, other_sent) is the best match in both directions.
MUTUAL_SQL = """
UPDATE lang_pair p
JOIN lang_pair r ON r.wikidata_id = p.wikidata_id AND r.other_lang = p.other_lang
                AND r.direction <> p.direction
                AND r.fi_sent = p.fi_sent AND r.other_sent = p.other_sent
SET p.mutual = 1, p.matched = (p.distance < %(th)s)
WHERE p.wikidata_id = %(q)s"""

CHANCE_SQL = """
SELECT f.sent_no, MIN(VEC_DISTANCE_COSINE(f.embedding, o.embedding)) AS distance
FROM lang_sentence f
JOIN lang_sentence o ON o.lang = %(lang)s AND o.wikidata_id IN ({pool})
WHERE f.wikidata_id = %(q)s AND f.lang = 'fi'
GROUP BY f.sent_no"""

_NUM_SEP = re.compile(r"(?<=\d)[\s  ,](?=\d{3}\b)")      # 80 000 / 80,000 -> 80000
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_FOOTNOTE = re.compile(r"\[\d+\]")                                     # [130]: a reference, not a number


def numbers(text: str) -> set[str]:
    t = _NUM_SEP.sub("", _FOOTNOTE.sub("", text))
    return {n.replace(",", ".") for n in _NUM.findall(t)}


def ensure_columns(cur) -> None:
    cur.execute("ALTER TABLE lang_pair ADD COLUMN IF NOT EXISTS mutual BOOL NOT NULL DEFAULT 0, "
                "ADD COLUMN IF NOT EXISTS matched BOOL NOT NULL DEFAULT 0")


def match(cur, topics: list[str]) -> float:
    t = time.perf_counter()
    for q in topics:
        cur.execute("DELETE FROM lang_pair WHERE wikidata_id = %s", (q,))
        for lang in ("sv", "en"):
            for direction, side in (("fi", "f"), ("other", "o")):
                cur.execute(PAIR_SQL.format(side=side), dict(q=q, lang=lang, direction=direction))
        cur.execute(MUTUAL_SQL, dict(q=q, th=THRESHOLD))
    return time.perf_counter() - t


def match_parallel(topics: list[str], workers: int) -> float:
    """match() over several connections (one per worker); topics are independent."""
    from concurrent.futures import ThreadPoolExecutor
    t = time.perf_counter()
    chunks = [topics[i::workers] for i in range(workers)]
    done = [0]

    def run(chunk: list[str]) -> None:
        con = connect(autocommit=True)
        try:
            cur = con.cursor()
            for i in range(0, len(chunk), 50):
                match(cur, chunk[i:i + 50])
                done[0] += len(chunk[i:i + 50])
                print(f"  {done[0]:,} / {len(topics):,} topics, {time.perf_counter() - t:.0f} s", flush=True)
        finally:
            con.close()

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(run, chunks))
    return time.perf_counter() - t


def topics_with_sentences(cur) -> list[str]:
    cur.execute("SELECT wikidata_id FROM lang_sentence GROUP BY wikidata_id "
                "HAVING COUNT(DISTINCT lang) = 3 ORDER BY wikidata_id")
    return [r["wikidata_id"] for r in cur.fetchall()]


def calibrate(cur) -> None:
    cur.execute("SELECT wikidata_id, lang, COUNT(*) AS n FROM lang_sentence GROUP BY wikidata_id, lang")
    count = {(r["wikidata_id"], r["lang"]): r["n"] for r in cur.fetchall()}
    cur.execute("SELECT wikidata_id FROM lang_topic")
    # The stage 1 calibration pool: random topics embedded with --null (not heroes, not --extreme).
    nulls = sorted({q for q, _ in count} - set(HEROES))
    chance = []
    rng = np.random.default_rng(1918)
    for q in HEROES:
        for lang in ("sv", "en"):
            pool, n = [], 0
            for nq in rng.permutation(nulls):
                if count.get((nq, lang)):
                    pool.append(str(nq))
                    n += count[(nq, lang)]
                if n >= count[(q, lang)]:
                    break
            cur.execute(CHANCE_SQL.format(pool=",".join(f"'{p}'" for p in pool)), dict(q=q, lang=lang))
            chance += [float(r["distance"]) for r in cur.fetchall()]
    print(f"threshold = {np.percentile(chance, CHANCE_PERCENTILE):.3f} "
          f"({CHANCE_PERCENTILE}th percentile of {len(chance)} chance distances; in use: {THRESHOLD})")


def report(cur) -> None:
    print(f"THRESHOLD = {THRESHOLD} (cosine distance); matched = mutual best match AND distance < threshold\n")
    print("| topic | lang | fi sentences | matched (mutual) | missing in lang | best-only (not mutual) "
          "| lang sentences | only in lang |")
    print("|---|---|---|---|---|---|---|---|")
    for q, name in HEROES.items():
        for lang in ("sv", "en"):
            cur.execute("""SELECT direction, COUNT(*) AS n, SUM(matched) AS matched,
                                  SUM(distance < %s) AS below FROM lang_pair
                           WHERE wikidata_id = %s AND other_lang = %s GROUP BY direction""", (THRESHOLD, q, lang))
            d = {r["direction"]: r for r in cur.fetchall()}
            f, o = d["fi"], d["other"]
            print(f"| {name} | {lang} | {f['n']} | {int(f['matched'])} | **{f['n'] - int(f['matched'])}** "
                  f"| {int(f['below']) - int(f['matched'])} | {o['n']} | {o['n'] - int(o['matched'])} |")

    sql = """
SELECT p.wikidata_id, f.sent_no, f.text AS fi_text, p.distance, o.text AS nearest_en
FROM lang_pair p
JOIN lang_topic t ON t.wikidata_id = p.wikidata_id
JOIN lang_sentence f ON f.lang = 'fi' AND f.page_id = t.fi_page_id AND f.sent_no = p.fi_sent
JOIN lang_sentence o ON o.lang = 'en' AND o.page_id = t.en_page_id AND o.sent_no = p.other_sent
WHERE p.other_lang = 'en' AND p.direction = 'fi' AND NOT p.matched
  AND p.wikidata_id IN ('Q29207', 'Q211855')
  AND LENGTH(f.text) - LENGTH(REPLACE(f.text, ' ', '')) >= 7
ORDER BY p.distance DESC"""
    cur.execute(sql)
    missing = cur.fetchall()
    print(f"\n=== missing in English: {len(missing)} Finnish sentences of 8+ words with no matched English sentence\n"
          f"{sql.strip()}\n")
    for r in missing[:8]:
        print(f"[{HEROES[r['wikidata_id']]} fi#{r['sent_no']}] nearest en {float(r['distance']):.3f}\n"
              f"  FI: {r['fi_text']}\n  nearest EN: {r['nearest_en']}\n")

    cur.execute("""
SELECT p.wikidata_id, p.other_lang, p.fi_sent, p.other_sent, p.distance, f.text AS fi_text, o.text AS other_text
FROM lang_pair p
JOIN lang_topic t ON t.wikidata_id = p.wikidata_id
JOIN lang_sentence f ON f.lang = 'fi' AND f.page_id = t.fi_page_id AND f.sent_no = p.fi_sent
JOIN lang_sentence o ON o.lang = p.other_lang
     AND o.page_id = IF(p.other_lang = 'sv', t.sv_page_id, t.en_page_id) AND o.sent_no = p.other_sent
WHERE p.direction = 'fi' AND p.matched AND p.wikidata_id IN ('Q29207', 'Q211855')""")
    pairs = cur.fetchall()
    diff = []
    for r in pairs:
        nf, no = numbers(r["fi_text"]), numbers(r["other_text"])
        if nf and no and nf - no and no - nf:
            diff.append((r, sorted(nf - no), sorted(no - nf), len(nf & no)))
    print(f"=== matched pairs where each side has a number the other lacks: {len(diff)} of {len(pairs)}\n")
    diff.sort(key=lambda x: (-x[3], float(x[0]["distance"])))
    for r, only_fi, only_other, shared in diff[:8]:
        print(f"[{HEROES[r['wikidata_id']]} fi#{r['fi_sent']} ~ {r['other_lang']}#{r['other_sent']}] "
              f"{float(r['distance']):.3f}, shared {shared}, only fi {only_fi}, only {r['other_lang']} {only_other}\n"
              f"  FI: {r['fi_text']}\n  {r['other_lang'].upper()}: {r['other_text']}\n")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", help="comma-separated wikidata ids (default: all with sentences)")
    ap.add_argument("--report", action="store_true", help="hero counts and examples (no rematching)")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--workers", type=int, default=1, help="parallel connections (topics are independent)")
    a = ap.parse_args()
    con = connect(autocommit=True)
    cur = con.cursor()
    ensure_columns(cur)
    if a.calibrate:
        calibrate(cur)
    elif a.report:
        report(cur)
    else:
        cur.execute("ANALYZE TABLE lang_sentence")   # stale statistics = a full-language scan per topic
        cur.fetchall()
        topics = a.topics.split(",") if a.topics else topics_with_sentences(cur)
        secs = match(cur, topics) if a.workers <= 1 else match_parallel(topics, a.workers)
        cur.execute("SELECT COUNT(*) AS n, SUM(mutual) AS mutual, SUM(matched) AS matched FROM lang_pair")
        r = cur.fetchone()
        print(f"matched {len(topics)} topics in {secs:.1f} s; lang_pair {r['n']:,} rows, "
              f"{int(r['mutual']):,} mutual, {int(r['matched']):,} matched")
    con.close()


if __name__ == "__main__":
    main()
