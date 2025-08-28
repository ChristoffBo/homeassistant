import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

MEM_DIR = Path("/share/jarvis_prime/memory")
EVENTS = MEM_DIR / "events.json"

def _now() -> int:
    return int(time.time())

def ensure_store() -> None:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    if not EVENTS.exists():
        EVENTS.write_text("[]", encoding="utf-8")

def _read() -> List[Dict[str, Any]]:
    ensure_store()
    try:
        return json.loads(EVENTS.read_text(encoding="utf-8"))
    except Exception:
        return []

def _write(rows: List[Dict[str, Any]]) -> None:
    EVENTS.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

def prune_older_than(hours: int = 24) -> None:
    rows = _read()
    cutoff = _now() - hours * 3600
    rows = [r for r in rows if isinstance(r, dict) and r.get("ts", 0) >= cutoff]
    _write(rows)

def log_event(source: str, title: str, body: str, tags: Optional[List[str]] = None, hours: int = 24) -> None:
    ensure_store()
    prune_older_than(hours)
    rows = _read()
    rows.append({
        "ts": _now(),
        "source": source,
        "title": title,
        "body": body,
        "tags": tags or []
    })
    _write(rows)

def query_today(keyword_any: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    ensure_store()
    prune_older_than(24)
    rows = _read()
    start = _now() - 24 * 3600
    out = [r for r in rows if r.get("ts", 0) >= start]
    if keyword_any:
        low = [k.lower() for k in keyword_any]
        def match(r):
            blob = f"{r.get('title','')} {r.get('body','')}".lower()
            return any(k in blob for k in low)
        out = [r for r in out if match(r)]
    return out
