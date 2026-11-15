"""The demo's landing and map: find the articles that need an editor, and their neighbours.

GET /api/topics?q=&mode=meaning|title&chip=&limit=   the worklist, narrowed by
      q + mode=meaning  semantic search: the query embedded with bge-m3 on CPU, ranked by
                        VEC_DISTANCE_COSINE against dataset S's article vectors (fi, sv and en), so it
                        also finds articles that never use the word
      q + mode=title    plain title search (fi / sv / en), the fallback
      chip              a topic: a Finnish category and its subcategories, WITH RECURSIVE over
                        category_link (dataset S's category tree)
GET /api/chips                                        the topic chips, with their category roots and counts
GET /api/similar/{wikidata_id}?k=10                   the k most similar mapped articles (article vectors)
GET /api/topic-places                                 where each topic sits on the map (topic_place)
GET /api/queries/{name}                               the text of db/queries/{name}.sql (SQL drawer for
                                                      the edit-war views)
Every answer carries `sql` (a list of {label, sql}) and `ms` (database time).
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, HTTPException, Query

from api.db import DB_ERRORS, db_error, pool, render
from common import embed
from common.db import ROOT
from ingest.load_judgements import PRIMARY_MODEL

router = APIRouter(tags=["explore"])

EF_SEARCH = 80                 # mhnsw_ef_search: the RAG repo's finding (recall vs speed)
VECTOR_CANDIDATES = 300        # nearest article vectors (any language) before mapping them to topics
MEANING_TOPICS = 60            # topics kept for a semantic search
CHIP_DEPTH = 2                 # the category and two levels of subcategories

# Topic chips: a Finnish category (or two) in dataset S's tree. "Russian era": the tree has no
# "Venäjän vallan aika", so its nearest, the Grand Duchy (Suomen suuriruhtinaskunta).
CHIPS = {
    "civil-war": {"label": "Civil War 1918", "roots": ["Suomen sisällissota"]},
    "presidents": {"label": "Presidents", "roots": ["Suomen presidentit"]},
    "wars-1939-44": {"label": "Winter and Continuation Wars", "roots": ["Talvisota", "Jatkosota"]},
    "swedish-era": {"label": "Swedish era", "roots": ["Ruotsin vallan aika Suomessa"]},
    "russian-era": {"label": "Russian era", "roots": ["Suomen suuriruhtinaskunta"],
                    "note": "no 'Venäjän vallan aika' category in the tree: the Grand Duchy is the nearest"},
}


def run(statements: list[tuple[str, tuple]]) -> tuple[list[dict], float]:
    """Run statements on one connection (session variables carry over); rows of the last one."""
    try:
        with pool.connection() as con, con.cursor() as cur:
            t = time.perf_counter()
            for sql, params in statements:
                cur.execute(sql.replace("?", "%s") if params else sql, params or None)
            rows = list(cur.fetchall())
            return rows, round((time.perf_counter() - t) * 1000, 2)
    except DB_ERRORS as e:
        raise db_error(e)


def _num(v, nd=3):
    return None if v is None else round(float(v), nd)


def _int(v):
    return None if v is None else int(v)


def chip_cte(roots: list[str]) -> tuple[str, list]:
    first = " UNION ".join(["SELECT CAST(? AS VARCHAR(255)) AS name"] * len(roots))
    return f"""cat (name, depth) AS (          -- the chip's category and its subcategories
  SELECT r.name, 0 FROM ({first}) r
  UNION
  SELECT l.child, c.depth + 1 FROM cat c JOIN category_link l ON l.parent = c.name WHERE c.depth < ?
),
chip_pages AS (                    -- articles in those categories (or a subcategory link to an article)
  SELECT ac.page_id FROM cat JOIN article_category ac ON ac.category = cat.name
  UNION
  SELECT a.page_id FROM cat JOIN lang_article a ON a.lang = 'fi' AND a.title = cat.name
)""", [*roots, CHIP_DEPTH]


HITS_CTE = f"""hits AS (                          -- semantic search: nearest article vectors, any language
  SELECT t.wikidata_id, MIN(v.distance) AS distance
  FROM (SELECT lang, page_id, VEC_DISTANCE_COSINE(embedding, ?) AS distance
        FROM lang_article_vector ORDER BY distance LIMIT {VECTOR_CANDIDATES}) v
  JOIN lang_topic t ON (v.lang = 'fi' AND t.fi_page_id = v.page_id)
                    OR (v.lang = 'sv' AND t.sv_page_id = v.page_id)
                    OR (v.lang = 'en' AND t.en_page_id = v.page_id)
  GROUP BY t.wikidata_id
)"""

JUDGED_CTE = """judged AS (                        -- Gemma's labels, primary model
  SELECT wikidata_id, COUNT(*) AS judged_pairs, SUM(label = 'contradiction') AS contradictions,
         SUM(label = 'framing') AS framing
  FROM pair_judgement WHERE model = ? GROUP BY wikidata_id
),
agreed AS (                        -- contradictions that two models agree on
  SELECT wikidata_id, COUNT(*) AS contradictions_agreed
  FROM (SELECT wikidata_id FROM pair_judgement WHERE label = 'contradiction'
        GROUP BY wikidata_id, other_lang, fi_sent_no, other_sent_no HAVING COUNT(DISTINCT model) >= 2) x
  GROUP BY wikidata_id
)"""

SELECT = """SELECT d.wikidata_id, fi.title AS title_fi, sv.title AS title_sv, en.title AS title_en,
       d.fi_page_id, d.rnk, d.score, d.fi_sv, d.fi_en, d.p_distance, d.p_missing, d.p_edit_war,
       d.fi_sentences, d.sv_sentences, d.en_sentences, d.missing_sv, d.missing_en,
       d.missing_in_fi_sv, d.missing_in_fi_en, d.edit_war_score,
       j.judged_pairs, j.contradictions, j.framing, g.contradictions_agreed{sim}
FROM article_divergence d
JOIN lang_topic t ON t.wikidata_id = d.wikidata_id
JOIN lang_article fi ON fi.lang = 'fi' AND fi.page_id = t.fi_page_id
JOIN lang_article sv ON sv.lang = 'sv' AND sv.page_id = t.sv_page_id
JOIN lang_article en ON en.lang = 'en' AND en.page_id = t.en_page_id{joins}
LEFT JOIN judged j ON j.wikidata_id = d.wikidata_id
LEFT JOIN agreed g ON g.wikidata_id = d.wikidata_id
WHERE NOT d.different_subject{where}
ORDER BY {order}
LIMIT ?"""


def _row(r: dict) -> dict:
    return {"wikidata_id": r["wikidata_id"],
            "titles": {"fi": r["title_fi"], "sv": r["title_sv"], "en": r["title_en"]},
            "fi_page_id": r["fi_page_id"], "rank": r["rnk"], "score": _num(r["score"]),
            "fi_sv": _num(r["fi_sv"]), "fi_en": _num(r["fi_en"]),
            "parts": {"distance": _num(r["p_distance"]), "missing": _num(r["p_missing"]),
                      "edit_war": _num(r["p_edit_war"])},
            "sentences": {"fi": r["fi_sentences"], "sv": r["sv_sentences"], "en": r["en_sentences"]},
            "missing_sv": r["missing_sv"], "missing_en": r["missing_en"],
            "missing_in_fi": {"sv": r["missing_in_fi_sv"], "en": r["missing_in_fi_en"]},
            "edit_war_score": _num(r["edit_war_score"]),
            "judged_pairs": _int(r["judged_pairs"]), "contradictions": _int(r["contradictions"]),
            "contradictions_agreed": _int(r["contradictions_agreed"]) or 0, "framing": _int(r["framing"]),
            "similarity": _num(1 - r["distance"]) if r.get("distance") is not None else None}


@router.get("/api/topics")
def topics(q: str = "", mode: str = Query("meaning", pattern="^(meaning|title)$"), chip: str = "",
           limit: int = Query(3000, ge=1, le=3000)):
    q = q.strip()
    if chip and chip not in CHIPS:
        raise HTTPException(404, f"unknown chip {chip}; see /api/chips")
    ctes, params, shown, joins, where, sim = [], [], [], "", "", ""
    order = "d.score DESC"
    notes = []
    if chip:
        cte, p = chip_cte(CHIPS[chip]["roots"])
        ctes.append(cte)
        params += p
        shown += p
        where += "\n  AND d.fi_page_id IN (SELECT page_id FROM chip_pages)"
    if q and mode == "meaning":
        t = time.perf_counter()
        vec = embed.embed(q)
        notes.append(f"query embedded with bge-m3 on CPU in {(time.perf_counter() - t) * 1000:.0f} ms")
        ctes.append(HITS_CTE)
        params.append(vec)
        shown.append(f"<bge-m3 vector of “{q}”, 1024 floats>")
        joins += "\nJOIN hits h ON h.wikidata_id = d.wikidata_id"
        sim = ", h.distance"
        order = "h.distance"
        limit = min(limit, MEANING_TOPICS)
    ctes.append(JUDGED_CTE)
    params.append(PRIMARY_MODEL)
    shown.append(PRIMARY_MODEL)
    if q and mode == "title":
        like = f"%{q}%"
        where += "\n  AND (fi.title LIKE ? OR sv.title LIKE ? OR en.title LIKE ?)"
        params += [like] * 3
        shown += [like] * 3
    params.append(limit)
    shown.append(limit)
    sql = ("WITH RECURSIVE " if chip else "WITH ") + ",\n".join(ctes) + "\n" + \
        SELECT.format(sim=sim, joins=joins, where=where, order=order)
    rows, ms = run([(f"SET SESSION mhnsw_ef_search = {EF_SEARCH}", ()), (sql, tuple(params))])
    label = {"meaning": "Semantic search", "title": "Title search"}[mode] if q else "Worklist"
    if chip:
        label += f" · {CHIPS[chip]['label']}"
    sql_shown = render(sql, shown)
    if q and mode == "meaning":
        tag = f"<bge-m3 vector of “{q}”, 1024 floats>".replace("'", "''")
        sql_shown = sql_shown.replace(f"'{tag}'", tag)
    return {"sql": [{"label": label, "sql": sql_shown}], "ms": ms, "notes": notes,
            "filter": {"q": q, "mode": mode if q else None, "chip": chip or None},
            "data": [_row(r) for r in rows]}


CHIP_COUNT_SQL = """WITH RECURSIVE {cte}
SELECT COUNT(*) AS n FROM lang_topic t
JOIN article_divergence d USING (wikidata_id)
WHERE NOT d.different_subject AND t.fi_page_id IN (SELECT page_id FROM chip_pages)"""
_chip_counts: dict = {}


@router.get("/api/chips")
def chips():
    out, sqls, total = [], [], 0.0
    for key, c in CHIPS.items():
        cte, p = chip_cte(c["roots"])
        sql = CHIP_COUNT_SQL.format(cte=cte)
        if key not in _chip_counts:
            rows, ms = run([(sql, tuple(p))])
            _chip_counts[key] = (rows[0]["n"], ms)
        n, ms = _chip_counts[key]
        total += ms
        out.append({"id": key, "label": c["label"], "categories": c["roots"], "topics": n, "note": c.get("note")})
        sqls.append({"label": c["label"], "sql": render(sql, p)})
    return {"sql": sqls, "ms": round(total, 2), "data": out}


SIMILAR_SQL = """SELECT t.wikidata_id, fi.title AS title_fi, en.title AS title_en, p.lat, p.lon,
       d.score, n.distance
FROM (SELECT lang, page_id, VEC_DISTANCE_COSINE(embedding, @v) AS distance
      FROM lang_article_vector ORDER BY distance LIMIT ?) n
JOIN lang_topic t ON n.lang = 'fi' AND t.fi_page_id = n.page_id
JOIN topic_place p USING (wikidata_id)
JOIN article_divergence d USING (wikidata_id)
JOIN lang_article fi ON fi.lang = 'fi' AND fi.page_id = t.fi_page_id
JOIN lang_article en ON en.lang = 'en' AND en.page_id = t.en_page_id
WHERE t.wikidata_id <> ? AND NOT d.different_subject
ORDER BY n.distance
LIMIT ?"""
SET_V = """SET @v = (SELECT v.embedding FROM lang_topic t
          JOIN lang_article_vector v ON v.lang = 'fi' AND v.page_id = t.fi_page_id
          WHERE t.wikidata_id = ?)"""


@router.get("/api/similar/{wikidata_id}")
def similar(wikidata_id: str, k: int = Query(10, ge=1, le=30)):
    """The k most similar mapped articles: nearest Finnish article vectors (the vector index), kept
    when they are fi + sv + en topics with a place on the map."""
    cand = 200
    rows, ms = run([(f"SET SESSION mhnsw_ef_search = {EF_SEARCH}", ()), (SET_V, (wikidata_id,)),
                    (SIMILAR_SQL, (cand, wikidata_id, k))])
    data = [{"wikidata_id": r["wikidata_id"], "titles": {"fi": r["title_fi"], "en": r["title_en"]},
             "lat": float(r["lat"]), "lon": float(r["lon"]), "score": _num(r["score"]),
             "similarity": _num(1 - r["distance"])} for r in rows]
    sql = render(SET_V, (wikidata_id,)) + ";\n\n" + render(SIMILAR_SQL, (cand, wikidata_id, k))
    return {"sql": [{"label": "Most similar articles", "sql": sql}], "ms": ms, "data": data}


PLACES_SQL = """SELECT p.wikidata_id, p.lat, p.lon, p.located_by, p.place
FROM topic_place p
JOIN article_divergence d USING (wikidata_id)
WHERE NOT d.different_subject"""


@router.get("/api/topic-places")
def topic_places():
    rows, ms = run([(PLACES_SQL, ())])
    return {"sql": [{"label": "Places", "sql": PLACES_SQL}], "ms": ms,
            "data": {r["wikidata_id"]: [round(float(r["lat"]), 4), round(float(r["lon"]), 4), r["located_by"],
                                        r["place"]] for r in rows}}


@router.get("/api/queries/{name}")
def query_text(name: str):
    """The SQL of one of Kristian's views (db/queries/*.sql), for the SQL drawer."""
    if not re.fullmatch(r"[a-z_]+", name) or not (ROOT / "db" / "queries" / f"{name}.sql").exists():
        raise HTTPException(404, f"no query {name}")
    return {"name": name, "sql": (ROOT / "db" / "queries" / f"{name}.sql").read_text(encoding="utf-8")}
