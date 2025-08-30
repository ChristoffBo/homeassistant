#!/usr/bin/env python3
# storage.py — SQLite inbox store for Jarvis Prime
# - WAL mode + synchronous=NORMAL for performance (see SQLite docs)
# - Emoji/UTF‑8 safe
# - Simple helpers for UI & API

from __future__ import annotations
import os, json, sqlite3, threading, time
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.getenv("JARVIS_DB_PATH", "/data/jarvis.db")

# internal lock to serialize schema/setting changes
_db_lock = threading.RLock()

def _connect(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # schema
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            body        TEXT NOT NULL,
            source      TEXT NOT NULL,
            priority    INTEGER NOT NULL DEFAULT 5,
            created_at  INTEGER NOT NULL,
            read        INTEGER NOT NULL DEFAULT 0,
            extras      TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    return conn

# Keep a single connection per process
_CONN: Optional[sqlite3.Connection] = None

def init_db(path: str = DB_PATH) -> None:
    """Ensure database and schema exist."""
    global _CONN
    with _db_lock:
        _CONN = _connect(path)

def _conn() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        _CONN = _connect(DB_PATH)
    return _CONN

def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    out = dict(r)
    # decode extras if present
    if out.get("extras"):
        try:
            out["extras"] = json.loads(out["extras"])
        except Exception:
            pass
    return out

# -------------------- Message ops --------------------
def save_message(title: str, body: str, source: str, priority: int = 5, extras: Optional[Dict[str, Any]] = None, created_at: Optional[int] = None) -> int:
    ts = int(created_at or time.time())
    ex = json.dumps(extras or {}, ensure_ascii=False)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO messages(title, body, source, priority, created_at, read, extras) VALUES(?,?,?,?,?,0,?)",
            (title, body, source, int(priority), ts, ex)
        )
        return int(cur.lastrowid)

def list_messages(limit: int = 50, q: Optional[str] = None, offset: int = 0) -> List[Dict[str, Any]]:
    sql = "SELECT id, title, body, source, priority, created_at, read, extras FROM messages"
    args: List[Any] = []
    if q:
        qlike = f"%{q}%"
        sql += " WHERE title LIKE ? OR body LIKE ? OR source LIKE ?"
        args += [qlike, qlike, qlike]
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [int(limit), int(offset)]
    cur = _conn().execute(sql, args)
    return [_row_to_dict(r) for r in cur.fetchall()]

def get_message(mid: int) -> Optional[Dict[str, Any]]:
    cur = _conn().execute(
        "SELECT id, title, body, source, priority, created_at, read, extras FROM messages WHERE id=?",
        (int(mid),)
    )
    r = cur.fetchone()
    return _row_to_dict(r) if r else None

def delete_message(mid: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM messages WHERE id=?", (int(mid),))
        return cur.rowcount > 0

def mark_read(mid: int, read: bool = True) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE messages SET read=? WHERE id=?", (1 if read else 0, int(mid)))
        return cur.rowcount > 0

def purge_older_than(days: int) -> int:
    cutoff = int(time.time()) - (int(days) * 86400)
    with _conn() as c:
        cur = c.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
        return int(cur.rowcount)

# -------------------- Settings helpers --------------------
def get_retention_days(default: int = 30) -> int:
    try:
        cur = _conn().execute("SELECT value FROM settings WHERE key='retention_days'")
        r = cur.fetchone()
        return int(r["value"]) if r else int(default)
    except Exception:
        return int(default)

def set_retention_days(days: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO settings(key, value) VALUES('retention_days', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(days)),),
        )

__all__ = [
    "init_db", "save_message", "list_messages", "get_message", "delete_message",
    "mark_read", "purge_older_than", "get_retention_days", "set_retention_days"
]
