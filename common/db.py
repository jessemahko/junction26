"""Settings and the MariaDB connection, shared by ingest/, scoring/ and api/.

Settings come from environment variables, optionally from a .env file in the repo root
(see .env.example).
"""
from __future__ import annotations

import os
import queue
from contextlib import contextmanager
from pathlib import Path

import pymysql
import pymysql.cursors

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "db" / "queries"


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                value = value.split(" #", 1)[0].strip()      # allow inline comments
                if value:
                    os.environ.setdefault(key.strip(), value)


_load_env()


def settings() -> dict:
    return dict(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "wiki"),
    )


def connect(database: str | None = None, autocommit: bool = False, dict_rows: bool = True,
            read_timeout: int | None = None):
    cfg = settings()
    if database is not None:
        cfg["database"] = database
    return pymysql.connect(
        **cfg,
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=read_timeout,      # API: fail fast instead of hanging; loaders: no limit
        autocommit=autocommit,
        cursorclass=pymysql.cursors.DictCursor if dict_rows else pymysql.cursors.Cursor,
        # Wikipedia's times are UTC; TIMESTAMP columns are shown in the session time zone.
        init_command="SET time_zone = '+00:00'",
        max_allowed_packet=256 * 1024 * 1024,
    )


def load_query(name: str) -> str:
    """Read db/queries/<name>.sql. Queries use pymysql's %(name)s placeholders, so a literal
    percent sign in SQL is written %%."""
    sql = (QUERIES / f"{name}.sql").read_text(encoding="utf-8")
    # Drop full-line comments: pymysql would try to fill in %(…)s written inside them.
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


class Pool:
    """A tiny thread-safe connection pool (FastAPI runs sync endpoints in a thread pool)."""

    def __init__(self, size: int = 8, database: str | None = None, read_timeout: int | None = 30):
        self._database = database
        self._read_timeout = read_timeout
        self._q: queue.LifoQueue = queue.LifoQueue(maxsize=size)
        for _ in range(size):
            self._q.put(None)

    @contextmanager
    def connection(self):
        conn = self._q.get()
        try:
            if conn is None:
                conn = connect(self._database, autocommit=True, read_timeout=self._read_timeout)
            else:
                conn.ping(reconnect=True)
            yield conn
        except pymysql.err.OperationalError:
            conn = None   # drop a broken connection; a fresh one is made next time
            raise
        finally:
            self._q.put(conn)
