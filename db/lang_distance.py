r"""Stage 1, level 1: whole-article distance between the fi / sv / en versions of the 2,919 shared topics.

    .venv\Scripts\python -m db.lang_distance > data\lang_distance.txt

Cosine distance between dataset S's bge-m3 article vectors (0 = same direction). Prints the SQL, the
10 most and least similar topics per pair, the distribution, and how much of the distance is
explained by the two versions having different lengths.
"""
from __future__ import annotations

import sys
import time

import numpy as np

from common.db import connect

SQL = """
SELECT t.wikidata_id, fi.title AS title_fi, sv.title AS title_sv, en.title AS title_en,
       fi.len AS len_fi, sv.len AS len_sv, en.len AS len_en,
       vf.truncated OR vs.truncated OR ve.truncated AS truncated,
       VEC_DISTANCE_COSINE(vf.embedding, vs.embedding) AS fi_sv,
       VEC_DISTANCE_COSINE(vf.embedding, ve.embedding) AS fi_en,
       VEC_DISTANCE_COSINE(vs.embedding, ve.embedding) AS sv_en
FROM lang_topic t
JOIN lang_article fi ON fi.lang = 'fi' AND fi.page_id = t.fi_page_id
JOIN lang_article sv ON sv.lang = 'sv' AND sv.page_id = t.sv_page_id
JOIN lang_article en ON en.lang = 'en' AND en.page_id = t.en_page_id
JOIN lang_article_vector vf ON vf.lang = 'fi' AND vf.page_id = t.fi_page_id
JOIN lang_article_vector vs ON vs.lang = 'sv' AND vs.page_id = t.sv_page_id
JOIN lang_article_vector ve ON ve.lang = 'en' AND ve.page_id = t.en_page_id"""

PAIRS = {"fi_sv": ("fi", "sv"), "fi_en": ("fi", "en"), "sv_en": ("sv", "en")}
HEROES = {"Q29207": "Sauli Niinistö", "Q211855": "Suomen sisällissota"}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    con = connect()
    cur = con.cursor()
    t = time.perf_counter()
    cur.execute(SQL)
    rows = cur.fetchall()
    ms = (time.perf_counter() - t) * 1000
    print(f"{SQL.strip()}\n\n-> {len(rows):,} topics in {ms:.0f} ms\n")
    n_trunc = sum(1 for r in rows if r["truncated"])
    print(f"{n_trunc:,} topics have at least one truncated vector (article longer than bge-m3 reads)\n")

    for pair, (a, b) in PAIRS.items():
        d = np.array([float(r[pair]) for r in rows])
        la = np.array([r[f"len_{a}"] for r in rows], dtype=float)
        lb = np.array([r[f"len_{b}"] for r in rows], dtype=float)
        ratio = np.abs(np.log((la + 1) / (lb + 1)))           # 0 = same length; 0.69 = one twice the other
        short = np.log(np.minimum(la, lb) + 1)                 # the shorter version's size
        X = np.column_stack([np.ones_like(d), ratio, short])
        coef, *_ = np.linalg.lstsq(X, d, rcond=None)
        resid = d - X @ coef
        r2 = 1 - resid.var() / d.var()
        r_ratio = np.corrcoef(ratio, d)[0, 1]
        r_short = np.corrcoef(short, d)[0, 1]
        print(f"=== {a}–{b}")
        q = np.percentile(d, [0, 10, 25, 50, 75, 90, 99, 100])
        print("distribution: min {:.3f} · p10 {:.3f} · p25 {:.3f} · median {:.3f} · p75 {:.3f} · "
              "p90 {:.3f} · p99 {:.3f} · max {:.3f}".format(*q))
        print(f"mean {d.mean():.3f}, sd {d.std():.3f}")
        hist, edges = np.histogram(d, bins=10)
        print("histogram: " + "  ".join(f"{edges[i]:.2f}–{edges[i + 1]:.2f}: {hist[i]}" for i in range(10)))
        print(f"length: corr(distance, |log length ratio|) = {r_ratio:+.2f}; "
              f"corr(distance, log shorter length) = {r_short:+.2f}; "
              f"both together explain R² = {r2:.0%} of the variance")
        print(f"        fit: distance = {coef[0]:.3f} + {coef[1]:.3f}·|log ratio| + {coef[2]:.3f}·log(shorter)")
        for r, res in zip(rows, resid):
            r[f"{pair}_resid"] = float(res)
        order = sorted(rows, key=lambda r: float(r[pair]))

        def line(r):
            return (f"  {float(r[pair]):.3f}  {r['wikidata_id']:<10} {r['title_' + a]} / {r['title_' + b]}"
                    f"  ({r['len_' + a]:,} / {r['len_' + b]:,} chars)")
        print("10 most similar:")
        for r in order[:10]:
            print(line(r))
        print("10 least similar:")
        for r in order[-10:][::-1]:
            print(line(r))
        by_res = sorted(rows, key=lambda r: r[f"{pair}_resid"])
        print("10 least similar after removing the length effect (largest residual):")
        for r in by_res[-10:][::-1]:
            print(line(r) + f"  residual {r[pair + '_resid']:+.3f}")
        for q_id, name in HEROES.items():
            r = next(x for x in rows if x["wikidata_id"] == q_id)
            rank = 1 + sum(1 for x in rows if float(x[pair]) > float(r[pair]))
            print(f"{name}: {float(r[pair]):.3f}, rank {rank:,} of {len(rows):,} by distance "
                  f"(1 = least similar), residual {r[pair + '_resid']:+.3f}")
        print()
    con.close()


if __name__ == "__main__":
    main()
