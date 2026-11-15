r"""Import Gemma's pair judgements (docs/contracts.md b) into pair_judgement.

    .venv\Scripts\python -m ingest.load_judgements                       # every data/verda/judgements*.parquet, oldest first
    .venv\Scripts\python -m ingest.load_judgements data/verda/judgements-v2-12b.parquet

Re-runnable: for each (model, topic) in a file, that model's old rows for the topic are replaced, so a
bigger or repeated run of the same model just overwrites, and a second model (e.g. the 12B check) is
kept next to the first. Without arguments the files are taken oldest first (by modification time), so
the newest run of a model wins for the topics it covers.

Checks before anything is written (the whole file is refused if one fails):
  * every judged pair points at sentences that exist in OUR lang_sentence numbering
    (fi_sent_no in the topic's Finnish page, other_sent_no in its sv / en page);
  * if data/verda/sentences-{lang}.parquet is there (Jesse's sentence split), its texts must equal
    lang_sentence's for every topic it covers: same numbering, same text;
  * labels and tones are the contract's values.
Pairs that are not one of our mutual matches are imported but counted in the report.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pyarrow.parquet as pq

from common.db import ROOT, connect

VERDA = ROOT / "data" / "verda"
# The worklist's counts use this model; others are second opinions ("both models agree").
PRIMARY_MODEL = "google/gemma-3-27b-it"
LABELS = {"same", "contradiction", "framing", "partial"}
TONES = {"neutral", "loaded", "partisan", None}

DDL = """CREATE TABLE IF NOT EXISTS pair_judgement (
  wikidata_id         VARCHAR(20) NOT NULL,
  fi_sent_no          INT UNSIGNED NOT NULL,     -- lang_sentence.sent_no of the Finnish sentence
  other_lang          CHAR(2) NOT NULL,
  other_sent_no       INT UNSIGNED NOT NULL,     -- lang_sentence.sent_no in other_lang
  label               ENUM('same', 'contradiction', 'framing', 'partial') NOT NULL,
  reason              TEXT,
  tone_fi             ENUM('neutral', 'loaded', 'partisan'),
  tone_other          ENUM('neutral', 'loaded', 'partisan'),
  fi_claim            TEXT,                      -- the claim Gemma read from each sentence (English)
  other_claim         TEXT,
  same_specific_fact  BOOL,                      -- Gemma: both sentences are about the same specific fact
  model               VARCHAR(100) NOT NULL,
  source_file         VARCHAR(200),
  imported_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (wikidata_id, other_lang, fi_sent_no, other_sent_no, model),
  KEY label (label, wikidata_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"""

# The table first existed (empty) with only the contract's columns; bring it up to date.
UPGRADE = [
    "ALTER TABLE pair_judgement ADD COLUMN IF NOT EXISTS fi_claim TEXT AFTER tone_other",
    "ALTER TABLE pair_judgement ADD COLUMN IF NOT EXISTS other_claim TEXT AFTER fi_claim",
    "ALTER TABLE pair_judgement ADD COLUMN IF NOT EXISTS same_specific_fact BOOL AFTER other_claim",
    "ALTER TABLE pair_judgement ADD COLUMN IF NOT EXISTS source_file VARCHAR(200) AFTER model",
    "ALTER TABLE pair_judgement ADD COLUMN IF NOT EXISTS imported_at TIMESTAMP NOT NULL "
    "DEFAULT CURRENT_TIMESTAMP AFTER source_file",
    "CREATE INDEX IF NOT EXISTS label ON pair_judgement (label, wikidata_id)",
]

COLS = ["wikidata_id", "fi_sent_no", "other_lang", "other_sent_no", "label", "reason", "tone_fi",
        "tone_other", "fi_claim", "other_claim", "same_specific_fact", "model", "source_file"]


def ensure_table(cur) -> None:
    cur.execute(DDL)
    for sql in UPGRADE:
        cur.execute(sql)


def _in(ids) -> str:
    return ", ".join(["%s"] * len(ids))


def our_sentences(cur, topics: list[str]) -> dict:
    """{(wikidata_id, lang, sent_no): text} from lang_sentence, for the topics' fi / sv / en pages."""
    cur.execute(f"""SELECT t.wikidata_id, s.lang, s.sent_no, s.text
FROM lang_topic t
JOIN lang_sentence s ON (s.lang, s.page_id) IN (('fi', t.fi_page_id), ('sv', t.sv_page_id), ('en', t.en_page_id))
WHERE t.wikidata_id IN ({_in(topics)})""", topics)
    return {(r["wikidata_id"], r["lang"], r["sent_no"]): r["text"] for r in cur.fetchall()}


def check_sentence_files(ours: dict, topics: set[str]) -> list[str]:
    """Jesse's sentences-{lang}.parquet against lang_sentence, for the judged topics it covers."""
    problems = []
    for lang in ("fi", "sv", "en"):
        f = VERDA / f"sentences-{lang}.parquet"
        if not f.exists():
            continue
        theirs = {(r["wikidata_id"], lang, r["sent_no"]): r["text"]
                  for r in pq.read_table(f, columns=["wikidata_id", "sent_no", "text"]).to_pylist()
                  if r["wikidata_id"] in topics}
        mine = {k: v for k, v in ours.items() if k[1] == lang and k[0] in {t for t, _, _ in theirs}}
        bad = [k for k in theirs if mine.get(k) != theirs[k]] + [k for k in mine if k not in theirs]
        print(f"  {f.name}: {len(theirs):,} sentences of the judged topics, {len(bad)} differ from lang_sentence")
        problems += [f"{f.name} {k}" for k in bad[:5]]
    return problems


def load_file(con, path: Path) -> None:
    rows = pq.read_table(path).to_pylist()
    missing_cols = set(COLS) - {"source_file"} - set(rows[0]) if rows else set()
    if missing_cols:
        raise SystemExit(f"{path.name}: missing columns {sorted(missing_cols)}")
    cur = con.cursor()
    topics = sorted({r["wikidata_id"] for r in rows})
    ours = our_sentences(cur, topics)
    problems = check_sentence_files(ours, set(topics))
    for r in rows:
        key = (r["wikidata_id"], r["fi_sent_no"], r["other_lang"], r["other_sent_no"])
        if (r["wikidata_id"], "fi", r["fi_sent_no"]) not in ours:
            problems.append(f"{key}: no Finnish sentence {r['fi_sent_no']} in lang_sentence")
        if (r["wikidata_id"], r["other_lang"], r["other_sent_no"]) not in ours:
            problems.append(f"{key}: no {r['other_lang']} sentence {r['other_sent_no']} in lang_sentence")
        if r["label"] not in LABELS or r["tone_fi"] not in TONES or r["tone_other"] not in TONES:
            problems.append(f"{key}: label/tone outside the contract: {r['label']}, {r['tone_fi']}, {r['tone_other']}")
    if problems:
        print("\n".join("  " + p for p in problems[:20]))
        raise SystemExit(f"{path.name}: {len(problems)} problem(s), nothing imported")

    # Pairs that are not our mutual matches (lang_pair.matched): imported, but worth knowing.
    cur.execute(f"""SELECT wikidata_id, other_lang, fi_sent, other_sent FROM lang_pair
WHERE direction = 'fi' AND matched AND wikidata_id IN ({_in(topics)})""", topics)
    mutual = {(r["wikidata_id"], r["other_lang"], r["fi_sent"], r["other_sent"]) for r in cur.fetchall()}
    not_mutual = sum((r["wikidata_id"], r["other_lang"], r["fi_sent_no"], r["other_sent_no"]) not in mutual
                     for r in rows)

    models = sorted({r["model"] for r in rows})
    con.begin()
    deleted = 0
    for m in models:
        mt = sorted({r["wikidata_id"] for r in rows if r["model"] == m})
        deleted += cur.execute(f"DELETE FROM pair_judgement WHERE model = %s AND wikidata_id IN ({_in(mt)})",
                               [m, *mt])
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
    cur.executemany(f"INSERT INTO pair_judgement ({', '.join(COLS)}) VALUES ({_in(COLS)})",
                    [tuple(rel if c == "source_file" else r[c] for c in COLS) for r in rows])
    con.commit()
    labels = {l: sum(r["label"] == l for r in rows) for l in sorted(LABELS)}
    print(f"{path.name}: {len(rows):,} judgements, {len(topics)} topic(s), model(s) {', '.join(models)}; "
          f"replaced {deleted:,} old row(s); {not_mutual} pair(s) not a mutual match; labels {labels}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    files = [Path(a).resolve() for a in sys.argv[1:]] or sorted(VERDA.glob("judgements*.parquet"),
                                                                 key=lambda f: f.stat().st_mtime)
    if not files:
        raise SystemExit(f"no judgements*.parquet in {VERDA}")
    con = connect(autocommit=True)
    ensure_table(con.cursor())
    con.autocommit(False)
    for f in files:
        load_file(con, f)
    cur = con.cursor()
    cur.execute("SELECT model, COUNT(*) AS n, COUNT(DISTINCT wikidata_id) AS topics FROM pair_judgement GROUP BY model")
    for r in cur.fetchall():
        print(f"pair_judgement: {r['model']}: {r['n']:,} rows, {r['topics']} topic(s)")
    print(f"done in {time.time() - t0:.1f} s")
    con.close()


if __name__ == "__main__":
    main()
