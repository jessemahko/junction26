"""Wikitext -> readable blocks. Copied from the reference repo
(reference/mariadb-system-versioning-wikipedia/history.py, clean()). Not MediaWiki's parser:
templates, tables and references are dropped, links become plain words, headings and lists kept."""
import re


def _drop_nested(text, start, end):
    out, depth, i = [], 0, 0
    while i < len(text):
        if text.startswith(start, i):
            depth += 1; i += len(start)
        elif depth and text.startswith(end, i):
            depth -= 1; i += len(end)
        else:
            if not depth:
                out.append(text[i])
            i += 1
    return "".join(out)


def clean(wikitext):
    """Wikitext -> a list of (kind, text) blocks: kind is 'h' (heading), 'li' or 'p'."""
    t = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    t = re.sub(r"<ref[^>/]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = _drop_nested(t, "{{", "}}")
    t = _drop_nested(t, "{|", "|}")
    t = re.sub(r"\[\[(?:Tiedosto|Kuva|File|Image|Luokka|Category):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", "", t)
    t = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", t)
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("'''", "").replace("''", "")
    blocks = []
    for line in t.split("\n"):
        line = line.strip()
        if not line:
            continue
        heading = re.match(r"^(=+)\s*(.*?)\s*=+$", line)
        if heading:
            blocks.append(("h", heading.group(2)))
        elif line[0] in "*#":
            blocks.append(("li", line.lstrip("*#: ")))
        elif line[0] not in "|!:;":
            blocks.append(("p", line))
    return blocks
