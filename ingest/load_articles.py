"""Read article revisions from a dataset, one article at a time, oldest revision first.  (owner: P2)

Sources:
  * dataset M of MariaDB/mariadb-wikipedia-datasets: data/m/versions-NN.parquet
    columns page_id, title, rev_id, parent_id, timestamp (UTC), user, anonymous, comment, minor,
    sha1, bytes, text  — every saved version of 19,742 History-of-Finland articles.
  * JSONL: one revision per line with the same field names (timestamp as ISO-8601 UTC).
  * the synthetic demo article (ingest/synthetic.py), no download needed.

    python -m ingest.load_articles --dataset small --list        # which articles, how many versions
    python -m ingest.load_articles --pages 1150 --list
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from common.db import ROOT

DATA = ROOT / "data"
M_DIR = DATA / "m"
LISTS = Path(__file__).resolve().parent / "lists"

# Dataset presets (see docs/decisions.md):
#   demo   — synthetic article, works offline
#   small  — the 50 articles of MariaDB's time-machine demo (incl. Suomen sisällissota, 1150)
#   medium — every article in versions-01..04 of dataset M (~1/4 of M)
#   large  — all of dataset M: 19,742 articles, 862,076 versions
DATASETS = {
    "demo": dict(kind="synthetic"),
    "small": dict(kind="parquet", files=None, pages_from=LISTS / "small.tsv"),
    "medium": dict(kind="parquet", files=[f"versions-{i:02d}.parquet" for i in range(1, 5)]),
    "large": dict(kind="parquet", files=None),
    # the globe: the GEO_TOP (default 300) most-edited articles that have a place (ingest/geo.py)
    "geo": dict(kind="parquet", files=None, pages_from="geo"),
}

FIELDS = ["page_id", "title", "rev_id", "timestamp", "user", "anonymous", "comment", "minor",
          "sha1", "text"]


@dataclass
class Revision:
    rev_id: int
    ts: datetime          # naive UTC
    user: str | None
    anonymous: bool
    comment: str | None
    minor: bool
    sha1: str | None
    text: str | None


@dataclass
class Page:
    page_id: int
    title: str
    revisions: list[Revision] = field(default_factory=list)


def _naive_utc(ts) -> datetime:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _rev(row: dict) -> Revision:
    return Revision(
        rev_id=int(row["rev_id"]), ts=_naive_utc(row["timestamp"]), user=row.get("user"),
        anonymous=bool(row.get("anonymous")), comment=row.get("comment"),
        minor=bool(row.get("minor")), sha1=row.get("sha1"), text=row.get("text"),
    )


def page_list(path: Path) -> set[int]:
    with open(path, encoding="utf-8") as f:
        return {int(r["page_id"]) for r in csv.DictReader(f, delimiter="\t")}


def iter_parquet(paths: Iterable[Path], pages: set[int] | None = None,
                 skip: set[int] | None = None) -> Iterator[Page]:
    """Stream pages from dataset M files. Row groups whose page_id range holds no wanted page
    are skipped using the parquet statistics, so --pages 1150 reads ~2 of 287 row groups."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    skip = skip or set()
    for path in paths:
        f = pq.ParquetFile(path)
        col = f.schema_arrow.get_field_index("page_id")
        current: Page | None = None
        for i in range(f.metadata.num_row_groups):
            st = f.metadata.row_group(i).column(col).statistics
            if pages is not None and st is not None and st.has_min_max:
                if not any(st.min <= p <= st.max for p in pages):
                    if current is not None:
                        yield current
                        current = None
                    continue
            table = f.read_row_group(i, columns=FIELDS)
            if pages is not None:
                table = table.filter(pc.is_in(table.column("page_id"), value_set=_arrow_set(pages)))
            if skip:
                table = table.filter(pc.invert(pc.is_in(table.column("page_id"),
                                                        value_set=_arrow_set(skip))))
            for row in table.to_pylist():
                pid = int(row["page_id"])
                if current is None or current.page_id != pid:
                    if current is not None:
                        yield current
                    current = Page(pid, row["title"])
                current.title = row["title"]          # pages get renamed; keep the latest
                current.revisions.append(_rev(row))
        if current is not None:
            yield current


def _arrow_set(ids: set[int]):
    import pyarrow as pa
    return pa.array(sorted(ids), type=pa.uint32())


def iter_jsonl(path: Path, pages: set[int] | None = None, skip: set[int] | None = None) -> Iterator[Page]:
    by_page: dict[int, Page] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            pid = int(row["page_id"])
            if (pages is not None and pid not in pages) or (skip and pid in skip):
                continue
            page = by_page.setdefault(pid, Page(pid, row["title"]))
            page.title = row["title"]
            page.revisions.append(_rev(row))
    yield from by_page.values()


def iter_pages(dataset: str = "small", pages: set[int] | None = None,
               skip: set[int] | None = None) -> Iterator[Page]:
    """Every page of a dataset preset, or of a .parquet/.jsonl path, revisions sorted by time."""
    for page in _iter_unsorted(dataset, pages, skip):
        page.revisions.sort(key=lambda r: (r.ts, r.rev_id))
        yield page


def _iter_unsorted(dataset, pages, skip):
    if dataset.endswith(".jsonl"):
        yield from iter_jsonl(Path(dataset), pages, skip)
        return
    if dataset.endswith(".parquet"):
        yield from iter_parquet([Path(dataset)], pages, skip)
        return
    if dataset not in DATASETS:
        raise SystemExit(f"Unknown dataset {dataset!r}: use one of {', '.join(DATASETS)} or a path")
    preset = DATASETS[dataset]
    if preset["kind"] == "synthetic":
        from ingest.synthetic import demo_pages
        for p in demo_pages():
            if (pages is None or p.page_id in pages) and not (skip and p.page_id in skip):
                yield p
        return
    if pages is None and preset.get("pages_from") == "geo":
        from ingest.geo import GEO_INDEX, load_index
        index = load_index()
        if not index:
            raise SystemExit(f"No {GEO_INDEX}. Run: python -m ingest.geo")
        top = int(os.environ.get("GEO_TOP", 300))
        pages = {int(r["page_id"]) for r in sorted(index.values(), key=lambda r: -int(r["versions"]))[:top]}
    elif pages is None and preset.get("pages_from"):
        pages = page_list(preset["pages_from"])
    names = preset["files"]
    files = [M_DIR / n for n in names] if names else sorted(M_DIR.glob("versions-*.parquet"))
    missing = [f.name for f in files if not f.exists()]
    if not files or missing:
        raise SystemExit(f"Dataset M files missing in {M_DIR}: {missing or 'all'}. "
                         f"Run: python -m ingest.download {'--all' if not names else ' '.join(n[9:11] for n in names)}")
    yield from iter_parquet(files, pages, skip)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="small")
    ap.add_argument("--pages", help="comma-separated page ids")
    ap.add_argument("--list", action="store_true", help="print each article and its version count")
    a = ap.parse_args()
    wanted = {int(x) for x in a.pages.split(",")} if a.pages else None
    n_pages = n_revs = 0
    for p in iter_pages(a.dataset, wanted):
        n_pages += 1
        n_revs += len(p.revisions)
        if a.list:
            print(f"{p.page_id:>8}  {len(p.revisions):>6} versions  "
                  f"{p.revisions[0].ts:%Y-%m-%d} – {p.revisions[-1].ts:%Y-%m-%d}  {p.title}")
    print(f"{n_pages} articles, {n_revs} versions")
