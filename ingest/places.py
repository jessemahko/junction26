"""Stage 2: find every wikilink target in every stored version, look the targets up on
Wikidata, and fill `place` (targets with coordinates) and `page_place` (each article's own location).

    .venv\\Scripts\\python -m ingest.places          # the articles in article_list (the 50 dev ones)
    .venv\\Scripts\\python -m ingest.places --all    # every article in the table (stage 6)

Lookups are cached in data/places.tsv, so each title goes to the APIs only once; reruns are cheap.

How a title becomes a place (two API steps, both 50 titles/ids per request, made one at a time):
  1. fi.wikipedia.org action=query&redirects=1&prop=pageprops: follows redirects and
     normalisation ("Helsingin kaupunki" -> "Helsinki") and gives the Wikidata id. Wikidata's own
     wbgetentities&sites=fiwiki&redirects=yes reported redirect titles as missing, so it is not used
     for this step.
  2. wikidata.org wbgetentities&ids=...&props=claims: P625 (coordinates, Earth only),
     P31 (instance of, as English labels) and P276 (location, for page_place).

places.tsv columns: title (as linked), resolved (fi.wikipedia title after redirects), qid, lat,
lon, kind (first P31 label), kinds (all P31 labels, |-separated), p276. Empty qid = no page or no
Wikidata item; empty lat = no coordinates.

Resumable: titles already in places.tsv are skipped and results are appended every 250 titles,
so a killed run loses at most one chunk. Rerun the same command to continue.

`place` gets only places whose kinds pass the whitelist in kinds.py (category, is_country), plus
the articles' own locations (category 'own_location' when not whitelisted).
"""
import csv, gzip, io, json, os, time, urllib.parse, urllib.request
from collections import defaultdict
import sys
import pymysql.cursors
from common.db import ROOT, connect
from ingest.links import extract
from ingest.kinds import classify, is_country
from ingest.labels_en import load_labels

CACHE = os.path.join(ROOT, "data", "places.tsv")
FIELDS = ["title", "resolved", "qid", "lat", "lon", "kind", "kinds", "p276"]
USER_AGENT = ("RewrittenJunction2026/0.1 (Junction 2026 hackathon: map of how Finnish Wikipedia "
              "wrote Finland's history; https://github.com/JUSSI-G/Junction26)")
EARTH = "http://www.wikidata.org/entity/Q2"
requests_made = 0


def api(url, params):
    """GET a MediaWiki API with retries and maxlag; returns parsed JSON."""
    global requests_made
    # maxlag=30: back off when Wikimedia's servers are badly lagged. 5 (the bot-edit convention)
    # kept us waiting indefinitely on a steady ~11 s reported lag; these are read-only requests.
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "30"}
    body = urllib.parse.urlencode(params).encode()
    for attempt in range(20):                            # up to ~15 min of backoff in total
        try:
            req = urllib.request.Request(url, data=body, headers={
                "User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                retry_after = r.headers.get("Retry-After")
            requests_made += 1
            data = json.loads(raw)
            if data.get("error", {}).get("code") == "maxlag":
                # Servers are lagging: wait as asked (Retry-After), longer each time.
                wait = min(60, max(int(retry_after or 5), 5 * (attempt + 1)))
                print(f"  maxlag ({data['error'].get('lag', '?')} s lag), waiting {wait} s",
                      flush=True)
                time.sleep(wait)
                continue
            if "error" in data:
                raise RuntimeError(data["error"])
            return data
        except (OSError, ValueError) as e:              # network error or bad JSON: back off
            print(f"  retry {attempt + 1}: {e}", flush=True)
            time.sleep(min(60, 3 * (attempt + 1)))
    raise RuntimeError(f"API failed: {url} {params.get('titles') or params.get('ids')}")


def resolve_titles(titles):
    """{title: (resolved title, qid)} via fi.wikipedia, following normalisation and redirects."""
    data = api("https://fi.wikipedia.org/w/api.php", {
        "action": "query", "titles": "|".join(titles), "redirects": "1",
        "prop": "pageprops", "ppprop": "wikibase_item"})["query"]
    step = {}
    for key in ("normalized", "redirects"):
        for m in data.get(key, []):
            step[m["from"]] = m["to"]
    pages = {p["title"]: p for p in data.get("pages", [])}
    out = {}
    for t in titles:
        r, seen = t, set()
        while r in step and r not in seen:              # normalised -> redirect (-> redirect)
            seen.add(r)
            r = step[r]
        p = pages.get(r)
        if p is None or p.get("missing") or p.get("invalid"):
            out[t] = ("", "")
        else:
            out[t] = (p["title"], p.get("pageprops", {}).get("wikibase_item", ""))
    return out


def first_value(claims, pid):
    for s in claims.get(pid, []):
        v = s.get("mainsnak", {}).get("datavalue", {}).get("value")
        if v is not None:
            return v
    return None


def entities(qids, sitelinks=False):
    """{qid: {lat, lon, p31, p276, fititle}} from wbgetentities."""
    params = {"action": "wbgetentities", "ids": "|".join(qids), "props": "claims"}
    if sitelinks:
        params.update(props="claims|sitelinks", sitefilter="fiwiki")
    out = {}
    for q, e in api("https://www.wikidata.org/w/api.php", params)["entities"].items():
        claims = e.get("claims", {})
        coord = first_value(claims, "P625")
        if coord and coord.get("globe", EARTH) != EARTH:
            coord = None                                 # coordinates on the Moon etc.
        p276 = first_value(claims, "P276")
        p31s = [s["mainsnak"]["datavalue"]["value"]["id"] for s in claims.get("P31", [])
                if isinstance(s.get("mainsnak", {}).get("datavalue", {}).get("value"), dict)]
        out[q] = {"lat": coord["latitude"] if coord else None,
                  "lon": coord["longitude"] if coord else None,
                  "p31": p31s[0] if p31s else None,
                  "p31s": p31s,
                  "p276": p276["id"] if isinstance(p276, dict) else None,
                  "fititle": e.get("sitelinks", {}).get("fiwiki", {}).get("title")}
    return out


def labels(qids):
    data = api("https://www.wikidata.org/w/api.php", {
        "action": "wbgetentities", "ids": "|".join(qids), "props": "labels", "languages": "en|fi"})
    return {q: (e.get("labels", {}).get("en") or e.get("labels", {}).get("fi") or {}).get("value", q)
            for q, e in data["entities"].items()}


def chunks(items, n=50):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def load_cache():
    """Read places.tsv. A half-written last line (run killed mid-write) is dropped: those titles
    are simply looked up again."""
    if not os.path.exists(CACHE):
        return {}
    with open(CACHE, encoding="utf-8", newline="") as f:
        content = f.read()
    if not content.endswith("\n"):                      # killed mid-write: drop the partial line
        content = content[:content.rfind("\n") + 1]
        if not args.no_lookup:                          # read-only mode never writes the cache
            with open(CACHE, "w", encoding="utf-8", newline="") as f:
                f.write(content)
    reader = csv.DictReader(io.StringIO(content, newline=""), delimiter="\t")
    old_format = "kinds" not in reader.fieldnames
    if old_format and args.no_lookup:
        raise SystemExit("places.tsv has no kinds column; run once without --no-lookup")
    rows = {r["title"]: r for r in reader if r.get("p276") is not None}
    if old_format:                                      # cache from before the kinds column
        backfill_kinds(rows)
    return rows


def backfill_kinds(rows):
    """One-off migration: fetch all P31 labels for cached places with coordinates, rewrite file."""
    need = [r for r in rows.values() if r["lat"]]
    print(f"Backfilling all P31 kinds for {len(need)} cached places", flush=True)
    info = {}
    for c in chunks(sorted({r["qid"] for r in need})):
        info.update(entities(c))
    fetch_labels({p for i in info.values() for p in i["p31s"]})
    for r in rows.values():
        r["kinds"] = "|".join(kind_label.get(p, p) for p in info.get(r["qid"], {}).get("p31s", [])) \
            if r["lat"] else ""
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows.values())
    os.replace(tmp, CACHE)


def fetch_labels(qids):
    for c in chunks(sorted(set(qids) - kind_label.keys())):
        kind_label.update(labels(c))


def append_cache(rows):
    new = not os.path.exists(CACHE)
    with open(CACHE, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, delimiter="\t", lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)


kind_label = {}


def lookup(titles, cache):
    """Look up every title not in the cache; append results to places.tsv in chunks of 250."""
    todo = sorted(t for t in titles if t not in cache)
    print(f"{len(titles)} titles, {len(titles) - len(todo)} cached, {len(todo)} to look up", flush=True)
    t0 = time.time()
    for n, part in enumerate(chunks(todo, 250)):
        resolved = {}
        for c in chunks(part):
            resolved.update(resolve_titles(c))
        qids = sorted({q for _, q in resolved.values() if q})
        info = {}
        for c in chunks(qids):
            info.update(entities(c))
        fetch_labels({p for i in info.values() if i["lat"] is not None for p in i["p31s"]})
        rows = []
        for t in part:
            r, q = resolved[t]
            i = info.get(q, {})
            has = i.get("lat") is not None
            rows.append({"title": t, "resolved": r, "qid": q,
                         "lat": i["lat"] if has else "", "lon": i["lon"] if has else "",
                         "kind": kind_label.get(i.get("p31"), "") if has else "",
                         "kinds": "|".join(kind_label.get(p, p) for p in i["p31s"]) if has else "",
                         "p276": i.get("p276") or ""})
        append_cache(rows)
        cache.update({r["title"]: r for r in rows})
        done = min((n + 1) * 250, len(todo))
        print(f"  {done}/{len(todo)} looked up, {requests_made} requests, {time.time() - t0:.0f} s",
              flush=True)


# ---------------------------------------------------------------- 1. extract link targets
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--all", action="store_true",
                    help="every article in the table (default: only those in article_list)")
parser.add_argument("--no-lookup", action="store_true",
                    help="read places.tsv only (never call the APIs or write the cache); refill "
                         "place/page_place, e.g. after changing kinds.py while another run appends")
args = parser.parse_args()
SCOPE = "" if args.all else " WHERE page_id IN (SELECT page_id FROM article_list)"

t_start = time.time()
sys.stdout.reconfigure(encoding="utf-8")
con = connect(dict_rows=False)
cur = con.cursor()
cur.execute("SELECT page_id, title FROM article" + SCOPE)              # current titles
article_title = dict(cur.fetchall())

ever = defaultdict(set)     # target -> pages that linked it in any version
now = defaultdict(set)      # target -> pages that link it in the current version
versions = 0
read = con.cursor(pymysql.cursors.SSCursor)      # streamed: 12 GB of text does not fit in memory
read.execute("SELECT page_id, row_end > NOW(), content FROM article FOR SYSTEM_TIME ALL" + SCOPE)
for page_id, is_current, text in read:
    versions += 1
    for t in extract(text):
        ever[t].add(page_id)
        if is_current:
            now[t].add(page_id)
read.close()
t_extract = time.time() - t_start
print(f"Extracted {len(ever)} distinct link targets from {versions} versions in {t_extract:.0f} s",
      flush=True)

# ---------------------------------------------------------------- 2. Wikidata lookups
cache = load_cache()
t0 = time.time()
if args.no_lookup:
    missing = (set(ever) | set(article_title.values())) - cache.keys()
    print(f"--no-lookup: {len(missing)} titles not in the cache are treated as non-places")
    for t in missing:
        cache[t] = {"title": t, "resolved": "", "qid": "", "lat": "", "lon": "", "kind": "",
                    "kinds": "", "p276": ""}
else:
    lookup(set(ever) | set(article_title.values()), cache)
t_lookup = time.time() - t0

# ---------------------------------------------------------------- 3. each article's own location
own, method = {}, {}
need_p276 = {}
for page_id, title in article_title.items():
    r = cache[title]
    if r["lat"]:
        own[page_id], method[page_id] = r["resolved"], "P625"
    elif r["p276"]:
        need_p276[page_id] = r["p276"]
loc_info = {}
by_qid = {r["qid"]: r for r in cache.values() if r["qid"] and r["lat"] and r["resolved"]}
for q in set(need_p276.values()) & by_qid.keys():       # location already cached: no request
    r = by_qid[q]
    loc_info[q] = {"lat": float(r["lat"]), "lon": float(r["lon"]), "fititle": r["resolved"]}
if not args.no_lookup:
    for c in chunks(sorted(set(need_p276.values()) - loc_info.keys())):
        loc_info.update(entities(c, sitelinks=True))
extra_rows = []
for page_id, q in need_p276.items():
    i = loc_info.get(q, {})
    if i.get("lat") is None or not i.get("fititle"):
        method[page_id] = f"P276 {q} without coordinates or fi article"
        continue
    t = i["fititle"]
    if t not in cache and q in by_qid:                  # cached under a redirect title
        cache[t] = by_qid[q]
    if t not in cache:                                  # location not linked anywhere: cache it
        fetch_labels(i["p31s"])
        row = {"title": t, "resolved": t, "qid": q, "lat": i["lat"], "lon": i["lon"],
               "kind": kind_label.get(i["p31"], "") if i["p31"] else "",
               "kinds": "|".join(kind_label.get(p, p) for p in i["p31s"]), "p276": ""}
        extra_rows.append(row)
        cache[t] = row
    own[page_id], method[page_id] = cache[t]["resolved"], "P276"
if extra_rows and not args.no_lookup:
    append_cache(extra_rows)

# ---------------------------------------------------------------- 4. fill place and page_place
coords = {}                                             # resolved title -> row, any kind
for t in set(ever) | set(own.values()):
    r = cache.get(t)
    if r and r["lat"]:
        coords.setdefault(r["resolved"], r)
places, excluded = {}, defaultdict(int)                 # resolved title -> (row, category, kind)
own_titles = set(own.values())
for t, r in coords.items():
    category, label = classify([k for k in (r["kinds"] or r["kind"] or "").split("|") if k])
    if category:
        places[t] = (r, category, label)
    elif t in own_titles:                               # e.g. Turun palo, Isoviha: keep as origin
        places[t] = (r, "own_location", r["kind"])
    else:
        excluded[r["kind"] or "(no P31)"] += 1
cur.execute("DELETE FROM place")
en = load_labels()                                      # data/place_labels.tsv, from labels_en.py
cur.executemany("INSERT INTO place (title, en_label, qid, lat, lon, kind, category, is_country) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [(t, en.get(r["qid"], "")[:255] or None, r["qid"], float(r["lat"]), float(r["lon"]),
                  (kind or "")[:50] or None, category, is_country(category))
                 for t, (r, category, kind) in places.items()])
cur.execute("DELETE FROM page_place")
cur.executemany("INSERT INTO page_place (page_id, place_title) VALUES (%s, %s)", list(own.items()))
con.commit()

# ---------------------------------------------------------------- 5. report
with_page = sum(1 for t in ever if cache[t]["resolved"])
with_item = sum(1 for t in ever if cache[t]["qid"])
with_coord = sum(1 for t in ever if cache[t]["lat"])
print(f"\nLink targets: {len(ever)} distinct; {with_page} are existing fi.wikipedia pages, "
      f"{with_item} have a Wikidata item, {with_coord} have coordinates "
      f"-> {len(coords)} distinct after merging redirects.")
by_cat = defaultdict(int)
for _, category, _ in places.values():
    by_cat[category] += 1
print(f"Kind whitelist: {len(places)} kept in `place` "
      f"({', '.join(f'{c} {n}' for c, n in sorted(by_cat.items(), key=lambda x: -x[1]))}), "
      f"{sum(excluded.values())} excluded.")
print(f"Lookups took {t_lookup:.0f} s, {requests_made} API requests.")

by_method = defaultdict(list)
for page_id in article_title:
    by_method[method.get(page_id, "none")].append(article_title[page_id])
print(f"\nOwn location for {len(own)} of {len(article_title)} articles:")
for m, titles in sorted(by_method.items(), key=lambda x: -len(x[1])):
    print(f"  {m}: {len(titles)}")
for page_id, p in sorted(own.items(), key=lambda x: article_title[x[0]]):
    print(f"    {article_title[page_id]} -> {p} ({method[page_id]})")

linking_ever, linking_now = defaultdict(set), defaultdict(set)
for t, pages in ever.items():
    if cache[t]["lat"] and cache[t]["resolved"] in places \
            and places[cache[t]["resolved"]][1] != "own_location":
        linking_ever[cache[t]["resolved"]] |= pages
        linking_now[cache[t]["resolved"]] |= now.get(t, set())
print("\nTop 30 places by number of linking articles (ever / in current versions):")
top = sorted(linking_ever, key=lambda p: (-len(linking_ever[p]), -len(linking_now[p]), p))[:30]
for rank, p in enumerate(top, 1):
    print(f"  {rank:2}. {p:<32} {len(linking_ever[p]):3} / {len(linking_now[p]):3}   "
          f"{places[p][1]}: {places[p][2]}")
print(f"\nTotal {time.time() - t_start:.0f} s")
con.close()
