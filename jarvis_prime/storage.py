# storage.py — SQLite persistence for Jarvis Prime inbox (FULL)
from __future__ import annotations
import sqlite3
import json
import os
import threading
from contextlib import contextmanager
from typing import Any, Dict, List

DB_PATH = os.environ.get("INBOX_DB_PATH", "/data/messages.db")

_lock = threading.RLock()

def _connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

@contextmanager
def _db(path: str | None = None):
    conn = _connect(path)
    try:
        yield conn
    finally:
        conn.close()

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            source TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 5,
            extras TEXT DEFAULT '{}',
            inbound INTEGER NOT NULL DEFAULT 1
        );
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        '''
    )
    row = conn.execute("SELECT value FROM settings WHERE key='retention_days'").fetchone()
    if not row:
        conn.execute("INSERT INTO settings(key,value) VALUES('retention_days','30')")

def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "ts" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN ts DATETIME DEFAULT CURRENT_TIMESTAMP")
    if "priority" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN priority INTEGER NOT NULL DEFAULT 5")
    if "extras" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN extras TEXT DEFAULT '{}'")
    if "inbound" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN inbound INTEGER NOT NULL DEFAULT 1")
    conn.execute("UPDATE messages SET ts = COALESCE(ts, CURRENT_TIMESTAMP)")
    conn.execute("UPDATE messages SET priority = COALESCE(priority, 5)")
    conn.execute("UPDATE messages SET extras = COALESCE(extras, '{}')")
    conn.execute("UPDATE messages SET inbound = COALESCE(inbound, 1)")

def init_db(path: str | None = None) -> None:
    with _lock, _db(path) as conn:
        _ensure_schema(conn)
        _migrate(conn)

def set_retention_days(days: int) -> None:
    days = int(max(1, days))
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('retention_days',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(days),),
        )

def get_retention_days() -> int:
    with _lock, _db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='retention_days'").fetchone()
        return int(row["value"]) if row else 30

def purge_older_than(days: int | None = None) -> int:
    if days is None:
        days = get_retention_days()
    with _lock, _db() as conn:
        cur = conn.execute("DELETE FROM messages WHERE ts < datetime('now', ?)", (f'-{int(days)} days',))
        return cur.rowcount

def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    try:
        extras = json.loads(r["extras"]) if r["extras"] else {}
    except Exception:
        extras = {}
    # convert ts (SQLite text like 'YYYY-MM-DD HH:MM:SS') to epoch (seconds)
    from datetime import datetime
    ts_v = r["ts"]
    try:
        if isinstance(ts_v, (int, float)):
            ts_epoch = int(ts_v)
        else:
            ts_epoch = int(datetime.fromisoformat(str(ts_v)).timestamp())
    except Exception:
        ts_epoch = 0
    return {
        "id": r["id"],
        "ts": ts_epoch,
        "title": r["title"],
        "body": r["body"],
        "source": r["source"],
        "priority": r["priority"],
        "extras": extras,
        "inbound": bool(r["inbound"]),
    }

def list_messages(limit: int = 100, offset: int = 0, q: str | None = None) -> List[Dict[str, Any]]:
    limit = int(max(1, min(500, limit)))
    offset = int(max(0, offset))
    with _lock, _db() as conn:
        if q:
            cur = conn.execute(
                "SELECT * FROM messages WHERE title LIKE ? OR body LIKE ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (f'%{q}%', f'%{q}%', limit, offset),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [_row_to_dict(r) for r in cur.fetchall()]

def save_message(title: str, body: str, source: str, priority: int = 5, extras: dict | None = None, inbound: int = 1) -> int:
    extras_json = json.dumps(extras or {}, ensure_ascii=False)
    with _lock, _db() as conn:
        cur = conn.execute(
            "INSERT INTO messages(title, body, source, priority, extras, inbound) VALUES(?,?,?,?,?,?)",
            (title, body, source, int(priority), extras_json, int(inbound)),
        )
        return int(cur.lastrowid)

def get_message(msg_id: int):
    with _lock, _db() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id=?", (int(msg_id),)).fetchone()
        return _row_to_dict(row) if row else None

def delete_message(msg_id: int) -> int:
    with _lock, _db() as conn:
        cur = conn.execute("DELETE FROM messages WHERE id=?", (int(msg_id),))
        return cur.rowcount
