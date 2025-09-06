# /app/beautify.py
from __future__ import annotations
import re, json, importlib, random, html, os
from typing import List, Tuple, Optional, Dict, Any

# -------- Regex library --------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
# tolerate spaces/newlines between ] and (, and angle-bracketed URLs
# CAPTURE ALT (group 1) + URL (group 2)
MD_IMG_RE  = re.compile(r'!\[([^\]]*)\]\s*\(\s*<?\s*(https?://[^\s)]+?)\s*>?\s*\)', re.I | re.S)
KV_RE      = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+)$', re.M)

# timestamps and types
TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')

# Strict IPv4: each octet 0-255
IP_RE  = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{2})\b')
HOST_RE = re.compile(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b')
VER_RE  = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')

EMOJI_RE = re.compile("["  # a few unicode ranges
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

def _linewise_dedup_markdown(text: str, protect_message: bool = False) -> str:
    """Safe de-dup that never splits on '.' and can protect the 📝 Message block."""
    lines = text.splitlines()
    out: List[str] = []
    seen: set = set()
    in_code = False
    in_msg  = False

    for ln in lines:
        t = ln.rstrip()

        # code fences pass-through
        if t.strip().startswith("```"):
            in_code = not in_code
            out.append(t); continue
        if in_code:
            out.append(t); continue

        # Message block protection
        if protect_message:
            if t.strip().startswith("📝 Message"):
                in_msg = True
                out.append(t); continue
            # a new section header ends the message block
            if in_msg and (t.strip().startswith("📄 ") or t.strip().startswith("🧠 ") or t.strip().startswith("![") or t.strip().startswith("📟 ")):
                in_msg = False

        if protect_message and in_msg:
            out.append(t)  # no dedup inside the Message block
            continue

        key = re.sub(r'\s+', ' ', t.strip()).lower()
        if key and key not in seen:
            seen.add(key); out.append(t)
        elif t.strip() == "":
            if out and out[-1].strip() != "":
                out.append(t)

    return "\n".join(out).strip()

def _harvest_images(text: str) -> Tuple[str, List[str], List[str]]:
    """Strip images from body but keep meaning: retain ALT as [image: ALT]."""
    if not text: return "", [], []
    urls: List[str] = []
    alts: List[str] = []

    def _md(m):
        alt = (m.group(1) or "").strip()
        url = m.group(2)
        alts.append(alt)
        urls.append(url)
        return f"[image: {alt}]" if alt else "[image]"

    def _bare(m):
        u = m.group(1).rstrip('.,;:)]}>"\'')
        urls.append(u)
        return ""  # remove bare URL

    text = MD_IMG_RE.sub(_md, text)
    text = IMG_URL_RE.sub(_bare, text)

    uniq=[]; seen=set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen: seen.add(u); uniq.append(u)
    return text.strip(), uniq, alts

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
    if re.search(r'\d', v):  # emphasize numeric values
        v = f"`{v}`"
    return f"- **{label.strip()}:** {v}"

# -------- Persona overlay --------
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

# -------- Minimal header (no dash bars) --------
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

# --------------------
# LLM persona riffs ONLY
# --------------------
def _persona_llm_riffs(context: str, persona: Optional[str]) -> List[str]:
    if not persona:
        return []
    enabled = os.getenv("BEAUTIFY_LLM_ENABLED", os.getenv("llm_enabled","true")).lower() in ("1","true","yes")
    if not enabled:
        return []
    try:
        mod = importlib.import_module("personality")
        mod = importlib.reload(mod)
        if hasattr(mod, "llm_quips"):
            max_lines = int(os.getenv("LLM_PERSONA_LINES_MAX", "3") or "3")
            out = mod.llm_quips(persona, context=context, max_lines=max_lines)
            if isinstance(out, list):
                return [str(x).strip() for x in out if str(x).strip()]
    except Exception:
        pass
    return []

# --------- ADDITIVE: global helpers for riffs & persona ----------
def _effective_persona(passed_persona: Optional[str]) -> Optional[str]:
    if passed_persona:
        return passed_persona
    try:
        with open("/data/personality_state.json", "r", encoding="utf-8") as f:
            st = json.load(f)
            p = (st.get("current_persona") or "").strip()
            if p:
                return p
    except Exception:
        pass
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            opt = json.load(f)
            p = (opt.get("default_persona") or "").strip()
            if p:
                return p
    except Exception:
        pass
    p = (os.getenv("DEFAULT_PERSONA") or "").strip()
    return p or None

def _global_riff_hint(extras_in: Optional[Dict[str, Any]], source_hint: Optional[str]) -> bool:
    if isinstance(extras_in, dict) and "riff_hint" in extras_in:
        try:
            return bool(extras_in.get("riff_hint"))
        except Exception:
            return True
    src = (source_hint or "").strip().lower()
    auto_sources = {
        "smtp","proxy","webhook","webhooks","apprise","gotify","ntfy",
        "sonarr","radarr","watchtower","speedtest","apt","syslog"
    }
    if src in auto_sources:
        return True
    default_on = os.getenv("BEAUTIFY_RIFFS_DEFAULT", "true").lower() in ("1","true","yes")
    return default_on

def _debug(msg: str) -> None:
    if os.getenv("BEAUTIFY_DEBUG", "").lower() in ("1","true","yes"):
        try:
            print(f"[beautify] {msg}")
        except Exception:
            pass

# ===== NEW: global OFF switch =====
def _beautify_is_disabled() -> bool:
    env = (os.getenv("BEAUTIFY_ENABLED") or "").strip().lower()
    if env in ("0","false","no","off","disabled"):
        return True
    try:
        with open("/data/options.json","r",encoding="utf-8") as f:
            opt = json.load(f)
            v = str(opt.get("beautify_enabled","true")).strip().lower()
            if v in ("0","false","no","off","disabled"):
                return True
    except Exception:
        pass
    return False

# ============================
# ADDITIVE: Watchtower-aware summarizer
# ============================
_WT_HOST_RX = re.compile(r'\bupdates?\s+on\s+([A-Za-z0-9._-]+)', re.I)
_WT_UPDATED_RXES = [
    re.compile(
        r'^\s*[-*]\s*(?P<name>/?[A-Za-z0-9._-]+)\s*\((?P<img>[^)]+)\)\s*:\s*(?P<old>[0-9a-f]{7,64})\s+updated\s+to\s+(?P<new>[0-9a-f]{7,64})\s*$',
        re.I),
    re.compile(
        r'^\s*[-*]\s*(?P<name>/?[A-Za-z0-9._-]+)\s*:\s*(?P<old>[0-9a-f]{7,64})\s+updated\s+to\s+(?P<new>[0-9a-f]{7,64})\s*$',
        re.I),
]
_WT_FRESH_RX = re.compile(r':\s*Fresh\s*$', re.I)

def _watchtower_host_from_title(title: str) -> Optional[str]:
    m = _WT_HOST_RX.search(title or "")
    if m:
        return m.group(1).strip()
    return None

def _summarize_watchtower(title: str, body: str, limit: int = 50) -> Tuple[str, Dict[str, Any]]:
    lines = (body or "").splitlines()
    updated: List[Tuple[str, str, str]] = []
    for ln in lines:
        if _WT_FRESH_RX.search(ln):
            continue
        for rx in _WT_UPDATED_RXES:
            m = rx.match(ln)
            if m:
                name = (m.groupdict().get("name") or "").strip()
                img  = (m.groupdict().get("img") or "").strip()
                new  = (m.groupdict().get("new") or "").strip()
                if not img:
                    img = name
                updated.append((name, img, new))
                break

    host = _watchtower_host_from_title(title) or "unknown"
    meta: Dict[str, Any] = {"watchtower::host": host, "watchtower::updated_count": len(updated)}

    if not updated:
        md = f"**Host:** `{host}`\n\n_No updates (all images fresh)._"
        return md, meta

    if len(updated) > max(1, limit):
        updated = updated[:limit]
        meta["watchtower::truncated"] = True

    bullets = "\n".join([f"• `{name}` → `{img}` @ `{new}`" for name, img, new in updated])
    md = f"**Host:** `{host}`\n\n**Updated ({len(updated)}):**\n{bullets}"
    return md, meta

# -------- Public API --------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     extras_in: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:

    # Honor global OFF switch: pass-through (no image/regex processing)
    if _beautify_is_disabled():
        title_s = (title or "").strip()
        body_s  = (body or "").strip()
        lines: List[str] = [ "📟 Jarvis Prime — Message" ]
        if title_s:
            lines += ["", "📄 Facts", f"- **Subject:** {title_s}"]
        if body_s:
            lines += ["", "📝 Message", body_s]
        text = "\n".join(lines).strip()
        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "jarvis::beautified": False
        }
        return text, extras

    stripped = _strip_noise(body)
    normalized = _normalize(stripped)
    normalized = html.unescape(normalized)

    # images (keep meaning via ALT placeholders)
    body_wo_imgs, images, image_alts = _harvest_images(normalized)

    kind = _detect_type(title, body_wo_imgs)
    badge = _severity_badge(title + " " + body_wo_imgs)

    # ===== Watchtower special-case =====
    if kind == "Watchtower":
        lines: List[str] = []
        lines += _header("Watchtower", badge)

        eff_persona = _effective_persona(persona)
        if persona_quip:
            pol = _persona_overlay_line(eff_persona)
            if pol: lines += [pol]

        wt_md, wt_meta = _summarize_watchtower(title, body_wo_imgs)
        lines += ["", wt_md]

        ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
        riff_hint = _global_riff_hint(extras_in, source_hint)
        riffs: List[str] = []
        if eff_persona and riff_hint:
            riffs = _persona_llm_riffs(ctx, eff_persona)
        real_riffs = [ (r or "").replace("\r","").strip() for r in (riffs or []) ]
        real_riffs = [ r for r in real_riffs if r ]
        if real_riffs:
            lines += ["", f"🧠 {eff_persona} riff"]
            for r in real_riffs:
                lines.append("> " + r)

        text = "\n".join(lines).strip()
        text = _format_align_check(text)
        text = _linewise_dedup_markdown(text, protect_message=True)

        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "jarvis::beautified": True,
            "jarvis::llm_riff_lines": len(real_riffs or []),
            "watchtower::host": wt_meta.get("watchtower::host"),
            "watchtower::updated_count": wt_meta.get("watchtower::updated_count"),
        }
        if wt_meta.get("watchtower::truncated"):
            extras["watchtower::truncated"] = True
        if isinstance(extras_in, dict):
            extras.update(extras_in)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== Standard path =====
    lines: List[str] = []
    lines += _header(kind, badge)

    eff_persona = _effective_persona(persona)
    if persona_quip:
        pol = _persona_overlay_line(eff_persona)
        if pol: lines += [pol]

    facts, details = _categorize_bullets(title, body_wo_imgs)
    if facts:
        lines += ["", "📄 Facts", *facts]
    if details:
        lines += ["", "📄 Details", *details]

    # --- Always keep human content visible (entire body, not just first paragraph)
    message_snip = (body_wo_imgs or "").strip() or (normalized or "").strip()

    if message_snip:
        lines += ["", "📝 Message", message_snip]

    # Inline the first image as poster; keep list in extras
    if images:
        lines += ["", f"![poster]({images[0]})"]

    # LLM persona riffs (render only if non-empty)
    ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
    riffs: List[str] = []
    riff_hint = _global_riff_hint(extras_in, source_hint)
    _debug(f"persona={eff_persona}, riff_hint={riff_hint}, src={source_hint}, images={len(images)}")
    if eff_persona and riff_hint:
        riffs = _persona_llm_riffs(ctx, eff_persona)

    real_riffs = [ (r or "").replace("\r","").strip() for r in (riffs or []) ]
    real_riffs = [ r for r in real_riffs if r ]
    if real_riffs:
        lines += ["", f"🧠 {eff_persona} riff"]
        for r in real_riffs:
            lines.append("> " + r)

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text, protect_message=True)

    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images,
        "jarvis::llm_riff_lines": len(real_riffs or []),
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}
    if isinstance(extras_in, dict):
        extras.update(extras_in)

    return text, extras
