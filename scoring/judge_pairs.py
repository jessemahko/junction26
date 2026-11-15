r"""Gemma judges matched fi–sv and fi–en sentence pairs (docs/contracts.md b).

For each topic, every Finnish sentence is paired with its **mutual best** match in sv and in en
(fi's nearest other-language sentence, whose nearest Finnish sentence is that same fi sentence),
kept if the cosine distance is <= --threshold (0.418, Jussi's stage-1 threshold: the 5th percentile
of chance matches). Gemma labels each pair same / contradiction / framing / partial, with a one-line
reason and the tone of each sentence, as structured JSON (response_format json_schema).

    python -m scoring.judge_pairs --topics Q29207,Q211855 --concurrency 32

Input: data/verda/sentences-{fi,sv,en}.parquet (scripts/verda/embed_sentences.py).
Output: data/verda/judgements.parquet (contract b), judgements-detail.csv (with the texts and
distances, for reading), judge_run.json (timings, invalid-JSON rate, label counts).
Endpoint: any OpenAI-compatible server, from .env: SCORING_URL (base URL, …/v1), SCORING_API_KEY,
GEMMA_MODEL. vLLM on Verda now; Google AI Studio's OpenAI endpoint also works (it may ignore
json_schema, the parser copes with fenced JSON).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "verda"
LANG_NAME = {"fi": "Finnish", "sv": "Swedish", "en": "English"}
LABELS = ["same", "contradiction", "framing", "partial"]
TONES = ["neutral", "loaded", "partisan"]

# Order matters with guided decoding: the model first writes down the specific fact each sentence
# states and whether it is the same fact, then its reason, and only then commits to a label.
SCHEMA = {
    "type": "object",
    "properties": {
        "fi_claim": {"type": "string", "maxLength": 200},
        "other_claim": {"type": "string", "maxLength": 200},
        "same_specific_fact": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 300},
        "label": {"type": "string", "enum": LABELS},
        "tone_fi": {"type": "string", "enum": TONES},
        "tone_other": {"type": "string", "enum": TONES},
    },
    "required": ["fi_claim", "other_claim", "same_specific_fact", "reason", "label", "tone_fi", "tone_other"],
    "additionalProperties": False,
}

PROMPT = """You compare two Wikipedia sentences about the same topic, written in different language editions.
Article: "{title}"

Finnish sentence: "{fi}"
{other_name} sentence: "{other}"

Step 1. "fi_claim" and "other_claim": in English, the specific fact each sentence states (who / what /
how many / when), in a few words.
Step 2. "same_specific_fact": true only if both sentences state a value for the very same thing: the same
quantity, event, date or name, with the same scope (same place, time span, group and kind of count).
"Losses in one battle" and "losses in the whole war", "one regiment" and "the whole army",
"the 2012 election" and "the 2018 election" are NOT the same specific fact.
Step 3. "reason": one short English sentence naming the concrete difference (or "Same claim.").
Step 4. "label", by these rules:
- "contradiction": ONLY if same_specific_fact is true AND the two values clearly disagree, so both
  cannot be true (e.g. born 1948 vs born 1950; 900 vs 2,000 soldiers; the treaty signed in May vs in August).
  Estimates, approximations or ranges for the same quantity that differ moderately (less than 25 %,
  e.g. "about 5,000" vs "4,600", "300 ships" vs "an estimated 260") are "partial", not
  contradiction. If same_specific_fact is false, the label is never "contradiction".
- "same": they make the same claim. Differences in wording, translation, naming (e.g. "the Social
  Democratic Party" vs "the SDP", "seized power" vs "took over"), or one side adding only a minor extra detail
  (such as a date, a place or a title) are still "same".
- "framing": the same fact told with a clearly different slant, judgement or tone (a value judgement,
  loaded word, or who is credited / blamed present in one and not the other).
- "partial": they overlap only partly: one makes a substantive claim the other lacks, they are about
  related but different facts, or the moderate-difference estimate case above.
Tone of each sentence: "neutral" (encyclopedic), "loaded" (word choice takes a side without
attribution) or "partisan" (openly presents one side's view as fact)."""


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                v = re.split(r"\s+#", v, maxsplit=1)[0]          # inline comment: KEY=value   # e.g. …
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_sentences(topics: list[str]) -> dict[str, dict[str, dict]]:
    """{lang: {wikidata_id: {"page_id", "sent_no": [...], "text": [...], "emb": ndarray}}}"""
    out = {}
    for lang in ("fi", "sv", "en"):
        t = pq.read_table(DATA / f"sentences-{lang}.parquet")
        t = t.filter(pc.is_in(t["wikidata_id"], value_set=pa.array(topics)))
        by = {}
        for r in t.to_pylist():
            d = by.setdefault(r["wikidata_id"], {"page_id": r["page_id"], "sent_no": [], "text": [], "emb": []})
            d["sent_no"].append(r["sent_no"]); d["text"].append(r["text"]); d["emb"].append(r["embedding"])
        for d in by.values():
            d["emb"] = np.asarray(d["emb"], dtype=np.float32)
        out[lang] = by
    return out


def mutual_pairs(fi: dict, other: dict, threshold: float) -> list[tuple[int, int, float]]:
    """(fi index, other index, cosine distance) for mutual best matches within the threshold.
    Embeddings are L2-normalised, so cosine distance = 1 - dot product."""
    sim = fi["emb"] @ other["emb"].T
    best_o = sim.argmax(axis=1)
    best_f = sim.argmax(axis=0)
    out = []
    for i, j in enumerate(best_o):
        d = 1.0 - float(sim[i, j])
        if best_f[j] == i and d <= threshold:
            out.append((i, int(j), round(d, 4)))
    return out


def parse(content: str) -> dict | None:
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        r = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(r, dict) or r.get("label") not in LABELS or r.get("tone_fi") not in TONES \
            or r.get("tone_other") not in TONES or not isinstance(r.get("reason"), str) \
            or not isinstance(r.get("same_specific_fact"), bool):
        return None
    out = {"label": r["label"], "reason": r["reason"].strip()[:300], "tone_fi": r["tone_fi"],
           "tone_other": r["tone_other"], "fi_claim": str(r.get("fi_claim", "")).strip()[:200],
           "other_claim": str(r.get("other_claim", "")).strip()[:200],
           "same_specific_fact": r["same_specific_fact"], "downgraded": False}
    # The rule, enforced: no contradiction unless both sentences state the same specific fact.
    if out["label"] == "contradiction" and not out["same_specific_fact"]:
        out["label"], out["downgraded"] = "partial", True
    return out


class Judge:
    def __init__(self, url: str, model: str, key: str | None, concurrency: int, schema: bool = True):
        import httpx
        self.url = url.rstrip("/") + "/chat/completions"
        self.model = model
        self.schema = schema
        self.sem = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(timeout=180, headers={"Authorization": f"Bearer {key or 'none'}"})
        self.responses = 0     # answers received
        self.invalid = 0       # answers that were not valid JSON for the schema
        self.failed = 0        # pairs with no valid answer after retries
        self.tokens_in = 0
        self.tokens_out = 0

    async def judge(self, title: str, fi: str, other_lang: str, other: str) -> dict | None:
        body = {"model": self.model, "temperature": 0, "max_tokens": 400,
                "messages": [{"role": "user", "content": PROMPT.format(
                    title=title, fi=fi, other_name=LANG_NAME[other_lang], other=other)}]}
        if self.schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "pair_judgement", "schema": SCHEMA, "strict": True}}
        async with self.sem:
            for attempt in range(3):
                try:
                    r = await self.client.post(self.url, json=body)
                    r.raise_for_status()
                    j = r.json()
                    self.responses += 1
                    u = j.get("usage") or {}
                    self.tokens_in += u.get("prompt_tokens", 0); self.tokens_out += u.get("completion_tokens", 0)
                    res = parse(j["choices"][0]["message"]["content"] or "")
                    if res:
                        return res
                    self.invalid += 1
                except Exception as e:  # network / 5xx: back off and retry
                    if attempt == 2:
                        print(f"  request failed: {e!r}", file=sys.stderr)
                    await asyncio.sleep(2 ** attempt)
        self.failed += 1
        return None


async def run(items: list[dict], judge: Judge) -> list[dict | None]:
    done = 0

    async def one(it):
        nonlocal done
        res = await judge.judge(it["title"], it["fi_text"], it["other_lang"], it["other_text"])
        done += 1
        if done % 100 == 0 or done == len(items):
            print(f"  {done:,} / {len(items):,}", flush=True)
        return res

    try:
        return await asyncio.gather(*(one(it) for it in items))
    finally:
        await judge.client.aclose()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topics", default="Q29207,Q211855", help="wikidata ids, comma-separated")
    ap.add_argument("--threshold", type=float, default=0.418)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--topics-file", type=Path, help="one wikidata id per line (text after # ignored); overrides --topics")
    ap.add_argument("--tag", help="write judgements-<tag>.parquet / judgements-detail-<tag>.csv / judge_run-<tag>.json")
    ap.add_argument("--only-pairs", type=Path, help="judge only the pairs in this judgements parquet …")
    ap.add_argument("--only-label", help="… that have this label there (e.g. contradiction)")
    ap.add_argument("--limit", type=int, help="judge only the first N pairs (prompt testing)")
    ap.add_argument("--no-schema", action="store_true", help="for endpoints without json_schema support")
    ap.add_argument("--gpu", default=None, help="GPU name for the run log, e.g. 'A100 80GB'")
    ap.add_argument("--eur-per-hour", type=float, default=None, help="GPU price, for the cost line")
    a = ap.parse_args()

    url, model = os.environ.get("SCORING_URL"), os.environ.get("GEMMA_MODEL")
    if not url or not model:
        sys.exit("Set SCORING_URL (OpenAI-compatible base URL, …/v1), GEMMA_MODEL and SCORING_API_KEY in .env")

    if a.topics_file:
        topics = [ln.split("#", 1)[0].strip() for ln in a.topics_file.read_text(encoding="utf-8").splitlines()]
        topics = list(dict.fromkeys(q for q in topics if q))
    else:
        topics = [q.strip() for q in a.topics.split(",") if q.strip()]
    sents = load_sentences(topics)
    titles = {r["wikidata_id"]: r["title"] for r in pq.read_table(
        ROOT / "data" / "s" / "articles-fi.parquet", columns=["wikidata_id", "title"]).to_pylist()
        if r["wikidata_id"] in topics}

    items = []
    for q in topics:
        fi = sents["fi"].get(q)
        if not fi:
            print(f"{q}: no Finnish sentences in data/verda, skipped"); continue
        for lang in ("sv", "en"):
            other = sents[lang].get(q)
            if not other:
                continue
            pairs = mutual_pairs(fi, other, a.threshold)
            print(f"{q} {titles.get(q, '')}: fi {len(fi['text'])} · {lang} {len(other['text'])} sentences → "
                  f"{len(pairs)} mutual-best pairs within {a.threshold}")
            for i, j, d in pairs:
                items.append({"wikidata_id": q, "title": titles.get(q, q), "fi_sent_no": fi["sent_no"][i],
                              "fi_text": fi["text"][i], "other_lang": lang, "other_sent_no": other["sent_no"][j],
                              "other_text": other["text"][j], "distance": d})
    if a.only_pairs:
        keep = {(r["wikidata_id"], r["fi_sent_no"], r["other_lang"], r["other_sent_no"])
                for r in pq.read_table(a.only_pairs).to_pylist() if not a.only_label or r["label"] == a.only_label}
        items = [it for it in items if (it["wikidata_id"], it["fi_sent_no"], it["other_lang"], it["other_sent_no"]) in keep]
        print(f"--only-pairs: {len(items):,} of {len(keep):,} listed pairs found", flush=True)
    if a.limit:
        items = items[:a.limit]
    print(f"judging {len(items):,} pairs with {model} at {url} (concurrency {a.concurrency})", flush=True)

    judge = Judge(url, model, os.environ.get("SCORING_API_KEY"), a.concurrency, schema=not a.no_schema)
    t_start = time.time()
    started = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    results = asyncio.run(run(items, judge))
    wall = time.time() - t_start
    ended = time.strftime("%Y-%m-%d %H:%M:%S %Z")

    rows = [{**it, **res, "model": model} for it, res in zip(items, results) if res]
    sfx = f"-{a.tag}" if a.tag else ""
    DATA.mkdir(parents=True, exist_ok=True)
    cols = ["wikidata_id", "fi_sent_no", "other_lang", "other_sent_no", "label", "reason", "tone_fi", "tone_other",
            "fi_claim", "other_claim", "same_specific_fact", "model"]
    schema = pa.schema([("wikidata_id", pa.string()), ("fi_sent_no", pa.int32()), ("other_lang", pa.string()),
                        ("other_sent_no", pa.int32()), ("label", pa.string()), ("reason", pa.string()),
                        ("tone_fi", pa.string()), ("tone_other", pa.string()), ("fi_claim", pa.string()),
                        ("other_claim", pa.string()), ("same_specific_fact", pa.bool_()), ("model", pa.string())])
    pq.write_table(pa.Table.from_pylist([{c: r[c] for c in cols} for r in rows], schema=schema),
                   DATA / f"judgements{sfx}.parquet")
    with open(DATA / f"judgements-detail{sfx}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["wikidata_id", "title", "fi_sent_no", "other_lang", "other_sent_no",
                                          "distance", "label", "same_specific_fact", "downgraded", "tone_fi", "tone_other",
                                          "reason", "fi_claim", "other_claim", "fi_text", "other_text"],
                           extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    labels = {lang: dict(Counter(r["label"] for r in rows if r["other_lang"] == lang)) for lang in ("sv", "en")}
    run_log = {
        "model": model, "endpoint": url.split("//")[-1].split("/")[0], "tag": a.tag,
        "topics": len(topics), "topics_with_pairs": len({it["wikidata_id"] for it in items}),
        "only_pairs": str(a.only_pairs) if a.only_pairs else None, "only_label": a.only_label, "threshold": a.threshold,
        "concurrency": a.concurrency, "pairs": len(items), "judged": len(rows), "failed": judge.failed,
        "responses": judge.responses, "invalid_json": judge.invalid,
        "invalid_json_rate": round(judge.invalid / judge.responses, 4) if judge.responses else None,
        "started": started, "ended": ended, "wall_s": round(wall, 1),
        "pairs_per_s": round(len(rows) / wall, 2) if wall else None,
        "tokens_in": judge.tokens_in, "tokens_out": judge.tokens_out,
        "tokens_per_s": round((judge.tokens_in + judge.tokens_out) / wall) if wall else None,
        "labels": labels, "downgraded_contradictions": sum(r["downgraded"] for r in rows),
        "same_specific_fact_true": sum(r["same_specific_fact"] for r in rows), "gpu": a.gpu, "eur_per_hour": a.eur_per_hour,
        "cost_eur_run": round(a.eur_per_hour * wall / 3600, 4) if a.eur_per_hour else None,
    }
    (DATA / f"judge_run{sfx}.json").write_text(json.dumps(run_log, indent=2), encoding="utf-8")
    print(json.dumps(run_log, indent=2))


if __name__ == "__main__":
    main()
