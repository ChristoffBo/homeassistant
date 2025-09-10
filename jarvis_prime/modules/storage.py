#!/usr/bin/env python3
# storage.py — SQLite inbox store for Jarvis Prime (JP7)
from __future__ import annotations
import os, json, sqlite3, threading, time
from typing import Any, Dict, List, Optional, Set

DB_PATH = os.getenv("JARVIS_DB_PATH", "/data/jarvis.db")
_db_lock = threading.RLock()
_CONN: Optional[sqlite3.Connection] = None

# ---------------------- internal helpers ----------------------
def _columns(conn: sqlite3.Connection) -> Set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}

def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables and backfill any missing columns on existing DBs.
       Supports old DBs that used a NOT NULL `ts` column instead of `created_at`.
    """
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # base tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            title  TEXT NOT NULL,
            body   TEXT NOT NULL,
            source TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    cols = _columns(conn)

    if "priority" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN priority INTEGER NOT NULL DEFAULT 5")
        cols.add("priority")

    if "created_at" not in cols and "ts" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0")
        cols.add("created_at")

    if "read" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN read INTEGER NOT NULL DEFAULT 0")
        cols.add("read")

    if "extras" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN extras TEXT")
        cols.add("extras")

    if "saved" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN saved INTEGER NOT NULL DEFAULT 0")
        cols.add("saved")

def _connect(path: str) -> sqlite3.Connection:
    # Enable cross-thread use to support aiosmtpd worker thread
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)  # autocommit
    _ensure_schema(conn)
    return conn

def init_db(path: str = DB_PATH) -> None:
    """Ensure database exists and is upgraded to latest schema."""
    global _CONN
    with _db_lock:
        _CONN = _connect(path)

def _conn() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        _CONN = _connect(DB_PATH)
    return _CONN

def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    if d.get("extras"):
        try:
            d["extras"] = json.loads(d["extras"])
        except Exception:
            pass
    d["saved"] = bool(int(d.get("saved", 0)))
    d["read"] = bool(int(d.get("read", 0)))
    return d

# ---------------------- public API ----------------------
def save_message(title: str, body: str, source: str, priority: int = 5, extras: Optional[Dict[str, Any]] = None, created_at: Optional[int] = None) -> int:
    ts = int(created_at or time.time())
    ex = json.dumps(extras or {}, ensure_ascii=False)
    with _db_lock:
        c = _conn()
        cols = _columns(c)
        # Build INSERT dynamically depending on whether legacy `ts` exists
        time_cols = []
        params = [title, body, source, int(priority)]
        if "created_at" in cols:
            time_cols.append("created_at")
            params.append(ts)
        if "ts" in cols:
            time_cols.append("ts")
            params.append(ts)
        columns_sql = "title, body, source, priority"
        if time_cols:
            columns_sql += ", " + ", ".join(time_cols)
        columns_sql += ", read, extras, saved"
        sql = f"INSERT INTO messages({columns_sql}) VALUES({','.join(['?']* (4 + len(time_cols) + 3))})"
        params.extend([0, ex, 0])
        cur = c.execute(sql, params)
        return int(cur.lastrowid)

def list_messages(limit: int = 50, q: Optional[str] = None, offset: int = 0, saved: Optional[bool] = None) -> List[Dict[str, Any]]:
    c = _conn()
    cols = _columns(c)
    time_expr = "COALESCE(created_at, ts)" if "ts" in cols else "created_at"
    if "created_at" not in cols and "ts" in cols:
        time_expr = "ts"
    sql = f"SELECT id, title, body, source, priority, {time_expr} AS created_at, read, extras, saved FROM messages"
    args: List[Any] = []
    clauses = []
    if q:
        like = f"%{q}%"
        clauses.append("(title LIKE ? OR body LIKE ? OR source LIKE ?)")
        args += [like, like, like]
    if saved is not None:
        clauses.append("saved=?")
        args.append(1 if saved else 0)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [int(limit), int(offset)]
    cur = c.execute(sql, args)
    return [_row_to_dict(r) for r in cur.fetchall()]

def get_message(mid: int) -> Optional[Dict[str, Any]]:
    c = _conn()
    cols = _columns(c)
    time_expr = "COALESCE(created_at, ts)" if "ts" in cols else "created_at"
    if "created_at" not in cols and "ts" in cols:
        time_expr = "ts"
    cur = c.execute(
        f"SELECT id, title, body, source, priority, {time_expr} AS created_at, read, extras, saved FROM messages WHERE id=?",
        (int(mid),),
    )
    r = cur.fetchone()
    return _row_to_dict(r) if r else None

def delete_message(mid: int) -> bool:
    with _db_lock:
        c = _conn()
        cur = c.execute("DELETE FROM messages WHERE id=?", (int(mid),))
        return cur.rowcount > 0

def delete_all(keep_saved: bool=False) -> int:
    with _db_lock:
        c = _conn()
        if keep_saved:
            cur = c.execute("DELETE FROM messages WHERE saved=0")
        else:
            cur = c.execute("DELETE FROM messages")
        return int(cur.rowcount)

def mark_read(mid: int, read: bool = True) -> bool:
    with _db_lock:
        c = _conn()
        cur = c.execute("UPDATE messages SET read=? WHERE id=?", (1 if read else 0, int(mid)))
        return cur.rowcount > 0

def set_saved(mid: int, saved: bool = True) -> bool:
    with _db_lock:
        c = _conn()
        cur = c.execute("UPDATE messages SET saved=? WHERE id=?", (1 if saved else 0, int(mid)))
        return cur.rowcount > 0

def purge_older_than(days: int) -> int:
    with _db_lock:
        c = _conn()
        cols = _columns(c)
        tcol = "created_at" if "created_at" in cols else ("ts" if "ts" in cols else "created_at")
        cutoff = int(time.time()) - (int(days) * 86400)
        cur = c.execute(f"DELETE FROM messages WHERE {tcol} < ?", (cutoff,))
        return int(cur.rowcount)

def get_retention_days(default: int = 30) -> int:
    try:
        r = _conn().execute("SELECT value FROM settings WHERE key='retention_days'").fetchone()
        return int(r["value"]) if r else int(default)
    except Exception:
        return int(default)

def set_retention_days(days: int) -> None:
    with _db_lock:
        c = _conn()
        c.execute(
            "INSERT INTO settings(key, value) VALUES('retention_days', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(days)),),
        )

__all__ = [
    "init_db", "save_message", "list_messages", "get_message", "delete_message",
    "delete_all", "mark_read", "set_saved", "purge_older_than",
    "get_retention_days", "set_retention_days"
]
