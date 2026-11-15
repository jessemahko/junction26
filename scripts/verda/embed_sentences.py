r"""Embed every sentence of the topics that exist in fi, sv and en (dataset S) with bge-m3.

Output, docs/contracts.md (a): data/verda/sentences-{lang}.parquet, one row per sentence:
lang, page_id (int32), wikidata_id, sent_no (int32), text, embedding (list<float32>[1024], L2-normalised),
model. Sentences are split with ingest.sentences.text_sentences(), the shared splitter, so the sentence
numbers agree with Jussi's lang_sentence. `text` is the sentence as text_sentences() returns it.

    # this laptop, CPU, the two hero articles only:
    python scripts/verda/embed_sentences.py --pages "Sauli Niinistö,Suomen sisällissota"
    # Verda GPU, all 2,919 topics:
    python scripts/verda/embed_sentences.py

--pages takes titles (any language), wikidata ids or fi page ids, comma-separated.
Device auto: CUDA if present (fp16), else CPU. Same model and library as ingest/embed_cpu.py
(sentence-transformers, BAAI/bge-m3, normalize_embeddings=True), so distances are comparable.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")   # quiet the fork warning at exit
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from ingest.sentences import text_sentences  # noqa: E402

LANGS = ("fi", "sv", "en")
MODEL_ID = "BAAI/bge-m3"
MODEL_NAME = "bge-m3"          # the contract's `model` value for sentence-transformers runs
DIM = 1024
SCHEMA = pa.schema([
    ("lang", pa.string()), ("page_id", pa.int32()), ("wikidata_id", pa.string()), ("sent_no", pa.int32()),
    ("text", pa.string()), ("embedding", pa.list_(pa.float32())), ("model", pa.string()),
])


def load_articles(src: Path) -> dict[str, dict[str, dict]]:
    """{lang: {wikidata_id: {page_id, title, text}}} for the topics present in all three languages."""
    by_lang = {}
    for lang in LANGS:
        t = pq.read_table(src / f"articles-{lang}.parquet", columns=["page_id", "wikidata_id", "title", "text"])
        by_lang[lang] = {r["wikidata_id"]: r for r in t.to_pylist() if r["wikidata_id"]}
    shared = set.intersection(*(set(d) for d in by_lang.values()))
    return {lang: {q: d[q] for q in shared} for lang, d in by_lang.items()}


def pick(arts: dict[str, dict[str, dict]], pages: str | None) -> list[str]:
    topics = sorted(arts["fi"])
    if not pages:
        return topics
    wanted = {p.strip().casefold() for p in pages.split(",") if p.strip()}
    out = [q for q in topics if q.casefold() in wanted
           or any(arts[l][q]["title"].casefold() in wanted or str(arts[l][q]["page_id"]) in wanted for l in LANGS)]
    missing = wanted - {x.casefold() for q in out for x in
                        [q, *(arts[l][q]["title"] for l in LANGS), *(str(arts[l][q]["page_id"]) for l in LANGS)]}
    if missing:
        sys.exit(f"not found among the shared fi/sv/en topics: {', '.join(sorted(missing))}")
    return out


def pick_device(arg: str) -> str:
    import torch
    if arg != "auto":
        return arg
    return "cuda" if torch.cuda.is_available() else "cpu"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=ROOT / "data" / "s")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "verda")
    ap.add_argument("--pages", help="only these topics: titles, wikidata ids or fi page ids, comma-separated")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu", "mps"])
    ap.add_argument("--batch-size", type=int, default=0, help="default: 256 on GPU, 32 on CPU")
    ap.add_argument("--chunk", type=int, default=20_000, help="sentences per encode call / parquet row group")
    a = ap.parse_args()

    t_start = time.time()
    arts = load_articles(a.src)
    topics = pick(arts, a.pages)
    print(f"{len(arts['fi']):,} topics in fi, sv and en; embedding {len(topics):,}", flush=True)

    # Split first (CPU, fast), so the GPU sees one long stream per language.
    t = time.time()
    per_lang: dict[str, list[tuple[int, str, int, str]]] = {}
    for lang in LANGS:
        rows = []
        for q in topics:
            r = arts[lang][q]
            for i, (_, s) in enumerate(text_sentences(r["text"])):
                rows.append((int(r["page_id"]), q, i, s))
        per_lang[lang] = rows
    t_split = time.time() - t
    print("sentences: " + ", ".join(f"{l} {len(v):,}" for l, v in per_lang.items()) + f"  (split in {t_split:.1f} s)",
          flush=True)

    import torch
    from sentence_transformers import SentenceTransformer
    device = pick_device(a.device)
    bs = a.batch_size or (256 if device == "cuda" else 32)
    t = time.time()
    model = SentenceTransformer(MODEL_ID, device=device)
    if device == "cuda":
        model.half()
    t_load = time.time() - t
    gpu = torch.cuda.get_device_name(0) if device == "cuda" else None
    print(f"model {MODEL_ID} on {device}{f' ({gpu})' if gpu else ''}, batch {bs}, loaded in {t_load:.0f} s", flush=True)

    a.out.mkdir(parents=True, exist_ok=True)
    stats = {}
    t_embed_all = 0.0
    for lang, rows in per_lang.items():
        path = a.out / f"sentences-{lang}.parquet"
        t_lang = 0.0
        with pq.ParquetWriter(path, SCHEMA, compression="zstd") as w:
            for c in range(0, len(rows), a.chunk):
                part = rows[c:c + a.chunk]
                t = time.time()
                vecs = model.encode([s for _, _, _, s in part], batch_size=bs, normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=False).astype("float32")
                t_lang += time.time() - t
                assert vecs.shape[1] == DIM
                w.write_table(pa.table({
                    "lang": [lang] * len(part),
                    "page_id": pa.array([p for p, _, _, _ in part], pa.int32()),
                    "wikidata_id": [q for _, q, _, _ in part],
                    "sent_no": pa.array([i for _, _, i, _ in part], pa.int32()),
                    "text": [s for _, _, _, s in part],
                    "embedding": pa.array(list(vecs), pa.list_(pa.float32())),
                    "model": [MODEL_NAME] * len(part),
                }, schema=SCHEMA))
                print(f"  {lang} {min(c + a.chunk, len(rows)):>8,} / {len(rows):,}  {t_lang:6.1f} s", flush=True)
        t_embed_all += t_lang
        stats[lang] = {"sentences": len(rows), "embed_s": round(t_lang, 2),
                       "sentences_per_s": round(len(rows) / t_lang, 1) if t_lang else None}
        print(f"{lang}: {len(rows):,} sentences in {t_lang:.1f} s ({stats[lang]['sentences_per_s']} /s) -> {path}", flush=True)

    n = sum(len(v) for v in per_lang.values())
    run = {
        "topics": len(topics), "pages": a.pages, "sentences": n, "per_lang": stats,
        "device": device, "gpu": gpu, "cpu": platform.processor() or platform.machine(),
        "threads": torch.get_num_threads(), "batch_size": bs, "dtype": "float16" if device == "cuda" else "float32",
        "model": MODEL_ID, "torch": torch.__version__,
        "sentence_transformers": __import__("sentence_transformers").__version__,
        "split_s": round(t_split, 2), "model_load_s": round(t_load, 1), "embed_s": round(t_embed_all, 1),
        "sentences_per_s": round(n / t_embed_all, 1) if t_embed_all else None,
        "wall_s": round(time.time() - t_start, 1),
        "finished": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    (a.out / "embed_run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    print(f"embedded {n:,} sentences in {t_embed_all:.1f} s on {device} = {run['sentences_per_s']} sentences/s "
          f"(wall {run['wall_s']} s incl. model load)")


if __name__ == "__main__":
    main()
