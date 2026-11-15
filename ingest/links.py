"""Wikilink extraction from wikitext. Shared by places.py (stage 2) and place_links.py (stage 3)."""
import html
import re
from collections import Counter

# [[Target]] or [[Target|label]]. [^\[\]] keeps nested links in image captions
# ([[Tiedosto:x.jpg|... [[Tampere]] ...]]) from swallowing the inner link: the outer one fails
# to match and the inner one matches on its own.
LINK_RE = re.compile(r"\[\[([^\[\]\|\n]+)(?:\|[^\[\]]*)?\]\]")

SKIP_NAMESPACES = {
    "luokka", "category", "tiedosto", "file", "kuva", "image", "media", "wikipedia", "wp",
    "malline", "template", "käyttäjä", "user", "keskustelu", "talk", "ohje", "help", "portaali",
    "portal", "toiminnot", "special", "moduuli", "module", "wikisanakirja", "wikt", "wiktionary",
    "commons", "wikilähteet", "s", "w", "q", "m", "meta", "d", "wikidata",
}
LANG_PREFIX = re.compile(r"^[a-z]{2,3}(-[a-z]+)*$")   # en:, sv:, se:, fiu-vro:, zh-min-nan: ...
BAD_CHARS = re.compile(r"[{}<>\[\]|]")


def normalize(raw):
    """Link text -> page title as MediaWiki would read it, or None when it is not an article link."""
    t = html.unescape(raw).replace("_", " ").replace(" ", " ")
    t = t.split("#", 1)[0]                     # [[Tampere#Historia]] -> Tampere
    t = re.sub(r"\s+", " ", t).strip()
    if t.startswith(":"):                      # [[:Luokka:X]] links to the category page itself
        t = t[1:].strip()
    if not t or BAD_CHARS.search(t) or len(t.encode()) > 255:
        return None
    if ":" in t:
        prefix = t.split(":", 1)[0].strip()
        if prefix.lower() in SKIP_NAMESPACES or LANG_PREFIX.match(prefix):
            return None
    return t[0].upper() + t[1:]


def extract(text):
    """Counter {title: times linked} for one version of an article."""
    out = Counter()
    for m in LINK_RE.finditer(text or ""):
        t = normalize(m.group(1))
        if t:
            out[t] += 1
    return out


if __name__ == "__main__":
    sample = ("[[Tampere]] ja [[tampere|Tampereella]] [[Helsingin_kaupunki#Historia|Hki]] "
              "[[Luokka:Sodat]] [[en:Finnish Civil War]] [[:sv:X]] [[#Taustaa]] "
              "[[Tiedosto:A.jpg|thumb|Kuva [[Viipuri]]sta]] [[Suomen sisällissota|sota]]")
    print(extract(sample))
