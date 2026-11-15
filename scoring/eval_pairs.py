r"""Hand-labelled check of Gemma's pair judgements (scoring/judge_pairs.py).

    python -m scoring.eval_pairs --sample 30     # write scoring/eval/pairs_labels.csv (blank `label`)
    python -m scoring.eval_pairs                 # after labelling: accuracy against Gemma
    python -m scoring.eval_pairs --judgements data/verda/judgements-v1.parquet data/verda/judgements.parquet
                                                 # before / after table
    python -m scoring.eval_pairs --sample 20 --labels scoring/eval/pairs_test.csv \
        --exclude scoring/eval/pairs_labels.csv  # a held-out test set

The sample is stratified by Gemma's label (so rare labels are represented), seeded, and the CSV does
**not** contain Gemma's label, so the human labeller is not anchored. Labels: same, contradiction,
framing, partial (docs/contracts.md b).
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DETAIL = ROOT / "data" / "verda" / "judgements-detail.csv"
JUDGEMENTS = ROOT / "data" / "verda" / "judgements.parquet"
LABELS_CSV = ROOT / "scoring" / "eval" / "pairs_labels.csv"
LABELS = ["same", "contradiction", "framing", "partial"]
KEY = ("wikidata_id", "fi_sent_no", "other_lang", "other_sent_no")
FIELDS = ["n", *KEY, "distance", "fi_text", "other_text", "label", "notes"]
# How many of each Gemma label to sample (rare labels oversampled; the rest is "partial").
QUOTA = {"contradiction": 8, "framing": 8, "same": 4}


def key(r: dict) -> tuple:
    return (r["wikidata_id"], int(r["fi_sent_no"]), r["other_lang"], int(r["other_sent_no"]))


def sample(n: int, seed: int, out: Path = LABELS_CSV, exclude: list[Path] = (), quota: dict = QUOTA) -> None:
    if out.exists() and any(r.get("label") for r in csv.DictReader(open(out, encoding="utf-8"))):
        sys.exit(f"{out} already has labels; not overwriting")
    taken = {key(r) for p in exclude for r in csv.DictReader(open(p, encoding="utf-8"))}
    rows = [r for r in csv.DictReader(open(DETAIL, encoding="utf-8")) if key(r) not in taken]
    rng = random.Random(seed)
    by = {lab: [r for r in rows if r["label"] == lab] for lab in LABELS}
    picked = []
    for lab, q in quota.items():
        picked += rng.sample(by[lab], min(q, len(by[lab])))
    rest = [r for r in rows if r not in picked]
    rest_partial = [r for r in rest if r["label"] == "partial"]
    fill = rng.sample(rest_partial, min(n - len(picked), len(rest_partial)))
    picked += fill
    if len(picked) < n:  # not enough partials: top up from anything left
        left = [r for r in rest if r not in picked]
        picked += rng.sample(left, n - len(picked))
    rng.shuffle(picked)
    print("Gemma labels in the sample (hidden from the labeller):", dict(Counter(r["label"] for r in picked)))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(picked, 1):
            w.writerow({**r, "n": i, "label": "", "notes": ""})
    print(f"wrote {len(picked)} pairs to {out} (fill in `label`: {' / '.join(LABELS)})")


def load_human(path: Path) -> dict:
    human = {key(r): r for r in csv.DictReader(open(path, encoding="utf-8")) if r["label"].strip()}
    if not human:
        sys.exit(f"no labels in {path} yet")
    return human


def per_label(human: dict, gemma: dict) -> dict:
    pairs = [(h["label"].strip(), gemma[k]["label"]) for k, h in human.items() if k in gemma]
    out = {"n": len(pairs), "correct": sum(h == g for h, g in pairs)}
    for lab in LABELS:
        g = [h for h, gl in pairs if gl == lab]
        h = [gl for hl, gl in pairs if hl == lab]
        out[lab] = (sum(x == lab for x in g), len(g), sum(x == lab for x in h), len(h))
    return out


def compare(labels: Path, paths: list[Path]) -> None:
    """Before/after table: one column block per judgements file."""
    human = load_human(labels)
    runs = [(p.stem, per_label(human, {key(r): r for r in pq.read_table(p).to_pylist()})) for p in paths]
    fmt = lambda a, b: f"{a}/{b}" if b else "–"  # noqa: E731
    print(f"{len(human)} hand-labelled pairs ({labels.name})\n")
    print(f"{'':<15}" + "".join(f"{name:>26}" for name, _ in runs))
    print(f"{'':<15}" + "".join(f"{'precision':>14}{'recall':>12}" for _ in runs))
    for lab in LABELS:
        print(f"  {lab:<13}" + "".join(f"{fmt(m[lab][0], m[lab][1]):>14}{fmt(m[lab][2], m[lab][3]):>12}" for _, m in runs))
    print(f"  {'accuracy':<13}" + "".join(f"{m['correct'] / m['n']:>13.0%} ({m['correct']}/{m['n']})"[:26].rjust(26) for _, m in runs))


def evaluate(labels: Path = LABELS_CSV, judgements: Path = JUDGEMENTS) -> None:
    human = load_human(labels)
    bad = {r["label"] for r in human.values()} - set(LABELS)
    if bad:
        sys.exit(f"unknown labels: {bad}")
    gemma = {key(r): r for r in pq.read_table(judgements).to_pylist()}
    pairs = [(h["label"].strip(), gemma[k]["label"]) for k, h in human.items() if k in gemma]
    n = len(pairs)
    acc = sum(h == g for h, g in pairs) / n
    print(f"{n} hand-labelled pairs · model {next(iter(gemma.values()))['model']}")
    print(f"accuracy (4 labels): {acc:.0%}  ({sum(h == g for h, g in pairs)}/{n})")
    # Lenient: a note "alt: <label>; …" names a second label the labeller would also accept.
    alt = {k: h["notes"].split(";")[0].removeprefix("alt:").strip()
           for k, h in human.items() if h.get("notes", "").startswith("alt:")}
    ok = sum(h["label"].strip() == gemma[k]["label"] or alt.get(k) == gemma[k]["label"]
             for k, h in human.items() if k in gemma)
    if alt:
        print(f"accuracy, accepting the labeller's alternative label ({len(alt)} pairs have one): {ok / n:.0%}  ({ok}/{n})")
    # Coarser question the editor cares about: is there a problem (contradiction/framing) or not?
    prob = lambda x: x in ("contradiction", "framing")  # noqa: E731
    acc2 = sum(prob(h) == prob(g) for h, g in pairs) / n
    print(f"accuracy (problem = contradiction|framing vs not): {acc2:.0%}")
    print("\nper Gemma label: precision (human agrees) · per human label: recall (Gemma finds it)")
    for lab in LABELS:
        g = [h for h, gl in pairs if gl == lab]
        h = [gl for hl, gl in pairs if hl == lab]
        p = f"{sum(x == lab for x in g)}/{len(g)}" if g else "–"
        r = f"{sum(x == lab for x in h)}/{len(h)}" if h else "–"
        print(f"  {lab:<14} precision {p:>6}   recall {r:>6}")
    print("\nconfusion (rows = human, columns = Gemma):")
    c = Counter(pairs)
    print(" " * 15 + "".join(f"{lab[:8]:>10}" for lab in LABELS))
    for hl in LABELS:
        print(f"  {hl:<13}" + "".join(f"{c[(hl, gl)]:>10}" for gl in LABELS))
    print("\ndisagreements:")
    for k, h in human.items():
        g = gemma.get(k)
        if g and g["label"] != h["label"].strip():
            print(f"  #{h['n']:>2} {k[2]} human {h['label']:<13} gemma {g['label']:<13} {g['reason'][:110]}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, help="write a new labelling sample of N pairs")
    ap.add_argument("--seed", type=int, default=1918)
    ap.add_argument("--labels", type=Path, default=LABELS_CSV, help="labelled CSV (or the sample to write)")
    ap.add_argument("--judgements", type=Path, nargs="+", default=[JUDGEMENTS],
                    help="one file: full report; several: before/after table")
    ap.add_argument("--exclude", type=Path, nargs="*", default=[], help="with --sample: skip pairs in these CSVs")
    ap.add_argument("--quota", help="with --sample: e.g. contradiction=5,framing=5,same=4 (rest partial)")
    a = ap.parse_args()
    if a.sample:
        quota = {k: int(v) for k, v in (x.split("=") for x in a.quota.split(","))} if a.quota else QUOTA
        sample(a.sample, a.seed, a.labels, a.exclude, quota)
    elif len(a.judgements) > 1:
        compare(a.labels, a.judgements)
    else:
        evaluate(a.labels, a.judgements[0])


if __name__ == "__main__":
    main()
