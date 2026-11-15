"""Load article versions from dataset M (data/m/*.parquet) into the system-versioned `article`
table, with Wikipedia's real edit times.

    .venv\\Scripts\\python -m ingest.load_parquet                     # the 50 dev articles
    .venv\\Scripts\\python -m ingest.load_parquet --list all          # every article in the parquet files

Safe to stop and run again: articles already in the table are skipped.

How a version gets its time (same as reference load.py): with
SET system_versioning_insert_history = 1, MariaDB accepts row_start/row_end from us. Each version
starts when it was saved on Wikipedia and ends when the next one was saved; the newest version is
inserted without row_end, so it stays the current row.

Streaming: each article sits entirely in one parquet file, rows grouped by page_id, oldest first.
We read one row group at a time and write an article when the next page_id begins, so memory
stays small for the full load. Row groups whose page_id range holds no wanted article are skipped.
"""
import argparse, csv, glob, os, sys, time
from datetime import timedelta
import pyarrow as pa
import pyarrow.parquet as pq
from common.db import ROOT, connect

DEFAULT_LIST = os.path.join(ROOT, "reference", "mariadb-system-versioning-wikipedia", "data", "articles.tsv")
BATCH_BYTES = 8_000_000   # rows sent per executemany; MariaDB's packet limit is 16 MB
COLS = ["page_id", "title", "rev_id", "parent_id", "timestamp", "user", "anonymous",
        "comment", "minor", "sha1", "bytes", "text"]
INSERT = """INSERT INTO article (page_id, title, rev_id, parent_id, editor, anonymous, comment,
            minor, sha1, len, content, row_start{}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s{})"""

parser = argparse.ArgumentParser()
parser.add_argument("--list", default=DEFAULT_LIST,
                    help="TSV with page_id,title,why — or 'all' for every article")
parser.add_argument("--data", default=os.path.join(ROOT, "data", "m"))
args = parser.parse_args()

sys.stdout.reconfigure(encoding="utf-8")
con = connect(dict_rows=False)
cur = con.cursor()
cur.execute("SET time_zone = '+00:00'")                  # Wikipedia's times are UTC
cur.execute("SET system_versioning_insert_history = 1")

wanted = None                                            # None = every article
if args.list != "all":
    with open(args.list, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    wanted = {int(r["page_id"]) for r in rows}
    cur.executemany("INSERT IGNORE INTO article_list (page_id, title, why) VALUES (%s, %s, %s)",
                    [(int(r["page_id"]), r["title"], r.get("why")) for r in rows])
    con.commit()
cur.execute("SELECT DISTINCT page_id FROM article FOR SYSTEM_TIME ALL")
loaded = {p for (p,) in cur.fetchall()}
print(f"{'all' if wanted is None else len(wanted)} articles wanted, {len(loaded)} already in the table")


def save(versions):
    """Write all versions of one article: earlier ones as history rows, the last as current."""
    versions.sort(key=lambda v: (v["timestamp"], v["rev_id"]))
    for i in range(1, len(versions)):                    # two edits in the same second:
        if versions[i]["timestamp"] <= versions[i - 1]["timestamp"]:   # keep order, 1 µs apart
            versions[i]["timestamp"] = versions[i - 1]["timestamp"] + timedelta(microseconds=1)
    rows = [(v["page_id"], v["title"], v["rev_id"], v["parent_id"] or None, v["user"],
             bool(v["anonymous"]), v["comment"], bool(v["minor"]), v["sha1"], v["bytes"],
             v["text"] or "", v["timestamp"]) for v in versions]
    history = [r + (versions[i + 1]["timestamp"],) for i, r in enumerate(rows[:-1])]
    batch, size = [], 0
    for row in history + [None]:
        if batch and (row is None or size + len(row[10]) * 2 > BATCH_BYTES):
            cur.executemany(INSERT.format(", row_end", ",%s"), batch)
            batch, size = [], 0
        if row is not None:
            batch.append(row)
            size += len(row[10]) * 2 + 1000              # text dominates; *2 for multi-byte chars
    cur.execute(INSERT.format("", ""), rows[-1])         # current version: no row_end
    con.commit()


def keep(page_id):
    return (wanted is None or page_id in wanted) and page_id not in loaded


def stats_range(meta, rg):
    s = meta.row_group(rg).column(0).statistics           # column 0 = page_id
    return (s.min, s.max) if s is not None and s.has_min_max else (None, None)


t0 = time.time()
total_articles = total_versions = total_bytes = 0
for path in sorted(glob.glob(os.path.join(args.data, "*.parquet"))):
    pf = pq.ParquetFile(path)
    assert pf.schema_arrow.names[0] == "page_id"
    todo = None if wanted is None else sorted(wanted - loaded)
    t_file = time.time()
    articles = n_versions = 0
    current_id, versions = None, []
    for rg in range(pf.metadata.num_row_groups):
        lo, hi = stats_range(pf.metadata, rg)
        if todo is not None and lo is not None and not any(lo <= p <= hi for p in todo):
            continue
        table = pf.read_row_group(rg, columns=COLS)
        # tz-aware UTC -> naive UTC (same instant; avoids needing a tz database on Windows)
        ts = table.column("timestamp").cast(pa.timestamp("us"))
        table = table.set_column(COLS.index("timestamp"), "timestamp", ts)
        for v in table.to_pylist():
            if v["page_id"] != current_id:
                if versions:
                    save(versions)
                    loaded.add(current_id)
                    articles += 1
                    n_versions += len(versions)
                    print(f"  {versions[-1]['title']}: {len(versions)} versions", flush=True)
                current_id, versions = v["page_id"], []
            if keep(v["page_id"]):
                versions.append(v)
                total_bytes += v["bytes"] or 0
    if versions:                                        # the file's last article
        save(versions)
        loaded.add(current_id)
        articles += 1
        n_versions += len(versions)
        print(f"  {versions[-1]['title']}: {len(versions)} versions", flush=True)
    if articles:
        print(f"{os.path.basename(path)}: {articles} articles, {n_versions} versions, "
              f"{time.time() - t_file:.1f} s", flush=True)
    total_articles += articles
    total_versions += n_versions

elapsed = time.time() - t0
cur.execute("SELECT COUNT(DISTINCT page_id), COUNT(*) FROM article FOR SYSTEM_TIME ALL")
in_table, rows_in_table = cur.fetchone()
print(f"Loaded {total_articles} articles, {total_versions} versions, {total_bytes / 1e6:.0f} MB of "
      f"wikitext in {elapsed:.1f} s. Table now: {in_table} articles, {rows_in_table} versions.")
if wanted is not None and wanted - loaded:
    print(f"Not found in parquet: {sorted(wanted - loaded)}", file=sys.stderr)
con.close()
