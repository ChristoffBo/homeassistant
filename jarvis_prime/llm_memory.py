# /app/llm_memory.py
from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime

def _now() -> float:
    return time.time()

def _read(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return []

def _write(path: Path, data: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def store_event(path: Path, *, title: str, text: str):
    rows = _read(path)
    rows.append({"ts": _now(), "title": title, "text": text})
    _write(path, rows)

def flush_older_than(path: Path, *, hours: int = 24):
    rows = _read(path)
    if not rows:
        return
    cutoff = _now() - hours * 3600
    rows = [r for r in rows if r.get("ts", 0) >= cutoff]
    _write(path, rows)

def _today_rows(path: Path) -> list[dict]:
    rows = _read(path)
    if not rows:
        return []
    today = datetime.now().date()
    return [r for r in rows if datetime.fromtimestamp(r["ts"]).date() == today]

def summarize_today(path: Path) -> str:
    items = _today_rows(path)
    if not items:
        return "No events today."
    lines = []
    for r in items[-25:]:
        t = datetime.fromtimestamp(r["ts"]).strftime("%H:%M")
        lines.append(f"• {t} — {r.get('title', '')}")
    return "### Today\n" + "\n".join(lines)

def failures_today(path: Path) -> str:
    items = _today_rows(path)
    if not items:
        return "No failures detected today."
    bad = []
    for r in items:
        blob = (r.get("title","") + " " + r.get("text","")).lower()
        if any(x in blob for x in ("error", "failed", "down", "unhealthy", "critical", "panic", "timeout")):
            bad.append(r)
    if not bad:
        return "No failures detected today."
    lines = []
    for r in bad[-25:]:
        t = datetime.fromtimestamp(r["ts"]).strftime("%H:%M")
        lines.append(f"• {t} — {r.get('title', '')}")
    return "### Things that broke\n" + "\n".join(lines)
