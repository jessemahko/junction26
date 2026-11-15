r"""English Wikidata labels for the places in `place` (shown next to the Finnish names).

    .venv\Scripts\python -m ingest.labels_en

Fetches wbgetentities&props=labels&languages=en, 50 ids per request, once per QID: results are
cached in data/place_labels.tsv (qid, en_label). Then fills place.en_label. Safe to rerun; run it
after places.py (which also fills en_label from the cache when the file exists).
"""
import csv, gzip, json, os, time, urllib.parse, urllib.request
from common.db import ROOT, connect

CACHE = os.path.join(ROOT, "data", "place_labels.tsv")
USER_AGENT = ("RewrittenJunction2026/0.1 (Junction 2026 hackathon: map of how Finnish Wikipedia "
              "wrote Finland's history; https://github.com/JUSSI-G/Junction26)")


def load_labels():
    if not os.path.exists(CACHE):
        return {}
    with open(CACHE, encoding="utf-8", newline="") as f:
        return {r["qid"]: r["en_label"] for r in csv.DictReader(f, delimiter="\t")}


def fetch(qids):
    body = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(qids),
                                   "props": "labels", "languages": "en", "format": "json",
                                   "formatversion": "2", "maxlag": "30"}).encode()
    for attempt in range(10):
        try:
            req = urllib.request.Request("https://www.wikidata.org/w/api.php", data=body, headers={
                "User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            data = json.loads(raw)
            if "error" in data:
                raise ValueError(data["error"].get("code"))
            return {q: e.get("labels", {}).get("en", {}).get("value", "")
                    for q, e in data["entities"].items()}
        except (OSError, ValueError) as e:
            print(f"  retry {attempt + 1}: {e}", flush=True)
            time.sleep(min(60, 5 * (attempt + 1)))
    raise RuntimeError("Wikidata labels request failed")


if __name__ == "__main__":
    con = connect(dict_rows=False)
    cur = con.cursor()
    cur.execute("ALTER TABLE place ADD COLUMN IF NOT EXISTS en_label VARCHAR(255) AFTER title")
    cur.execute("SELECT DISTINCT qid FROM place WHERE qid IS NOT NULL AND qid <> ''")
    qids = [q for (q,) in cur.fetchall()]
    labels = load_labels()
    todo = sorted(set(qids) - labels.keys())
    print(f"{len(qids)} places, {len(labels)} labels cached, {len(todo)} to fetch", flush=True)
    t0, requests = time.time(), 0
    new = not os.path.exists(CACHE)
    with open(CACHE, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        if new:
            w.writerow(["qid", "en_label"])
        for i in range(0, len(todo), 50):
            got = fetch(todo[i:i + 50])
            requests += 1
            for q in todo[i:i + 50]:
                labels[q] = got.get(q, "")
                w.writerow([q, labels[q]])
            f.flush()
    cur.executemany("UPDATE place SET en_label = %s WHERE qid = %s",
                    [(labels[q][:255] or None, q) for q in qids])
    con.commit()
    cur.execute("SELECT COUNT(*), COUNT(en_label), SUM(en_label <> title) FROM place")
    print("place: %s rows, %s with an English label, %s where it differs from the Finnish title"
          % cur.fetchone() + f" ({requests} requests, {time.time() - t0:.0f} s)")
    con.close()
