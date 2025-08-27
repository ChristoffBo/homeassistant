# /app/beautify.py
# Unified beautifier for Jarvis Prime.
# Five-layer pipeline:
#   1) Ingest   2) Detect   3) Normalize   4) Interpret   5) Render
#
# Works out-of-the-box for unknown sources. Can be extended at runtime via
# /data/beautify_rules.yaml (optional). If rules file is missing or invalid,
# builtin detectors/normalizers still run.
#
# Public entrypoint:
#   beautify_message(title, body, *, mood="serious", source_hint=None, extras=None, now=None, config=None)
# -> returns (final_text: str, final_extras: dict|None)

from __future__ import annotations
import re, json, os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# YAML is optional; we fail soft if not present.
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

# -----------------------------
# Constants & shared lookups
# -----------------------------

DIV = "━━━━━━━━━━━━━━━━━━━━━━━━━━"
DEFAULT_TIME_FMT = "%Y-%m-%d %H:%M"

ICON_BY_CATEGORY = {
    "system": "🖥",
    "media": "🎬",
    "network": "📡",
    "dns": "🧬",
    "storage": "🗄",
    "update": "🐧",
    "digest": "📰",
    "home": "🏠",
    "generic": "🤖",
}

CATEGORY_TITLES = {
    "system": "System Report",
    "media": "Media Report",
    "network": "Network Report",
    "dns": "DNS Summary",
    "storage": "Storage Report",
    "update": "Update Report",
    "digest": "Daily Digest",
    "home": "Home Report",
    "generic": "Message",
}

# Mood tinting – keeps a consistent vibe without needing personality.py
MOOD_PREFIX = {
    "serious": "🛡",
    "calm": "💡",
    "excited": "🚀",
    "angry": "🔥",
    "sarcastic": "😏",
    "playful": "✨",
    "tired": "😴",
    "depressed": "🌑",
    "ai": "🧠",
}

# Rules file path (optional)
RULES_PATH = "/data/beautify_rules.yaml"

# -----------------------------
# Utilities
# -----------------------------

def _now(dt: Optional[datetime]) -> datetime:
    return dt or datetime.now()

def _first_nonempty(lines: List[str]) -> str:
    for ln in lines:
        s = ln.strip()
        if s:
            return s
    return ""

def _clip_lines(txt: str, max_lines: int = 200) -> str:
    # protect against accidental huge payloads
    lines = txt.splitlines()
    if len(lines) <= max_lines:
        return txt
    return "\n".join(lines[:max_lines] + ["…"])

def _try_json(s: str) -> Optional[Any]:
    try:
        return json.loads(s)
    except Exception:
        return None

def _try_yaml(s: str) -> Optional[Any]:
    if not yaml:
        return None
    try:
        return yaml.safe_load(s)
    except Exception:
        return None

def _strip_patterns(text: str, patterns: List[str]) -> str:
    out = text
    for pat in patterns:
        try:
            out = re.sub(pat, "", out, flags=re.IGNORECASE)
        except Exception:
            pass
    # drop excessive blank lines
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out

def _pick_icon(category: str, fallback: str = "🤖") -> str:
    return ICON_BY_CATEGORY.get(category, fallback)

def _mood_prefix(mood: str) -> str:
    return MOOD_PREFIX.get(str(mood or "serious").lower(), "🧠")

def _as_facts(obj: Any, limit: int = 8) -> List[Tuple[str, str]]:
    # Convert small dicts into key/value list for display
    facts: List[Tuple[str, str]] = []
    if isinstance(obj, dict):
        for i, (k, v) in enumerate(obj.items()):
            if i >= limit:
                break
            facts.append((str(k), str(v)))
    return facts

# -----------------------------
# Rules loading (optional)
# -----------------------------

_loaded_rules: Dict[str, Any] = {}
_rules_mtime: float = -1.0

def _load_rules_if_changed(path: str = RULES_PATH) -> Dict[str, Any]:
    global _loaded_rules, _rules_mtime
    try:
        st = os.stat(path)
        if st.st_mtime != _rules_mtime:
            if not yaml:
                return _loaded_rules
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                _loaded_rules = data
                _rules_mtime = st.st_mtime
    except FileNotFoundError:
        _loaded_rules = {}
    except Exception:
        # fail soft
        pass
    return _loaded_rules

# -----------------------------
# Data containers
# -----------------------------

class Norm:
    """Normalized message fields Jarvis understands."""
    def __init__(self) -> None:
        self.category: str = "generic"
        self.source: str = "Generic"
        self.host: Optional[str] = None
        self.timestamp: Optional[str] = None  # ISO-ish string
        self.severity: str = "info"           # info | warn | crit
        self.title: Optional[str] = None
        self.summary: Optional[str] = None
        self.facts: List[Tuple[str, str]] = []
        self.image_url: Optional[str] = None
        self.actions: List[Dict[str, str]] = []

# -----------------------------
# DETECTION
# -----------------------------

def _detect_builtin(title: str, body: str, source_hint: Optional[str]) -> Dict[str, Any]:
    t = (title or "").lower()
    b = (body or "").lower()
    hint = (source_hint or "").lower()

    # ARR JSON fingerprint
    js = _try_json(body)
    if isinstance(js, dict) and ("movie" in js or "series" in js or "release" in js):
        return {"source": "ARR", "category": "media", "icon": "🎬"}

    # Speedtest
    if any(x in t for x in ("speedtest", "ookla")) or "ping" in b and "download" in b and "upload" in b:
        return {"source": "SpeedTest", "category": "network", "icon": "📡"}

    # Watchtower
    if "watchtower" in t or "watchtower" in b:
        return {"source": "Watchtower", "category": "update", "icon": "🐳"}

    # QNAP / NAS
    if "[qnap" in t or "qnap systems" in b or re.search(r"\bNAS Name:\b", body):
        return {"source": "QNAP", "category": "storage", "icon": "🗄"}

    # Unraid
    if "unraid" in t or "unraid" in b:
        return {"source": "Unraid", "category": "storage", "icon": "🗄"}

    # Proxmox
    if "proxmox" in t or "pve" in b:
        return {"source": "Proxmox", "category": "system", "icon": "🖥"}

    # Technitium / DNS
    if "technitium" in t or "technitium" in b or re.search(r"\b(dns queries|blocked|failures)\b", b):
        return {"source": "Technitium", "category": "dns", "icon": "🧬"}

    # Home Assistant
    if "homeassistant" in t or "home assistant" in b:
        return {"source": "HomeAssistant", "category": "home", "icon": "🏠"}

    # SMTP/mail generic
    if "subject" in t or "mail" in hint:
        return {"source": "Mail", "category": "system", "icon": "✉️"}

    # Proxy/generic
    if "proxy" in hint:
        return {"source": "Proxy", "category": "system", "icon": "🔀"}

    # Fallback
    return {"source": "Generic", "category": "generic", "icon": "🤖"}

def _detect_with_rules(title: str, body: str, source_hint: Optional[str], rules: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a dict with keys {source, category, icon, strip:[...]} if a rule matches."""
    try:
        dets = rules.get("detectors") or []
        for rule in dets:
            mt = rule.get("match", {})
            ok = True
            if "title" in mt:
                if not re.search(mt["title"], title or "", flags=re.IGNORECASE):
                    ok = False
            if ok and "body" in mt:
                if not re.search(mt["body"], body or "", flags=re.IGNORECASE):
                    ok = False
            if ok and "hint" in mt and source_hint is not None:
                if not re.search(mt["hint"], source_hint or "", flags=re.IGNORECASE):
                    ok = False
            if not ok:
                continue
            setv = rule.get("set", {})
            out = {
                "source": setv.get("source", "Generic"),
                "category": setv.get("category", "generic"),
                "icon": setv.get("icon", _pick_icon(setv.get("category", "generic"))),
            }
            if "strip" in setv and isinstance(setv["strip"], list):
                out["strip"] = list(setv["strip"])
            # Attach any extractor definitions for the normalizer stage
            if "extract" in rule:
                out["extract"] = rule["extract"]
            return out
    except Exception:
        pass
    return None

# -----------------------------
# NORMALIZATION
# -----------------------------

_QNAP_FOOTER = [
    r"©\s*\d{4}\s*QNAP Systems, Inc\.!?",
    r"To configure notification rules.*",  # long boilerplate
]

def _norm_arr(js: dict) -> Norm:
    n = Norm()
    n.category, n.source = "media", "ARR"
    movie = js.get("movie") or {}
    series = js.get("series") or {}
    rel = js.get("release") or {}
    ep = js.get("episode") or {}

    # Poster
    poster = None
    images = (movie.get("images") or series.get("images") or [])
    for i in images:
        if str(i.get("coverType", "")).lower() == "poster" and i.get("url"):
            poster = i["url"]; break
    n.image_url = poster

    # Title & summary
    if movie:
        name = movie.get("title") or "Unknown Movie"
        year = movie.get("year") or ""
        n.title = f"{name} ({year})"
        n.summary = rel.get("quality") or "New movie event"
        runtime = movie.get("runtime") or 0
        size = rel.get("size") or ""
        n.facts = [("Runtime", f"{runtime}m" if runtime else "?"),
                   ("Quality", str(rel.get("quality") or "?")),
                   ("Size", _fmt_size(size) if size else "?")]
    elif series:
        sname = series.get("title") or "Unknown Series"
        season = int(ep.get("seasonNumber") or 0)
        enum = int(ep.get("episodeNumber") or 0)
        n.title = f"{sname} • S{season:02}E{enum:02}"
        n.summary = ep.get("title") or "New episode event"
        runtime = ep.get("runtime") or 0
        size = rel.get("size") or ""
        n.facts = [("Runtime", f"{runtime}m" if runtime else "?"),
                   ("Quality", str(rel.get("quality") or "?")),
                   ("Size", _fmt_size(size) if size else "?")]
    return n

def _fmt_size(v: Any) -> str:
    try:
        num = float(v)
        for unit in ["B","KB","MB","GB","TB","PB"]:
            if num < 1024.0:
                return f"{num:0.1f}{unit}"
            num /= 1024.0
    except Exception:
        pass
    return str(v)

def _extract_first(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip()

def _norm_qnap(title: str, body: str) -> Norm:
    clean = _strip_patterns(body, _QNAP_FOOTER)
    n = Norm()
    n.category, n.source = "storage", "QNAP"
    n.title = "[QNAP] Notification"
    n.host = _extract_first(r"NAS Name:\s*(.+)", clean) or _extract_first(r"\[(.+?)\]", title) or None
    ts = _extract_first(r"Date/Time:\s*([0-9/:\- ]+)", clean)
    if ts:
        n.timestamp = ts.replace("/", "-").strip()
    # summary = first meaningful sentence
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    # drop lines that are headers repeating the title
    if lines and lines[0].startswith("[") and lines[0].endswith("]"):
        lines = lines[1:]
    n.summary = _first_nonempty(lines[0:3])
    # facts – show host/time if present
    if n.host: n.facts.append(("Host", n.host))
    if n.timestamp: n.facts.append(("Time", n.timestamp))
    return n

def _norm_speedtest(title: str, body: str) -> Norm:
    n = Norm()
    n.category, n.source = "network", "SpeedTest"
    n.title = "Speed Test Result"
    ping = _extract_first(r"ping[:=]\s*([\d\.]+)\s*ms", body) or _extract_first(r"Ping:\s*([\d\.]+)", body)
    down = _extract_first(r"download[:=]\s*([\d\.]+)\s*(?:mbps|mib/s|mibps|mb/s)", body) or _extract_first(r"Download:\s*([\d\.]+)", body)
    up = _extract_first(r"upload[:=]\s*([\d\.]+)\s*(?:mbps|mib/s|mibps|mb/s)", body) or _extract_first(r"Upload:\s*([\d\.]+)", body)
    if ping: n.facts.append(("Ping", f"{ping} ms"))
    if down: n.facts.append(("Down", f"{down} Mbps"))
    if up: n.facts.append(("Up", f"{up} Mbps"))
    n.summary = "Throughput snapshot"
    return n

def _norm_watchtower(title: str, body: str) -> Norm:
    n = Norm()
    n.category, n.source = "update", "Watchtower"
    n.title = "Container Update"
    # crude cues
    if "no updates" in body.lower() or "up to date" in body.lower():
        n.summary = "All images up to date"
        n.severity = "info"
    else:
        n.summary = "Containers updated"
    # small facts list (first few changed images)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    changed = [ln for ln in lines if re.search(r"(updated|new image|pulled)", ln, re.IGNORECASE)]
    for ln in changed[:6]:
        n.facts.append(("Change", ln))
    return n

def _norm_generic(title: str, body: str, source: str, category: str) -> Norm:
    n = Norm()
    n.category, n.source = category, source
    n.title = title.strip() or f"{source} {CATEGORY_TITLES.get(category,'Message')}"
    body = _clip_lines(body or "", 200)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    # Summary: first meaningful line
    n.summary = _first_nonempty(lines[:3])
    # Facts: if JSON/YAML and small, render as bullets
    js = _try_json(body)
    if isinstance(js, dict) and 0 < len(js) <= 10:
        n.facts = _as_facts(js, limit=8)
    else:
        y = _try_yaml(body)
        if isinstance(y, dict) and 0 < len(y) <= 10:
            n.facts = _as_facts(y, limit=8)
        else:
            # Otherwise, pick up to 4 short lines as facts
            for ln in lines[:4]:
                if len(ln) <= 120:
                    key = "Info"
                    if ":" in ln and len(ln.split(":")[0]) <= 24:
                        key, ln = ln.split(":", 1)
                    n.facts.append((key.strip().title(), ln.strip()))
    return n

# -----------------------------
# INTERPRETATION
# -----------------------------

def _interpret(n: Norm) -> str:
    # Basic heuristics; rules file can augment (see _interpret_with_rules)
    if n.category == "update":
        if any("up to date" in v.lower() for _, v in n.facts) or (n.summary and "up to date" in n.summary.lower()):
            return "Nothing to pull — all images are current."
        return "Updates applied successfully."
    if n.category == "dns":
        # try to infer ratios
        total = _get_num(n.facts, ("Total", "Total Queries", "Queries"))
        blocked = _get_num(n.facts, ("Blocked",))
        if total and blocked is not None and total > 0:
            pct = int(round((blocked / total) * 100))
            if pct >= 60: return "Blocking rate is strong — ad load minimal."
            if pct >= 30: return "Blocking active — within normal ranges."
            return "Low blocking percentage — check upstream lists?"
        return "DNS traffic within observed ranges."
    if n.category == "network":
        down = _get_num(n.facts, ("Down", "Download"))
        up   = _get_num(n.facts, ("Up", "Upload"))
        if down and up:
            if down > 400: return "Throughput excellent — green across the board."
            if down > 100: return "Throughput healthy for daily operations."
            return "Throughput modest — investigate if persistent."
        return "Network snapshot captured."
    if n.category == "storage":
        return "Storage system reported an event; no anomalies detected." if n.severity == "info" else "Storage attention may be required."
    if n.category == "media":
        return "Media event processed — enjoy the show 🍿."
    if n.category == "digest":
        return "Daily systems overview compiled."
    return "Message received and archived. No anomalies detected."

def _interpret_with_rules(n: Norm, rules: Dict[str, Any]) -> Optional[str]:
    try:
        ints = rules.get("interpret") or []
        # very small DSL: conditions on (category, source, facts/summary text contains)
        for rule in ints:
            when = rule.get("when", {})
            ok = True
            if "category" in when and n.category != when["category"]:
                ok = False
            if ok and "source" in when and n.source != when["source"]:
                ok = False
            if ok and "summary_contains" in when:
                if not n.summary or when["summary_contains"].lower() not in n.summary.lower():
                    ok = False
            if ok and "fact_key" in when and "fact_value_contains" in when:
                val = _get_fact_value(n.facts, when["fact_key"])
                if not val or when["fact_value_contains"].lower() not in val.lower():
                    ok = False
            if not ok:
                continue
            say = rule.get("say")
            if say:
                return str(say)
    except Exception:
        pass
    return None

def _get_fact_value(facts: List[Tuple[str, str]], key: str) -> Optional[str]:
    k = key.lower()
    for fk, fv in facts:
        if fk.lower() == k:
            return fv
    return None

def _get_num(facts: List[Tuple[str, str]], keys: Tuple[str, ...]) -> Optional[float]:
    for k in keys:
        v = _get_fact_value(facts, k)
        if v is None:
            continue
        try:
            # extract leading number
            m = re.search(r"[-+]?\d*\.?\d+", v.replace(",", ""))
            if m:
                return float(m.group(0))
        except Exception:
            pass
    return None

# -----------------------------
# RENDERING
# -----------------------------

def _render(n: Norm, *, mood: str, now: Optional[datetime]) -> Tuple[str, Optional[Dict[str, Any]]]:
    icon = _pick_icon(n.category)
    mood_tag = _mood_prefix(mood)
    ts = n.timestamp or _now(now).strftime(DEFAULT_TIME_FMT)

    lines: List[str] = []
    lines.append(f"{icon} Jarvis Prime — {n.source} {CATEGORY_TITLES.get(n.category, 'Message')}")
    lines.append(DIV)
    # Header facts
    if n.host: lines.append(f"📟 Host: {n.host}")
    if ts:     lines.append(f"🕒 Time: {ts}")

    # Facts list
    if n.facts:
        for k, v in n.facts:
            lines.append(f"🔹 {k}: {v}")

    # Summary
    if n.summary:
        lines.append("") if lines[-1] != "" else None
        lines.append(f"🧾 {n.summary}")

    # Interpretation
    interpret = _interpret(n)
    # Merge rule-based override if present
    rules = _load_rules_if_changed()
    rule_interpret = _interpret_with_rules(n, rules)
    if rule_interpret:
        interpret = rule_interpret

    lines.append("")
    lines.append(f"{mood_tag} {interpret}")
    lines.append(f"Mood: {mood.strip() if mood else 'serious'}")
    lines.append(DIV)
    lines.append("— Jarvis Neural Core")

    # Extras (poster/big image)
    extras = None
    if n.image_url:
        extras = {"client::notification": {"bigImageUrl": n.image_url}}

    return "\n".join(lines), extras

# -----------------------------
# PUBLIC ENTRYPOINT
# -----------------------------

def beautify_message(
    title: str,
    body: str,
    *,
    mood: str = "serious",
    source_hint: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Main call used by bot.py / smtp_server.py / proxy.py.
    Returns (final_text, final_extras).
    """
    title = (title or "").strip()
    body = _clip_lines(body or "", 200)

    # Layer 1: Ingest – inputs already gathered

    # Layer 2: Detect – rules first, then builtin
    rules = _load_rules_if_changed()
    det = _detect_with_rules(title, body, source_hint, rules) or _detect_builtin(title, body, source_hint)
    source = det.get("source", "Generic")
    category = det.get("category", "generic")
    strip_patterns = det.get("strip", [])

    if strip_patterns:
        body = _strip_patterns(body, strip_patterns)

    # Layer 3: Normalize
    n: Norm
    js = _try_json(body)
    if isinstance(js, dict) and source == "ARR":
        n = _norm_arr(js)
    elif source == "QNAP":
        n = _norm_qnap(title, body)
    elif source == "SpeedTest":
        n = _norm_speedtest(title, body)
    elif source == "Watchtower":
        n = _norm_watchtower(title, body)
    else:
        n = _norm_generic(title, body, source, category)

    # Layer 4: Interpret – done in renderer using heuristics + optional rules

    # Layer 5: Render – unified Jarvis card
    final_text, ex = _render(n, mood=mood, now=now)

    # Merge caller extras (e.g., posters from ARR routing) *without* overriding our bigImage if we already set one.
    if extras:
        ex = ex or {}
        # Respect existing bigImageUrl if we already found a poster
        if isinstance(ex, dict):
            existing = ((ex.get("client::notification") or {}).get("bigImageUrl"))
            incoming = ((extras.get("client::notification") or {}).get("bigImageUrl"))
            if not existing and incoming:
                ex.setdefault("client::notification", {})["bigImageUrl"] = incoming
            # Merge all other keys shallowly
            for k, v in extras.items():
                if k == "client::notification":
                    continue
                ex[k] = v

    return final_text, ex
