"""The demo app's routes (api/explore.py): worklist with semantic / title search and topic chips, the map's
places and most-similar articles, and the SQL behind each."""
from __future__ import annotations

import os

import pymysql
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_WARM", "0")          # the semantic test loads bge-m3 itself
from api.main import app                           # noqa: E402
from common.db import connect                      # noqa: E402


def _ready() -> bool:
    try:
        c = connect(dict_rows=False)
    except pymysql.err.OperationalError:
        return False
    try:
        with c.cursor() as cur:
            for t in ("article_divergence", "category_link", "topic_place"):
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                if not cur.fetchone()[0]:
                    return False
        return True
    except pymysql.err.ProgrammingError:
        return False
    finally:
        c.close()


pytestmark = pytest.mark.skipif(not _ready(), reason="run ingest.load_categories and db.build_topic_place first")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_landing_redirects_to_the_editor_app(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/contested/"


def test_worklist_without_filter(client):
    body = client.get("/api/topics").json()
    rows = body["data"]
    assert len(rows) > 2800 and "FROM article_divergence" in body["sql"][0]["sql"]
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert {"titles", "parts", "missing_in_fi", "contradictions_agreed", "edit_war_score"} <= set(rows[0])
    assert rows[0]["similarity"] is None


def test_chips_walk_the_category_tree(client):
    chips = {c["id"]: c for c in client.get("/api/chips").json()["data"]}
    assert set(chips) == {"civil-war", "presidents", "wars-1939-44", "swedish-era", "russian-era"}
    assert all(c["topics"] > 0 for c in chips.values())
    body = client.get("/api/topics?chip=civil-war").json()
    assert "WITH RECURSIVE" in body["sql"][0]["sql"] and "category_link" in body["sql"][0]["sql"]
    ids = {r["wikidata_id"] for r in body["data"]}
    assert "Q211855" in ids and len(ids) == chips["civil-war"]["topics"]
    pres = {r["titles"]["fi"] for r in client.get("/api/topics?chip=presidents").json()["data"]}
    assert "Sauli Niinistö" in pres
    assert client.get("/api/topics?chip=nope").status_code == 404


def test_title_search(client):
    body = client.get("/api/topics", params={"q": "sisällissota", "mode": "title"}).json()
    titles = [r["titles"]["fi"] for r in body["data"]]
    assert "Suomen sisällissota" in titles and "LIKE" in body["sql"][0]["sql"]


def test_semantic_search_finds_what_the_title_does_not_say(client):
    """bge-m3 on CPU + VEC_DISTANCE: an English query finds Finnish prison-camp articles."""
    body = client.get("/api/topics", params={"q": "sisällissota"}).json()
    assert body["data"][0]["wikidata_id"] == "Q211855"
    assert "VEC_DISTANCE_COSINE" in body["sql"][0]["sql"] and "1024 floats" in body["sql"][0]["sql"]
    sims = [r["similarity"] for r in body["data"]]
    assert sims == sorted(sims, reverse=True)
    camps = [r["titles"]["fi"] for r in client.get("/api/topics", params={"q": "civil war prison camps"}).json()["data"][:5]]
    assert any("vankileiri" in t for t in camps)
    both = client.get("/api/topics", params={"q": "sisällissota", "chip": "civil-war"}).json()["data"]
    assert both and all(r["similarity"] is not None for r in both)


def test_similar_articles(client):
    body = client.get("/api/similar/Q211855").json()
    rows = body["data"]
    assert len(rows) == 10 and all(r["wikidata_id"] != "Q211855" for r in rows)
    sims = [r["similarity"] for r in rows]
    assert sims == sorted(sims, reverse=True) and 0 < sims[-1] <= sims[0] < 1
    assert all(r["lat"] and r["lon"] for r in rows)
    assert "SET @v" in body["sql"][0]["sql"] and "VEC_DISTANCE_COSINE(embedding, @v)" in body["sql"][0]["sql"]


def test_topic_places(client):
    data = client.get("/api/topic-places").json()["data"]
    assert len(data) > 2500
    lat, lon, how, place = data["Q29207"]
    assert how in ("page_place", "article_geo", "inferred") and 59 < lat < 71


def test_query_text_for_the_edit_war_views(client):
    assert "SYSTEM_TIME" in client.get("/api/queries/edit_wars").json()["sql"]
    assert client.get("/api/queries/..%2F..%2Fsecrets").status_code == 404
    assert client.get("/api/queries/nope").status_code == 404
