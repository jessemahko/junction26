"""Revisions of one article -> rows for `article` and `article_sentence` with real edit times.

A sentence's *life* starts in the revision that adds it and ends in the revision that removes
it. If a later revision adds the exact same sentence back, that is a new life (same sent_hash,
new row). This module computes all lives in Python; the loader writes them with
system_versioning_insert_history (bulk) or replays them as ordinary DML (replay).

Blanking vandalism: a revision that wipes most of an article and is then undone would give
*every* sentence a second life and drown the real edit wars. Such revisions are dropped
(counted in BuildResult.dropped) — see `_vandalism`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ingest.load_articles import Page, Revision
from ingest.sentences import sentences

FOREVER = None   # row_end of a current row: let MariaDB fill in "still current"

MASS_REMOVAL = 0.5        # a revision that removes >= 50 % of the sentences …
MIN_SENTENCES = 5         # … of an article with at least this many sentences …
RESTORE = 0.8             # … and is followed by a revision restoring >= 80 % of them …
RESTORE_WITHIN = timedelta(days=7)   # … within a week, is vandalism.


@dataclass
class ParsedRevision:
    rev: Revision
    ts: datetime
    sents: list[tuple[bytes, str]]
    hashes: frozenset


@dataclass
class BuildResult:
    page_id: int
    title: str
    article_rows: list[tuple] = field(default_factory=list)    # history + current
    sentence_rows: list[tuple] = field(default_factory=list)   # history + current
    kept: list[ParsedRevision] = field(default_factory=list)
    rev_ids: list[int] = field(default_factory=list)          # every revision, kept or dropped, in order
    revisions: int = 0
    dropped: int = 0


def parse(page: Page) -> list[ParsedRevision]:
    """Sentences of every revision; identical wikitext (same sha1) is parsed once."""
    cache: dict[str, list] = {}
    out: list[ParsedRevision] = []
    last: datetime | None = None
    for r in page.revisions:
        key = r.sha1 or str(hash(r.text))
        if key not in cache:
            cache[key] = sentences(r.text)
        ts = r.ts
        if last is not None and ts <= last:          # two edits in the same second (or clock
            ts = last + timedelta(microseconds=1)     # skew): keep order, 1 µs apart
        last = ts
        s = cache[key]
        out.append(ParsedRevision(r, ts, s, frozenset(h for h, _ in s)))
    return out


def _vandalism(revs: list[ParsedRevision]) -> set[int]:
    drop: set[int] = set()
    # Rule 1: a span of revisions undone by an exact revert (sha1 seen before, not just before)
    # that contained a mass removal.
    seen: dict[str, int] = {}
    for k, r in enumerate(revs):
        j = seen.get(r.rev.sha1) if r.rev.sha1 else None
        if j is not None and j < k - 1:
            base = revs[j].hashes
            if len(base) >= MIN_SENTENCES and any(
                    len(revs[i].hashes & base) < (1 - MASS_REMOVAL) * len(base) for i in range(j + 1, k)):
                drop.update(range(j + 1, k))
        if r.rev.sha1:
            seen[r.rev.sha1] = k
    # Rule 2: a single mass removal repaired by hand (no exact revert) soon after.
    for i in range(1, len(revs) - 1):
        prev, cur, nxt = revs[i - 1].hashes, revs[i].hashes, revs[i + 1].hashes
        if (len(prev) >= MIN_SENTENCES and len(cur & prev) < (1 - MASS_REMOVAL) * len(prev)
                and len(nxt & prev) >= RESTORE * len(prev)
                and revs[i + 1].ts - revs[i].ts <= RESTORE_WITHIN):
            drop.add(i)
    return drop


def build(page: Page, with_content: bool = False, filter_vandalism: bool = True) -> BuildResult:
    revs = parse(page)
    drop = _vandalism(revs) if filter_vandalism else set()
    kept = [r for i, r in enumerate(revs) if i not in drop]
    res = BuildResult(page.page_id, page.title, revisions=len(revs), dropped=len(drop), kept=kept,
                      rev_ids=[r.rev.rev_id for r in revs])

    # hash -> [position, text, rev_id, editor, anon, prev_hash, start]
    open_lives: dict[bytes, list] = {}
    for n, pr in enumerate(kept):
        r = pr.rev
        # Close lives of sentences this revision removed.
        removed = []
        for h in [h for h in open_lives if h not in pr.hashes]:
            life = open_lives.pop(h)
            res.sentence_rows.append((page.page_id, h, *life, pr.ts))
            removed.append((h, life[1]))
        # Open lives for sentences this revision added (or brought back).
        added = [(pos, h, text) for pos, (h, text) in enumerate(pr.sents) if h not in open_lives]
        prev = match_rewrites(removed, [(h, t) for _, h, t in added]) if removed and n else {}
        for pos, h, text in added:
            open_lives[h] = [pos, text, r.rev_id, r.user, r.anonymous, prev.get(h), pr.ts]
        end = kept[n + 1].ts if n + 1 < len(kept) else FOREVER
        res.article_rows.append((
            page.page_id, page.title, r.rev_id, r.user, r.anonymous, r.comment, r.minor, r.sha1,
            len(pr.sents), b"".join(h for h, _ in pr.sents),
            r.text if with_content else None, pr.ts, end))
    for h, life in open_lives.items():
        res.sentence_rows.append((page.page_id, h, *life, FOREVER))
    # Only the latest wikitext is needed after this (geo); don't ship 100s of MB between processes.
    for pr in kept[:-1]:
        pr.rev.text = None
    return res


_WORD = re.compile(r"\w+")
REWRITE_SIMILARITY = 0.4     # word-set Jaccard: above this, a new sentence is a rewrite of an old one
MAX_PAIRS = 40_000           # skip matching for huge restructurings (cost is added × removed)


def match_rewrites(removed: list[tuple[bytes, str]], added: list[tuple[bytes, str]]) -> dict[bytes, bytes]:
    """For sentences added in a revision, find the sentence (removed in the same revision) each
    one rewrites: greedy best word-overlap match. Returns {added_hash: removed_hash}."""
    if not added or len(removed) * len(added) > MAX_PAIRS:
        return {}
    words_r = [(h, set(_WORD.findall(t.lower()))) for h, t in removed]
    pairs = []
    for ha, ta in added:
        wa = set(_WORD.findall(ta.lower()))
        for hr, wr in words_r:
            union = len(wa | wr)
            if union:
                j = len(wa & wr) / union
                if j >= REWRITE_SIMILARITY:
                    pairs.append((j, ha, hr))
    out, used = {}, set()
    for j, ha, hr in sorted(pairs, key=lambda p: -p[0]):
        if ha not in out and hr not in used:
            out[ha] = hr
            used.add(hr)
    return out
