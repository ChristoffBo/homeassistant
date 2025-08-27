# /app/beautify.py
# Jarvis Prime – Beautify Engine (7 stages)
# 1) INGEST     : take raw title/body + optional hints
# 2) DETECT     : identify source (sonarr/radarr/watchtower/qnap/unraid/speedtest/json/yaml/generic)
# 3) NORMALIZE  : harvest images, strip image text, prep initial facts
# 4) INTERPRET  : per-source synthesis (facts & content sections)
# 5) RENDER     : assemble Jarvis card sections (no inline images)
# 6) DEDUPE     : remove duplicated lines AND duplicated sentences
# 7) RESTORE IMG: attach a single hero image via extras.bigImageUrl
#
# Notes:
# - We NEVER put markdown images back into the body (prevents duplicates).
# - Gotify displays bigImageUrl across Web + Android as the one hero image.
# - Personality quips are added outside (in send_message), not here.

from __future__ import annotations
import json, re
from typing import Tuple, Optional, List, Dict

try:
    import yaml  # optional
except Exception:
    yaml = None

# ---------------------------
# Stage 0: shared regex & utils
# ---------------------------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)
PUNCT_SPLIT = re.compile(r'([.!?])')

LIKELY_POSTER_HOSTS = (
    "githubusercontent.com", "fanart.tv", "themoviedb.org", "image.tmdb.org",
    "trakt.tv", "tvdb.org", "gravatar.com"
)

def _prefer_host_key(url: str) -> int:
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").lower()
        return 0 if any(k in host for k in LIKELY_POSTER_HOSTS) else 1
    except Exception:
        return 1

def _first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        t = ln.strip()
        if t: return t
    return ""

def _normline(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r'^(info|message|note|status)\s*[:\-]\s*', '', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s)
    return s.lower()

def _dedup_lines(lines: List[str]) -> List[str]:
    seen = set(); out: List[str] = []
    for ln in lines:
        base = _normline(ln)
        if base and base not in seen:
            seen.add(base); out.append(ln)
        elif not base and (not out or out[-1] != ""):
            out.append("")  # single blank keeper
    while out and out[0] == "": out.pop(0)
    while out and out[-1] == "": out.pop()
    return out

def _dedup_sentences(text: str) -> str:
    # Split by punctuation, keep order, remove repeated sentences (case/space-insensitive)
    parts: List[str] = []
    buf = ""
    for piece in PUNCT_SPLIT.split(text):
        if PUNCT_SPLIT.fullmatch(piece):
            if buf:
                parts.append(buf + piece)
                buf = ""
        else:
            buf += piece
    if buf.strip():
        parts.append(buf)

    seen = set(); out: List[str] = []
    for frag in parts:
        norm = re.sub(r'\s+', ' ', frag.strip()).lower()
        if norm and norm not in seen:
            seen.add(norm); out.append(frag)
    return "".join(out)

def _lines(*chunks) -> List[str]:
    out: List[str] = []
    for c in chunks:
        if not c: continue
        if isinstance(c, (list, tuple)):
            out.extend([x for x in c if x is not None])
        else:
            out.append(c)
    return out

# ---------------------------
# Stage 1: INGEST
# ---------------------------
def _ingest(title: str, body: str, mood: str, source_hint: Optional[str]) -> Dict:
    return {
        "title": title or "",
        "body": body or "",
        "mood": (mood or "serious"),
        "hint": (source_hint or None),
    }

# ---------------------------
# Stage 2: DETECT
# ---------------------------
def _detect_source(t: str, b: str, hint: Optional[str]) -> str:
    tb = (t + " " + b).lower()
    if hint: return hint
    if "sonarr" in tb:      return "sonarr"
    if "radarr" in tb:      return "radarr"
    if "watchtower" in tb:  return "watchtower"
    if ("speedtest" in tb) or ("ookla" in tb): return "speedtest"
    if ("qnap" in tb) or ("nas name" in b.lower() and "qnap" in b.lower()): return "qnap"
    if "unraid" in tb:      return "unraid"
    # structured payloads
    if _looks_json(b):      return "json"
    if _looks_yaml(b):      return "yaml"
    return "generic"

# ---------------------------
# Stage 3: NORMALIZE
# - Pull out image URLs (remove from text)
# - Clean spacing
# - Provide a sorted, unique image list (poster-hosts preferred)
# ---------------------------
def _harvest_images(text: str) -> tuple[str, List[str]]:
    if not text:
        return "", []

    urls: List[str] = []

    def _md(m):
        urls.append(m.group(1))
        return ""

    text = MD_IMG_RE.sub(_md, text)

    def _bare(m):
        urls.append(m.group(1))
        return ""

    text = IMG_URL_RE.sub(_bare, text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    # unique, with preference
    seen = set(); uniq: List[str] = []
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen:
            seen.add(u); uniq.append(u)
    return text, uniq

# ---------------------------
# Stage 4: INTERPRET (per-source)
# ---------------------------
def _header(title: str) -> List[str]:
    return ["———————————————", f"📟 Jarvis Prime — {title.strip()}", "———————————————"]

def _kv(label: str, value: str) -> str:   return f"⏺ {label}: {value}"
def _section(s: str) -> str:              return f"📄 {s}"

def _interpret_generic(clean: str) -> List[str]:
    facts: List[str] = []
    first = _first_nonempty_line(clean)
    if first: facts.append(_kv("Info", first))
    lines = _lines(_header("Generic Message"), *facts)
    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if body_lines: lines += ["", _section("Message"), *body_lines]
    return lines

def _interpret_sonarr(clean: str) -> List[str]:
    facts: List[str] = []
    ts = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}.*\d{1,2}:\d{2})', clean)
    if ts: facts.append(_kv("Time", ts.group(1)))
    first = _first_nonempty_line(clean)
    if first: facts.append(_kv("Info", first))
    lines = _lines(_header("Generic Message"), *facts)
    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if body_lines: lines += ["", _section("Message"), *body_lines]
    return lines

def _interpret_radarr(clean: str) -> List[str]:
    facts: List[str] = []
    first = _first_nonempty_line(clean)
    if first: facts.append(_kv("Info", first))
    lines = _lines(_header("Generic Message"), *facts)
    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if body_lines: lines += ["", _section("Message"), *body_lines]
    return lines

def _interpret_watchtower(clean: str) -> List[str]:
    facts: List[str] = []
    low = clean.lower()
    if "no new images" in low: facts.append("• All containers up-to-date")
    if "updated" in low:      facts.append("• Containers updated")
    lines = _lines(_header("Watchtower Update"), *facts)
    if not facts: lines += ["", _section("Report"), clean]
    return lines

def _interpret_speedtest(clean: str) -> List[str]:
    dl = re.search(r'down(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    ul = re.search(r'up(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    pg = re.search(r'ping\D+([\d.]+)\s*ms', clean, re.I)
    facts: List[str] = []
    if pg: facts.append(_kv("Ping", f"{pg.group(1)} ms"))
    if dl: facts.append(_kv("Down", f"{dl.group(1)} {dl.group(2)}"))
    if ul: facts.append(_kv("Up", f"{ul.group(1)} {ul.group(2)}"))
    lines = _lines(_header("Speedtest"), *facts)
    if not facts: lines += ["", _section("Raw"), clean]
    return lines

def _interpret_qnap(clean: str) -> List[str]:
    facts: List[str] = []
    nas  = re.search(r'NAS Name:\s*(.+)', clean, re.I)
    when = re.search(r'(?:Date/Time|Date):\s*([^\n]+)', clean, re.I)
    if nas:  facts.append(_kv("NAS", nas.group(1).strip()))
    if when: facts.append(_kv("Time", when.group(1).strip()))
    first = _first_nonempty_line(clean)
    if first and not any(first in x for x in facts):
        facts.append(_kv("Info", first))
    lines = _lines(_header("QNAP Notice"), *facts)
    tail = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if tail: lines += ["", _section("Details"), *_dedup_lines(tail)]
    return lines

def _interpret_unraid(clean: str) -> List[str]:
    first = _first_nonempty_line(clean)
    facts = [_kv("Info", first)] if first else []
    return _lines(_header("Unraid Event"), *facts, "", _section("Details"), clean)

def _interpret_structured(kind: str, clean: str) -> List[str]:
    try:
        if kind == "json":
            obj = json.loads(clean)
            if isinstance(obj, dict) and 0 < len(obj) <= 10:
                bullets = [f"• {k}: {obj[k]}" for k in obj]
                return _lines(_header("JSON Payload"), "", *bullets)
    except Exception:
        pass
    if kind == "yaml" and yaml:
        try:
            obj = yaml.safe_load(clean)
            if isinstance(obj, dict) and 0 < len(obj) <= 10:
                bullets = [f"• {k}: {obj[k]}" for k in obj]
                return _lines(_header("YAML Payload"), "", *bullets)
        except Exception:
            pass
    # Fallback to generic if parsing not nice
    return _interpret_generic(clean)

# ---------------------------
# Stage 5: RENDER (assemble) – return text only here
# ---------------------------
def _render(lines: List[str]) -> str:
    # De-dup *lines*, join, then sentence de-dup (Stage 6 handled after)
    return "\n".join(_dedup_lines(lines)).strip()

# ---------------------------
# Stage 6/7: DEDUPE SENTENCES + RESTORE IMAGE (hero)
# ---------------------------
def _finalize(text: str, images: List[str]) -> Tuple[str, Optional[dict]]:
    text = _dedup_sentences(text)
    hero = images[0] if images else None
    extras = None
    if hero:
        extras = {
            "client::display": {"contentType": "text/markdown"},
            "client::notification": {"bigImageUrl": hero},
        }
    return text, extras

# ---------------------------
# Helpers: structured sniffers
# ---------------------------
def _looks_json(s: str) -> bool:
    try: json.loads(s); return True
    except Exception: return False

def _looks_yaml(s: str) -> bool:
    if not yaml: return False
    try:
        obj = yaml.safe_load(s)
        return isinstance(obj, (dict, list))
    except Exception:
        return False

# ---------------------------
# Public: the full pipeline
# ---------------------------
def beautify_message(title: str, body: str, *, mood: str = "serious", source_hint: str | None = None) -> Tuple[str, Optional[dict]]:
    # Stage 1: INGEST
    ctx = _ingest(title, body, mood, source_hint)

    # Early tiny payloads: wrap minimal
    if len(ctx["body"]) < 2 and not IMG_URL_RE.search(ctx["title"] + " " + ctx["body"]):
        return "\n".join(_dedup_lines(_lines(_header("Message"), ctx["body"]))).strip(), None

    # Stage 2: DETECT
    kind = _detect_source(ctx["title"], ctx["body"], ctx["hint"])

    # Stage 3: NORMALIZE (strip images from text, collect urls)
    clean, images = _harvest_images(ctx["body"])

    # Stage 4: INTERPRET (per source)
    if kind == "sonarr":       lines = _interpret_sonarr(clean)
    elif kind == "radarr":     lines = _interpret_radarr(clean)
    elif kind == "watchtower": lines = _interpret_watchtower(clean)
    elif kind == "speedtest":  lines = _interpret_speedtest(clean)
    elif kind == "qnap":       lines = _interpret_qnap(clean)
    elif kind == "unraid":     lines = _interpret_unraid(clean)
    elif kind in ("json", "yaml"):
        lines = _interpret_structured(kind, clean)
    else:
        lines = _interpret_generic(clean)

    # Stage 5: RENDER (text)
    text = _render(lines)

    # Stage 6 + 7: sentence de-dup + hero restore via extras
    return _finalize(text, images)
