r"""Start AikaKone: one command.

    python start.py                 # http://127.0.0.1:8000
    python start.py --port 8080
    python start.py --rebuild       # rebuild the web app even if it looks up to date

1. checks the database settings in .env (see .env.example) and that MariaDB answers;
2. builds the web app (web/dist) when it is missing or older than web/src (npm install first if needed);
3. runs the API, which also serves the web app: / redirects to /contested/.
The data must already be loaded: see the pipeline in README.md.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def newest(path: Path) -> float:
    return max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=0.0)


def check_db() -> None:
    sys.path.insert(0, str(ROOT))
    from common.db import connect, settings
    s = settings()
    try:
        con = connect()
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM article_divergence")
            n = cur.fetchone()["n"]
        con.close()
    except Exception as e:                                   # noqa: BLE001 - show any connection problem
        sys.exit(f"MariaDB at {s['host']}:{s['port']} (database {s['database']}): {e}\n"
                 "Check .env (copy .env.example) and that the data is loaded (README.md).")
    print(f"MariaDB {s['host']}:{s['port']}/{s['database']}: {n:,} topics in the worklist")


def build_web(force: bool) -> None:
    dist = WEB / "dist"
    if not force and dist.exists() and newest(dist) >= max(newest(WEB / "src"), newest(WEB / "public")):
        print("web app: up to date (web/dist)")
        return
    npm = shutil.which("npm")
    if not npm:
        sys.exit("npm not found: install Node 18+ to build the web app")
    if not (WEB / "node_modules").exists():
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=WEB, check=True)
    print("web app: building…")
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Start AikaKone")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the web app")
    a = ap.parse_args()
    check_db()
    build_web(a.rebuild)
    print(f"AikaKone: http://{a.host}:{a.port}/   (Ctrl+C to stop)")
    subprocess.run([sys.executable, "-m", "uvicorn", "api.main:app", "--host", a.host, "--port", str(a.port)],
                   cwd=ROOT)


if __name__ == "__main__":
    main()
