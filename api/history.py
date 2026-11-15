"""The history queries behind every view. Each function takes a DB connection and returns plain
JSON-ready data in the shape of the API contract (plan §6.2). SQL lives in db/queries/*.sql.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from common.db import load_query

STEP_DELTA = {"month": 1, "quarter": 3, "year": 12}


class NotFound(Exception):
    pass


# --- helpers -----------------------------------------------------------------------------------

def moment(value: str | date | datetime | None) -> str:
    """'2012', '2012-03', '2012-03-04', '2012-03-04T10:00[:00][Z]' -> 'YYYY-MM-DD HH:MM:SS.ffffff'.
    MariaDB's `TIMESTAMP %s` refuses a bare date. None = now."""
    if value is None:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, date):
        return f"{value:%Y-%m-%d} 00:00:00.000000"
    v = str(value).strip().replace("T", " ").rstrip("Z")
    if re.fullmatch(r"\d{4}", v):
        v += "-01-01"
    elif re.fullmatch(r"\d{4}-\d{2}", v):
        v += "-01"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"not a date: {value!r}") from e
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def iso(dt: datetime | None) -> str | None:
    """Datetime -> ISO-8601 UTC; MariaDB's 'still current' row_end (2038/2106) -> None."""
    if dt is None or dt.year >= 2038:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def hx(b: bytes | None) -> str | None:
    return b.hex() if b is not None else None


def num(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def _rows(conn, name: str, params: dict, **fmt) -> list[dict]:
    """Run db/queries/<name>.sql. `fmt` fills {placeholders} with server-side-generated SQL
    fragments only (whitelisted numbers / column lists), never with user input."""
    sql = load_query(name)
    for key, value in fmt.items():
        sql = sql.replace("{" + key + "}", str(value))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _order(blob: bytes | None) -> dict[bytes, int]:
    if not blob:
        return {}
    return {blob[i:i + 32]: i // 32 for i in range(0, len(blob), 32)}


# --- views -------------------------------------------------------------------------------------

def articles(conn, q: str = "", limit: int = 50) -> list[dict]:
    rows = _rows(conn, "articles", {"q": f"%{q}%", "limit": limit})
    return [dict(page_id=r["page_id"], title=r["title"], revisions=r["revisions"],
                 first_rev=iso(r["first_rev"]), last_rev=iso(r["last_rev"]),
                 n_sentences=r["n_sentences"]) for r in rows]


def as_of(conn, page_id: int, when=None) -> dict:
    p = {"page_id": page_id, "ts": moment(when)}
    art = _rows(conn, "as_of_article", p)
    if not art:
        raise NotFound(f"article {page_id} did not exist at {p['ts']}")
    a = art[0]
    order = _order(a["sentence_order"])
    sents = _rows(conn, "as_of_sentences", p)
    sents.sort(key=lambda s: order.get(s["sent_hash"], 10**9 + s["position"]))
    return dict(
        page_id=page_id, title=a["title"], rev_id=a["rev_id"], timestamp=iso(a["ts"]),
        editor=a["editor"], anonymous=bool(a["anonymous"]), comment=a["comment"],
        sentences=[dict(hash=hx(s["sent_hash"]), text=s["text"], position=i,
                        since=iso(s["since"]), editor=s["editor"], rev_id=s["rev_id"])
                   for i, s in enumerate(sents)])


def diff(conn, page_id: int, frm, to) -> dict:
    p = {"page_id": page_id, "from": moment(frm), "to": moment(to)}
    out = dict(added=[], removed=[], kept=0)
    for r in _rows(conn, "diff", p):
        if r["kind"] == "kept":
            out["kept"] = int(r["position"] or 0)
        else:
            out[r["kind"]].append(dict(hash=hx(r["sent_hash"]), text=r["text"],
                                       editor=r["editor"], rev_id=r["rev_id"]))
    return out


def contested(conn, page_id: int) -> list[dict]:
    rows = _rows(conn, "contested", {"page_id": page_id})
    if not rows:
        return []
    cur = _rows(conn, "as_of_article", {"page_id": page_id, "ts": moment(None)})
    order = _order(cur[0]["sentence_order"]) if cur else {}
    rows.sort(key=lambda r: order.get(r["sent_hash"], 10**9 + r["position"]))
    return [dict(hash=hx(r["sent_hash"]), text=r["text"], position=i, lives=r["lives"],
                 rewrites=int(r["rewrites"] or 0), total_days_alive=num(r["total_days_alive"]),
                 since=iso(r["since"]), first_seen=iso(r["first_seen"]), editor=r["editor"])
            for i, r in enumerate(rows)]


def edit_wars(conn, page_id: int, limit: int = 20) -> list[dict]:
    out: dict[bytes, dict] = {}
    for r in _rows(conn, "edit_wars", {"page_id": page_id, "limit": limit}):
        w = out.setdefault(r["sent_hash"], dict(hash=hx(r["sent_hash"]), text=r["text"],
                                                lives=r["lives"], periods=[]))
        w["periods"].append(dict(
            **{"from": iso(r["from"]), "to": iso(r["to"])}, editor=r["editor"],
            anonymous=bool(r["anonymous"]), rev_id=r["rev_id"], removed_by=r["removed_by"],
            removed_by_anonymous=bool(r["removed_by_anonymous"]) if r["removed_by_anonymous"] is not None else None,
            removed_rev=r["removed_rev"], removed_comment=r["removed_comment"]))
    return list(out.values())


DEFAULT_TERMS = ["vapaussota", "sisällissota", "kansalaissota", "punakapina", "luokkasota", "veljessota"]


def revisions(conn, page_id: int) -> list[dict]:
    return [dict(rev_id=r["rev_id"], timestamp=iso(r["ts"]), editor=r["editor"],
                 anonymous=bool(r["anonymous"]), comment=r["comment"], minor=bool(r["minor"]),
                 n_sentences=r["n_sentences"], is_revert=bool(r["is_revert"]))
            for r in _rows(conn, "revisions", {"page_id": page_id})]


def sentence_history(conn, page_id: int, sent_hash: str) -> list[dict]:
    try:
        h = bytes.fromhex(sent_hash)
    except ValueError as e:
        raise NotFound("bad hash") from e
    rows = _rows(conn, "sentence_history", {"page_id": page_id, "hash": h})
    if not rows:
        raise NotFound("sentence not found")
    return [dict(hash=hx(r["sent_hash"]), text=r["text"], editor=r["editor"],
                 anonymous=bool(r["anonymous"]), rev_id=r["rev_id"],
                 **{"from": iso(r["from"]), "to": iso(r["to"])}, depth=r["depth"],
                 tone=r["tone"], neutrality=num(r["neutrality"]), event_name=r["event_name"])
            for r in rows]


# --- bitemporal: system time (when Wikipedia said it) x application time (when it happened) -----

def _year_range(frm, to) -> tuple[str, str]:
    """Years 'YYYY' (inclusive) -> [YYYY-01-01, (to+1)-01-01) for the period overlap test."""
    a, b = int(frm), int(to)
    if not (1000 <= a <= 9998 and 1000 <= b <= 9998) or b < a:
        raise ValueError("years must be 1000..9998 and from <= to")
    return f"{a:04d}-01-01", f"{b + 1:04d}-01-01"


def about(conn, page_id: int, when, frm: int, to: int) -> list[dict]:
    lo, hi = _year_range(frm, to)
    rows = _rows(conn, "about", {"page_id": page_id, "ts": moment(when), "from": lo, "to": hi})
    return [dict(hash=hx(r["sent_hash"]), text=r["text"], event_from=r["event_from"].year,
                 event_to=r["event_to"].year - 1) for r in rows]


# --- the globe -----------------------------------------------------------------------------------

# --- /stats ------------------------------------------------------------------------------------
