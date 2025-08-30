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
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with conn:
        # WAL + NORMAL for speed while remaining safe for typical uses
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        # schema: messages
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        INTEGER NOT NULL,
                source    TEXT    NOT NULL,
                title     TEXT    NOT NULL,
                body      TEXT    NOT NULL,
                meta      TEXT,
                delivered TEXT,
                read      INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_title ON messages(title);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);")
        # settings kv table
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
    global _CONN
    with _db_lock:
        _CONN = _connect(path)

def _conn() -> sqlite3.Connection:
    if _CONN is None:
        init_db(DB_PATH)
    assert _CONN is not None
    return _CONN

# ------------------------ Message helpers ------------------------

def save_message(source: str, title: str, body: str, meta: Optional[Dict[str, Any]] = None,
                 delivered: Optional[Dict[str, Any]] = None, ts: Optional[int] = None) -> int:
    """
    Persist a message and return the row id.
    """
    if ts is None:
        ts = int(time.time())
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    delivered_json = json.dumps(delivered or {}, ensure_ascii=False)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO messages(ts, source, title, body, meta, delivered, read) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (ts, source or "", title or "", body or "", meta_json, delivered_json)
        )
        return int(cur.lastrowid)

def list_messages(limit: int = 50, q: Optional[str] = None, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Return a list of message dicts, newest first. Optional search query across source/title/body.
    """
    sql = "SELECT * FROM messages"
    params: List[Any] = []
    if q:
        sql += " WHERE (source LIKE ? OR title LIKE ? OR body LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]
    sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    params += [int(limit), int(offset)]
    rows = _conn().execute(sql, params).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        # parse JSON fields
        for k in ("meta", "delivered"):
            try:
                d[k] = json.loads(d.get(k) or "{}")
            except Exception:
                d[k] = {}
        out.append(d)
    return out

def get_message(msg_id: int) -> Optional[Dict[str, Any]]:
    r = _conn().execute("SELECT * FROM messages WHERE id=?", (int(msg_id),)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("meta", "delivered"):
        try:
            d[k] = json.loads(d.get(k) or "{}")
        except Exception:
            d[k] = {}
    return d

def delete_message(msg_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM messages WHERE id=?", (int(msg_id),))
        return cur.rowcount > 0

def mark_read(msg_id: int, read: bool = True) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE messages SET read=? WHERE id=?", (1 if read else 0, int(msg_id)))
        return cur.rowcount > 0

def purge_older_than(days: int) -> int:
    """
    Delete messages older than N days. Returns number of rows removed.
    """
    cutoff = int(time.time()) - int(days) * 86400
    with _conn() as c:
        cur = c.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        return cur.rowcount

# ------------------------ Settings helpers ------------------------

def get_retention_days(default: int = 30) -> int:
    r = _conn().execute("SELECT value FROM settings WHERE key='retention_days'").fetchone()
    if not r or r["value"] is None:
        return int(default)
    try:
        return int(r["value"])
    except Exception:
        return int(default)

def set_retention_days(days: int) -> None:
    with _conn() as c:
        c.execute("INSERT INTO settings(key, value) VALUES('retention_days', ?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(days)),))

# Convenience export for other modules
__all__ = [
    "init_db", "save_message", "list_messages", "get_message", "delete_message",
    "mark_read", "purge_older_than", "get_retention_days", "set_retention_days"
]
