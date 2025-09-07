from __future__ import annotations
import re, json, importlib, random, html, os
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import unquote_plus, parse_qs  # ADD

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

EMOJI_RE = re.compile("[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF\U0001FA70-\U0001FAFF\U0001F1E6-\U0001F1FF]", flags=re.UNICODE)

LIKELY_POSTER_HOSTS = (
    "githubusercontent.com","fanart.tv","themoviedb.org","image.tmdb.org","trakt.tv","tvdb.org","gravatar.com"
)

# === NEW: universal finish helpers (non-destructive) ===
CODE_FENCE_RE = re.compile(r'```.*?```', re.S)
LINK_RE       = re.compile(r'\[[^\]]+?\]\([^)]+?\)')

def _fold_repeats(text: str, threshold: int = 3) -> str:
    """Collapse runs of identical lines into a single line with ×N, keep head/tail if huge."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1
        n = j - i
        if n > threshold:
            out.append(f"{lines[i]}  ×{n}")
        else:
            out.extend(lines[i:j])
        i = j
    if len(out) > 1200:
        return "\n".join(out[:700] + ["…(folded)"] + out[-300:])
    return "\n".join(out)

def _safe_truncate(s: str, max_len: int = 3500) -> str:
    """
    Non-destructive truncation: never cuts inside code fences, markdown links/images, or raw image URLs.
    Applies only if the final message is extremely long.
    """
    if len(s) <= max_len:
        return s
    protected = []
    for rx in (CODE_FENCE_RE, MD_IMG_RE, LINK_RE, IMG_URL_RE):
        for m in rx.finditer(s):
            protected.append((m.start(), m.end()))
    protected.sort()
    out, pos, used, budget = [], 0, 0, max_len
    for a, b in protected:
        if a > pos:
            chunk = s[pos:a]
            if used + len(chunk) > budget:
                room = max(0, budget - used - 8)
                sub  = chunk[:room]
                cut  = max(sub.rfind("\n"), sub.rfind(" "), sub.rfind("\t"))
                if cut < room * 0.6:
                    cut = room
                out.append(sub[:cut].rstrip() + "\n\n…(truncated)")
                return "".join(out)
            out.append(chunk); used += len(chunk)
        seg = s[a:b]
        if used + len(seg) > budget:
            out.append("\n\n…(truncated)")
            return "".join(out)
        out.append(seg); used += len(seg); pos = b
    if pos < len(s):
        tail = s[pos:]
        if used + len(tail) > budget:
            room = max(0, budget - used - 8)
            sub  = tail[:room]
            cut  = max(sub.rfind("\n"), sub.rfind(" "), sub.rfind("\t"))
            if cut < room * 0.6:
                cut = room
            out.append(sub[:cut].rstrip() + "\n\n…(truncated)")
            return "".join(out)
        out.append(tail)
    return "".join(out)

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

def _first_meaningful_line(s: str) -> str:
    """Return the first human line, skipping image placeholders and labels."""
    for ln in (s or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        # skip pure image placeholders or poster markdown
        if t.startswith("![poster]") or t.lower().startswith("[image"):
            continue
        # If the line starts with Subject/Message, strip the label and use the rest
        m = re.match(r'(?i)^(subject|message)\s*:?\s*(.*)$', t)
        if m:
            rest = m.group(2).strip()
            if rest:
                return rest
            else:
                continue
        return t
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
    # Drop intake/type label for a cleaner look; keep only Jarvis + severity badge
    return [f"📟 Jarvis Prime {badge}".rstrip()]

def _severity_badge(text: str) -> str:
    low = text.lower()
    if re.search(r'\b(error|failed|critical)\b', low): return "❌"
    if re.search(r'\b(warn|warning)\b', low): return "⚠️"
    if re.search(r'\b(success|ok|online|completed|pass|finished)\b', low): return "✅"
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
    # Kept for compatibility but not used in the simplified layout
    facts: List[str] = []
    details: List[str] = []

    ts = _harvest_timestamp(title, body)
    if ts: facts.append(_fmt_kv("Time", ts))
    if title.strip(): facts.append(_fmt_kv("Subject", title.strip()))

    IGNORED_KV_KEYS = {"title", "message", "priority", "topic", "tags"}

    for k,v in _extract_keyvals(body):
        key = k.strip().lower()
        if key in IGNORED_KV_KEYS:
            continue
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
def _read_options() -> Dict[str, Any]:
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _bool_from_env(*names: str, default: bool = False) -> bool:
    for n in names:
        v = (os.getenv(n) or "").strip().lower()
        if v in ("1","true","yes","on"):  return True
        if v in ("0","false","no","off"): return False
    return default

def _bool_from_options(opt: Dict[str, Any], key: str, default: bool = False) -> bool:
    try:
        v = str(opt.get(key, default)).strip().lower()
        return v in ("1","true","yes","on")
    except Exception:
        return default

def _llm_riffs_enabled() -> bool:
    # Allow env overrides and support both 'llm_enabled' and 'llm_persona_riffs_enabled'
    opt = _read_options()
    env_enabled = _bool_from_env("BEAUTIFY_LLM_ENABLED", "llm_enabled", default=True)
    # Prefer explicit llm_persona_riffs_enabled if present, else fall back to llm_enabled
    opt_riffs = _bool_from_options(opt, "llm_persona_riffs_enabled", default=None)
    if opt_riffs is not None:
        return opt_riffs
    return _bool_from_options(opt, "llm_enabled", default=env_enabled)

def _personality_enabled() -> bool:
    opt = _read_options()
    env_enabled = _bool_from_env("PERSONALITY_ENABLED", default=True)
    return _bool_from_options(opt, "personality_enabled", default=env_enabled)

def _ui_persona_header_enabled() -> bool:
    # If the UI renders its own persona header, don't inline ours (avoid duplicates)
    opt = _read_options()
    env_enabled = _bool_from_env("UI_PERSONA_HEADER", default=True)  # default TRUE to prevent duplicate persona
    return _bool_from_options(opt, "ui_persona_header", default=env_enabled)

def _llm_message_rewrite_enabled() -> bool:
    opt = _read_options()
    env_enabled = _bool_from_env("BEAUTIFY_LLM_REWRITE_ENABLED", "LLM_MESSAGE_REWRITE_ENABLED", default=False)
    return _bool_from_options(opt, "llm_rewrite_enabled", default=env_enabled)

def _llm_message_rewrite_max_chars() -> int:
    opt = _read_options()
    try:
        return int(os.getenv("LLM_MESSAGE_REWRITE_MAX_CHARS") or opt.get("llm_message_rewrite_max_chars", 800))
    except Exception:
        return 800

def _persona_llm_riffs(context: str, persona: Optional[str]) -> List[str]:
    if not persona:
        return []
    if not _llm_riffs_enabled():
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

# --------------------
# LLM persona REWRITE (optional)
# --------------------
def _persona_llm_rewrite(context: str, persona: Optional[str], max_chars: int = 800) -> Optional[str]:
    """
    Optional: rewrite/summarize the body with persona style via personality.llm_rewrite.
    Returns None to keep original.
    """
    if not persona or not _llm_riffs_enabled():  # piggyback on global LLM allow
        return None
    enabled = _llm_message_rewrite_enabled()
    if not enabled:
        return None
    try:
        mod = importlib.import_module("personality")
        mod = importlib.reload(mod)
        if hasattr(mod, "llm_rewrite"):
            out = mod.llm_rewrite(persona, context=context, max_chars=int(max_chars))
            if isinstance(out, str) and out.strip():
                return out.strip()
    except Exception:
        pass
    return None

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
        r'^\s*[-*]\s*(?P<name>/?[A-Za-z0-9._-]+)\s*(?P<img>[^)]+)\s*:\s*(?P<old>[0-9a-f]{7,64})\s+updated\s+to\s+(?P<new>[0-9a-f]{7,64})\s*$',
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

# -------- ADD: querystring detection & body cleanup helpers --------
_QS_TRIGGER_KEYS = {"title","message","priority","topic","tags"}

def _maybe_parse_query_payload(s: Optional[str]) -> Optional[Dict[str, str]]:
    """If the string looks like a URL-encoded querystring, parse and return {k:v} (first values)."""
    if not s:
        return None
    txt = s.strip().strip(' \t\r\n?')
    if "=" not in txt or "&" not in txt:
        return None
    dec = unquote_plus(txt)
    if not any((k + "=") in dec for k in _QS_TRIGGER_KEYS):
        return None
    try:
        parsed = parse_qs(dec, keep_blank_values=True, strict_parsing=False)
        return {k: (v[0] if isinstance(v, list) and v else "") for k, v in parsed.items()}
    except Exception:
        return None

_ACTION_SAYS_RX = re.compile(r'^\s*action\s+says:\s*.*$', re.I | re.M)

def _strip_action_says(text: str) -> str:
    """Remove any 'action says:' lines from visible body (riffs/personas untouched elsewhere)."""
    if not text:
        return ""
    out = _ACTION_SAYS_RX.sub("", text)
    return re.sub(r'\n{3,}', '\n\n', out).strip()

# MIME header stripping (SMTP / proxy leakage)
_MIME_HEADER_RX = re.compile(r'^\s*Content-(?:Disposition|Type|Length|Transfer-Encoding)\s*:.*$', re.I | re.M)
def _strip_mime_headers(text: str) -> str:
    if not text:
        return ""
    s = _MIME_HEADER_RX.sub("", text)
    return re.sub(r'\n{3,}', '\n\n', s).strip()

# --- SUBJECT CLEANUP & CARD TITLE -------------------------------------------------
INTAKE_NAMES = {"proxy","smtp","apprise","gotify","ntfy","webhook","webhooks"}

def _clean_subject(raw_title: str, body: str) -> str:
    """Remove intake tags, duplicate 'Jarvis Prime:' prefixes, and fallback to better subject."""
    t = (raw_title or "").strip()
    if not t:
        t = ""
    # Drop bracketed intake prefixes like [SMTP], [Proxy], etc.
    t = re.sub(r'^\s*\[(?:smtp|proxy|gotify|ntfy|apprise|webhooks?)\]\s*', '', t, flags=re.I)
    # If the title is literally just an intake keyword, try to mine a better subject
    if t.strip().lower() in INTAKE_NAMES or t.strip().lower() in {"message","notification","test"}:
        new_t = None
        # Look for 'Subject: XYZ' inside body
        for ln in (body or "").splitlines():
            m = re.match(r'\s*Subject\s*:\s*(.+)\s*$', ln, flags=re.I)
            if m:
                new_t = m.group(1).strip()
                break
        # If still not found, use the first meaningful human line
        if not new_t:
            cand = _first_meaningful_line(body)
            if cand and cand.strip().lower() not in INTAKE_NAMES:
                new_t = cand
        if new_t:
            t = new_t
    # Remove duplicate 'Jarvis Prime:' prefix(es)
    t = re.sub(r'^\s*(?:jarvis\s*prime\s*:?\s*)+', '', t, flags=re.I)
    return (t or "").strip()

def _build_client_title(subject: str) -> str:
    subj = (subject or "").strip()
    return f"Jarvis Prime: {subj}" if subj else "Jarvis Prime"

# --- Poster/icon fallback ---------------------------------------------------------
def _icon_map_from_options() -> Dict[str,str]:
    try:
        with open("/data/options.json","r",encoding="utf-8") as f:
            opt = json.load(f) or {}
            m = opt.get("icon_map") or {}
            if isinstance(m, dict):
                return {str(k).lower(): str(v) for k,v in m.items() if v}
    except Exception:
        pass
    return {}

def _icon_from_env(keyword: str) -> Optional[str]:
    key = f"ICON_{keyword.upper()}_URL"
    v = os.getenv(key) or ""
    return v.strip() or None

def _default_icon() -> Optional[str]:
    # default poster if nothing matches
    try:
        with open("/data/options.json","r",encoding="utf-8") as f:
            opt = json.load(f) or {}
            d = opt.get("default_icon") or ""
            if str(d).strip():
                return str(d).strip()
    except Exception:
        pass
    v = os.getenv("ICON_DEFAULT_URL") or ""
    return v.strip() or None

def _poster_fallback(title: str, body: str) -> Optional[str]:
    """Pick a poster icon if the intake didn't provide one, using keywords."""
    keywords = ["sonarr","radarr","lidarr","prowlarr","readarr","bazarr",
                "qbittorrent","transmission","jellyfin","plex","emby",
                "sabnzbd","overseerr","gluetun","pihole","unifi","portainer",
                "watchtower","docker","homeassistant","speedtest","apt"]
    text = f"{title} {body}".lower()
    opt_map = _icon_map_from_options()
    for word in keywords:
        if word in text:
            return opt_map.get(word) or _icon_from_env(word)
    # fallback default
    return _default_icon()

def _remove_kv_lines(text: str) -> str:
    """
    Keep human 'key: value' content (e.g., CPU: 68%). Only drop transport noise:
    - Content-* MIME lines
    - pure transport fields: title/message/topic/tags/priority (when alone)
    """
    if not text:
        return ""
    kept = []
    for ln in text.splitlines():
        t = ln.strip()
        if t.lower().startswith("content-"):
            continue
        m = KV_RE.match(t)
        if m:
            k = m.group(1).strip().lower()
            if k in {"title","message","topic","tags","priority"}:
                # skip transport/meta
                continue
        kept.append(ln)
    s = "\n".join(kept)
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s

# -------- Intake preprocessors --------
def _preprocess_smtp(title: str, body: str) -> Tuple[str, str]:
    body = _strip_mime_headers(body or "")
    body = re.sub(r'\n{2,}', '\n\n', body).strip()
    return (title or "").strip(), body

def _preprocess_gotify_like(title: str, body: str) -> Tuple[str, str]:
    qs = _maybe_parse_query_payload(body)
    if qs:
        t = qs.get("title", title)
        m = qs.get("message", body)
        return (t or "").strip(), (m or "").strip()
    return (title or "").strip(), (body or "").strip()

def _preprocess_proxy(title: str, body: str) -> Tuple[str, str]:
    # Extract form fields like: Content-Disposition: form-data; name="title"\r\n\r\nVALUE
    t = title or ""
    b = body or ""
    # Capture blocks
    blocks = re.findall(r'(?is)name="(title|message)"\s*\r?\n\r?\n(.*?)(?:\r?\n--|$)', b)
    fields = {k.lower(): v.strip() for k,v in blocks}
    # Also support URL-encoded query payloads in the body
    qs = _maybe_parse_query_payload(b)
    if qs:
        fields.update({k.lower(): v for k,v in qs.items()})
    if fields.get("title"): t = fields["title"]
    if fields.get("message"): b = fields["message"]
    # Clean remaining MIME noise
    b = re.sub(r'(?im)^content-disposition.*name="[^"]+"\s*', '', b)
    b = _strip_mime_headers(b)
    b = re.sub(r'\n{2,}', '\n\n', b).strip()
    return (t or "").strip(), b

def _preprocess_generic(title: str, body: str) -> Tuple[str, str]:
    return (title or "").strip(), (body or "").strip()

def _normalize_intake(source: str, title: str, body: str) -> Tuple[str, str]:
    src = (source or "").lower()
    if src == "smtp":
        return _preprocess_smtp(title, body)
    if src in ("gotify","ntfy","apprise"):
        return _preprocess_gotify_like(title, body)
    if src == "proxy":
        return _preprocess_proxy(title, body)
    return _preprocess_generic(title, body)

# --- Riff promotion for content-type cards ---------------------------------------
def _promote_riffs_to_message_if_needed(title: str, message_snip: str, riffs: List[str]) -> Tuple[str, List[str]]:
    # If body already exists, keep it.
    if message_snip.strip():
        return message_snip, riffs
    # Move riffs into the body for content-style titles.
    if re.search(r'(?i)\b(joke|quip|weird\s*fact|fact|quote)\b', (title or "")) and riffs:
        merged = "\n".join(r.strip().strip('"') for r in riffs if r.strip())
        return merged, []
    return message_snip, riffs

# -------- Public API --------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     extras_in: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:

    # If beautifier is OFF, still allow persona + riffs independently (raw passthrough)
    if _beautify_is_disabled():
        title_s = (title or "").strip()
        body_s  = (body or "").strip()
        clean_subject = _clean_subject(title_s, body_s)
        lines: List[str] = [ "📟 Jarvis Prime" ]
        if clean_subject:
            lines += ["", f"**Subject:** {clean_subject}"]
        if body_s:
            lines += ["", "📝 Message", body_s]

        eff_persona = _effective_persona(persona)
        # Personality overlay gated by personality_enabled toggle and UI header setting
        if persona_quip and _personality_enabled() and not _ui_persona_header_enabled():
            pol = _persona_overlay_line(eff_persona)
            if pol: lines += [pol]

        # Riffs independent toggle
        if _llm_riffs_enabled() and eff_persona:
            riffs = _persona_llm_riffs((title_s + "\n" + body_s).strip(), eff_persona)
            real_riffs = [ (r or "").replace("\r","").strip() for r in (riffs or []) ]
            real_riffs = [ r for r in real_riffs if r ]
            if real_riffs:
                lines += ["", f"🧠 {eff_persona} riff"]
                for r in real_riffs:
                    lines.append("> " + r)

        text = "\n".join(lines).strip()
        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": _build_client_title(clean_subject),
            "jarvis::beautified": False
        }
        return text, extras

    # --------- Beautifier ON path ---------
    # Normalize basic noise
    stripped = _strip_noise(body)
    normalized = _normalize(stripped)
    normalized = html.unescape(normalized)

    # Normalize intake (per-source cleanup)
    title, normalized = _normalize_intake(source_hint or "", title, normalized)

    # --- Querystring normalization (decode & extract clean title/message) ---
    qs_title = _maybe_parse_query_payload(title)
    qs_body  = _maybe_parse_query_payload(normalized)

    # prefer explicit fields; do NOT touch persona/riffs
    if qs_title and "title" in qs_title:
        title = unquote_plus(qs_title.get("title") or "") or title
    if qs_body and "title" in qs_body:
        title = unquote_plus(qs_body.get("title") or "") or title

    if qs_title and "message" in qs_title:
        normalized = unquote_plus(qs_title.get("message") or "") or normalized
    if qs_body and "message" in qs_body:
        normalized = unquote_plus(qs_body.get("message") or "") or normalized

    # If the entire title string looks querystring-ish, decode it once
    if (title or "").strip() and (qs_title or qs_body):
        try:
            title_decoded = unquote_plus(title.strip())
            if qs_title and "title" in qs_title:
                title = unquote_plus(qs_title.get("title") or "").strip() or title_decoded
            else:
                title = title_decoded
        except Exception:
            pass

    # remove 'action says:' lines from the visible body (riffs unaffected elsewhere) and MIME junk
    normalized = _strip_action_says(normalized)
    normalized = _strip_mime_headers(normalized)

    # images (keep meaning via ALT placeholders)
    body_wo_imgs, images, image_alts = _harvest_images(normalized)

    kind = _detect_type(title, body_wo_imgs)
    badge = _severity_badge(title + " " + body_wo_imgs)

    # Build cleaned subject and set card title
    clean_subject = _clean_subject(title, body_wo_imgs)

    # ===== Watchtower special-case =====
    if kind == "Watchtower":
        lines: List[str] = []
        lines += _header("Watchtower", badge)

        eff_persona = _effective_persona(persona)
        if persona_quip and _personality_enabled() and not _ui_persona_header_enabled():
            pol = _persona_overlay_line(eff_persona)
            if pol: lines += [pol]

        wt_md, wt_meta = _summarize_watchtower(title, body_wo_imgs)
        lines += ["", wt_md]

        ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
        riff_hint = _global_riff_hint(extras_in, source_hint)
        riffs: List[str] = []
        if riff_hint and _llm_riffs_enabled() and eff_persona:
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
        text = _fold_repeats(text)
        max_len = int(os.getenv("BEAUTIFY_MAX_LEN", "3500") or "3500")
        text = _safe_truncate(text, max_len=max_len)

        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": _build_client_title(clean_subject),
            "jarvis::beautified": True,
            "jarvis::llm_riff_lines": len(real_riffs or []),
            "watchtower::host": wt_meta.get("watchtower::host"),
            "watchtower::updated_count": wt_meta.get("watchtower::updated_count"),
        }
        if wt_meta.get("watchtower::truncated"):
            extras["watchtower::truncated"] = True
        if isinstance(extras_in, dict):
            extras.update(extras_in)
        # Poster (harvested or fallback)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        else:
            poster = _poster_fallback(title, body_wo_imgs) or _default_icon()
            if poster:
                extras["jarvis::allImageUrls"] = [poster]
                extras["client::notification"] = {"bigImageUrl": poster}
                lines += ["", f"![poster]({poster})"]
                text = "\n".join(lines).strip()
        return text, extras

    # ===== Standard path (Message-only layout) =====
    lines: List[str] = []
    lines += _header(kind, badge)

    eff_persona = _effective_persona(persona)
    if persona_quip and _personality_enabled() and not _ui_persona_header_enabled():
        pol = _persona_overlay_line(eff_persona)
        if pol: lines += [pol]

    subj = (clean_subject or "").strip()
    if subj:
        lines += ["", f"**Subject:** {subj}"]

    # Always keep human content visible (entire body); drop only transport kv/mime noise
    raw_message = (body_wo_imgs or "").strip() or normalized.strip()
    message_snip = _remove_kv_lines(raw_message).strip()
    if not message_snip:
        # Fallbacks to guarantee a message
        message_snip = (raw_message or normalized or "No message provided.").strip()

    # ---- OPTIONAL LLM MESSAGE REWRITE (toggleable) ----
    try:
        eff_persona_for_rewrite = _effective_persona(persona)
        max_chars = _llm_message_rewrite_max_chars()
        rewritten = _persona_llm_rewrite(message_snip, eff_persona_for_rewrite, max_chars=max_chars)
        if isinstance(rewritten, str) and rewritten.strip():
            message_snip = rewritten.strip()
    except Exception:
        pass

    # Prepare poster (but append after message)
    poster = None
    if images:
        poster = images[0]
    else:
        poster = _poster_fallback(title, body_wo_imgs) or _default_icon()
        if poster:
            images = [poster]

    # LLM persona riffs (render only if non-empty), independent toggle
    ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
    riffs: List[str] = []
    riff_hint = _global_riff_hint(extras_in, source_hint)
    _debug(f"persona={eff_persona}, riff_hint={riff_hint}, src={source_hint}, images={len(images)}")
    if riff_hint and _llm_riffs_enabled() and eff_persona:
        riffs = _persona_llm_riffs(ctx, eff_persona)

    real_riffs = [ (r or "").replace("\r","").strip() for r in (riffs or []) ]
    real_riffs = [ r for r in real_riffs if r ]

    # Promote riffs to the message when appropriate (e.g., Joke/Quip/Fact)
    message_snip, real_riffs = _promote_riffs_to_message_if_needed(subj, message_snip, real_riffs)

    # Now append message
    if message_snip:
        lines += ["", "📝 Message", message_snip]

    # Append poster after the body
    if poster:
        lines += ["", f"![poster]({poster})"]

    # Finally, append remaining riffs (if any)
    if real_riffs:
        lines += ["", f"🧠 {eff_persona} riff"]
        for r in real_riffs:
            lines.append("> " + r)

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text, protect_message=True)
    text = _fold_repeats(text)
    max_len = int(os.getenv("BEAUTIFY_MAX_LEN", "3500") or "3500")
    text = _safe_truncate(text, max_len=max_len)

    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "client::title": _build_client_title(clean_subject),
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images,
        "jarvis::llm_riff_lines": len(real_riffs or []),
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}
    if isinstance(extras_in, dict):
        extras.update(extras_in)

    return text, extras
