# /app/beautify.py
# Jarvis Prime – Beautify Engine (8‑Stage, Strip‑Out Clean Formatter)
# Stages per spec:
# 1) Strip raw message → remove garbage, emojis, random noise.
# 2) Normalize formatting → fix spacing, punctuation, casing (lightweight).
# 3) Detect type (notify, log, Sonarr/Radarr, backup, apt, etc.).
# 4) Rebuild structure → transform into Jarvis‑style bullet points/cards.
# 5) Overlay persona → inject the active persona’s voice, quips, emojis (from personality.py).
# 6) Double‑check vs original → verify all important info still present; if missing, fallback to stage 2 and retry.
# 7) Fail‑safe → if still inconsistent, mark as “failed beautify” and push raw message.
# 8) Final render → beautified message with images/posters preserved, sent to UI + outputs.
#
from __future__ import annotations
import re, json, importlib, random
from typing import List, Tuple, Optional, Dict, Any

# ---------------------------
# Regex & helpers
# Additional critical patterns
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')
RFC2822_DT_RE = re.compile(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\b')
HOST_RE = re.compile(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b')
SIGNAL_LINE_RE = re.compile(r'(?i)\b(error|failed|failure|warning|reboot|restarted|updated|upgraded|packages|status|success|ok|critical|offline|online)\b')

# ---------------------------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)
PUNCT_SPLIT = re.compile(r'([.!?])')
TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
VER_RE = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')
KV_RE = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+?)\s*$')
YESNO_RE = re.compile(r'\b(?:YES|NO|TRUE|FALSE|SUCCESS|FAILED|ERROR|WARNING|OK)\b', re.I)
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001FA70-\U0001FAFF"
    "\U0001F1E6-\U0001F1FF"
    "]",
    flags=re.UNICODE
)

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

def _normline_for_dedupe(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r'^\s*\[?(info|message|note|status|debug|notice|warn|warning|error|err)\]?\s*[:\-]\s*', '', s, flags=re.I)
    s = re.sub(r'^\s*(DEBUG|INFO|NOTICE|WARN|WARNING|ERROR)\s*[:\-]\s*', '', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s)
    return s.lower()

def _dedup_lines(lines: List[str]) -> List[str]:
    seen = set(); out: List[str] = []
    for ln in lines:
        base = _normline_for_dedupe(ln)
        if base and base not in seen:
            seen.add(base); out.append(ln)
        elif not base and (not out or out[-1] != ""):
            out.append("")
    while out and out[0] == "": out.pop(0)
    while out and out[-1] == "": out.pop()
    return out

def _dedup_sentences(text: str) -> str:
    parts: List[str] = []; buf = ""
    for piece in PUNCT_SPLIT.split(text):
        if PUNCT_SPLIT.fullmatch(piece):
            if buf: parts.append(buf + piece); buf = ""
        else:
            buf += piece
    if buf.strip(): parts.append(buf)
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
# Stage 1: Strip raw message (garbage/emojis/noise)
# ---------------------------
_NOISE_LINE_RE = re.compile(r'^\s*(?:sent from .+|via .+ api|automated message|do not reply)\.?\s*$', re.I)

def _strip_noise(text: str, *, aggressive: bool = True) -> str:
    if not text: return ""
    s = text
    # remove emojis if aggressive
    if aggressive:
        s = EMOJI_RE.sub("", s)
    # drop known noise lines
    kept: List[str] = []
    for ln in s.splitlines():
        if _NOISE_LINE_RE.match(ln): continue
        kept.append(ln)
    s = "\n".join(kept)
    return s

# ---------------------------
# Stage 2: Normalize formatting
# ---------------------------
def _normalize(s: str) -> str:
    if not s: return ""
    s = s.replace("\t", "  ")
    # normalize bullets
    s = re.sub(r'^\s*[-*]\s*', '• ', s, flags=re.M)
    # trim trailing spaces
    s = re.sub(r'[ \t]+$', '', s, flags=re.M)
    # collapse spacing
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = re.sub(r' +', ' ', s)
    return s.strip()

# ---------------------------
# Stage 3: Detect type (lightweight)
# ---------------------------
def _looks_json(body: str) -> bool:
    try: json.loads(body); return True
    except Exception: return False

def _detect_type(title: str, body: str) -> str:
    tb = (title + " " + body).lower()
    if "sonarr" in tb: return "sonarr"
    if "radarr" in tb: return "radarr"
    if "watchtower" in tb: return "watchtower"
    if "apt" in tb or "dpkg" in tb: return "apt"
    if "backup" in tb or "restore" in tb: return "backup"
    if "error" in tb or "warning" in tb: return "log"
    if _looks_json(body): return "json"
    return "notify"

# ---------------------------
# Stage 4: Rebuild structure (Jarvis card)
# ---------------------------
def _harvest_timestamp(text: str, title: str) -> Optional[str]:
    for src in (text or "", title or ""):
        m = TS_RE.search(src)
        if m: return m.group(1).strip()
    return None

def _harvest_subject(title: str) -> Optional[str]:
    t = (title or "").strip()
    return t if t and not IMG_URL_RE.search(t) else None

def _extract_keyvals(text: str) -> List[Tuple[str,str]]:
    out: List[Tuple[str,str]] = []
    for ln in text.splitlines():
        m = KV_RE.match(ln)
        if m:
            k = m.group(1).strip(); v = m.group(2).strip()
            if k and v: out.append((k, v))
    return out

def _extract_tokens(text: str) -> List[str]:
    toks: List[str] = []
    toks += IP_RE.findall(text or "")
    toks += VER_RE.findall(text or "")
    toks += [m.group(0) for m in YESNO_RE.finditer(text or "")]
    return list(dict.fromkeys(toks))

def _header(kind: str) -> List[str]:
    title = {
        "sonarr": "Sonarr",
        "radarr": "Radarr",
        "watchtower": "Watchtower",
        "apt": "APT Update",
        "backup": "Backup",
        "log": "Log Event",
        "json": "JSON Notice",
        "notify": "Message",
    }.get(kind, "Message")
    return ["———————————————", f"📟 Jarvis Prime — {title}", "———————————————"]

def _kv(label: str, value: str) -> str:   return f"⏺ {label}: {value}"
def _section(s: str) -> str:              return f"📄 {s}"

def _rebuild(kind: str, title: str, body: str) -> List[str]:
    facts: List[str] = []
    ts = _harvest_timestamp(body, title)
    if ts: facts.append(_kv("Time", ts))
    subj = _harvest_subject(title)
    if subj: facts.append(_kv("Subject", subj))
    first = _first_nonempty_line(body)
    if first: facts.append(_kv("Info", first))

    # bullets from key‑values
    kvs = _extract_keyvals(body)
    bullets = [f"• {k}: {v}" for k,v in kvs]

    # minimal kind‑specific hints (no heavy parsing)
    if kind in ("apt","watchtower","backup","log") and not bullets:
        # scan for short status lines to bulletize
        for ln in body.splitlines():
            if YESNO_RE.search(ln) or re.search(r'\b(upgraded|updated|failed|success|reboot)\b', ln, re.I):
                bullets.append(f"• {ln.strip()}")

    lines = _lines(_header(kind), *facts)
    if bullets: lines += ["", _section("Facts"), *bullets]
    # message section (keep images inline)
    body_lines = [ln for ln in body.splitlines() if ln.strip() or ln.strip()==""]
    if body_lines: lines += ["", _section("Message"), *body_lines]
    return lines

# ---------------------------
# Stage 5: Overlay persona (from personality.py)
# ---------------------------
def _load_persona(persona_name: Optional[str]) -> Dict[str, Any]:
    if not persona_name: return {}
    key = (persona_name or "").strip().lower()
    if key in ("neutral","ops","operations","none"): return {}
    try:
        mod = importlib.import_module("personality")
        mod = importlib.reload(mod)
    except Exception:
        return {}
    try:
        if hasattr(mod, "get_persona"):
            data = mod.get_persona(key)
            if isinstance(data, dict): return data
    except Exception:
        pass
    for attr in ("PERSONAS","PERSONA_STYLES","STYLES","profiles","overlays"):
        data = getattr(mod, attr, None)
        if isinstance(data, dict) and data.get(key):
            obj = data.get(key)
            if isinstance(obj, dict): return obj
    return {}

def _apply_persona(text: str, persona: Optional[str], persona_quip: bool) -> str:
    data = _load_persona(persona)
    label = (data.get("label") or "").strip() if isinstance(data, dict) else ""
    quips = data.get("quips") if isinstance(data, dict) else None
    if not label: return text
    quip_line = ""
    if persona_quip and isinstance(quips, (list,tuple)) and quips:
        try: quip_line = f'“{random.choice(list(quips))}”'
        except Exception: quip_line = ""
    lines = text.splitlines()
    insert_at = 3 if len(lines) >= 3 and lines[0].startswith("—") and "Jarvis Prime" in lines[1] else 0
    overlay_lines = [label] + ([quip_line] if quip_line else [])
    new_lines = lines[:insert_at] + overlay_lines + lines[insert_at:]
    return "\n".join(new_lines)

# ---------------------------
# Stage 6: Double‑check vs original (two passes)
# ---------------------------

def _critical_from_original(orig: str) -> List[str]:
    crit: List[str] = []
    text = orig or ""

    # 1) Key:Value pairs
    for k,v in _extract_keyvals(text):
        crit.append(f"{k}: {v}")

    # 2) Timestamps / dates / times (multiple formats)
    crit += TS_RE.findall(text) or []
    crit += DATE_ONLY_RE.findall(text) or []
    crit += TIME_ONLY_RE.findall(text) or []
    crit += RFC2822_DT_RE.findall(text) or []

    # 3) IPs, versions, YES/NO tokens
    crit += _extract_tokens(text)

    # 4) Hostnames/domains that often identify the target
    crit += HOST_RE.findall(text)

    # 5) High-signal lines (errors, status, updates, reboot, packages)
    for ln in text.splitlines():
        if SIGNAL_LINE_RE.search(ln):
            crit.append(re.sub(r'\s+', ' ', ln.strip()))

    # 6) First non-empty line
    first = _first_nonempty_line(text)
    if first: crit.append(first)

    # Unique (order-preserving) by lowercase/space-normalized
    seen = set(); out = []
    for c in crit:
        n = re.sub(r'\s+', ' ', str(c).strip()).lower()
        if n and n not in seen:
            seen.add(n); out.append(str(c))
    return out


def _verify_contains(text: str, tokens: List[str]) -> List[str]:
    missing: List[str] = []
    H = re.sub(r'\s+',' ', text.strip()).lower()
    for c in tokens:
        n = re.sub(r'\s+',' ', c.strip()).lower()
        if n and n not in H:
            missing.append(c)
    return missing

# ---------------------------
# Stage 7/8: Finalize (fail‑safe + render)
# ---------------------------
def _collect_images(text: str) -> List[str]:
    urls: List[str] = []
    for m in MD_IMG_RE.finditer(text or ""): urls.append(m.group(1))
    for m in IMG_URL_RE.finditer(text or ""): urls.append(m.group(1))
    # unique w/ poster preference
    uniq = []; seen=set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen:
            seen.add(u); uniq.append(u)
    return uniq

def _finalize_render(lines: List[str]) -> str:
    return "\n".join(_dedup_lines(lines)).strip()

# ---------------------------
# Public API
# ---------------------------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: str | None = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True) -> Tuple[str, Optional[dict]]:
    # 1) Strip
    stripped = _strip_noise(body, aggressive=True)
    # 2) Normalize
    norm1 = _normalize(stripped)
    # 3) Detect
    kind = _detect_type(title, norm1)
    # 4) Rebuild
    lines = _rebuild(kind, title, norm1)
    text0 = _finalize_render(lines)
    # 5) Overlay persona
    with_overlay = _apply_persona(text0, persona, persona_quip)

    # 6) Verify vs original; if missing, retry using relaxed strip (fallback to Stage 2 and rebuild)
    crit = _critical_from_original(body)
    missing = _verify_contains(with_overlay, crit)
    verify_meta: Dict[str, Any] = {"passed": len(missing)==0, "missing": missing, "pass": 1}

    if missing:
        # Retry with relaxed strip (less emoji/noise removal)
        norm2 = _normalize(_strip_noise(body, aggressive=False))
        lines2 = _rebuild(kind, title, norm2)
        text1 = _finalize_render(lines2)
        with_overlay2 = _apply_persona(text1, persona, persona_quip)
        missing2 = _verify_contains(with_overlay2, crit)
        verify_meta = {"passed": len(missing2)==0, "missing": missing2, "pass": 2}
        final_text = with_overlay2
        # 7) Fail‑safe: still inconsistent → mark failed and push raw message
        if missing2:
            fail_header = ["———————————————", "📟 Jarvis Prime — Beautify Failed", "———————————————"]
            final_text = "\n".join(fail_header + ["", "📄 Raw Message", body.strip()])
            verify_meta["failed"] = True
    else:
        final_text = with_overlay

    # 8) Final render + images preserved
    images = _collect_images(body)  # preserve images exactly as in original
    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::allImageUrls": images,
        "jarvis::verify": verify_meta,
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}

    # sentence de‑dup at very end (keeps overlay + images intact)
    final_text = _dedup_sentences(final_text)

    return final_text, extras
