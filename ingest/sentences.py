"""Wikitext -> clean text -> Finnish sentences -> normalised SHA-256 hashes.  (owner: P2)

Not MediaWiki's parser: templates, tables, references, files and categories are dropped, links
become their visible words. Good enough to compare sentences across revisions, and fast enough
for every revision of dataset M (pure regex, no dependencies).

    python -m ingest.sentences < some.wikitext      # spot-check the splitter
"""
from __future__ import annotations

import hashlib
import html
import re
import sys
import unicodedata

# --- wikitext cleaning -------------------------------------------------------------------------

_DROP_BLOCKS = re.compile(
    r"<!--.*?-->"
    r"|<ref[^>/]*/>"
    r"|<ref[^>]*>.*?</ref>"
    r"|<(gallery|math|timeline|imagemap|syntaxhighlight|source|score|graph|mapframe|templatedata)[^>]*>.*?</\1>"
    r"|__[A-ZÄÖ]+__",
    re.S | re.I,
)
_TAGS = re.compile(r"</?[a-zA-Z][^>]*>")
_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_EXTLINK = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")
_DROP_NS = re.compile(
    r"^\s*:?\s*(tiedosto|file|kuva|image|media|luokka|category|[a-z]{2,3}(-[a-z]+)?)\s*:", re.I
)
_HEADING = re.compile(r"^=+.*=+\s*$")
_EMPH = re.compile(r"'{2,}")
_REDIRECT = re.compile(r"^\s*#(ohjaus|redirect)", re.I)


_DELIMS: dict[tuple[str, str], re.Pattern] = {}


def _drop_nested(text: str, start: str, end: str) -> str:
    """Remove (possibly nested) start…end blocks. Jumps from delimiter to delimiter."""
    pat = _DELIMS.get((start, end))
    if pat is None:
        pat = _DELIMS[(start, end)] = re.compile(f"{re.escape(start)}|{re.escape(end)}")
    out, depth, keep_from = [], 0, 0
    for m in pat.finditer(text):
        if m.group() == start:
            if depth == 0:
                out.append(text[keep_from:m.start()])
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                keep_from = m.end()
    if depth == 0:
        out.append(text[keep_from:])
    return "".join(out)


def _link(m: re.Match) -> str:
    inner = m.group(1)
    if _DROP_NS.match(inner):
        # Files, categories, interwiki links: dropped. Note: 'fi:', 'en:' etc. are interwiki,
        # but so would be a 2-3 letter namespace; that is acceptable for comparison purposes.
        return ""
    return inner.split("|")[-1]


def clean_wikitext(text: str | None) -> str:
    if not text or _REDIRECT.match(text):
        return ""
    text = _DROP_BLOCKS.sub("", text)
    if "{{" in text:
        text = _drop_nested(text, "{{", "}}")
    if "{|" in text:
        text = _drop_nested(text, "{|", "|}")
    # Links, innermost first, so a file caption's inner links go before the file itself.
    for _ in range(5):
        new = _LINK.sub(_link, text)
        if new == text:
            break
        text = new
    text = _EXTLINK.sub(lambda m: m.group(1) or "", text)
    text = _TAGS.sub("", text)
    text = _EMPH.sub("", text)
    text = html.unescape(text)
    lines = []
    for line in text.split("\n"):
        s = line.strip()
        if not s or _HEADING.match(s) or s[0] in "|!{}":
            lines.append("")         # paragraph boundary
            continue
        s = s.lstrip("*#:; ").strip()
        lines.append(s)
    return "\n".join(lines)


# --- sentence splitting (Finnish) --------------------------------------------------------------

# Abbreviations that end in a period but do not end a sentence (lowercase, without the dot).
ABBREV = {
    "esim", "n", "ns", "mm", "yms", "jne", "ym", "tms", "vrt", "ks", "prof", "tri", "kpl", "klo",
    "nk", "os", "ent", "eaa", "jaa", "eKr", "jKr", "ekr", "jkr", "engl", "ruots", "lat", "saks",
    "ven", "ransk", "kreik", "tod", "kok", "so", "yl", "s", "v", "vv", "ap", "ip", "vt", "evl",
    "kenr", "ev", "kapt", "luutn", "maj", "res", "puh", "lk", "nro", "st", "pv", "tammik", "helmik", "maalisk", "huhtik", "toukok",
    "kesäk", "heinäk", "elok", "syysk", "lokak", "marrask", "jouluk", "suom", "alk", "ed",
    "toim", "jäs", "pj", "vpj", "kirj", "ts", "ns", "em", "mt", "ym", "dr", "mr",
    "e", "j", "k", "m", "t", "vs", "etc", "ca", "vol", "ibid",
}

# Candidate boundary: . ! or ? (possibly followed by closing quotes/brackets), whitespace, then
# something that can start a sentence.
_BOUNDARY = re.compile(r"([.!?]+[\"'”’)\]]*)\s+(?=[\"'“”„«(\[]?[A-ZÅÄÖÜ0-9])")


def split_sentences(paragraph: str) -> list[str]:
    out, start = [], 0
    for m in _BOUNDARY.finditer(paragraph):
        end = m.end(1)
        tail = paragraph[max(start, m.start(1) - 40):m.start(1)].split()
        token = tail[-1].lstrip("(\"'“„«") if tail else ""
        if m.group(1).startswith("."):
            if token.lower() in ABBREV or token in ABBREV:
                continue
            if len(token) == 1 and token.isalpha() and token.isupper():   # initials: K. J. Ståhlberg
                continue
            if re.fullmatch(r"[IVXLC]+", token) and len(token) <= 4 and token != "I":   # Kaarle XII.
                continue
        out.append(paragraph[start:end])
        start = m.end()
    out.append(paragraph[start:])
    return [s.strip() for s in out if s.strip()]


# --- normalisation + hashing -------------------------------------------------------------------

_QUOTES = str.maketrans({"”": '"', "“": '"', "„": '"', "«": '"', "»": '"',
                         "’": "'", "‘": "'", "´": "'", " ": " ", " ": " ", " ": " ", "­": ""})
_WS = re.compile(r"\s+")
_SPACE_PUNCT = re.compile(r"\s+([,.;:!?)])")
_HAS_LETTERS = re.compile(r"[A-Za-zÅÄÖåäö]{2}")

MAX_SENTENCE = 2000


def normalise(sentence: str) -> str:
    s = unicodedata.normalize("NFC", sentence).translate(_QUOTES)
    s = _WS.sub(" ", s).strip()
    s = _SPACE_PUNCT.sub(r"\1", s)
    return s[:MAX_SENTENCE]


def sent_hash(normalised: str) -> bytes:
    return hashlib.sha256(normalised.encode("utf-8")).digest()


def sentences(wikitext: str | None) -> list[tuple[bytes, str]]:
    """Distinct sentences of one revision, in order: [(sha256, normalised text), …].
    A sentence repeated within the revision is kept once (first occurrence)."""
    seen: set[bytes] = set()
    out: list[tuple[bytes, str]] = []
    for paragraph in clean_wikitext(wikitext).split("\n"):
        if not paragraph:
            continue
        for h, s in _paragraph(paragraph):
            if h not in seen:
                seen.add(h)
                out.append((h, s))
    return out


def text_sentences(text: str | None) -> list[tuple[bytes, str]]:
    """Like sentences(), for dataset S's plain text (Markdown-like, not wikitext): drops `#` headings
    and `|` table rows, strips `- ` / `* ` list markers, then splits and filters exactly as
    sentences() does. sent_no = the index in this list. Shared contract: docs/contracts.md (a)."""
    seen: set[bytes] = set()
    out: list[tuple[bytes, str]] = []
    for line in (text or "").split("\n"):
        s = line.strip()
        if not s or s[0] in "#|":
            continue
        s = s.lstrip("-*•:; ").strip()
        for h, sent in _paragraph(s):
            if h not in seen:
                seen.add(h)
                out.append((h, sent))
    return out


# Consecutive revisions share almost all paragraphs: cache the split per paragraph.
_PARA_CACHE: dict[str, list[tuple[bytes, str]]] = {}
_PARA_CACHE_MAX = 200_000


def _paragraph(paragraph: str) -> list[tuple[bytes, str]]:
    hit = _PARA_CACHE.get(paragraph)
    if hit is not None:
        return hit
    out = []
    for raw in split_sentences(paragraph):
        s = normalise(raw)
        if len(s) >= 8 and s.count(" ") >= 2 and _HAS_LETTERS.search(s):   # >= 3 words
            out.append((sent_hash(s), s))
    if len(_PARA_CACHE) >= _PARA_CACHE_MAX:
        _PARA_CACHE.clear()
    _PARA_CACHE[paragraph] = out
    return out

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for i, (h, s) in enumerate(sentences(sys.stdin.buffer.read().decode("utf-8"))):
        print(f"{i:4d} {h.hex()[:10]}  {s}")
