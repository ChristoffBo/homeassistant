#!/usr/bin/env python3
"""
SQLite storage for Jarvis Prime Inbox & settings.
Tables:
  - messages(id INTEGER PRIMARY KEY, ts INTEGER, source TEXT, title TEXT, body TEXT,
             meta TEXT, delivered TEXT)
  - settings(key TEXT PRIMARY KEY, value TEXT)
"""
from __future__ import annotations
import os, json, sqlite3, time, threading
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.getenv("JARVIS_DB_PATH", "/data/jarvis.db")
_init_lock = threading.RLock()

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    with _init_lock:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER NOT NULL,
              source TEXT NOT NULL,
              title TEXT NOT NULL,
              body TEXT,
              meta TEXT,
              delivered TEXT
            )""")
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts DESC)
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS settings(
              key TEXT PRIMARY KEY,
              value TEXT
            )""")
            conn.commit()
        finally:
            conn.close()

def save_message(source: str, title: str, body: str, *, meta: Optional[Dict[str, Any]] = None,
                 delivered: Optional[Dict[str, Any]] = None, ts: Optional[int] = None) -> int:
    ts = int(ts or time.time())
    rec = (ts, source or "unknown", title or "(no title)", body or "",
           json.dumps(meta or {}, ensure_ascii=False),
           json.dumps(delivered or {}, ensure_ascii=False))
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO messages(ts,source,title,body,meta,delivered) VALUES(?,?,?,?,?,?)
        """, rec)
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()

def get_message(mid: int) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM messages WHERE id=?", (mid,))
        row = cur.fetchone()
        if not row: return None
        return dict(row)
    finally:
        conn.close()

def delete_message(mid: int) -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE id=?", (mid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def search_messages(q: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        if q:
            like = f"%{q}%"
            cur.execute("""
              SELECT * FROM messages
              WHERE title LIKE ? OR body LIKE ? OR source LIKE ?
              ORDER BY ts DESC LIMIT ?
            """, (like, like, like, int(limit)))
        else:
            cur.execute("""
              SELECT * FROM messages ORDER BY ts DESC LIMIT ?
            """, (int(limit),))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def purge_older_than(days: int) -> int:
    cutoff = int(time.time() - days*86400)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()

def get_setting(key: str, default: Any = None) -> Any:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        if row is None: return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]
    finally:
        conn.close()

def set_setting(key: str, value: Any) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("REPLACE INTO settings(key,value) VALUES(?,?)",
                    (key, json.dumps(value)))
        conn.commit()
    finally:
        conn.close()
