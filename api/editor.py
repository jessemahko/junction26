"""The editor tool's routes: the worklist and the fi / sv / en comparison. Format: docs/contracts.md (c).

GET /api/worklist?limit=50&include_flagged=0   topics ranked by how much an editor is needed
GET /api/compare/{wikidata_id}                  fi / sv / en side by side, sentence by sentence

Both answers carry `sql`: the MariaDB queries behind them (vector distances, sentence matches).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.db import query, render
from db.lang_match import THRESHOLD
from ingest.load_judgements import PRIMARY_MODEL

router = APIRouter(tags=["editor"])
LANGS = ("fi", "sv", "en")


def _num(v, nd=3):
    return None if v is None else round(float(v), nd)


def _int(v):
    return None if v is None else int(v)


WORKLIST_SQL = """SELECT d.wikidata_id, fi.title AS title_fi, sv.title AS title_sv, en.title AS title_en,
       d.fi_page_id, d.score, d.fi_sv, d.fi_en, d.missing_sv, d.missing_en,
       d.missing_in_fi_sv, d.missing_in_fi_en, d.edit_war_score,
       j.judged_pairs, j.contradictions, j.framing
FROM article_divergence d
JOIN lang_topic t USING (wikidata_id)
LEFT JOIN (SELECT wikidata_id, COUNT(*) AS judged_pairs,
                  SUM(label = 'contradiction') AS contradictions, SUM(label = 'framing') AS framing
           FROM pair_judgement WHERE model = ? GROUP BY wikidata_id) j USING (wikidata_id)
JOIN lang_article fi ON fi.lang = 'fi' AND fi.page_id = t.fi_page_id
JOIN lang_article sv ON sv.lang = 'sv' AND sv.page_id = t.sv_page_id
JOIN lang_article en ON en.lang = 'en' AND en.page_id = t.en_page_id
{where}
ORDER BY d.different_subject, d.score DESC
LIMIT ?"""


@router.get("/api/worklist")
def worklist(limit: int = Query(50, ge=1, le=3000), include_flagged: bool = False):
    """Topics in fi + sv + en, highest score first. Topics flagged as "different subject" (the same
    Wikidata id, but the versions are about different things) are left out unless include_flagged.
    Gemma's counts (primary model) are null where the topic has not been judged; not in the score yet."""
    sql = WORKLIST_SQL.format(where="" if include_flagged else "WHERE NOT d.different_subject")
    params = (PRIMARY_MODEL, limit)
    rows, ms = query(sql, params)
    data = [{"wikidata_id": r["wikidata_id"],
             "titles": {"fi": r["title_fi"], "sv": r["title_sv"], "en": r["title_en"]},
             "fi_page_id": r["fi_page_id"], "score": _num(r["score"]),
             "fi_sv": _num(r["fi_sv"]), "fi_en": _num(r["fi_en"]),
             "missing_sv": r["missing_sv"], "missing_en": r["missing_en"],
             "missing_in_fi": {"sv": r["missing_in_fi_sv"], "en": r["missing_in_fi_en"]},
             "contradictions": _int(r["contradictions"]), "framing": _int(r["framing"]),
             "judged_pairs": _int(r["judged_pairs"]), "edit_war_score": _num(r["edit_war_score"])}
            for r in rows]
    return {"sql": render(sql, params), "ms": ms, "judged_by": PRIMARY_MODEL, "data": data}


TOPIC_SQL = """SELECT a.lang, a.page_id, a.title, a.url
FROM lang_topic t
JOIN lang_article a ON (a.lang, a.page_id) IN (('fi', t.fi_page_id), ('sv', t.sv_page_id), ('en', t.en_page_id))
WHERE t.wikidata_id = ?"""

SCORES_SQL = """SELECT VEC_DISTANCE_COSINE(f.embedding, s.embedding) AS fi_sv,
       VEC_DISTANCE_COSINE(f.embedding, e.embedding) AS fi_en,
       VEC_DISTANCE_COSINE(s.embedding, e.embedding) AS sv_en
FROM lang_topic t
JOIN lang_article_vector f ON f.lang = 'fi' AND f.page_id = t.fi_page_id
JOIN lang_article_vector s ON s.lang = 'sv' AND s.page_id = t.sv_page_id
JOIN lang_article_vector e ON e.lang = 'en' AND e.page_id = t.en_page_id
WHERE t.wikidata_id = ?"""

# Every Finnish sentence, with its aligned sv / en sentence (mutual best match closer than the
# threshold), and otherwise the sentence that covers it (its nearest one, closer than the threshold,
# but not mutual: e.g. one English sentence that says what two Finnish ones say).
FI_ROWS_SQL = f"""SELECT f.sent_no, f.text,
       ps.other_sent AS sv_sent, s.text AS sv_text, ps.distance AS sv_distance,
       pe.other_sent AS en_sent, e.text AS en_text, pe.distance AS en_distance,
       cs.other_sent AS cov_sv_sent, s2.text AS cov_sv_text, cs.distance AS cov_sv_distance,
       ce.other_sent AS cov_en_sent, e2.text AS cov_en_text, ce.distance AS cov_en_distance
FROM lang_topic t
JOIN lang_sentence f ON f.lang = 'fi' AND f.page_id = t.fi_page_id
LEFT JOIN lang_pair ps ON ps.wikidata_id = t.wikidata_id AND ps.other_lang = 'sv'
     AND ps.direction = 'fi' AND ps.fi_sent = f.sent_no AND ps.matched
LEFT JOIN lang_sentence s ON s.lang = 'sv' AND s.page_id = t.sv_page_id AND s.sent_no = ps.other_sent
LEFT JOIN lang_pair pe ON pe.wikidata_id = t.wikidata_id AND pe.other_lang = 'en'
     AND pe.direction = 'fi' AND pe.fi_sent = f.sent_no AND pe.matched
LEFT JOIN lang_sentence e ON e.lang = 'en' AND e.page_id = t.en_page_id AND e.sent_no = pe.other_sent
LEFT JOIN lang_pair cs ON cs.wikidata_id = t.wikidata_id AND cs.other_lang = 'sv' AND cs.direction = 'fi'
     AND cs.fi_sent = f.sent_no AND NOT cs.matched AND cs.distance < {THRESHOLD}
LEFT JOIN lang_sentence s2 ON s2.lang = 'sv' AND s2.page_id = t.sv_page_id AND s2.sent_no = cs.other_sent
LEFT JOIN lang_pair ce ON ce.wikidata_id = t.wikidata_id AND ce.other_lang = 'en' AND ce.direction = 'fi'
     AND ce.fi_sent = f.sent_no AND NOT ce.matched AND ce.distance < {THRESHOLD}
LEFT JOIN lang_sentence e2 ON e2.lang = 'en' AND e2.page_id = t.en_page_id AND e2.sent_no = ce.other_sent
WHERE t.wikidata_id = ?
ORDER BY f.sent_no"""

# sv / en sentences with NO Finnish sentence closer than the threshold (missing in Finnish); placed
# after their nearest Finnish sentence.
ONLY_SQL = f"""SELECT o.lang, o.sent_no, o.text, p.fi_sent AS nearest_fi, p.distance
FROM lang_topic t
JOIN lang_sentence o ON o.wikidata_id = t.wikidata_id AND o.lang IN ('sv', 'en')
     AND o.page_id = IF(o.lang = 'sv', t.sv_page_id, t.en_page_id)
JOIN lang_pair p ON p.wikidata_id = t.wikidata_id AND p.other_lang = o.lang
     AND p.direction = 'other' AND p.other_sent = o.sent_no
WHERE t.wikidata_id = ? AND NOT p.matched AND p.distance >= {THRESHOLD}
ORDER BY p.fi_sent, o.lang, o.sent_no"""

JUDGEMENTS_SQL = """SELECT fi_sent_no, other_lang, other_sent_no, label, reason, tone_fi, tone_other,
       fi_claim, other_claim, same_specific_fact, model
FROM pair_judgement
WHERE wikidata_id = ?
ORDER BY fi_sent_no, other_lang, other_sent_no, model"""

CONTRADICTION_NOTE = "Possible contradiction, check the sources"
LABEL_ORDER = {"contradiction": 0, "framing": 1, "partial": 2, "same": 3}


def _judgements(judged: list[dict]) -> dict:
    """{(fi_sent, lang, other_sent): [judgement, ...]} with the agreement between models per pair.
    both_models_agree (contradictions only): True when two or more models call the pair a
    contradiction, False when another model judged the pair and did not, None with one model."""
    by_pair: dict = {}
    for j in judged:
        by_pair.setdefault((j["fi_sent_no"], j["other_lang"], j["other_sent_no"]), []).append(j)
    out = {}
    for key, js in by_pair.items():
        contra = sum(j["label"] == "contradiction" for j in js)
        agree = None if len(js) < 2 else contra >= 2
        cells = []
        for j in js:
            c = j["label"] == "contradiction"
            ssf = j["same_specific_fact"]
            cells.append({"lang": j["other_lang"], "label": j["label"], "reason": j["reason"], "model": j["model"],
                          "tone_fi": j["tone_fi"], "tone_other": j["tone_other"],
                          "fi_claim": j["fi_claim"], "other_claim": j["other_claim"],
                          "same_specific_fact": None if ssf is None else bool(ssf),
                          "note": (CONTRADICTION_NOTE + (" (both models agree)" if agree else "")) if c else None,
                          "both_models_agree": agree if c else None})
        out[key] = cells
    return out


def _edit_url(url: str) -> str:
    """https://fi.wikipedia.org/wiki/X -> https://fi.wikipedia.org/w/index.php?title=X&action=edit"""
    return url.replace("/wiki/", "/w/index.php?title=", 1) + "&action=edit"


@router.get("/api/compare/{wikidata_id}")
def compare(wikidata_id: str):
    q = (wikidata_id,)
    topic_rows, ms1 = query(TOPIC_SQL, q)
    if not topic_rows:
        raise HTTPException(404, f"{wikidata_id} is not one of the topics in fi + sv + en")
    by_lang = {r["lang"]: r for r in topic_rows}
    topic = {"wikidata_id": wikidata_id,
             "titles": {l: by_lang[l]["title"] for l in LANGS},
             "urls": {l: by_lang[l]["url"] for l in LANGS},
             "edit_urls": {l: _edit_url(by_lang[l]["url"]) for l in LANGS},
             "page_ids": {l: by_lang[l]["page_id"] for l in LANGS}}
    sc, ms2 = query(SCORES_SQL, q)
    scores = {k: _num(sc[0][k]) for k in ("fi_sv", "fi_en", "sv_en")} if sc else {}
    fi_rows, ms3 = query(FI_ROWS_SQL, q)
    sqls = [render(s, q) for s in (TOPIC_SQL, SCORES_SQL, FI_ROWS_SQL)]
    if not fi_rows:
        return {"sql": ";\n\n".join(sqls), "ms": round(ms1 + ms2 + ms3, 2), "topic": topic, "scores": scores,
                "rows": [], "contradictions": [], "note": "sentence data not computed yet for this topic"}
    only, ms4 = query(ONLY_SQL, q)
    try:
        judged, ms5 = query(JUDGEMENTS_SQL, q)
    except HTTPException:            # pair_judgement not created yet
        judged, ms5 = [], 0
    sqls += [render(ONLY_SQL, q), render(JUDGEMENTS_SQL, q)]
    jpairs = _judgements(judged)

    after: dict = {}
    for o in only:
        after.setdefault(o["nearest_fi"], []).append(o)
    rows = []
    for r in fi_rows:
        sv = {"sent_no": r["sv_sent"], "text": r["sv_text"], "distance": _num(r["sv_distance"])} \
            if r["sv_sent"] is not None else None
        en = {"sent_no": r["en_sent"], "text": r["en_text"], "distance": _num(r["en_distance"])} \
            if r["en_sent"] is not None else None
        cov = {l: {"sent_no": r[f"cov_{l}_sent"], "text": r[f"cov_{l}_text"], "distance": _num(r[f"cov_{l}_distance"])}
               if r[f"cov_{l}_sent"] is not None else None for l in ("sv", "en")}
        # covered counts as present: the content is there, just not as a one-to-one pair
        status = ("missing_en" if en is None and cov["en"] is None
                  else "missing_sv" if sv is None and cov["sv"] is None else "match")
        # judgements belong to this row's own pairs only (aligned, or covered if a run judged those)
        js = []
        for l, cell in (("sv", sv or cov["sv"]), ("en", en or cov["en"])):
            if cell:
                js += jpairs.get((r["sent_no"], l, cell["sent_no"]), [])
        js.sort(key=lambda j: (not j["both_models_agree"], LABEL_ORDER[j["label"]], j["lang"], j["model"]))
        rows.append({"fi": {"sent_no": r["sent_no"], "text": r["text"]}, "sv": sv, "en": en,
                     "covered_by": cov, "status": status, "judgements": js})
        for o in after.get(r["sent_no"], []):
            cell = {"sent_no": o["sent_no"], "text": o["text"], "distance": _num(o["distance"])}
            rows.append({"fi": None, "sv": cell if o["lang"] == "sv" else None,
                         "en": cell if o["lang"] == "en" else None,
                         "covered_by": {"sv": None, "en": None},
                         "status": f"only_{o['lang']}", "judgements": []})
    return {"sql": ";\n\n".join(sqls), "ms": round(ms1 + ms2 + ms3 + ms4 + ms5, 2),
            "topic": topic, "scores": scores, "rows": rows, "contradictions": _contradictions(rows)}


def _contradictions(rows: list[dict]) -> list[dict]:
    """One entry per pair that any model called a contradiction, "both models agree" first, then in
    text order; `row` is the index into rows, for jumping to it."""
    out = []
    for i, r in enumerate(rows):
        for l in ("sv", "en"):
            js = [j for j in r["judgements"] if j["lang"] == l and j["label"] == "contradiction"]
            if not js:
                continue
            agree = js[0]["both_models_agree"]
            out.append({"row": i, "lang": l, "fi": r["fi"], "other": r[l] or r["covered_by"][l],
                        "note": js[0]["note"], "both_models_agree": agree,
                        "models": [j["model"] for j in js], "reason": js[0]["reason"],
                        "fi_claim": js[0]["fi_claim"], "other_claim": js[0]["other_claim"]})
    out.sort(key=lambda c: (not c["both_models_agree"], c["row"]))
    return out
