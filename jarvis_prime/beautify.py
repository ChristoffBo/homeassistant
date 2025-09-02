# /app/beautify.py
# Jarvis Prime — Beautify Engine (polished, persona-aware)
from __future__ import annotations
import re, json, importlib, random
from typing import List, Tuple, Optional, Dict, Any

# -------- Regex --------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)
PUNCT_SPLIT = re.compile(r'([.!?])')
TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')
# Strict IPv4 (0-255 each octet)
IP_RE = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b')
HOST_RE = re.compile(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b')
VER_RE = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')
KV_RE = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+?)\s*$')
SIGNAL_LINE_RE = re.compile(r'(?i)\b(error|failed|failure|warning|reboot|restarted|updated|upgraded|packages|status|success|ok|critical|offline|online|ping|upload|download)\b')
UNIT_TOKEN_RE = re.compile(r'(?i)\b(?:ms|mbps|gbps|gb|mb|kb|%|c|°c|°f|s|sec|secs|seconds|minutes|min|hrs|hours)\b')
EMOJI_RE = re.compile("["
    "\U0001F300-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001FA70-\U0001FAFF"
    "\U0001F1E6-\U0001F1FF"
    "]", flags=re.UNICODE)

LIKELY_POSTER_HOSTS = (
    "githubusercontent.com","fanart.tv","themoviedb.org","image.tmdb.org","trakt.tv","tvdb.org","gravatar.com"
)

# -------- Utils --------
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

def _strip_noise(text: str) -> str:
    if not text: return ""
    s = EMOJI_RE.sub("", text)
    # remove boilerplate footers
    NOISE_LINE_RE = re.compile(r'^\s*(?:sent from .+|via .+ api|automated message|do not reply)\.?\s*$', re.I)
    kept = [ln for ln in s.splitlines() if not NOISE_LINE_RE.match(ln)]
    return "\n".join(kept)

def _normalize(s: str) -> str:
    if not s: return ""
    s = s.replace("\t","  ")
    s = re.sub(r'[ \t]+$', '', s, flags=re.M)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def _looks_json(body: str) -> bool:
    try: json.loads(body); return True
    except Exception: return False

# -------- Type detection --------
def _detect_type(title: str, body: str) -> str:
    tb = (title + " " + body).lower()
    if "speedtest" in tb: return "SpeedTest"
    if "apt" in tb or "dpkg" in tb: return "APT Update"
    if "watchtower" in tb: return "Watchtower"
    if "sonarr" in tb: return "Sonarr"
    if "radarr" in tb: return "Radarr"
    if _looks_json(body): return "JSON"
    if "error" in tb or "warning" in tb or "failed" in tb: return "Log Event"
    return "Message"

# -------- Images --------
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

# -------- Persona --------
def _load_persona(persona_name: Optional[str]) -> Dict[str, Any]:
    if not persona_name: return {}
    key = (persona_name or "").strip().lower()
    if key in ("neutral","ops","operations","none"): return {}
    try:
        mod = importlib.import_module("personality")
        mod = importlib.reload(mod)
    except Exception:
        return {}
    # Preferred accessor
    if hasattr(mod, "get_persona"):
        try:
            data = mod.get_persona(key)
            if isinstance(data, dict): return data
        except Exception:
            pass
    # Fallbacks
    for attr in ("PERSONAS","PERSONA_STYLES","STYLES","profiles","overlays"):
        data = getattr(mod, attr, None)
        if isinstance(data, dict) and data.get(key):
            obj = data.get(key)
            if isinstance(obj, dict): return obj
    return {}

def _persona_overlay(persona: Optional[str], persona_quip: bool) -> List[str]:
    data = _load_persona(persona)
    overlay: List[str] = []
    if isinstance(data, dict):
        label = (data.get("label") or "").strip()
        emoji = (data.get("emoji") or "").strip()
        quips = data.get("quips") if isinstance(data.get("quips"), (list,tuple)) else None
        if label or emoji:
            overlay.append(f"{emoji} {label}".strip())
        if persona_quip and quips:
            try: overlay.append(f'“{random.choice(list(quips))}”')
            except Exception: pass
    return overlay

# -------- Header & Severity --------
def _header(kind: str, badge: str = "") -> List[str]:
    h = f"📟 Jarvis Prime — {kind} {badge}".rstrip()
    return ["———————————————", h, "———————————————"]

def _severity_badge(text: str) -> str:
    low = text.lower()
    if re.search(r'\b(error|failed|critical)\b', low): return "❌"
    if re.search(r'\b(warn|warning)\b', low): return "⚠️"
    if re.search(r'\b(success|ok|online|completed)\b', low): return "✅"
    return ""

# -------- Bullet helpers --------
def _fmt_kv(label: str, value: str) -> str:
    v = value.strip()
    if UNIT_TOKEN_RE.search(v) or re.search(r'\d', v):
        v_disp = f"`{v}`"
    else:
        v_disp = v
    return f"- **{label.strip()}:** {v_disp}"

def _b(line: str) -> str:
    return f"- {line.strip()}"

def _harvest_timestamp(title: str, body: str) -> Optional[str]:
    for src in (title or "", body or ""):
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

def _find_ips(*texts: str) -> List[str]:
    ips = []; seen = set()
    for t in texts:
        if not t: continue
        for m in IP_RE.finditer(t):
            ip = m.group(0)
            if ip not in seen:
                seen.add(ip); ips.append(ip)
    return ips

# -------- Build sections --------
def _categorize_bullets(title: str, body: str) -> Tuple[List[str], List[str]]:
    facts: List[str] = []
    details: List[str] = []

    ts = _harvest_timestamp(title, body)
    if ts: facts.append(_fmt_kv("Time", ts))
    if title.strip(): facts.append(_fmt_kv("Subject", title.strip()))

    # KVs
    for k,v in _extract_keyvals(body):
        label = k.strip().lower()
        if label in ("ping","download","upload","latency","jitter","loss","speed"):
            facts.append(_fmt_kv(k, v))
        elif label in ("status","result","state","ok","success","warning","error"):
            facts.append(_fmt_kv(k, v))
        else:
            details.append(_fmt_kv(k, v))

    # IPs/hosts/versions
    ips_found = _find_ips(title, body)
    for ip in ips_found:
        details.append(_fmt_kv("IP", ip))
    for host in HOST_RE.findall(body or ""):
        if not IP_RE.match(host):  # avoid IP-as-host
            details.append(_fmt_kv("host", host))

    # versions: avoid parts of IPs or longer dotted tokens
    body_s = body or ""
    for m in VER_RE.finditer(body_s):
        ver = m.group(0)
        tail = body_s[m.end(): m.end()+2]
        if tail.startswith('.') and len(tail) > 1 and tail[1].isdigit():
            continue
        if any(ver in ip for ip in ips_found):
            continue
        details.append(_fmt_kv("version", ver))

    # Signal lines
    for ln in (body or "").splitlines():
        if KV_RE.match(ln): 
            continue
        if SIGNAL_LINE_RE.search(ln):
            text = ln.strip()
            if re.search(r'(?i)\b(error|failed|failure|critical)\b', text):
                details.append(_b(f"Error: {text}"))
            elif re.search(r'(?i)\b(warn|warning)\b', text):
                details.append(_b(f"Warning: {text}"))
            elif re.search(r'(?i)\b(reboot|restart|updated|upgraded)\b', text):
                details.append(_b(f"Action: {text}"))
            else:
                details.append(_b(text))

    if not facts:
        first = _first_nonempty_line(body)
        if first: facts.append(_fmt_kv("Info", first))

    def _unique(seq: List[str]) -> List[str]:
        seen=set(); out=[]
        for x in seq:
            key = re.sub(r'\s+',' ', x.strip()).lower()
            if key and key not in seen:
                seen.add(key); out.append(x)
        return out

    return _unique(facts), _unique(details)

# -------- Alignment check --------
def _format_align_check(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Ensure blank line after header block
    if len(lines) >= 3 and lines[0].startswith("—") and "Jarvis Prime" in lines[1]:
        if len(lines) == 3 or lines[3].strip() != "":
            lines = lines[:3] + [""] + lines[3:]
    # Normalize bullets
    for i, ln in enumerate(lines):
        if re.match(r'^\s*[•*]\s+', ln):
            lines[i] = re.sub(r'^\s*[•*]\s+', '- ', ln)
        elif re.match(r'^\s*-\s*', ln):
            lines[i] = re.sub(r'^\s*-\s*', '- ', ln, count=1)
    # Collapse duplicate blanks
    out=[]; prev_blank=False
    for ln in lines:
        if ln.strip()=="" and prev_blank: 
            continue
        out.append(ln); prev_blank = (ln.strip()=="")
    return "\n".join(out).strip()

# -------- Public --------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: str | None = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True) -> Tuple[str, Optional[dict]]:
    stripped = _strip_noise(body)
    normalized = _normalize(stripped)

    # Images
    body_wo_imgs, images = _harvest_images(normalized)

    # Detect
    kind = _detect_type(title, body_wo_imgs)
    badge = _severity_badge(title + " " + body_wo_imgs)

    # Header + overlay
    lines: List[str] = _header(kind, badge)
    overlay = _persona_overlay(persona, persona_quip)
    if overlay: lines += overlay + [""]

    # Sections
    facts, details = _categorize_bullets(title, body_wo_imgs)
    if facts:
        lines += ["📄 Facts", *facts, ""]
    if details:
        lines += ["📄 Details", *details, ""]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _dedup_sentences(text)

    # Extras with images (hero restored) + beautified marker
    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}

    return text, extras
