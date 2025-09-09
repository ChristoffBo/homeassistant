# /app/llm_memory.py - 24h rolling memory store
import os, json, datetime, re, threading

BASE = os.getenv("JARVIS_SHARE_BASE", "/share/jarvis_prime")
MEM_DIR = os.path.join(BASE, "memory")
MEM_FILE = os.path.join(MEM_DIR, "events.json")
_os_lock = threading.RLock()

def _load():
    try:
        with open(MEM_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def _save(events):
    os.makedirs(MEM_DIR, exist_ok=True)
    with open(MEM_FILE, "w") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)

def log_event(kind: str, source: str, title: str, body: str, meta: dict):
    ev = {
        "ts": datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"Z",
        "kind": (kind or "").lower(),
        "source": source or "",
        "title": title or "",
        "body": body or "",
        "meta": meta or {},
    }
    with _os_lock:
        events = _load()
        events.append(ev)
        _save(events)

def prune(older_than_hours=24):
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=older_than_hours)
    with _os_lock:
        events = _load()
        keep = []
        for e in events:
            try:
                ts = datetime.datetime.fromisoformat(e.get("ts","").replace("Z",""))
            except Exception:
                continue
            if ts >= cutoff:
                keep.append(e)
        _save(keep)

def _today_window():
    now = datetime.datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now

def summarize_today() -> str:
    start, end = _today_window()
    events = _load()
    today = []
    for e in events:
        try:
            ts = datetime.datetime.fromisoformat(e.get("ts","").replace("Z",""))
        except Exception:
            continue
        if start <= ts <= end:
            today.append(e)
    if not today:
        return "Nothing notable yet today."
    counts = {}
    for e in today:
        k = e.get("kind") or "other"
        counts[k] = counts.get(k,0)+1
    bullets = [f"- {k}: {v}" for k,v in sorted(counts.items(), key=lambda x:-x[1])[:6]]
    return "Today so far:\n" + "\n".join(bullets)

ERROR_PATTERNS = re.compile(r"\b(down|failed|error|unhealthy|alert|timeout)\b", re.I)

def what_broke_today() -> str:
    start, end = _today_window()
    events = _load()
    bad = []
    for e in events:
        try:
            ts = datetime.datetime.fromisoformat(e.get("ts","").replace("Z",""))
        except Exception:
            continue
        if start <= ts <= end:
            body = (e.get("body") or "") + " " + (e.get("title") or "")
            if ERROR_PATTERNS.search(body):
                bad.append(e)
    if not bad:
        return "No failures reported today."
    lines = []
    for e in bad[-12:]:
        lines.append(f"- {e.get('ts')} • {e.get('source') or e.get('kind')} • {e.get('title')[:80]}")
    return "Issues today:\n" + "\n".join(lines)
