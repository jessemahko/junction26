r"""Build article_divergence: the editor worklist, one row per topic in fi + sv + en (2,919).

    .venv\Scripts\python -m db.build_divergence

Parts (each 0..1, higher = needs an editor more):
  distance    mean of the percentile ranks of the LENGTH-ADJUSTED fi–sv and fi–en distances.
              Whole-article distance = VEC_DISTANCE_COSINE between dataset S's bge-m3 vectors. It grows
              when one version is much longer, so for each pair a linear fit on all 2,919 topics,
                  distance ≈ a + b·|ln(len_fi / len_other)| + c·ln(min(len_fi, len_other)),
              (lengths in characters, +1) removes what length explains, and the residual is ranked.
              A high residual = the versions say different things, not just more or less.
  missing     mean of the percentile ranks of the LENGTH-ADJUSTED unaligned share for sv and en:
                  unaligned_l = (missing_l + missing_in_fi_l) / (fi_sentences + l_sentences)
              = the share of both versions' sentences with no counterpart closer than 0.418, in either
              direction. A much longer version leaves more unaligned by itself, so the same kind of fit
              as for the distance, on sentence counts over every topic with sentence data,
                  unaligned ≈ a + b·|ln(n_fi / n_l)| + c·ln(min(n_fi, n_l)),
              removes what length explains, and the residual is ranked.
  edit_war    PERCENT_RANK of (sentence lives that came back + whole-article reverts) of the Finnish
              article, from article_stats (built from article_sentence FOR SYSTEM_TIME ALL)
score = 0.3 · distance + 0.3 · missing + 0.4 · edit_war. A missing part (no sentences in a language,
no Finnish history) is left out and the others reweighted. p_distance / p_missing / p_edit_war keep the
parts, to explain a rank.

  missing_sv / missing_en       Finnish sentences with NO sv / en sentence closer than 0.418
                                (the nearest one, mutual or not: lang_pair direction 'fi')
  missing_in_fi_sv / _en        sv / en sentences with no Finnish sentence closer than 0.418
                                (lang_pair direction 'other')

"Different subject": the same Wikidata id, but the language versions are about different things
(Renki = a Finnish farmhand vs Farmworker). Flagged when the raw whole-article distance is above the
97th percentile for fi–sv or fi–en AND under SUBJECT_SHARE of the shorter version's sentences have a
mutual match, when that shorter version has at least MIN_SENTENCES sentences (a stub is not a
different subject). db/subject_overrides.tsv overrides the rule per topic (same / different).
Flagged topics get no rank and are left out of the main worklist.
"""
from __future__ import annotations

import csv
import sys
import time

import numpy as np

from common.db import ROOT, connect
from db.lang_distance import SQL as DISTANCE_SQL
from db.lang_match import THRESHOLD
from ingest.load_judgements import PRIMARY_MODEL, ensure_table

EXTREME_PERCENTILE = 97
SUBJECT_SHARE = 0.10
MIN_SENTENCES = 5
WEIGHTS = {"distance": 0.3, "missing": 0.3, "edit_war": 0.4}
OVERRIDES = ROOT / "db" / "subject_overrides.tsv"

DDL = [
    "DROP TABLE IF EXISTS article_divergence",
    """CREATE TABLE article_divergence (
  wikidata_id        VARCHAR(20) NOT NULL PRIMARY KEY,
  fi_page_id         INT UNSIGNED NOT NULL,
  fi_sv              FLOAT, fi_en FLOAT, sv_en FLOAT,       -- whole-article cosine distance
  fi_sv_resid        FLOAT, fi_en_resid FLOAT,              -- the same, minus what length explains
  has_sentences      BOOL NOT NULL DEFAULT 0,
  fi_sentences       INT, sv_sentences INT, en_sentences INT,
  missing_sv         INT, missing_en INT,                   -- NULL: sentences not computed
  missing_in_fi_sv   INT, missing_in_fi_en INT,
  share_sv           FLOAT, share_en FLOAT,                 -- mutual matches / shorter version's sentences
  unaligned_sv       FLOAT, unaligned_en FLOAT,             -- sentences without counterpart / all sentences
  unaligned_sv_resid FLOAT, unaligned_en_resid FLOAT,       -- the same, minus what length explains
  contradictions     INT,                                   -- NULL: Gemma has not judged this topic
  edit_war_score     FLOAT,                                 -- NULL: Finnish article not in dataset M
  different_subject  BOOL NOT NULL DEFAULT 0,
  subject_note       VARCHAR(400),
  p_distance         FLOAT, p_missing FLOAT, p_edit_war FLOAT,   -- the score's parts, 0..1
  score              FLOAT,
  rnk                INT,
  KEY (rnk)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""",
]

# Per topic, language and direction: sentences, mutual matches, and sentences with nothing closer than
# the threshold (= missing in the other language; direction 'other' = missing in Finnish).
SENTENCE_SQL = f"""
SELECT wikidata_id, other_lang, direction, COUNT(*) AS n, SUM(matched) AS matched,
       SUM(distance >= {THRESHOLD}) AS far
FROM lang_pair
GROUP BY wikidata_id, other_lang, direction"""

EDIT_WAR_SQL = """
SELECT t.wikidata_id,
       PERCENT_RANK() OVER (ORDER BY (s.lives - s.distinct_sentences) + s.reverts) AS edit_war_score
FROM lang_topic t
JOIN article_stats s ON s.page_id = t.fi_page_id"""

CONTRADICTIONS_SQL = f"""
SELECT wikidata_id, SUM(label = 'contradiction') AS contradictions
FROM pair_judgement WHERE model = '{PRIMARY_MODEL}' GROUP BY wikidata_id"""


def length_residual(dist: np.ndarray, la: np.ndarray, lb: np.ndarray) -> tuple[np.ndarray, dict]:
    """Residual of distance ≈ a + b·|ln ratio| + c·ln(shorter), least squares over all topics."""
    ratio = np.abs(np.log((la + 1) / (lb + 1)))
    short = np.log(np.minimum(la, lb) + 1)
    X = np.column_stack([np.ones_like(dist), ratio, short])
    coef, *_ = np.linalg.lstsq(X, dist, rcond=None)
    resid = dist - X @ coef
    return resid, {"a": coef[0], "b": coef[1], "c": coef[2], "r2": 1 - resid.var() / dist.var()}


def pct_rank(x: np.ndarray) -> np.ndarray:
    return x.argsort().argsort() / (len(x) - 1)


def load_overrides() -> dict:
    with open(OVERRIDES, encoding="utf-8", newline="") as f:
        return {r["wikidata_id"]: r for r in csv.DictReader(f, delimiter="\t")}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    con = connect(autocommit=True)
    cur = con.cursor()
    for ddl in DDL:
        cur.execute(ddl)
    ensure_table(cur)          # pair_judgement (python -m ingest.load_judgements fills it)
    cur.execute(DISTANCE_SQL)
    topics = {r["wikidata_id"]: r for r in cur.fetchall()}
    cur.execute("SELECT wikidata_id, fi_page_id FROM lang_topic")
    page = {r["wikidata_id"]: r["fi_page_id"] for r in cur.fetchall()}
    cur.execute(SENTENCE_SQL)
    sent: dict = {}
    for r in cur.fetchall():
        sent.setdefault(r["wikidata_id"], {})[(r["other_lang"], r["direction"])] = \
            (int(r["n"]), int(r["matched"]), int(r["far"]))
    cur.execute(EDIT_WAR_SQL)
    war = {r["wikidata_id"]: float(r["edit_war_score"]) for r in cur.fetchall()}
    cur.execute(CONTRADICTIONS_SQL)
    contra = {r["wikidata_id"]: int(r["contradictions"]) for r in cur.fetchall()}
    overrides = load_overrides()

    ids = sorted(topics)
    col = lambda k: np.array([float(topics[q][k]) for q in ids])
    d = {p: col(p) for p in ("fi_sv", "fi_en", "sv_en")}
    length = {l: col(f"len_{l}") for l in ("fi", "sv", "en")}
    resid, fit = {}, {}
    for pair, other in (("fi_sv", "sv"), ("fi_en", "en")):
        resid[pair], fit[pair] = length_residual(d[pair], length["fi"], length[other])
        print(f"length fit {pair}: distance = {fit[pair]['a']:.3f} + {fit[pair]['b']:.3f}·|ln ratio| "
              f"{fit[pair]['c']:+.4f}·ln(shorter); length explains R² = {fit[pair]['r2']:.0%}")
    pr = {p: pct_rank(resid[p]) for p in resid}
    cut = {p: np.percentile(d[p], EXTREME_PERCENTILE) for p in ("fi_sv", "fi_en")}

    rows = []
    for i, q in enumerate(ids):
        s = sent.get(q)
        has = bool(s and all(k in s for k in (("sv", "fi"), ("en", "fi"), ("sv", "other"), ("en", "other"))))
        r = dict(wikidata_id=q, fi_page_id=page[q], fi_sv=float(d["fi_sv"][i]), fi_en=float(d["fi_en"][i]),
                 sv_en=float(d["sv_en"][i]), fi_sv_resid=float(resid["fi_sv"][i]),
                 fi_en_resid=float(resid["fi_en"][i]), has_sentences=has, fi_sentences=None,
                 sv_sentences=None, en_sentences=None, missing_sv=None, missing_en=None,
                 missing_in_fi_sv=None, missing_in_fi_en=None, share_sv=None, share_en=None,
                 unaligned_sv=None, unaligned_en=None, unaligned_sv_resid=None, unaligned_en_resid=None,
                 contradictions=contra.get(q), edit_war_score=war.get(q), different_subject=False,
                 subject_note=None, p_distance=None, p_missing=None, p_edit_war=None, score=None, rnk=None)
        if has:
            r["fi_sentences"] = s[("sv", "fi")][0]
            for l in ("sv", "en"):
                r[f"{l}_sentences"] = s[(l, "other")][0]
                r[f"missing_{l}"] = s[(l, "fi")][2]
                r[f"missing_in_fi_{l}"] = s[(l, "other")][2]
                shorter = min(r["fi_sentences"], r[f"{l}_sentences"])
                r[f"share_{l}"] = s[(l, "fi")][1] / max(1, shorter)
                r[f"unaligned_{l}"] = (r[f"missing_{l}"] + r[f"missing_in_fi_{l}"]) / \
                    max(1, r["fi_sentences"] + r[f"{l}_sentences"])
                if (d[f"fi_{l}"][i] > cut[f"fi_{l}"] and r[f"share_{l}"] < SUBJECT_SHARE
                        and shorter >= MIN_SENTENCES and not r["different_subject"]):
                    r["different_subject"] = True
                    r["subject_note"] = (f"fi–{l} distance {d[f'fi_{l}'][i]:.3f} (> p{EXTREME_PERCENTILE} "
                                         f"{cut[f'fi_{l}']:.3f}) and only {r[f'share_{l}']:.0%} of the shorter "
                                         f"version's sentences match")
        o = overrides.get(q)
        if o:
            r["different_subject"] = o["subject"] == "different"
            r["subject_note"] = f"override ({o['subject']} subject): {o['note']}"
        r["p_distance"] = float((pr["fi_sv"][i] + pr["fi_en"][i]) / 2)
        r["p_edit_war"] = war.get(q)
        rows.append(r)

    # missing: length-adjusted unaligned share, over the topics with sentence data
    has = [r for r in rows if r["has_sentences"]]
    pm = {}
    for l in ("sv", "en"):
        u = np.array([r[f"unaligned_{l}"] for r in has])
        nf = np.array([float(r["fi_sentences"]) for r in has])
        no = np.array([float(r[f"{l}_sentences"]) for r in has])
        res, f = length_residual(u, nf, no)
        print(f"length fit unaligned_{l}: share = {f['a']:.3f} + {f['b']:.3f}·|ln ratio| {f['c']:+.4f}·ln(shorter) "
              f"(sentence counts); length explains R² = {f['r2']:.0%}")
        for r, v in zip(has, res):
            r[f"unaligned_{l}_resid"] = float(v)
        pm[l] = pct_rank(res)
    for k, r in enumerate(has):
        r["p_missing"] = float((pm["sv"][k] + pm["en"][k]) / 2)
    for r in rows:
        parts = {"distance": r["p_distance"], "missing": r["p_missing"], "edit_war": r["p_edit_war"]}
        avail = {k: v for k, v in parts.items() if v is not None}
        r["score"] = round(float(sum(WEIGHTS[k] * v for k, v in avail.items()) / sum(WEIGHTS[k] for k in avail)), 4)
    for k, r in enumerate(sorted((r for r in rows if not r["different_subject"]), key=lambda r: -r["score"]), 1):
        r["rnk"] = k
    cols = list(rows[0])
    cur.executemany(f"INSERT INTO article_divergence ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    [tuple(r[c] for c in cols) for r in rows])
    flagged = [r for r in rows if r["different_subject"]]
    print(f"article_divergence: {len(rows):,} topics, {sum(r['has_sentences'] for r in rows)} with sentence data, "
          f"{sum(r['edit_war_score'] is not None for r in rows):,} with an edit-war score, "
          f"{len(flagged)} flagged as different subject, {len(overrides)} override(s) ({time.time() - t0:.1f} s)")
    con.close()


if __name__ == "__main__":
    main()
