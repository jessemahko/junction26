"""Where on Earth is an article? Coordinates from Finnish wikitext.  (owner: P2)

1. The article's own coordinates: {{coord|…}} / {{Koordinaatit|…}} templates, or infobox fields
   lat_deg/lat_min/lat_sec/lat_dir + lon_*, or latd/latm/lats/latNS + longd/longm/longs/longEW.
2. Otherwise the place it names: infobox `paikka = [[Tampere]]` (also sijainti, taistelupaikka …)
   resolved through the coordinates of that place's own article (source = "place:<title>").

    python -m ingest.geo            # scan the latest revision of every article in dataset M
                                    # -> data/m/geo.tsv (page_id, title, versions, lat, lon, source)
"""
from __future__ import annotations

import csv
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ingest.load_articles import M_DIR

GEO_INDEX = M_DIR / "geo.tsv"

_COORD = re.compile(r"\{\{\s*(?:coord|koordinaatit)\s*\|([^{}]*)\}\}", re.I)
_NUM = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_PLACE = re.compile(r"\|\s*(?:paikka|sijainti|taistelupaikka|tapahtumapaikka|kaupunki|kunta|alue)\s*=\s*([^\n|]*)", re.I)
_LINK = re.compile(r"\[\[([^\]|#]+)")


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def _dms(parts: list[str]) -> float | None:
    if not parts or not all(_NUM.match(p) for p in parts):
        return None
    v = 0.0
    for p, div in zip(parts, (1, 60, 3600)):
        v += _f(p) / div
    return v


def _from_template(args: str) -> tuple[float, float] | None:
    pos = [a.strip() for a in args.split("|") if a.strip() and "=" not in a and ":" not in a]
    hemis = [i for i, a in enumerate(pos) if a.upper() in ("N", "S", "E", "W")]
    if len(hemis) >= 2:
        i, j = hemis[0], hemis[1]
        lat, lon = _dms(pos[:i]), _dms(pos[i + 1:j])
        if lat is None or lon is None:
            return None
        if pos[i].upper() == "S":
            lat = -lat
        if pos[j].upper() == "W":
            lon = -lon
        return lat, lon
    if len(pos) >= 2 and _NUM.match(pos[0]) and _NUM.match(pos[1]):
        return _f(pos[0]), _f(pos[1])
    return None


def _param(text: str, name: str) -> str | None:
    m = re.search(r"\|\s*" + name + r"\s*=\s*([^\n|}<]*)", text, re.I)
    return m.group(1).strip() if m and m.group(1).strip() else None


def _from_params(text: str) -> tuple[float, float] | None:
    for lat_k, lon_k, suffix in ((("lat_deg", "lat_min", "lat_sec"), ("lon_deg", "lon_min", "lon_sec"), ("lat_dir", "lon_dir")),
                                 (("latd", "latm", "lats"), ("longd", "longm", "longs"), ("latNS", "longEW"))):
        lat_parts = [p for p in (_param(text, k) for k in lat_k) if p]
        lon_parts = [p for p in (_param(text, k) for k in lon_k) if p]
        lat, lon = _dms(lat_parts), _dms(lon_parts)
        if lat is None or lon is None:
            continue
        if (_param(text, suffix[0]) or "N").upper().startswith("S"):
            lat = -lat
        if (_param(text, suffix[1]) or "E").upper().startswith("W"):
            lon = -lon
        return lat, lon
    return None


def own_coordinates(text: str | None) -> tuple[float, float] | None:
    if not text:
        return None
    for m in _COORD.finditer(text):
        c = _from_template(m.group(1))
        if c and -90 <= c[0] <= 90 and -180 <= c[1] <= 180:
            return round(c[0], 5), round(c[1], 5)
    c = _from_params(text)
    if c and -90 <= c[0] <= 90 and -180 <= c[1] <= 180:
        return round(c[0], 5), round(c[1], 5)
    return None


def named_places(text: str | None) -> list[str]:
    """Titles linked from the infobox's place fields, e.g. `paikka = [[Tampere]], [[Suomi]]`."""
    if not text:
        return []
    out = []
    for m in _PLACE.finditer(text[:20000]):
        out += [t.strip() for t in _LINK.findall(m.group(1))]
    return out


def _scan(path: Path) -> list[tuple]:
    """Latest revision of every page in one dataset M file -> (page_id, title, versions, coords, places)."""
    import pyarrow.parquet as pq
    f = pq.ParquetFile(path)
    last: dict[int, list] = {}
    for i in range(f.metadata.num_row_groups):
        t = f.read_row_group(i, columns=["page_id", "title", "text"])
        for pid, title, text in zip(t.column("page_id").to_pylist(), t.column("title").to_pylist(),
                                    t.column("text").to_pylist()):
            e = last.setdefault(pid, [title, None, 0])
            e[0], e[1], e[2] = title, text, e[2] + 1
    return [(pid, title, n, own_coordinates(text), named_places(text)) for pid, (title, text, n) in last.items()]


def build_index(workers: int = 4) -> int:
    files = sorted(M_DIR.glob("versions-*.parquet"))
    if not files:
        raise SystemExit("No dataset M files. Run: python -m ingest.download --all")
    rows: list[tuple] = []
    with ProcessPoolExecutor(workers) as ex:
        for path, part in zip(files, ex.map(_scan, files)):
            rows += part
            print(f"  {path.name}: {len(part)} articles", flush=True)
    by_title = {title: c for _, title, _, c, _ in rows if c}
    out, own, via = [], 0, 0
    for pid, title, n, c, places in rows:
        source = "own"
        if not c:
            for p in places:
                if p in by_title:
                    c, source = by_title[p], f"place:{p}"
                    break
        if c:
            own += source == "own"
            via += source != "own"
            out.append((pid, title, n, c[0], c[1], source))
    out.sort(key=lambda r: -r[2])
    with open(GEO_INDEX, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["page_id", "title", "versions", "lat", "lon", "source"])
        w.writerows(out)
    print(f"{len(rows)} articles scanned: {own} with own coordinates, {via} placed via a linked place "
          f"-> {GEO_INDEX}")
    return len(out)


def load_index() -> dict[int, dict]:
    if not GEO_INDEX.exists():
        return {}
    with open(GEO_INDEX, encoding="utf-8") as f:
        return {int(r["page_id"]): r for r in csv.DictReader(f, delimiter="\t")}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build_index()
