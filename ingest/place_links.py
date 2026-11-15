"""Stage 3: build the system-versioned `place_link` table — which article linked which place, when.

    .venv\\Scripts\\python -m ingest.place_links          # the articles in article_list (50 dev articles)
    .venv\\Scripts\\python -m ingest.place_links --all    # every article in the table

Rebuilds place_link from scratch (drop + create from schema.sql) every run.

For each article, its versions are read from `article FOR SYSTEM_TIME ALL` oldest first.
A link row (page_id, to_place) lives from the first version that links the place to the first
later version that doesn't. Written with real Wikipedia times via system_versioning_insert_history:
ended links as history rows, links still in the current version as current rows. A link that
disappears and comes back later is a second history row.

`mentions` = the most times the place was linked in one version during that row's lifetime.
(A new row per mention-count change would make "added that year" count those changes as new links.)

Noise filter: a version is skipped when a revert undoes it within 48 h. A revert is version j whose
sha1 equals an earlier version k other than j-1; versions k+1 .. j-1 are what it undid. If
time(j) - time(k+1) <= 48 h they are all skipped (vandalism + cleanup); slower reverts are kept,
because those are real disputes worth seeing. Skipped versions are logged to data/noise_skipped.tsv.

Only links to places with a whitelisted category count (place.category <> 'own_location').
Link text is mapped to places via data/places.tsv, so "Helsingin kaupunki" counts as Helsinki.
"""
import argparse, csv, os, re, time
from collections import Counter, defaultdict
from datetime import timedelta
import sys
from common.db import ROOT, connect
from ingest.links import extract

WINDOW = timedelta(hours=48)
BATCH_ROWS = 5000
SKIP_LOG = os.path.join(ROOT, "data", "noise_skipped.tsv")

parser = argparse.ArgumentParser()
parser.add_argument("--all", action="store_true")
args = parser.parse_args()

t_start = time.time()
sys.stdout.reconfigure(encoding="utf-8")
con = connect(dict_rows=False)
cur = con.cursor()

# --- places and the link-text -> place mapping
cur.execute("SELECT title FROM place WHERE category <> 'own_location'")
place_set = {t for (t,) in cur.fetchall()}
to_place = {}
with open(os.path.join(ROOT, "data", "places.tsv"), encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f, delimiter="\t"):
        if r.get("resolved") in place_set:
            to_place[r["title"]] = r["resolved"]
print(f"{len(place_set)} places, {len(to_place)} link texts map to them")

# --- recreate place_link (DELETE would leave the history rows behind)
schema = re.sub(r"--[^\n]*", "", open(os.path.join(ROOT, "db", "schema.sql"), encoding="utf-8").read())
create = next(s for s in schema.split(";") if "TABLE IF NOT EXISTS place_link" in s)
cur.execute("DROP TABLE IF EXISTS place_link")
cur.execute(create)
cur.execute("SET system_versioning_insert_history = 1")

scope = "" if args.all else " WHERE page_id IN (SELECT page_id FROM article_list)"
cur.execute("SELECT page_id, title FROM article" + scope + " ORDER BY page_id")
pages = cur.fetchall()

HIST = "INSERT INTO place_link (page_id, to_place, mentions, row_start, row_end) VALUES (%s,%s,%s,%s,%s)"
CURR = "INSERT INTO place_link (page_id, to_place, mentions, row_start) VALUES (%s,%s,%s,%s)"
hist_rows, curr_rows = [], []


def flush(force=False):
    global hist_rows, curr_rows
    if hist_rows and (force or len(hist_rows) >= BATCH_ROWS):
        cur.executemany(HIST, hist_rows)
        hist_rows = []
    if curr_rows and (force or len(curr_rows) >= BATCH_ROWS):
        cur.executemany(CURR, curr_rows)
        curr_rows = []


def noise_versions(versions):
    """Indexes of versions undone by a revert within 48 h, and the number of reverts seen."""
    skip, reverts, last_seen = set(), 0, {}
    for j, v in enumerate(versions):
        k = last_seen.get(v["sha1"]) if v["sha1"] else None
        if k is not None and k < j - 1:                  # j restores version k
            reverts += 1
            if v["time"] - versions[k + 1]["time"] <= WINDOW:
                skip.update(range(k + 1, j))
        if v["sha1"]:
            last_seen[v["sha1"]] = j
    return skip, reverts


total_versions = total_skipped = total_reverts = 0
skip_log = open(SKIP_LOG, "w", encoding="utf-8", newline="")
skip_log.write("page_id\trev_id\ttime\n")
read = con.cursor()
for page_id, title in pages:
    read.execute("""SELECT rev_id, sha1, row_start, row_end > NOW(), row_end, content
                    FROM article FOR SYSTEM_TIME ALL WHERE page_id = %s ORDER BY row_start""",
                 (page_id,))
    versions = [{"rev": r, "sha1": s, "time": t, "current": bool(c), "end": e, "text": x}
                for r, s, t, c, e, x in read.fetchall()]
    skip, reverts = noise_versions(versions)
    total_versions += len(versions)
    total_skipped += len(skip)
    total_reverts += reverts
    for i in sorted(skip):
        skip_log.write(f"{page_id}\t{versions[i]['rev']}\t{versions[i]['time']}\n")

    open_links = {}                                       # place -> [start, max mentions]
    for i, v in enumerate(versions):
        if i in skip:
            continue
        links = Counter()
        for t, n in extract(v["text"]).items():
            p = to_place.get(t)
            if p:
                links[p] += n
        for p in [p for p in open_links if p not in links]:   # link removed in this version
            start, mentions = open_links.pop(p)
            hist_rows.append((page_id, p, mentions, start, v["time"]))
        for p, n in links.items():
            if p in open_links:
                open_links[p][1] = max(open_links[p][1], min(n, 65535))
            else:
                open_links[p] = [v["time"], min(n, 65535)]
    last = versions[-1]
    for p, (start, mentions) in open_links.items():
        if last["current"]:
            curr_rows.append((page_id, p, mentions, start))
        else:                                             # article no longer current: close it
            hist_rows.append((page_id, p, mentions, start, last["end"]))
    flush()
flush(force=True)
con.commit()
skip_log.close()
t_build = time.time() - t_start

# --- report, using the SVT queries the API will use
cur.execute("SELECT COUNT(*) FROM place_link FOR SYSTEM_TIME ALL")
rows_all = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM place_link")
rows_now = cur.fetchone()[0]
print(f"\n{len(pages)} articles, {total_versions} versions, {total_reverts} reverts detected; "
      f"noise filter skipped {total_skipped} versions ({100 * total_skipped / total_versions:.1f} %)")
print(f"place_link: {rows_all} rows in all (history + current), {rows_now} current. "
      f"Built in {t_build:.0f} s")

cur.execute("""SELECT YEAR(row_start) y, COUNT(*) FROM place_link FOR SYSTEM_TIME ALL GROUP BY y""")
added = dict(cur.fetchall())
cur.execute("""SELECT YEAR(row_end) y, COUNT(*) FROM place_link FOR SYSTEM_TIME ALL
               WHERE row_end < NOW() GROUP BY y""")
removed = dict(cur.fetchall())
# Links added by an article's very first version are "the article was created", not a change.
cur.execute("""SELECT YEAR(l.row_start) y, COUNT(*) FROM place_link FOR SYSTEM_TIME ALL l
               JOIN (SELECT page_id, MIN(row_start) first FROM article FOR SYSTEM_TIME ALL"""
            + scope + """ GROUP BY page_id) f
                 ON f.page_id = l.page_id AND l.row_start = f.first GROUP BY y""")
created = dict(cur.fetchall())
print("\nyear   added (of which: new article)   removed")
for y in sorted(set(added) | set(removed)):
    print(f"{y}   {added.get(y, 0):6} ({created.get(y, 0):5})   {removed.get(y, 0):6}")

print("\nSuomen sisällissota (page 1150): places linked, AS OF")
prev = set()
for d in ["2005-01-01", "2010-01-01", "2018-01-01", None]:
    when = f"TIMESTAMP'{d} 00:00:00'" if d else "NOW()"
    cur.execute(f"""SELECT to_place, mentions FROM place_link FOR SYSTEM_TIME AS OF {when}
                    WHERE page_id = 1150 ORDER BY mentions DESC, to_place""")
    rows = cur.fetchall()
    now_set = {p for p, _ in rows}
    print(f"\n  {d or 'now'}: {len(rows)} places")
    print("    " + ", ".join(f"{p} ({m})" for p, m in rows))
    if prev:
        print(f"    + added since: {', '.join(sorted(now_set - prev)) or '-'}")
        print(f"    - removed since: {', '.join(sorted(prev - now_set)) or '-'}")
    prev = now_set
print(f"\nTotal {time.time() - t_start:.0f} s")
con.close()
