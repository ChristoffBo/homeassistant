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
            if in_msg and (t.strip().startswith("📄 ") or t.strip().startswith("🧠 ") or t.strip().startswith("![") or t.strip().startswith("📟 ")):
                in_msg = False

        if protect_message and in_msg:
            out.append(t)
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
        u = m.group(1).rstrip('.,;:)]>"\'')
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
    # Instead of showing "Jarvis Prime Proxy/SMTP", just show badge if any
    return [f"{badge}".strip()] if badge else []

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
    opt = _read_options()
    env_enabled = _bool_from_env("BEAUTIFY_LLM_ENABLED", "llm_enabled", default=True)
    opt_riffs = _bool_from_options(opt, "llm_persona_riffs_enabled", default=None)
    if opt_riffs is not None:
        return opt_riffs
    return _bool_from_options(opt, "llm_enabled", default=env_enabled)

def _personality_enabled() -> bool:
    opt = _read_options()
    env_enabled = _bool_from_env("PERSONALITY_ENABLED", default=True)
    return _bool_from_options(opt, "personality_enabled", default=env_enabled)

def _ui_persona_header_enabled() -> bool:
    opt = _read_options()
    env_enabled = _bool_from_env("UI_PERSONA_HEADER", default=True)
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

def _persona_llm_rewrite(context: str, persona: Optional[str], max_chars: int = 800) -> Optional[str]:
    if not persona or not _llm_riffs_enabled():
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
# --- SUBJECT CLEANUP & CARD TITLE -------------------------------------------------
INTAKE_NAMES = {"proxy","smtp","apprise","gotify","ntfy","webhook","webhooks"}

def _infer_subject_from_body(body: str) -> Optional[str]:
    b = (body or "").strip()
    for ln in b.splitlines():
        m = re.match(r'\s*Subject\s*:\s*(.+?)\s*$', ln, re.I)
        if m: return m.group(1).strip()
    m = re.search(r'\btest message from\s+(sonarr|radarr|lidarr|prowlarr|readarr)\b', b, re.I)
    if m: return f"{m.group(1).title()} - Test Notification"
    if re.search(r'\bspeedtest\b', b, re.I): return "SpeedTest Result"
    for ln in b.splitlines():
        t = ln.strip()
        if not t: continue
        if re.match(r'^(?:subject|title|message)\s*[:=]', t, re.I): continue
        return t[:120]
    return None

def _clean_subject(raw_title: str, body: str) -> str:
    t = (raw_title or "").strip()
    t = re.sub(r'^\s*\[(?:smtp|proxy|gotify|ntfy|apprise|webhooks?)\]\s*', '', t, flags=re.I)
    t = re.sub(r'^\s*(?:smtp|proxy|gotify|ntfy|apprise|webhooks?)\s*[:\-]\s*', '', t, flags=re.I)
    t = re.sub(r'^\s*(?:jarvis\s*prime\s*:?\s*)+', '', t, flags=re.I)
    if t.strip().lower() in INTAKE_NAMES or t.strip().lower() in {"message","notification","test"}:
        new_t = _infer_subject_from_body(body)
        if new_t: t = new_t
        else: t = ""
    return (t or "").strip()

def _build_client_title(subject: str) -> str:
    subj = (subject or "").strip()
    return subj or "Jarvis Prime"

# -------- beautify_message --------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     extras_in: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:

    if _beautify_is_disabled():
        raw_title = title if title else ""
        raw_body  = body if body else ""
        lines: List[str] = []
        eff_persona = _effective_persona(persona)
        if _personality_enabled() and not _ui_persona_header_enabled():
            pol = _persona_overlay_line(eff_persona)
            if pol: lines.append(pol)
        lines.append(raw_body)
        if _llm_riffs_enabled() and eff_persona:
            riff_ctx = _scrub_meta(raw_body if isinstance(raw_body, str) else "")
            riffs = _persona_llm_riffs(riff_ctx, eff_persona)
            real_riffs = [r.strip() for r in riffs if r.strip()]
            if real_riffs:
                lines += ["", f"🧠 {eff_persona} riff"]
                for r in real_riffs:
                    lines.append("> " + r)
        text = "\n".join(lines)
        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": raw_title or "Jarvis Prime",
            "jarvis::beautified": False
        }
        return text, extras

    # -------- Beautifier ON --------
    stripped = _strip_noise(body)
    normalized = _normalize(stripped)
    normalized = html.unescape(normalized)
    title, normalized = _normalize_intake(source_hint or "", title, normalized)

    body_wo_imgs, images, image_alts = _harvest_images(normalized)
    kind = _detect_type(title, body_wo_imgs)
    badge = _severity_badge(title + " " + body_wo_imgs)

    clean_subject = _clean_subject(title, body_wo_imgs)

    lines: List[str] = []
    if badge: lines += [badge]

    eff_persona = _effective_persona(persona)
    if persona_quip and _personality_enabled() and not _ui_persona_header_enabled():
        pol = _persona_overlay_line(eff_persona)
        if pol: lines += [pol]

    # --- USE SUBJECT AS HEADER ---
    subj = (clean_subject or "").strip()
    if subj:
        lines += [f"**{subj}**"]

    # Message body
    raw_message = (body_wo_imgs or "").strip() or normalized.strip()
    message_snip = _remove_kv_lines(raw_message).strip() or raw_message
    message_snip = _final_qs_cleanup(message_snip)

    try:
        eff_persona_for_rewrite = _effective_persona(persona)
        max_chars = _llm_message_rewrite_max_chars()
        rewrite_ctx = _scrub_meta(message_snip)
        rewritten = _persona_llm_rewrite(rewrite_ctx, eff_persona_for_rewrite, max_chars=max_chars)
        if isinstance(rewritten, str) and rewritten.strip():
            message_snip = _scrub_meta(rewritten.strip())
    except Exception:
        pass

    if message_snip:
        lines += ["", "📝 Message", message_snip]

    poster = None
    if images: poster = images[0]
    else:
        poster = _poster_fallback(title, body_wo_imgs) or _default_icon()
        if poster: images = [poster]
    if poster: lines += ["", f"![poster]({poster})"]

    riffs: List[str] = []
    riff_hint = _global_riff_hint(extras_in, source_hint)
    if riff_hint and _llm_riffs_enabled() and eff_persona:
        ctx = _scrub_meta(message_snip)
        if subj: ctx = (ctx + "\n\nSubject: " + subj).strip()
        riffs = _persona_llm_riffs(ctx, eff_persona)

    real_riffs = [r.strip() for r in riffs if r.strip()]
    if real_riffs:
        lines += ["", f"🧠 {eff_persona} riff"]
        for r in real_riffs: lines.append("> " + r)

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
    if images: extras["client::notification"] = {"bigImageUrl": images[0]}
    if isinstance(extras_in, dict): extras.update(extras_in)

    return text, extras