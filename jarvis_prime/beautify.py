# /app/beautify.py
from __future__ import annotations
import re, json, importlib, random, html, os
from typing import List, Tuple, Optional, Dict, Any

# -------- Regex library --------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
# tolerate spaces/newlines between ] and (, and angle-bracketed URLs
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\s*\(\s*<?\s*(https?://[^\s)]+?)\s*>?\s*\)', re.I | re.S)
KV_RE      = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+?)\s*$', re.M)

# timestamps and types
TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')

# Strict IPv4: each octet 0-255
IP_RE  = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b')
HOST_RE = re.compile(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b')
VER_RE  = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')

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

# -------- Helpers --------
def _prefer_host_key(url: str) -> int:
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").lower()
        return 0 if any(k in host for k in LIKELY_POSTER_HOSTS) else 1
    except Exception:
        return 1

def _strip_noise(text: str) -> str:
    if not text: return ""
    s = EMOJI_RE.sub("", text)
    NOISE = re.compile(r'^\s*(?:sent from .+|via .+ api|automated message|do not reply)\.?\s*$', re.I)
    kept = [ln for ln in s.splitlines() if not NOISE.match(ln)]
    return "\n".join(kept)

def _normalize(text: str) -> str:
    s = (text or "").replace("\t","  ")
    s = re.sub(r'[ \t]+$', "", s, flags=re.M)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def _linewise_dedup_markdown(text: str) -> str:
    lines = text.splitlines()
    out: List[str] = []
    seen: set = set()
    in_code = False
    for ln in lines:
        t = ln.rstrip()
        if t.strip().startswith("```"):
            in_code = not in_code
            out.append(t)
            continue
        if in_code:
            out.append(t)
            continue
        key = re.sub(r'\s+', ' ', t.strip()).lower()
        if key and key not in seen:
            seen.add(key); out.append(t)
        elif t.strip() == "":
            if out and out[-1].strip() != "":
                out.append(t)
    return "\n".join(out).strip()

def _harvest_images(text: str) -> Tuple[str, List[str]]:
    if not text: return "", []
    urls: List[str] = []
    def _md(m):  urls.append(m.group(1)); return ""
    def _bare(m):
        u = m.group(1).rstrip('.,;:)]}>"\'')
        urls.append(u)
        return ""
    text = MD_IMG_RE.sub(_md, text)
    text = IMG_URL_RE.sub(_bare, text)
    uniq=[]; seen=set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen: seen.add(u); uniq.append(u)
    return text.strip(), uniq

def _peek_images(text: str) -> List[str]:
    if not text: return []
    urls: List[str] = []
    for m in MD_IMG_RE.finditer(text or ""): urls.append(m.group(1))
    for m in IMG_URL_RE.finditer(text or ""):
        u = m.group(1).rstrip('.,;:)]}>"\'')
        urls.append(u)
    uniq=[]; seen=set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen: seen.add(u); uniq.append(u)
    return uniq
def _find_ips(*texts: str) -> List[str]:
    ips=[]; seen=set()
    for t in texts:
        if not t: continue
        for m in IP_RE.finditer(t):
            ip = m.group(0)
            if ip not in seen: seen.add(ip); ips.append(ip)
    return ips

def _repair_ipv4(val: str, *contexts: str) -> str:
    cand = re.sub(r'\s*\.\s*', '.', (val or '').strip())
    m = IP_RE.search(cand)
    if m: return m.group(0)
    parts = re.findall(r'\d{1,3}', cand)
    if len(parts) == 4:
        j = '.'.join(parts)
        if IP_RE.fullmatch(j): return j
    for ctx in contexts:
        m = IP_RE.search(ctx or "")
        if m: return m.group(0)
    return val.strip()

def _first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        t = ln.strip()
        if t: return t
    return ""

def _fmt_kv(label: str, value: str) -> str:
    v = value.strip()
    if re.search(r'\d', v):  
        v = f"`{v}`"
    return f"- **{label.strip()}:** {v}"

# Persona overlay, header, severity, etc… (unchanged from Part 1)
# ... [snip: same as before, kept intact] ...

# ============================
# Options + mode resolution
# ============================
_OPTS_CACHE: Optional[Dict[str, Any]] = None
def _load_options() -> Dict[str, Any]:
    global _OPTS_CACHE
    if _OPTS_CACHE is not None:
        return _OPTS_CACHE
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            _OPTS_CACHE = json.load(f) or {}
    except Exception:
        _OPTS_CACHE = {}
    return _OPTS_CACHE

def _resolve_mode(source_hint: Optional[str], passed_mode: Optional[str]) -> str:
    opts = _load_options()
    flat_full = bool(opts.get("beautify_full_enabled"))
    flat_lossless = bool(opts.get("beautify_lossless_enabled"))
    b = opts.get("beautify", {}) if isinstance(opts, dict) else {}
    nested_full = bool(b.get("full_enabled"))
    nested_lossless = bool(b.get("lossless_enabled"))
    full = flat_full or nested_full
    lossless = flat_lossless or nested_lossless

    if full and lossless:
        return "full"
    if full:
        return "full"
    if lossless:
        return "lossless"
    if isinstance(passed_mode, str) and passed_mode.strip():
        return passed_mode.strip().lower()
    try:
        src = (source_hint or "").strip().lower()
        srcs = b.get("sources") or {}
        if src and isinstance(srcs, dict) and isinstance(srcs.get(src), dict):
            m = (srcs[src].get("mode") or "").strip().lower()
            if m: return m
        m = (b.get("default_mode") or "").strip().lower()
        if m: return m
    except Exception:
        pass
    envm = (os.getenv("BEAUTIFY_DEFAULT_MODE") or "").strip().lower()
    return envm if envm else "standard"

# ============================
# Watchtower summarizer + Public API
# ============================
# (kept intact, unchanged except using _resolve_mode for mode selection)
# ... existing _summarize_watchtower(), beautify_message() etc ...

def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     extras_in: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Main entrypoint. Applies lossless or full beautify based on toggles.
    """
    eff_mode = _resolve_mode(source_hint, mode)

    stripped = _strip_noise(body)
    normalized = _normalize(stripped)
    normalized = html.unescape(normalized)

    images = _peek_images(normalized) if eff_mode == "lossless" else _harvest_images(normalized)[1]
    body_for_parse = normalized if eff_mode == "lossless" else _harvest_images(normalized)[0]

    kind = _detect_type(title, body_for_parse)
    badge = _severity_badge(title + " " + body_for_parse)

    lines: List[str] = []
    lines += _header(kind, badge)

    eff_persona = _effective_persona(persona)
    if persona_quip:
        pol = _persona_overlay_line(eff_persona)
        if pol: lines += [pol]

    facts, details = _categorize_bullets(title, body_for_parse)
    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    if images: lines += ["", f"![poster]({images[0]})"]

    if eff_mode == "lossless":
        lines += ["", "🗂 Raw", "```", body, "```"]

    ctx = (title or "").strip() + "\n" + (body_for_parse or "").strip()
    riffs: List[str] = []
    if eff_persona and _global_riff_hint(extras_in, source_hint):
        riffs = _persona_llm_riffs(ctx, eff_persona)
    if riffs:
        lines += ["", f"🧠 {eff_persona} riff"]
        for r in riffs:
            if r.strip():
                lines.append("> " + r.strip())

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)

    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images,
        "jarvis::mode": eff_mode,
        "jarvis::llm_riff_lines": len(riffs or []),
    }
    if images: extras["client::notification"] = {"bigImageUrl": images[0]}
    if isinstance(extras_in, dict): extras.update(extras_in)

    return text, extras