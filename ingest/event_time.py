"""Bitemporal: when did the events a sentence talks about happen?  (application time)

    python -m ingest.event_time          # fill sentence_event_time for every sentence not yet done

From the years a sentence mentions (no AI needed; Gemma can refine later via source='gemma'):
  "vuonna 1918"                 -> 1918-01-01 .. 1919-01-01
  "6. joulukuuta 1917", "6.12.1917" -> 1917
  "1920-luvulla"                -> 1920 .. 1930 (decade)
  "1800-luvun lopulla"          -> 1800 .. 1900 (century)
  several years                 -> from the earliest to the latest
Counts like "80 000 sotilasta" and "1 424 valkoista" are not years (no 4-digit run).
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date

from common.db import connect

MAX_YEAR = date.today().year
_DECADE = re.compile(r"(?<![\d.,])(1[0-9]{3}|20[0-9]{2})-lu[kv]")         # 1920-luvulla, 1800-luku
_YEAR = re.compile(r"(?<![\d,])(1[0-9]{3}|20[0-9]{2})(?![\d]|\s\d{3}\b|-lu[kv])")


def years(text: str) -> tuple[int, int] | None:
    """(first year, last year inclusive) the sentence talks about, or None."""
    spans: list[tuple[int, int]] = []
    for m in _DECADE.finditer(text):
        y = int(m.group(1))
        spans.append((y, y + 99) if y % 100 == 0 else (y, y + 9) if y % 10 == 0 else (y, y))
    for m in _YEAR.finditer(text):
        y = int(m.group(1))
        spans.append((y, y))
    spans = [(a, min(b, MAX_YEAR)) for a, b in spans if 1000 <= a <= MAX_YEAR]
    if not spans:
        return None
    return min(a for a, _ in spans), max(b for _, b in spans)


def fill(conn=None, batch: int = 5000, quiet: bool = False) -> int:
    """Article by article (index range scans on page_id) — one GROUP BY over every sentence life
    of dataset M spilled a temporary table big enough to fill the disk."""
    own = conn is None
    conn = conn or connect()
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute("SELECT page_id FROM article ORDER BY page_id")
        pages = [r["page_id"] for r in cur.fetchall()]
    checked = found = 0
    seen: set[bytes] = set()
    for k in range(0, len(pages), 200):
        chunk = pages[k:k + 200]
        with conn.cursor() as cur:
            cur.execute("SELECT sent_hash, text FROM article_sentence FOR SYSTEM_TIME ALL "
                        f"WHERE page_id IN ({','.join(str(int(p)) for p in chunk)})")
            rows = []
            for r in cur.fetchall():
                h = r["sent_hash"]
                if h in seen:
                    continue
                seen.add(h)
                checked += 1
                y = years(r["text"])
                if y:
                    rows.append((h, date(y[0], 1, 1), date(y[1] + 1, 1, 1)))
            for i in range(0, len(rows), batch):
                cur.executemany("INSERT IGNORE INTO sentence_event_time (sent_hash, event_from, event_to) "
                                "VALUES (%s, %s, %s)", rows[i:i + batch])
            found += len(rows)
        conn.commit()
        if not quiet and (k // 200) % 20 == 19:
            print(f"  {k + len(chunk):,}/{len(pages):,} articles, {found:,} sentences with a year", flush=True)
    if own:
        conn.close()
    if not quiet:
        print(f"{checked:,} distinct sentences checked, {found:,} mention a year "
              f"-> sentence_event_time ({time.time() - t0:.1f} s)")
    return found


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    fill()
