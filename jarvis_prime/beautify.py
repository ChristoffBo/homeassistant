#!/usr/bin/env python3
# /app/beautify.py
from __future__ import annotations
import re, json, importlib, html, os
from typing import List, Tuple, Optional, Dict, Any

# -------- Regex library --------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\s*\(\s*<?\s*(https?://[^\s)]+?)\s*>?\s*\)', re.I | re.S)
KV_RE      = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+?)\s*$')

# timestamps and types
TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')

# Strict IPv4
IP_RE  = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b')
HOST_RE = re.compile(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b')
VER_RE  = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')

EMOJI_RE = re.compile("[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF\U0001FA70-\U0001FAFF\U0001F1E6-\U0001F1FF]", flags=re.UNICODE)

LIKELY_POSTER_HOSTS = ("githubusercontent.com","fanart.tv","themoviedb.org","image.tmdb.org","trakt.tv","tvdb.org","gravatar.com")

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
            out.append(t); continue
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
        urls.append(u); return ""
    text = MD_IMG_RE.sub(_md, text)
    text = IMG_URL_RE.sub(_bare, text)
    uniq=[]; seen=set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen: seen.add(u); uniq.append(u)
    return text.strip(), uniq

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

# -------- Persona overlay (top canned) --------
def _persona_overlay_line(persona: Optional[str]) -> Optional[str]:
    if not persona: return None
    try:
        mod = importlib.import_module("personality")
        mod = importlib.reload(mod)
        quip = ""
        if hasattr(mod, "quip"):
            try: quip = str(mod.quip(persona) or "").strip()
            except Exception: quip = ""
        return f"💬 {persona} says: {'— ' + quip if quip else ''}".rstrip()
    except Exception:
        return f"💬 {persona} says:"

# -------- Minimal header --------
def _header(kind: str, badge: str = "") -> List[str]:
    return [f"📟 Jarvis Prime — {kind} {badge}".rstrip()]

def _severity_badge(text: str) -> str:
    low = text.lower()
    if re.search(r'\b(error|failed|critical)\b', low): return "❌"
    if re.search(r'\b(warn|warning)\b', low): return "⚠️"
    if re.search(r'\b(success|ok|online|completed)\b', low): return "✅"
    return ""

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
    if "error" in tb or "warning" in tb or "failed" in tb: return "Log Event"
    return "Message"

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
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out

def _categorize_bullets(title: str, body: str) -> Tuple[List[str], List[str]]:
    facts: List[str] = []
    details: List[str] = []

    ts = _harvest_timestamp(title, body)
    if ts: facts.append(_fmt_kv("Time", ts))
    if title.strip(): facts.append(_fmt_kv("Subject", title.strip()))

    for k,v in _extract_keyvals(body):
        key = k.strip().lower()
        val = v
        if key in ("ip","ip address","address"):
            val = _repair_ipv4(v, title, body)
            details.append(_fmt_kv("IP", val))
        elif key in ("ping","download","upload","latency","jitter","loss","speed"):
            facts.append(_fmt_kv(k, v))
        elif key in ("status","result","state","ok","success","warning","error"):
            facts.append(_fmt_kv(k, v))
        else:
            details.append(_fmt_kv(k, v))

    ip_list = _find_ips(title, body)
    for ip in ip_list:
        if f"`{ip}`" not in " ".join(details):
            details.append(_fmt_kv("IP", ip))
    for host in HOST_RE.findall(body or ""):
        if not IP_RE.match(host):
            details.append(_fmt_kv("host", host))

    for m in VER_RE.finditer(body or ""):
        ver = m.group(0)
        if any(ver in ip for ip in ip_list):
            continue
        details.append(_fmt_kv("version", ver))

    if not facts:
        first = _first_nonempty_line(body)
        if first: facts.append(_fmt_kv("Info", first))

    def _uniq(lines: List[str]) -> List[str]:
        seen=set(); out=[]
        for ln in lines:
            key = re.sub(r'\s+',' ', ln.strip()).lower()
            if key and key not in seen: seen.add(key); out.append(ln)
        return out

    return _uniq(facts), _uniq(details)

def _format_align_check(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and lines[0].strip() == "": lines.pop(0)
    out=[]
    for ln in lines:
        if ln.strip() == "":
            if out and out[-1].strip() == "":
                continue
        out.append(ln)
    return "\n".join(out).strip()

# ---- LLM persona (bottom) ----
def _persona_llm_lines(persona: Optional[str], title: str, body_wo_imgs: str) -> List[str]:
    enabled = os.getenv("BEAUTIFY_LLM_ENABLED", os.getenv("llm_enabled","true")).lower() in ("1","true","yes")
    if not enabled or not persona:
        return []
    try:
        mod = importlib.import_module("personality")
        mod = importlib.reload(mod)
        if hasattr(mod, "llm_quips"):
            lines = mod.llm_quips(persona, title, body_wo_imgs,
                                  max_lines=int(os.getenv("LLM_PERSONA_LINES_MAX","3")),
                                  allow_profanity=os.getenv("PERSONALITY_ALLOW_PROFANITY","false").lower() in ("1","true","yes"))
            # Post-sanitize to avoid breaking markdown
            clean = []
            for ln in lines or []:
                t = ln.replace("`", "'").replace("*", "").strip()
                if t:
                    clean.append(t)
            return clean[:3]
    except Exception:
        return []
    return []

# -------- Public API --------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True) -> Tuple[str, Optional[Dict[str, Any]]]:

    stripped = _strip_noise(body)
    normalized = _normalize(stripped)
    normalized = html.unescape(normalized)

    # harvest images (no LLM rewrite of facts)
    body_wo_imgs, images = _harvest_images(normalized)

    kind = _detect_type(title, body_wo_imgs)
    badge = _severity_badge(title + " " + body_wo_imgs)

    lines: List[str] = []
    lines += _header(kind, badge)

    # Persona canned one-liner at the top (unchanged facts below)
    if persona_quip:
        pol = _persona_overlay_line(persona)
        if pol: lines += [pol]

    facts, details = _categorize_bullets(title, body_wo_imgs)
    if facts:
        lines += ["", "📄 Facts", *facts]
    if details:
        lines += ["", "📄 Details", *details]

    # Poster image (inline first image)
    if images:
        lines += ["", f"![poster]({images[0]})"]

    # LLM persona riffs at the very bottom (1–3 lines), never touching facts
    llm_lines = _persona_llm_lines(persona, title or "", body_wo_imgs or "")
    if llm_lines:
        lines += ["", f"🧠 {persona} riff", *[f"> {ln}" for ln in llm_lines]]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)

    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images,
        "jarvis::llm_used": bool(bool(llm_lines)),
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}

    return text, extras
