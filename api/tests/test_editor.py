"""The editor routes against the loaded database, checked field by field against docs/contracts.md (c)
and the shapes of web/mocks/worklist.json and compare.json."""
from __future__ import annotations

import json

import pymysql
import pytest
from fastapi.testclient import TestClient

from api.main import app
from common.db import ROOT, connect


def _ready() -> bool:
    try:
        c = connect(dict_rows=False)
    except pymysql.err.OperationalError:
        return False
    try:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM article_divergence")
            return cur.fetchone()[0] > 0
    except pymysql.err.ProgrammingError:
        return False
    finally:
        c.close()


pytestmark = pytest.mark.skipif(not _ready(), reason="article_divergence not built (python -m db.build_divergence)")
MOCKS = ROOT / "web" / "mocks"
STATUSES = {"match", "missing_sv", "missing_en", "only_sv", "only_en"}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_worklist_matches_the_contract(client):
    r = client.get("/api/worklist?limit=3000")
    assert r.status_code == 200
    body = r.json()
    assert "FROM article_divergence" in body["sql"]
    mock_keys = set(json.loads((MOCKS / "worklist.json").read_text(encoding="utf-8"))["data"][0])
    rows = body["data"]
    assert rows and all(set(x) == mock_keys for x in rows)
    assert all(set(x["titles"]) == {"fi", "sv", "en"} for x in rows)
    assert all(set(x["missing_in_fi"]) == {"sv", "en"} for x in rows)
    scores = [x["score"] for x in rows]
    assert scores == sorted(scores, reverse=True) and 0 <= min(scores) and max(scores) <= 1
    flagged = client.get("/api/worklist?limit=3000&include_flagged=1").json()["data"]
    assert len(flagged) == 2919 and len(rows) < 2919          # different-subject topics left out
    assert body["judged_by"] and "pair_judgement" in body["sql"]
    for x in rows:                                            # Gemma counts: all null or all numbers
        g = [x["contradictions"], x["framing"], x["judged_pairs"]]
        assert g == [None] * 3 or all(isinstance(v, int) for v in g)


@pytest.mark.parametrize("q", ["Q29207", "Q211855"])
def test_compare_hero_matches_the_contract(client, q):
    r = client.get(f"/api/compare/{q}")
    assert r.status_code == 200
    body = r.json()
    mock = json.loads((MOCKS / "compare.json").read_text(encoding="utf-8"))
    assert set(body["topic"]) == set(mock["topic"]) and set(body["scores"]) == {"fi_sv", "fi_en", "sv_en"}
    assert body["topic"]["edit_urls"]["en"].endswith("&action=edit")
    assert "VEC_DISTANCE_COSINE" in body["sql"] and "lang_pair" in body["sql"]
    rows = body["rows"]
    assert rows and {x["status"] for x in rows} <= STATUSES
    fi = [x["fi"]["sent_no"] for x in rows if x["fi"]]
    assert fi == sorted(fi) and fi == list(range(len(fi)))      # every Finnish sentence, in order
    for x in rows:
        assert set(x) == {"fi", "sv", "en", "covered_by", "status", "judgements"}
        assert set(x["covered_by"]) == {"sv", "en"}
        for lang in ("sv", "en"):
            here = x[lang] or x["covered_by"][lang]
            assert x[lang] is None or x["covered_by"][lang] is None       # aligned OR covered, not both
            if here and x["fi"]:
                assert here["distance"] <= 0.418          # shown rounded to 3 decimals
        if x["status"] == "match":
            assert (x["sv"] or x["covered_by"]["sv"]) and (x["en"] or x["covered_by"]["en"])
        if x["status"] == "missing_en":
            assert x["en"] is None and x["covered_by"]["en"] is None
        if x["status"].startswith("only_"):
            assert x["fi"] is None and x[x["status"][5:]] is not None
    for lang in ("sv", "en"):                                     # each sv / en sentence at most once
        seen = [x[lang]["sent_no"] for x in rows if x[lang]]
        assert len(seen) == len(set(seen))
    jkeys = set(mock["rows"][0]["judgements"][0])
    for x in rows:
        for j in x["judgements"]:
            assert set(j) == jkeys
            cell = x[j["lang"]] or x["covered_by"][j["lang"]]
            assert cell is not None                               # judges this row's own pair
            if j["label"] == "contradiction":
                assert j["note"].startswith("Possible contradiction, check the sources")
            else:
                assert j["note"] is None and j["both_models_agree"] is None
    assert set(body["contradictions"][0]) == set(mock["contradictions"][0]) if body["contradictions"] else True
    for c in body["contradictions"]:
        assert rows[c["row"]]["fi"] == c["fi"] and c["lang"] in ("sv", "en")


def test_compare_without_sentences_says_so(client):
    q = client.get("/api/worklist?limit=3000").json()["data"]
    no_sentences = next((x["wikidata_id"] for x in q if x["missing_en"] is None), None)
    if no_sentences is None:
        pytest.skip("every topic has sentence data (the GPU run covers all 2,919)")
    body = client.get(f"/api/compare/{no_sentences}").json()
    assert body["rows"] == [] and "not computed yet" in body["note"]
    assert body["scores"]["fi_en"] is not None


def test_compare_unknown_topic_is_404(client):
    assert client.get("/api/compare/Q1").status_code == 404


def test_missing_counts_agree_between_worklist_and_compare(client):
    """missing_en in the worklist = the compare rows with status missing_en (nothing within 0.418)."""
    work = {x["wikidata_id"]: x for x in client.get("/api/worklist?limit=3000").json()["data"]}
    for q in ("Q29207", "Q211855"):
        rows = client.get(f"/api/compare/{q}").json()["rows"]
        assert sum(r["status"] == "missing_en" for r in rows) == work[q]["missing_en"]
        assert sum(r["status"] == "only_en" for r in rows) == work[q]["missing_in_fi"]["en"]


def test_subject_override(client):
    """db/subject_overrides.tsv: Maunu Eerikinpojan maanlaki is the same law in every language."""
    kept = {x["wikidata_id"] for x in client.get("/api/worklist?limit=3000").json()["data"]}
    assert "Q339275" in kept


def test_judgements_imported_for_the_heroes(client):
    """Jesse's Gemma 27B run (data/verda/judgements.parquet): every judged pair lands on a row, and the
    worklist counts equal the rows' judgements."""
    body = client.get("/api/worklist?limit=3000").json()
    model = body["judged_by"]
    work = {x["wikidata_id"]: x for x in body["data"]}
    con = connect()
    try:
        with con.cursor() as cur:
            # pairs that are still mutual matches (a re-embedding can flip a near-tie; those do not
            # attach to a row)
            cur.execute("""SELECT j.wikidata_id, COUNT(*) AS n, SUM(p.matched) AS attached
FROM pair_judgement j
LEFT JOIN lang_pair p ON p.wikidata_id = j.wikidata_id AND p.other_lang = j.other_lang AND p.direction = 'fi'
     AND p.fi_sent = j.fi_sent_no AND p.other_sent = j.other_sent_no
WHERE j.model = %s GROUP BY j.wikidata_id""", (model,))
            rows = cur.fetchall()
            counts = {r["wikidata_id"]: int(r["n"]) for r in rows}
            attached = {r["wikidata_id"]: int(r["attached"] or 0) for r in rows}
    finally:
        con.close()
    if not counts:
        pytest.skip("no judgements imported (python -m ingest.load_judgements)")
    for q in set(counts) & {"Q29207", "Q211855"}:
        body = client.get(f"/api/compare/{q}").json()
        primary = [j for r in body["rows"] for j in r["judgements"] if j["model"] == model]
        assert len(primary) == attached[q] and counts[q] == work[q]["judged_pairs"]
        assert attached[q] >= counts[q] - 3          # at most a few near-ties flipped
        shown = sum(j["label"] == "contradiction" for j in primary)
        assert work[q]["contradictions"] - 3 <= shown <= work[q]["contradictions"]
        assert sum(j["label"] == "framing" for j in primary) <= work[q]["framing"]
        assert len(body["contradictions"]) >= shown


def test_both_models_agree_sorts_first():
    """Two models on one pair: agreement marked, agreed contradictions first (no database needed)."""
    from api.editor import _contradictions, _judgements
    base = dict(fi_sent_no=1, other_lang="en", other_sent_no=2, reason="r", tone_fi="neutral",
                tone_other="neutral", fi_claim="a", other_claim="b", same_specific_fact=1)
    judged = [dict(base, label="contradiction", model="big"), dict(base, label="contradiction", model="small"),
              dict(base, fi_sent_no=0, other_sent_no=0, label="contradiction", model="big"),
              dict(base, fi_sent_no=0, other_sent_no=0, label="same", model="small"),
              dict(base, fi_sent_no=3, other_sent_no=3, label="contradiction", model="big")]
    jp = _judgements(judged)
    assert {j["both_models_agree"] for j in jp[(1, "en", 2)]} == {True}
    assert "both models agree" in jp[(1, "en", 2)][0]["note"]
    assert [j["both_models_agree"] for j in jp[(0, "en", 0)]] == [False, None]   # the 'same' has none
    assert jp[(3, "en", 3)][0]["both_models_agree"] is None                      # judged by one model
    cell = lambda n: {"sent_no": n, "text": "t", "distance": 0.1}
    rows = [{"fi": {"sent_no": k, "text": "t"}, "sv": None, "en": cell(o), "covered_by": {"sv": None, "en": None},
             "judgements": jp[(k, "en", o)]} for k, o in ((0, 0), (1, 2), (3, 3))]
    out = _contradictions(rows)
    assert [c["row"] for c in out] == [1, 0, 2] and out[0]["models"] == ["big", "small"]


def test_import_refuses_unknown_sentence_numbers(tmp_path):
    """ingest.load_judgements checks numbering against lang_sentence before writing anything."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ingest.load_judgements import load_file
    row = dict(wikidata_id="Q29207", fi_sent_no=99999, other_lang="en", other_sent_no=0, label="same",
               reason="r", tone_fi="neutral", tone_other="neutral", fi_claim="a", other_claim="b",
               same_specific_fact=True, model="test/not-a-model")
    f = tmp_path / "judgements-bad.parquet"
    pq.write_table(pa.Table.from_pylist([row]), f)
    con = connect()
    try:
        with pytest.raises(SystemExit, match="nothing imported"):
            load_file(con, f)
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM pair_judgement WHERE model = 'test/not-a-model'")
            assert cur.fetchone()["n"] == 0
    finally:
        con.close()


def test_talonpoika_is_a_different_subject(client):
    """db/subject_overrides.tsv: Talonpoika / Allmoge / Peasant are three different concepts."""
    kept = {x["wikidata_id"] for x in client.get("/api/worklist?limit=3000").json()["data"]}
    assert "Q838811" not in kept
