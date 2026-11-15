"""Evaluate a scorer against hand labels.  (owner: P3)

    python -m scoring.eval --sample 50          # write scoring/eval/labels.csv with 50 real
                                                # sentences (stratified: edit-war, loaded-looking,
                                                # random) and EMPTY label columns -> label by hand
    python -m scoring.eval --backend heuristic  # agreement of the keyword baseline
    SCORING_URL=… GEMMA_MODEL=google/gemma-3-4b-it  python -m scoring.eval --backend llm
    SCORING_URL=… GEMMA_MODEL=google/gemma-3-27b-it python -m scoring.eval --backend llm

Labels: tone (neutral|loaded|partisan), event_name (basic form or empty), neutrality (0–1).
Reports tone accuracy, event-name accuracy, neutrality MAE, JSON validity, and the disagreements
(the "honest failure examples" for the pitch).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import random
import sys
from pathlib import Path

from common.db import connect
from scoring.score import LLM, heuristic, normalise_event

LABELS = Path(__file__).parent / "eval" / "labels.csv"
FIELDS = ["page_id", "title", "text", "tone", "event_name", "neutrality", "notes"]


def sample(n: int) -> None:
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT s.page_id, a.title, s.text, COUNT(*) AS lives
                       FROM article_sentence FOR SYSTEM_TIME ALL s JOIN article a USING (page_id)
                       WHERE s.page_id < 900000000
                       GROUP BY s.page_id, s.sent_hash""")
        rows = list(cur.fetchall())
    if not rows:
        raise SystemExit("No real articles loaded. Load some first (make ingest).")
    random.seed(1918)
    contested = [r for r in rows if r["lives"] > 1]
    loaded = [r for r in rows if heuristic(r["text"], r["title"])["tone"] != "neutral"]
    picked, seen = [], set()
    for pool, k in ((contested, n // 3), (loaded, n // 3), (rows, n)):
        random.shuffle(pool)
        for r in pool:
            if len(picked) >= n or k <= 0:
                break
            if r["text"] not in seen:
                seen.add(r["text"])
                picked.append(r)
                k -= 1
    LABELS.parent.mkdir(exist_ok=True)
    if LABELS.exists() and any(row.get("tone") for row in csv.DictReader(open(LABELS, encoding="utf-8"))):
        raise SystemExit(f"{LABELS} already has labels; not overwriting.")
    with open(LABELS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for r in picked:
            w.writerow(dict(page_id=r["page_id"], title=r["title"], text=r["text"]))
    print(f"Wrote {len(picked)} sentences to {LABELS}. Fill in tone, event_name, neutrality by hand.")


def evaluate(backend: str) -> None:
    rows = [r for r in csv.DictReader(open(LABELS, encoding="utf-8")) if r.get("tone")]
    if not rows:
        raise SystemExit(f"No labelled rows in {LABELS}. Run --sample, then label by hand.")
    if backend == "heuristic":
        preds = [heuristic(r["text"], r["title"]) for r in rows]
        invalid, calls, model = 0, len(rows), "heuristic-v1"
    else:
        model = os.environ.get("GEMMA_MODEL", "gemma")
        llm = LLM(os.environ["SCORING_URL"], model, 16, os.environ.get("SCORING_API_KEY"))

        async def go():
            return await asyncio.gather(*(llm.score(r["text"], r["title"]) for r in rows))
        preds = asyncio.run(go())
        invalid, calls = llm.invalid, llm.calls
    tone_ok = ev_ok = 0
    mae, misses = 0.0, []
    for r, p in zip(rows, preds):
        if p is None:
            misses.append((r, None))
            continue
        t_ok = p["tone"] == r["tone"]
        e_ok = (normalise_event(r["event_name"]) or None) == p["event_name"]
        tone_ok += t_ok
        ev_ok += e_ok
        mae += abs(float(r["neutrality"] or 0.5) - p["neutrality"])
        if not (t_ok and e_ok):
            misses.append((r, p))
    n = len(rows)
    print(f"model {model}: {n} labelled sentences")
    print(f"  tone accuracy        {tone_ok / n:6.1%}")
    print(f"  event-name accuracy  {ev_ok / n:6.1%}")
    print(f"  neutrality MAE       {mae / n:6.3f}")
    print(f"  valid JSON           {1 - invalid / max(calls, 1):6.1%} ({invalid} invalid of {calls} calls)")
    print("\nDisagreements (label -> prediction):")
    for r, p in misses[:15]:
        got = f"{p['tone']}/{p['event_name']}" if p else "NO ANSWER"
        print(f"  [{r['tone']}/{r['event_name'] or '-'} -> {got}] {r['text'][:110]}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int)
    ap.add_argument("--backend", choices=["llm", "heuristic"], default="heuristic")
    a = ap.parse_args()
    sample(a.sample) if a.sample else evaluate(a.backend)
