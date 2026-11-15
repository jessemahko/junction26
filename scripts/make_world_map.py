r"""Make the map's coastlines, borders and lakes: web/public/world.json (2D) and world3d.json (3D globe).

    python scripts/make_world_map.py <ne_10m_admin_0_countries.geojson> <ne_10m_lakes.geojson>

Source: Natural Earth 1:10m (public domain), github.com/nvkelso/natural-earth-vector/geojson/.
The whole world, simplified (Douglas–Peucker) with more detail where the demo looks closely:
  2D: 0.012° (~1 km) inside Northern Europe, 0.05° elsewhere; every lake in Northern Europe, only the
      big ones (scalerank <= 2) elsewhere.
  3D: 0.03° / 0.15° and no lakes: the globe triangulates every polygon, so it gets fewer points.
Coordinates rounded to 3 decimals.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

NORTH = (-12.0, 50.0, 50.0, 72.5)        # lon_min, lat_min, lon_max, lat_max: Northern Europe
MIN_LAKE_POINTS = 6
OUT = Path(__file__).resolve().parents[1] / "web" / "public"
LEVELS = {"world.json": {"near": 0.012, "far": 0.05, "lakes": True},
          "world3d.json": {"near": 0.03, "far": 0.15, "lakes": False}}


def rdp(pts: list, tol: float) -> list:
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = pts[i], pts[j]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5
        best, k = -1.0, -1
        for m in range(i + 1, j):
            if norm < 1e-9:      # a closed ring: first == last, so measure from that point
                d = ((pts[m][0] - ax) ** 2 + (pts[m][1] - ay) ** 2) ** 0.5
            else:
                d = abs(dy * (pts[m][0] - ax) - dx * (pts[m][1] - ay)) / norm
            if d > best:
                best, k = d, m
        if best > tol:
            keep[k] = True
            stack += [(i, k), (k, j)]
    return [p for p, f in zip(pts, keep) if f]


def rings(geom: dict) -> list:
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def near(ring: list) -> bool:
    x0, y0, x1, y1 = NORTH
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x, y, *_ in ring)


def shape(ring: list, level: dict) -> list | None:
    r = rdp([list(p[:2]) for p in ring], level["near"] if near(ring) else level["far"])
    if len(r) < 4:
        return None
    return [[round(x, 3), round(y, 3)] for x, y in r]


def main() -> None:
    countries = json.load(open(sys.argv[1], encoding="utf-8"))
    lakes = json.load(open(sys.argv[2], encoding="utf-8"))
    for name, level in LEVELS.items():
        land = []
        for f in countries["features"]:
            p = f["properties"]
            polys = [s for s in (shape(r, level) for r in rings(f["geometry"])) if s]
            if polys:
                land.append({"name": p.get("NAME_EN") or p.get("NAME"),
                             "iso": p.get("ISO_A2_EH") or p.get("ISO_A2"), "polys": polys})
        water = []
        if level["lakes"]:
            for f in lakes["features"]:
                for r in rings(f["geometry"]):
                    if not near(r) and (f["properties"].get("scalerank") or 9) > 2:
                        continue
                    s = shape(r, level)
                    if s and len(s) >= MIN_LAKE_POINTS:
                        water.append(s)
        out = OUT / name
        out.write_text(json.dumps({"north": NORTH, "source": "Natural Earth 1:10m (public domain)",
                                   "land": land, "lakes": water}, separators=(",", ":")), encoding="utf-8")
        pts = sum(len(p) for c in land for p in c["polys"]) + sum(len(p) for p in water)
        print(f"{out.name}: {len(land)} countries, {len(water)} lakes, {pts:,} points, {out.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
