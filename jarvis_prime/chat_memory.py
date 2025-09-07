#!/usr/bin/env python3
# /app/chat_memory.py
#
# Lightweight persistent chat history for Jarvis Prime.
# - Stores one JSON object per line (JSONL) for robustness.
# - Thread-safe appends.
# - Prunes to a moving window of the most recent N turns.
# - Defaults can be overridden by env:
#     CHAT_HISTORY_FILE (default: /data/chat_history.jsonl)
#     CHAT_HISTORY_MAX_TURNS (default: 24)
#
from __future__ import annotations
import os
import json
import time
import threading
from typing import List, Dict, Any, Optional

DEFAULT_PATH = os.getenv("CHAT_HISTORY_FILE", "/data/chat_history.jsonl")
DEFAULT_MAX_TURNS = int(os.getenv("CHAT_HISTORY_MAX_TURNS", "24"))

_lock = threading.Lock()

def _ensure_parent(path: str) -> None:
    try:
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass

def _read_all(path: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not path or not os.path.exists(path):
        return items
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append(obj)
                except Exception:
                    # skip corrupted lines
                    continue
    except Exception:
        pass
    return items

def _write_all(path: str, items: List[Dict[str, Any]]) -> None:
    _ensure_parent(path)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for obj in items:
                try:
                    f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                except Exception:
                    continue
        os.replace(tmp, path)
    except Exception:
        # best-effort; ignore errors
        pass

def append(role: str, content: str, *, path: str = DEFAULT_PATH, max_turns: Optional[int] = None) -> None:
    """Append a new chat turn and prune to the most recent max_turns *pairs* (user+assistant ~= 2 turns).
    If max_turns is None, uses DEFAULT_MAX_TURNS.
    """
    ts = int(time.time())
    rec = {"role": str(role or "user"), "content": str(content or ""), "ts": ts}
    with _lock:
        items = _read_all(path)
        items.append(rec)
        # prune by number of records (turns). Each message is one record.
        limit = DEFAULT_MAX_TURNS if max_turns is None else int(max_turns)
        if limit > 0 and len(items) > limit:
            items = items[-limit:]
        _write_all(path, items)

def recent(n: int, *, path: str = DEFAULT_PATH) -> List[Dict[str, Any]]:
    """Return the most recent n records (messages)."""
    if n <= 0:
        return []
    with _lock:
        items = _read_all(path)
    return items[-n:]

def all_history(*, path: str = DEFAULT_PATH) -> List[Dict[str, Any]]:
    with _lock:
        return _read_all(path)

def clear(*, path: str = DEFAULT_PATH) -> None:
    with _lock:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def size_bytes(*, path: str = DEFAULT_PATH) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0

def size_mb(*, path: str = DEFAULT_PATH) -> float:
    return round(size_bytes(path=path) / (1024 * 1024), 3)

if __name__ == "__main__":
    # quick self-test
    clear()
    append("user", "Hello, Jarvis!")
    append("assistant", "Hey! How can I help?", max_turns=24)
    print("recent 2:", recent(2))
    print("size MB:", size_mb())
