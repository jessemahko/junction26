"""The API: one FastAPI app.

  * explore routes (api/explore.py): the worklist with semantic / title search and topic chips, the
    map's places and most-similar articles.
  * editor routes (api/editor.py): the fi / sv / en comparison (docs/contracts.md c).
  * history routes (this file): the Finnish article's history from the system-versioned sentences
    (as-of, diff, contested sentences, edit wars, bitemporal "about"). Models in api/models.py.

    uvicorn api.main:app --port 8000          # http://localhost:8000/docs

The built React app (web/dist) is served at /contested/; / redirects there.
"""
from __future__ import annotations

import mimetypes
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api import history as H
from api import models as M
from api.db import DB_ERRORS, db_error, pool
from api.editor import router as editor_router
from api.explore import router as explore_router
from common import embed
from common.db import ROOT

app = FastAPI(title="AikaKone", version="3.0",
              description="Finnish, Swedish and English Wikipedia on Finland's history: where the versions "
                          "differ, and where editors fight. MariaDB vectors + system-versioned tables.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
app.include_router(editor_router)
app.include_router(explore_router)
app.add_middleware(GZipMiddleware, minimum_size=2000)
if os.environ.get("EMBED_WARM", "1") == "1":
    embed.warm()                  # load bge-m3 for the semantic search in a background thread

def run(fn, *args):
    try:
        with pool.connection() as conn:
            return fn(conn, *args)
    except H.NotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except DB_ERRORS as e:
        # Timeout, lost connection, or a table that is not loaded yet: say so (api/db.py).
        raise db_error(e)


@app.get("/api/health")
def health():
    return run(lambda c: {"ok": True, "db": c.get_server_info()})


@app.get("/api/articles", response_model=list[M.ArticleSummary])
def list_articles(q: str = "", limit: int = Query(50, le=500)):
    return run(H.articles, q, limit)


@app.get("/api/articles/{page_id}/as-of", response_model=M.AsOf)
def as_of(page_id: int, date: str | None = Query(None, description="YYYY[-MM[-DD]] or ISO datetime, UTC; default now")):
    return run(H.as_of, page_id, date)


@app.get("/api/articles/{page_id}/diff", response_model=M.Diff)
def diff(page_id: int, from_: str = Query(..., alias="from"), to: str | None = None):
    return run(H.diff, page_id, from_, to)


@app.get("/api/articles/{page_id}/contested", response_model=list[M.Contested])
def contested(page_id: int):
    return run(H.contested, page_id)


@app.get("/api/articles/{page_id}/edit-wars", response_model=list[M.EditWar])
def edit_wars(page_id: int, limit: int = Query(20, le=200)):
    return run(H.edit_wars, page_id, limit)


@app.get("/api/articles/{page_id}/revisions", response_model=list[M.RevisionTick])
def revisions(page_id: int):
    return run(H.revisions, page_id)


@app.get("/api/articles/{page_id}/sentences/{sent_hash}/history", response_model=list[M.Ancestor])
def sentence_history(page_id: int, sent_hash: str):
    return run(H.sentence_history, page_id, sent_hash)


@app.get("/api/articles/{page_id}/about", response_model=list[M.About])
def about(page_id: int, from_: int = Query(..., alias="from", description="first year of the events"),
          to: int = Query(..., description="last year of the events (inclusive)"),
          date: str | None = Query(None, description="what Wikipedia said at this moment; default now")):
    """Bitemporal: sentences alive at `date` (system time) about events in `from`–`to` (application time)."""
    return run(H.about, page_id, date, from_, to)


# The built frontends are served from the same origin for single-box deploys.
# Windows' registry often maps .js to text/plain, which browsers refuse for module scripts.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
CONTESTED = ROOT / "web" / "dist"            # React: sentence views (vite base /contested/)
if CONTESTED.exists():
    app.mount("/contested", StaticFiles(directory=CONTESTED, html=True), name="contested")


@app.get("/", include_in_schema=False)
def landing():
    return RedirectResponse("/contested/")
