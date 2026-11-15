"""Download dataset M (every version of the History-of-Finland articles) from the MariaDB release.

    python -m ingest.download 01            # just versions-01.parquet (20 MB; holds page 1150)
    python -m ingest.download 01 02 03 04   # what --dataset medium needs
    python -m ingest.download --all         # all 16 files, 315 MB (small and large need these)

Files land in data/m/ and are checked against the release's SHA256SUMS. Already-downloaded,
verified files are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import urllib.error
import urllib.request

from ingest.load_articles import M_DIR

RELEASE = "https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/download/m-2026-10/"


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(name: str) -> None:
    dest = M_DIR / name
    tmp = dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(RELEASE + name, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except urllib.error.URLError as e:
        # Some Windows Python installs miss the CA chain (CERTIFICATE_VERIFY_FAILED); curl uses the OS store.
        curl = shutil.which("curl")
        if not curl:
            raise SystemExit(f"Download failed ({e}) and curl is not available") from e
        # relative -o from inside the folder: Windows curl can't write to non-ASCII absolute paths
        subprocess.run([curl, "-sSfL", "-o", tmp.name, RELEASE + name], check=True, cwd=M_DIR)
    tmp.replace(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("numbers", nargs="*", help="file numbers, e.g. 01 02")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    M_DIR.mkdir(parents=True, exist_ok=True)
    fetch("SHA256SUMS")
    sums = {}
    for line in (M_DIR / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        sums[name.lstrip("*")] = digest
    names = sorted(n for n in sums if n.startswith("versions-"))
    if not a.all:
        names = [f"versions-{int(n):02d}.parquet" for n in a.numbers] or ["versions-01.parquet"]
    for name in names:
        path = M_DIR / name
        if path.exists() and sha256(path) == sums[name]:
            print(f"{name}: ok (already here)")
            continue
        print(f"{name}: downloading …", flush=True)
        fetch(name)
        if sha256(path) != sums[name]:
            raise SystemExit(f"{name}: checksum mismatch — delete it and run again")
        print(f"{name}: ok ({path.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
