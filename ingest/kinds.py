"""Which Wikidata kinds count as places on the globe.

A place's kinds are the English labels of ALL its P31 (instance of) values; it is kept when any
label matches a whitelist group. Groups are tried in order, so a place that is both a country
and something else is a country.

    .venv\\Scripts\\python -m ingest.kinds     # show included / excluded kinds for the cached places
"""
import re

# (category, pattern, exclusions). Patterns match one P31 label, case-insensitive, whole words.
GROUPS = [
    ("country", r"^(state|country)$|sovereign state|nation state|historical country|unrecognized state"
                r"|kingdom|empire|^republic$|federal republic|constitutional monarchy|island country"
                r"|landlocked country|mediterranean country|commonwealth realm|dominion|colony"
                r"|grand duchy|principality|country of the kingdom",
     r"republic of|autonomous|state of|state in|federated state|u\.s\. state|constituent country"
     r"|governorate"),
    ("camp",     r"\b(prison camp|prisoner-of-war camp|concentration camp|internment camp"
                 r"|labou?r camp|extermination camp|transit camp|camp)\b",
     r"\b(summer|holiday|training|scout|military camp|base camp|campus)\b"),
    ("battle",   r"\b(battle|siege)\b", None),
    ("treaty",   r"\b(treaty|armistice)\b", None),
    ("fortress", r"\b(fortress|castle|fort|fortification|stronghold|citadel|kremlin|defen[cs]e line)\b",
     None),
    ("settlement", r"\b(municipality|town|city|village|settlement|posyolok|urban area|hamlet|metropolis"
                   r"|megacity|capital|şəhər|comune|commune|borough|market town)\b",
     r"\b(hall|theat(re|er)|fire|library|museum|school|church|old town|gate|wall|district"
     r"|neighbou?rhood|quarter|hotel|station|park|orchestra)\b"),
    ("region",   r"\b(region|provinces?|county|oblast|governorate|län|lands of sweden|territory"
                 r"|territorial entity|isthmus|peninsula|republic of russia|republic of the soviet union"
                 r"|autonomous|federated state|u\.s\. state|state of|state in|constituent country)\b",
     r"\b(organization|organisation|dissolution)\b"),
    ("island",   r"\b(island|archipelago|islet|island group)\b", None),
    ("water",    r"\b(river|lake)\b", None),
]
_compiled = [(c, re.compile(p, re.I), re.compile(x, re.I) if x else None) for c, p, x in GROUPS]


def classify(labels):
    """labels: list of P31 labels -> (category, matched label) or (None, None)."""
    for category, pattern, exclude in _compiled:
        for label in labels:
            if pattern.search(label) and not (exclude and exclude.search(label)):
                return category, label
    return None, None


def is_country(category):
    return category == "country"


if __name__ == "__main__":
    import csv, os, sys
    from collections import Counter, defaultdict
    sys.stdout.reconfigure(encoding="utf-8")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "places.tsv")
    rows = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("lat") and r.get("resolved"):
                rows.setdefault(r["resolved"], r)
    included, excluded = defaultdict(Counter), Counter()
    for r in rows.values():
        labels = (r.get("kinds") or r["kind"] or "").split("|")
        cat, label = classify([l for l in labels if l])
        if cat:
            included[cat][label] += 1
        else:
            excluded[labels[0] or "(no P31)"] += 1
    print(f"{len(rows)} places with coordinates")
    for cat, _, _ in GROUPS:
        c = included[cat]
        print(f"\nINCLUDED {cat}: {sum(c.values())}")
        print("   " + ", ".join(f"{k} {n}" for k, n in c.most_common()))
    print(f"\nEXCLUDED: {sum(excluded.values())} places, {len(excluded)} kinds (first P31 label)")
    print("   " + ", ".join(f"{k} {n}" for k, n in excluded.most_common(60)))
