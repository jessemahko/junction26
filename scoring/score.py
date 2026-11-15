"""Score every distinct sentence (across every revision) for neutrality.  (owner: P3)

    # Gemma behind any OpenAI-compatible server (vLLM on Verda, Ollama, Featherless):
    SCORING_URL=http://<verda-ip>:8000/v1 GEMMA_MODEL=google/gemma-3-12b-it \
        python -m scoring.score --backend llm --concurrency 64

    # Offline keyword baseline (no GPU) — makes V4 work locally, and is the eval's baseline:
    python -m scoring.score --backend heuristic

    python -m scoring.score --pages 1150 --limit 500          # just part of one article

Idempotent: only sentences without a row in sentence_score are selected; results are upserted.
Prints throughput (sentences/s) for docs/process-log.md and docs/numbers.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from common.db import connect

PROMPT = (Path(__file__).parent / "prompt.txt").read_text(encoding="utf-8")

SCHEMA = {
    "type": "object",
    "properties": {
        "event_name": {"type": ["string", "null"]},
        "tone": {"type": "string", "enum": ["neutral", "loaded", "partisan"]},
        "neutrality": {"type": "number", "minimum": 0, "maximum": 1},
        "loaded_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["event_name", "tone", "neutrality", "loaded_terms"],
    "additionalProperties": False,
}

# Inflected forms -> basic form. Finnish inflects names (sisällissodan, vapaussodaksi …); the
# model is asked for the basic form, and this map also catches what it misses.
EVENT_STEMS = [
    ("vapaussod", "vapaussota"), ("vapaussota", "vapaussota"),
    ("sisällissod", "sisällissota"), ("sisällissota", "sisällissota"),
    ("kansalaissod", "kansalaissota"), ("kansalaissota", "kansalaissota"),
    ("luokkasod", "luokkasota"), ("luokkasota", "luokkasota"),
    ("veljessod", "veljessota"), ("veljessota", "veljessota"),
    ("punakapin", "punakapina"), ("torpparikapin", "torpparikapina"),
    ("vallankumou", "vallankumous"), ("talvisod", "talvisota"), ("jatkosod", "jatkosota"),
]

# Baseline lexicon: words that take a side when used without attribution.
LOADED = ["punakapina", "kapinalli", "punikki", "lahtari", "vapaussota", "vapaussodan", "vapauttaj",
          "luokkasota", "terroristi", "roisto", "petturi", "sankari", "urhea", "julma", "raaka",
          "veriteko", "punaterrori", "valkoterrori", "yllyttäm", "rosvo", "verikoir", "murhaaj"]
ATTRIBUTION = re.compile(r"\b(kutsu|nimit|käytti|käyttivät|mukaan|puhuivat|sanottiin|kutsuivat|"
                         r"nimeä|nimiä|nimity)", re.I)


def normalise_event(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip().lower()
    for stem, base in EVENT_STEMS:
        if n.startswith(stem):
            return base
    return n[:255] or None


def heuristic(text: str, title: str) -> dict:
    """Transparent keyword baseline. Not a model: it is what Gemma has to beat in the eval."""
    low = text.lower()
    event = next((base for stem, base in EVENT_STEMS if stem in low), None)
    hits = [w for w in LOADED if w in low]
    attributed = bool(ATTRIBUTION.search(low))
    if hits and not attributed:
        tone, neutrality = ("partisan", 0.2) if len(hits) > 1 else ("loaded", 0.45)
    else:
        tone, neutrality = "neutral", 0.9 if not hits else 0.75
    return dict(event_name=event, tone=tone, neutrality=neutrality, loaded_terms=hits if tone != "neutral" else [])


def _clean(result: dict) -> dict:
    tone = result.get("tone") if result.get("tone") in ("neutral", "loaded", "partisan") else "neutral"
    try:
        neu = min(1.0, max(0.0, float(result.get("neutrality", 0.5))))
    except (TypeError, ValueError):
        neu = 0.5
    terms = result.get("loaded_terms") or []
    if not isinstance(terms, list):
        terms = [str(terms)]
    return dict(event_name=normalise_event(result.get("event_name")), tone=tone,
                neutrality=round(neu, 2), loaded_terms=[str(t)[:100] for t in terms][:10])


class LLM:
    """OpenAI-compatible chat endpoint with guided JSON output (vLLM: response_format json_schema)."""

    def __init__(self, url: str, model: str, concurrency: int, api_key: str | None = None):
        import httpx
        self.url = url.rstrip("/") + "/chat/completions"
        self.model = model
        self.sem = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(timeout=120, headers={"Authorization": f"Bearer {api_key or 'none'}"})
        self.invalid = 0
        self.calls = 0

    async def score(self, text: str, title: str) -> dict | None:
        body = {
            "model": self.model, "temperature": 0, "max_tokens": 200,
            "messages": [{"role": "user", "content": PROMPT.format(title=title, sentence=text)}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "npov", "schema": SCHEMA, "strict": True}},
        }
        async with self.sem:
            for attempt in range(3):
                self.calls += 1
                try:
                    r = await self.client.post(self.url, json=body)
                    r.raise_for_status()
                    content = r.json()["choices"][0]["message"]["content"]
                    content = content.strip().removeprefix("```json").removesuffix("```").strip()
                    return _clean(json.loads(content))
                except (json.JSONDecodeError, KeyError, IndexError):
                    self.invalid += 1           # retry on invalid JSON
                except Exception as e:          # network / 5xx: back off and retry
                    if attempt == 2:
                        print(f"  request failed: {e}", file=sys.stderr)
                    await asyncio.sleep(2 ** attempt)
        return None


def todo(conn, pages: list[int] | None, limit: int | None) -> list[dict]:
    """Unscored distinct sentences, article by article (no GROUP BY over all of history: at the
    scale of dataset M that spills a temporary table of many GB)."""
    with conn.cursor() as cur:
        if pages is None:
            cur.execute("SELECT page_id FROM article ORDER BY page_id")
            pages = [r["page_id"] for r in cur.fetchall()]
        cur.execute("SELECT page_id, title FROM article")
        titles = {r["page_id"]: r["title"] for r in cur.fetchall()}
    out: list[dict] = []
    seen: set[bytes] = set()
    for k in range(0, len(pages), 200):
        chunk = ",".join(str(int(p)) for p in pages[k:k + 200])
        with conn.cursor() as cur:
            cur.execute(f"""SELECT s.page_id, s.sent_hash, s.text
                            FROM article_sentence FOR SYSTEM_TIME ALL s
                            LEFT JOIN sentence_score sc ON sc.sent_hash = s.sent_hash
                            WHERE s.page_id IN ({chunk}) AND sc.sent_hash IS NULL""")
            for r in cur.fetchall():
                if r["sent_hash"] not in seen:
                    seen.add(r["sent_hash"])
                    out.append(dict(sent_hash=r["sent_hash"], text=r["text"], title=titles.get(r["page_id"], "")))
                    if limit and len(out) >= limit:
                        return out
    return out


def save(conn, rows: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sentence_score (sent_hash, event_name, tone, neutrality, loaded_terms, model) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE event_name=VALUES(event_name), "
            "tone=VALUES(tone), neutrality=VALUES(neutrality), loaded_terms=VALUES(loaded_terms), "
            "model=VALUES(model), scored_at=CURRENT_TIMESTAMP", rows)
    conn.commit()


async def run_llm(conn, items, llm: LLM, model_name: str, batch: int = 256) -> int:
    done = 0
    t0 = time.time()
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        results = await asyncio.gather(*(llm.score(it["text"], it["title"]) for it in chunk))
        rows = [(it["sent_hash"], r["event_name"], r["tone"], r["neutrality"],
                 json.dumps(r["loaded_terms"], ensure_ascii=False), model_name)
                for it, r in zip(chunk, results) if r is not None]
        save(conn, rows)
        done += len(rows)
        el = time.time() - t0
        print(f"  {done:,}/{len(items):,} scored  {done / el:6.1f} sentences/s  "
              f"invalid JSON {llm.invalid}/{llm.calls}", flush=True)
    return done


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["llm", "heuristic"], default="llm" if os.environ.get("SCORING_URL") else "heuristic")
    ap.add_argument("--pages", help="comma-separated page ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--rescore", action="store_true", help="delete existing scores of this backend's model first")
    a = ap.parse_args()
    pages = [int(p) for p in a.pages.split(",")] if a.pages else None
    conn = connect()
    model = "heuristic-v1" if a.backend == "heuristic" else os.environ.get("GEMMA_MODEL", "gemma")
    if a.rescore:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentence_score WHERE model = %s", (model,))
        conn.commit()
    items = todo(conn, pages, a.limit)
    print(f"{len(items):,} sentences to score with {model}")
    t0 = time.time()
    if a.backend == "heuristic":
        rows = []
        for it in items:
            r = heuristic(it["text"], it["title"])
            rows.append((it["sent_hash"], r["event_name"], r["tone"], r["neutrality"],
                         json.dumps(r["loaded_terms"], ensure_ascii=False), model))
        for i in range(0, len(rows), 5000):
            save(conn, rows[i:i + 5000])
        done = len(rows)
    else:
        url = os.environ.get("SCORING_URL")
        if not url:
            raise SystemExit("Set SCORING_URL (OpenAI-compatible base URL, e.g. http://host:8000/v1) and GEMMA_MODEL")
        llm = LLM(url, model, a.concurrency, os.environ.get("SCORING_API_KEY"))
        done = asyncio.run(run_llm(conn, items, llm, model))
    el = time.time() - t0
    print(f"Scored {done:,} sentences in {el:.1f} s ({done / el if el else 0:,.1f} sentences/s) with {model}")


if __name__ == "__main__":
    main()
