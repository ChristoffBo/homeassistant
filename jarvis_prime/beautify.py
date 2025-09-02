# /app/beautify.py
# Jarvis Prime — Beautify Engine (Clean bullets + Persona + Image-Preserving + Format Alignment Check)
# Stages:
# 1) Strip → remove emojis/boilerplate noise.
# 2) Normalize → tidy spacing/newlines.
# 3) Detect → light heuristics for card title.
# 4) Harvest images → strip image lines from body, keep list, set hero.
# 5) Rebuild → professional Markdown bullets (📄 Facts + 📄 Message).
# 6) Persona overlay → label/emoji/quip from personality.py under header.
# 7) Format alignment check → enforce bullet/section/header spacing and alignment.
# 8) Render → dedupe sentences; return with hero + allImageUrls in extras.
from __future__ import annotations
import re, json, importlib, random
from typing import List, Tuple, Optional, Dict, Any

# ---------- Regex ----------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)
PUNCT_SPLIT = re.compile(r'([.!?])')
TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')
IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
VER_RE = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')
KV_RE = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+?)\s*$')
YESNO_RE = re.compile(r'\b(?:YES|NO|TRUE|FALSE|SUCCESS|FAILED|ERROR|WARNING|OK)\b', re.I)
EMOJI_RE = re.compile("["
    "\U0001F300-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001FA70-\U0001FAFF"
    "\U0001F1E6-\U0001F1FF"
    "]", flags=re.UNICODE)
SIGNAL_LINE_RE = re.compile(r'(?i)\b(error|failed|failure|warning|reboot|restarted|updated|upgraded|packages|status|success|ok|critical|offline|online|ping|upload|download)\b')

LIKELY_POSTER_HOSTS = (
    "githubusercontent.com","fanart.tv","themoviedb.org","image.tmdb.org","trakt.tv","tvdb.org","gravatar.com"
)

# ---------- Utils ----------
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

def _dedup_sentences(text: str) -> str:
    parts: List[str] = []; buf = ""
    for piece in PUNCT_SPLIT.split(text):
        if PUNCT_SPLIT.fullmatch(piece):
            if buf: parts.append(buf + piece); buf = ""
        else:
            buf += piece
    if buf.strip(): parts.append(buf)
    seen=set(); out=[]
    for frag in parts:
        n = re.sub(r'\s+',' ', frag.strip()).lower()
        if n not in seen:
            seen.add(n); out.append(frag)
    return "".join(out)

# ---------- Stage 1: Strip ----------
_NOISE_LINE_RE = re.compile(r'^\s*(?:sent from .+|via .+ api|automated message|do not reply)\.?\s*$', re.I)
def _strip_noise(text: str) -> str:
    if not text: return ""
    s = EMOJI_RE.sub("", text)
    kept = [ln for ln in s.splitlines() if not _NOISE_LINE_RE.match(ln)]
    return "\n".join(kept)

# ---------- Stage 2: Normalize ----------
def _normalize(s: str) -> str:
    if not s: return ""
    s = s.replace("\t","  ")
    s = re.sub(r'[ \t]+$', '', s, flags=re.M)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

# ---------- Stage 3: Detect (light) ----------
def _looks_json(body: str) -> bool:
    try: json.loads(body); return True
    except Exception: return False
def _detect_type(title: str, body: str) -> str:
    tb = (title + " " + body).lower()
    if "speedtest" in tb: return "SpeedTest"
    if "apt" in tb or "dpkg" in tb: return "APT Update"
    if "watchtower" in tb: return "Watchtower"
    if "sonarr" in tb: return "Sonarr"
    if "radarr" in tb: return "Radarr"
    if _looks_json(body): return "JSON"
    if "error" in tb or "warning" in tb: return "Log Event"
    return "Message"

# ---------- Stage 4a: Harvest images ----------
def _harvest_images(text: str) -> Tuple[str, List[str]]:
    if not text: return "", []
    urls: List[str] = []
    def _md(m):
        urls.append(m.group(1)); return ""
    text = MD_IMG_RE.sub(_md, text)
    def _bare(m):
        urls.append(m.group(1)); return ""
    text = IMG_URL_RE.sub(_bare, text)
    uniq=[]; seen=set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen:
            seen.add(u); uniq.append(u)
    return text.strip(), uniq

# ---------- Stage 4b: Rebuild (neat bullets) ----------
def _header(kind: str) -> List[str]:
    return ["———————————————", f"📟 Jarvis Prime — {kind}", "———————————————"]
def _kv(label: str, value: str) -> str: return f"- {label}: {value}"
def _b(line: str) -> str: return f"- {line}"

def _harvest_timestamp(text: str, title: str) -> Optional[str]:
    for src in (text or "", title or ""):
        for rx in (TS_RE, DATE_ONLY_RE, TIME_ONLY_RE):
            m = rx.search(src)
            if m: return m.group(0).strip()
    return None

def _extract_keyvals(text: str) -> List[Tuple[str,str]]:
    out: List[Tuple[str,str]] = []
    for ln in (text or "").splitlines():
        m = KV_RE.match(ln)
        if m:
            k = m.group(1).strip(); v = m.group(2).strip()
            if k and v: out.append((k, v))
    return out

def _bullet_card(kind: str, title: str, body: str) -> List[str]:
    bullets: List[str] = []
    ts = _harvest_timestamp(body, title)
    if ts: bullets.append(_kv("Time", ts))
    if title.strip(): bullets.append(_kv("Subject", title.strip()))
    first = _first_nonempty_line(body)
    if first and first != title.strip(): bullets.append(_kv("Info", first))

    for k,v in _extract_keyvals(body): bullets.append(_kv(k, v))

    # Also bulletize short signal lines
    for ln in (body or "").splitlines():
        if KV_RE.match(ln): continue
        if SIGNAL_LINE_RE.search(ln): bullets.append(_b(ln.strip()))

    # Fallback: basic lines if nothing collected
    if not bullets:
        for ln in (body or "").splitlines():
            t = ln.strip()
            if t: bullets.append(_b(t))
            if len(bullets) >= 10: break

    lines = _header(kind) + ["", "📄 Facts", *bullets]
    return lines

# ---------- Stage 5: Persona overlay ----------
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

def _apply_persona(lines: List[str], persona: Optional[str], persona_quip: bool) -> List[str]:
    data = _load_persona(persona)
    label = (data.get("label") or "").strip() if isinstance(data, dict) else ""
    emoji = (data.get("emoji") or "").strip() if isinstance(data, dict) else ""
    quips = data.get("quips") if isinstance(data, dict) else None

    overlay = []
    if emoji or label:
        overlay.append(f"{emoji} {label}".strip())
    if persona_quip and isinstance(quips,(list,tuple)) and quips:
        try: overlay.append(f'“{random.choice(list(quips))}”')
        except Exception: pass

    if not overlay: return lines
    insert_at = 3 if len(lines) >= 3 and lines[0].startswith("—") and "Jarvis Prime" in lines[1] else 0
    return lines[:insert_at] + overlay + lines[insert_at:]

# ---------- Stage 7: Format alignment check ----------
def _format_align_check(text: str) -> str:
    # Ensure header separation and bullet alignment
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Ensure there is an empty line after header ruler section
    if len(lines) >= 3 and lines[0].startswith("—") and "Jarvis Prime" in lines[1]:
        if (len(lines) == 3) or (lines[3].strip() != ""):
            lines = lines[:3] + [""] + lines[3:]
    # Normalize bullets to "- " (not "• ")
    for i, ln in enumerate(lines):
        if re.match(r'^\s*[•*]\s+', ln):
            lines[i] = re.sub(r'^\s*[•*]\s+', '- ', ln)
        elif re.match(r'^\s*-\s*', ln):
            # keep "- "; collapse extra spaces after "-"
            lines[i] = re.sub(r'^\s*-\s*', '- ', ln, count=1)
    # Ensure section titles are not duplicated and spaced
    out: List[str] = []
    prev_blank = False
    for ln in lines:
        if ln.strip() == "" and prev_blank:
            continue
        out.append(ln)
        prev_blank = (ln.strip() == "")
    return "\n".join(out).strip()

# ---------- Stage 8: Public API ----------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: str | None = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True) -> Tuple[str, Optional[dict]]:
    # 1) Strip + 2) Normalize
    stripped = _strip_noise(body)
    normalized = _normalize(stripped)

    # 3) Detect
    kind = _detect_type(title, normalized)

    # 4) Images
    text_wo_imgs, images = _harvest_images(normalized)

    # 5) Rebuild
    lines = _bullet_card(kind, title, text_wo_imgs)

    # 6) Persona overlay
    lines = _apply_persona(lines, persona, persona_quip)

    # 7) Format alignment check
    text = _format_align_check("\n".join(lines))

    # 8) Render
    text = _dedup_sentences(text)
    extras: Dict[str, Any] = {"client::display": {"contentType": "text/markdown"},
                              "jarvis::allImageUrls": images}
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}
    return text, extras
