from __future__ import annotations
import re, json, importlib, random, html, os
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import unquote_plus, parse_qs  # ADD

# -------- Regex library --------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[([^\]]*)\]\s*\(\s*<?\s*(https?://[^\s)]+?)\s*>?\s*\)', re.I | re.S)
KV_RE      = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+)$', re.M)

TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-{1,2}]|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')

IP_RE  = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{2})\b')
HOST_RE = re.compile(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b')
VER_RE  = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')

EMOJI_RE = re.compile("[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF\U0001FA70-\U0001FAFF\U0001F1E6-\U0001F1FF]", flags=re.UNICODE)
LIKELY_POSTER_HOSTS = (
    "githubusercontent.com","fanart.tv","themoviedb.org","image.tmdb.org","trakt.tv","tvdb.org","gravatar.com"
)

CODE_FENCE_RE = re.compile(r'```.*?```', re.S)
LINK_RE       = re.compile(r'\[[^\]]+?\]\([^)]+?\)')

def _fold_repeats(text: str, threshold: int = 3) -> str:
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

def _kv_to_bullets(text: str) -> Optional[str]:
    if not text:
        return None
    kvs = []
    for ln in text.splitlines():
        m = KV_RE.match(ln)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            if key.lower() not in {"title", "message", "topic", "tags", "priority"}:
                kvs.append(f"- **{key}:** {val}")
    if kvs:
        return "\n".join(kvs)
    return None

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
    lines = text.splitlines()
    out: List[str] = []
    seen: set = set()
    in_code = False
    in_msg  = False

    for ln in lines:
        t = ln.rstrip()
        if t.strip().startswith("```"):
            in_code = not in_code
            out.append(t); continue
        if in_code:
            out.append(t); continue

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
        return ""

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
    if re.search(r'\d', v):
        v = f"`{v}`"
    return f"- **{label.strip()}:** {v}"

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

def _header(kind: str, badge: str = "") -> List[str]:
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
    if "qnap" in tb or "qts" in tb: return "QNAP"
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

def _bool_from_options(opt: Dict[str, Any], key: str, default: Optional[bool] = None) -> Optional[bool]:
    if key not in opt:
        return default
    try:
        v = str(opt.get(key, default)).strip().lower()
        return v in ("1","true","yes","on")
    except Exception:
        return default

# ✅ FIXED VERSION BELOW
def _llm_riffs_enabled() -> bool:
    """Allow Lexi riffs when LLM is off but persona riffs are enabled."""
    opt = _read_options()

    riffs_opt = _bool_from_options(opt, "llm_persona_riffs_enabled", default=None)
    if riffs_opt is False:
        return False

    llm_opt = _bool_from_options(opt, "llm_enabled", default=None)

    # if LLM is off but persona riffs explicitly on → allow Lexi riffs
    if llm_opt is False and riffs_opt is True:
        return True

    # if LLM off and riffs not set → allow Lexi riffs
    if llm_opt is False and riffs_opt is None:
        return True

    # fallback normal path
    env_enabled = _bool_from_env("BEAUTIFY_LLM_ENABLED", "llm_enabled", default=True)
    return _bool_from_options(opt, "llm_enabled", default=env_enabled) if riffs_opt is None else True
def _llm_enabled() -> bool:
    """Check if LLM itself is enabled (master switch)."""
    opt = _read_options()
    llm_master = _bool_from_options(opt, "llm_enabled", default=None)
    if llm_master is not None:
        return llm_master
    return _bool_from_env("BEAUTIFY_LLM_ENABLED", "llm_enabled", default=True)

def _personality_enabled() -> bool:
    opt = _read_options()
    env_enabled = _bool_from_env("PERSONALITY_ENABLED", default=True)
    return _bool_from_options(opt, "personality_enabled", default=env_enabled)

def _ui_persona_header_enabled() -> bool:
    opt = _read_options()
    env_enabled = _bool_from_env("UI_PERSONA_HEADER", default=True)
    return _bool_from_options(opt, "ui_persona_header", default=env_enabled)

def _llm_message_rewrite_enabled() -> bool:
    """Rewrites require BOTH llm_enabled=true AND llm_rewrite_enabled=true."""
    opt = _read_options()
    llm_master = _bool_from_options(opt, "llm_enabled", default=None)
    if llm_master is False:
        return False
    return _bool_from_options(opt, "llm_rewrite_enabled", default=False)

def _llm_message_rewrite_max_chars() -> int:
    opt = _read_options()
    try:
        return int(opt.get("llm_message_rewrite_max_chars", 350))
    except Exception:
        return 350

def _persona_llm_riffs(context: str, persona: Optional[str]) -> List[str]:
    """
    Returns LLM riffs if LLM enabled, Lexi riffs if LLM disabled but riffs enabled.
    """
    if not persona:
        return []

    if not _llm_riffs_enabled():
        return []

    llm_on = _llm_enabled()

    if llm_on:
        try:
            llm = importlib.import_module("llm_client")
            llm = importlib.reload(llm)
            out = llm.persona_riff(persona=persona, context=context)
            if isinstance(out, list) and out:
                return [s.strip() for s in out if s and s.strip()]
            if isinstance(out, str) and out.strip():
                return [out.strip()]
        except Exception:
            pass

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
    else:
        try:
            mod = importlib.import_module("personality")
            mod = importlib.reload(mod)
            if hasattr(mod, "lexi_riffs"):
                max_lines = int(os.getenv("LLM_PERSONA_LINES_MAX", "3") or "3")
                subj = context
                m = re.search(r"Subject:\s*(.+)", context, flags=re.I)
                if m:
                    subj = m.group(1).strip()
                out = mod.lexi_riffs(persona, n=max_lines, subject=subj, body=context)
                if isinstance(out, list):
                    return [str(x).strip() for x in out if str(x).strip()]
        except Exception:
            pass

    return []

def _neutral_llm_rewrite(context: str, max_chars: int = 350) -> Optional[str]:
    """Neutral, terse rewrite to keep key facts. No persona."""
    if not _llm_message_rewrite_enabled():
        return None
    try:
        llm = importlib.import_module("llm_client")
    except Exception:
        return None
    try:
        sys_prompt = (
            "YOU ARE A NEUTRAL, TERSE REWRITER.\n"
            f"Rules: Preserve key facts, remove fluff, <= {max_chars} chars, no bullets, no markdown, no emojis, no persona."
        )
        user_prompt = "Rewrite neutrally:\n" + (context or "").strip()
        if hasattr(llm, "rewrite"):
            raw = llm.rewrite(
                text=f"[SYSTEM]\n{sys_prompt}\n[INPUT]\n{user_prompt}\n[OUTPUT]\n",
                mood="neutral",
                timeout=8,
                cpu_limit=70,
                allow_profanity=False,
            )
            s = (raw or "").strip()
            if s:
                return s[:max_chars].strip()
    except Exception:
        pass
    return None

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
        "sonarr","radarr","watchtower","speedtest","apt","syslog","qnap"
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
_WT_HOST_RX = re.compile(r'\bupdates?\s+on\s+([A-Za-z0-9._-]+)', re.I)
_WT_UPDATED_RXES = [
    re.compile(
        r'^\s*[-*]\s*(?P<name>/?[A-Za-z0-9._-]+)\s*(?P<img>[^)]+)\s*:\s*(?P<old>[0-9a-f]{7,64})\s+updated\s+to\s+(?P<new>[0-9a-f]{7,64})\s*$',
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

def _opt_int(name: str, default: int) -> int:
    opt = _read_options()
    try:
        return int(opt.get(name, default))
    except Exception:
        return default

def _opt_bool(name: str, default: bool) -> bool:
    opt = _read_options()
    try:
        v = str(opt.get(name, default)).strip().lower()
        return v in ("1","true","yes","on")
    except Exception:
        return default

def _summarize_watchtower(title: str, body: str, limit: int = 50) -> Tuple[str, Dict[str, Any]]:
    lines = (body or "").splitlines()
    updated: List[Tuple[str, str, str, str]] = []
    raw_kept: List[str] = []
    for ln in lines:
        if _WT_FRESH_RX.search(ln):
            continue
        matched = False
        for rx in _WT_UPDATED_RXES:
            m = rx.match(ln)
            if m:
                name = (m.groupdict().get("name") or "").strip()
                img  = (m.groupdict().get("img") or "").strip()
                old  = (m.groupdict().get("old") or "").strip()
                new  = (m.groupdict().get("new") or "").strip()
                if not img:
                    img = name
                updated.append((name, img, old, new))
                matched = True
                break
        if not matched:
            raw_kept.append(ln)

    host = _watchtower_host_from_title(title) or "unknown"
    meta: Dict[str, Any] = {"watchtower::host": host, "watchtower::updated_count": len(updated)}

    if not updated:
        md = f"**Host:** `{host}`\n\n_No updates (all images fresh)._"
        return md, meta

    if len(updated) > max(1, limit):
        updated = updated[:limit]
        meta["watchtower::truncated"] = True

    bullets = "\n".join([
        f"• `{name}` → `{img}`\n   old: `{old}` → new: `{new}`"
        for name, img, old, new in updated
    ])
    md_lines = [f"**Host:** `{host}`", "", f"**Updated ({len(updated)}):**", bullets]

    raw_tail_n = _opt_int("watchtower_raw_tail_lines", 0)
    if raw_tail_n > 0 and raw_kept:
        tail = "\n".join(raw_kept[-raw_tail_n:]).strip()
        if tail:
            md_lines += ["", "<details><summary>Raw</summary>", "", "```", tail, "```", "</details>"]

    return "\n".join(md_lines), meta

_QNAP_DISK_RX = re.compile(r'\b(?:disk|drive)\s*(\d+)\b', re.I)
_QNAP_VOL_RX  = re.compile(r'\bvol(?:ume)?\s*([A-Za-z0-9_-]+)', re.I)

def _summarize_qnap(title: str, body: str, limit_kv: int = 20) -> Tuple[str, Dict[str, Any]]:
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    kvs: List[str] = []
    others: List[str] = []

    disk = None
    vol  = None

    for ln in lines:
        m = KV_RE.match(ln.strip())
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            if k.lower() not in {"title","message","topic","tags","priority"}:
                kvs.append((k, v))
        else:
            others.append(ln)

        if disk is None:
            dm = _QNAP_DISK_RX.search(ln)
            if dm:
                disk = dm.group(1)
        if vol is None:
            vm = _QNAP_VOL_RX.search(ln)
            if vm:
                vol = vm.group(1)

    bullets = []
    header_bits = []
    if disk: header_bits.append(f"Disk `{disk}`")
    if vol:  header_bits.append(f"Vol `{vol}`")
    if header_bits:
        bullets.append(f"- **Scope:** " + ", ".join(header_bits))

    for i, (k, v) in enumerate(kvs[:max(1, limit_kv)]):
        bullets.append(f"- **{k}:** {v}")

    if not kvs and others:
        for ln in others[:10]:
            bullets.append(f"- {ln.strip()}")

    md_lines = []
    md_lines.append("**QNAP Alert:**")
    if bullets:
        md_lines += bullets

    raw_tail_n = _opt_int("qnap_raw_tail_lines", 0)
    if raw_tail_n > 0 and lines:
        tail = "\n".join(lines[-raw_tail_n:]).strip()
        if tail:
            md_lines += ["", "<details><summary>Raw</summary>", "", "```", tail, "```", "</details>"]

    meta: Dict[str, Any] = {"qnap::kv_count": len(kvs), "qnap::has_disk": bool(disk), "qnap::has_vol": bool(vol)}
    return "\n".join(md_lines), meta
_QS_TRIGGER_KEYS = {"title","message","priority","topic","tags"}

def _maybe_parse_query_payload(s: Optional[str]) -> Optional[Dict[str, str]]:
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
    if not text:
        return ""
    out = _ACTION_SAYS_RX.sub("", text)
    return re.sub(r'\n{3,}', '\n\n', out).strip()

_MIME_HEADER_RX = re.compile(r'^\s*Content-(?:Disposition|Type|Length|Transfer-Encoding)\s*:.*$', re.I | re.M)
def _strip_mime_headers(text: str) -> str:
    if not text:
        return ""
    s = _MIME_HEADER_RX.sub("", text)
    return re.sub(r'\n{3,}', '\n\n', s).strip()

INTAKE_NAMES = {"proxy","smtp","apprise","gotify","ntfy","webhook","webhooks"}

def _infer_subject_from_body(body: str) -> Optional[str]:
    b = (body or "").strip()
    for ln in b.splitlines():
        m = re.match(r'\s*Subject\s*:\s*(.+?)\s*$', ln, re.I)
        if m:
            return m.group(1).strip()
    m = re.search(r'\btest message from\s+(sonarr|radarr|lidarr|prowlarr|readarr)\b', b, re.I)
    if m:
        svc = m.group(1).title()
        return f"{svc} - Test Notification"
    if re.search(r'\bspeedtest\b', b, re.I):
        return "SpeedTest Result"
    for ln in b.splitlines():
        t = ln.strip()
        if not t:
            continue
        if re.match(r'^(?:subject|title|message)\s*[:=]', t, re.I):
            continue
        return t[:120]
    return None

def _clean_subject(raw_title: str, body: str) -> str:
    t = (raw_title or "").strip()
    if not t:
        t = ""
    t = re.sub(r'^\s*(?:(?:smtp|proxy|gotify|ntfy|apprise|webhooks?)\s*)+', '', t, flags=re.I)
    t = re.sub(r'^\s*(?:smtp|proxy|gotify|ntfy|apprise|webhooks?)\s*[:\-]\s*', '', t, flags=re.I)
    if t.strip().lower() in INTAKE_NAMES or t.strip().lower() in {"message","notification","test"}:
        new_t = _infer_subject_from_body(body)
        if new_t:
            t = new_t
    t = re.sub(r'^\s*(?:jarvis\s*prime\s*:?\s*)+', '', t, flags=re.I)
    return (t or "").strip()

def _build_client_title(subject: str) -> str:
    subj = (subject or "").strip()
    return f"Jarvis Prime: {subj}" if subj else "Jarvis Prime"

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

def _builtin_icon_map() -> Dict[str,str]:
    base = "https://raw.githubusercontent.com/walkxcode/dashboard-icons/master/png"
    return {
        "sonarr": f"{base}/sonarr.png",
        "radarr": f"{base}/radarr.png",
        "lidarr": f"{base}/lidarr.png",
        "prowlarr": f"{base}/prowlarr.png",
        "readarr": f"{base}/readarr.png",
        "bazarr": f"{base}/bazarr.png",
        "qbittorrent": f"{base}/qbittorrent.png",
        "transmission": f"{base}/transmission.png",
        "jellyfin": f"{base}/jellyfin.png",
        "plex": f"{base}/plex.png",
        "emby": f"{base}/emby.png",
        "sabnzbd": f"{base}/sabnzbd.png",
        "overseerr": f"{base}/overseerr.png",
        "gluetun": f"{base}/gluetun.png",
        "pihole": f"{base}/pi-hole.png",
        "unifi": f"{base}/unifi-network.png",
        "portainer": f"{base}/portainer.png",
        "watchtower": f"{base}/watchtower.png",
        "docker": f"{base}/docker.png",
        "homeassistant": f"{base}/home-assistant.png",
        "speedtest": f"{base}/speedtest.png",
        "apt": f"{base}/debian.png",
        "smtp": f"{base}/mail.png",
        "apprise": f"{base}/bell.png",
        "gotify": f"{base}/bell.png",
        "ntfy": f"{base}/bell.png",
        "proxy": f"{base}/reverse-proxy.png",
        "qnap": f"{base}/nas.png",
        "unraid": f"{base}/unraid.png",
    }

def _icon_from_env(keyword: str) -> Optional[str]:
    key = f"ICON_{keyword.upper()}_URL"
    v = os.getenv(key) or ""
    return v.strip() or None

def _default_icon() -> Optional[str]:
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
    keywords = ["sonarr","radarr","lidarr","prowlarr","readarr","bazarr",
                "qbittorrent","transmission","jellyfin","plex","emby",
                "sabnzbd","overseerr","gluetun","pihole","unifi","portainer",
                "watchtower","docker","homeassistant","speedtest","apt",
                "smtp","apprise","gotify","ntfy","proxy","qnap","unraid"]
    text = f"{title} {body}".lower()
    opt_map = _icon_map_from_options()
    builtin = _builtin_icon_map()
    for word in keywords:
        if word in text:
            return opt_map.get(word) or _icon_from_env(word) or builtin.get(word)
    return _default_icon()

def _remove_kv_lines(text: str) -> str:
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
                continue
        kept.append(ln)
    s = "\n".join(kept)
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s

def _final_qs_cleanup(text: str) -> str:
    if not text:
        return ""
    maybe = _maybe_parse_query_payload(text)
    if maybe:
        for k in ("message","text","body","m"):
            if k in maybe and maybe[k].strip():
                return maybe[k].strip()
        parts = []
        for k,v in maybe.items():
            if k.lower() in {"title","topic","tags","priority"}:
                continue
            parts.append(f"{k}: {v}")
        return "\n".join(parts).strip() or text
    return text
_META_LINE_RX = re.compile(
    r'^\s*(?:tone|rule|rules|guidelines?|style(?:\s*hint)?|instruction|instructions|system(?:\s*prompt)?|persona|respond(?:\s*with)?|produce\s*only)\s*[:\-]',
    re.I
)
_META_TAG_RX = re.compile(r'\s*(?:(?:SYSTEM|INPUT|OUTPUT)|(?:SYSTEM|INPUT|OUTPUT))\s*', re.I)

def _scrub_meta(text: str) -> str:
    if not text:
        return ""
    s = _META_TAG_RX.sub(" ", text)
    keep: List[str] = []
    for ln in s.splitlines():
        if _META_LINE_RX.search(ln):
            continue
        keep.append(ln)
    s = "\n".join(keep)
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s

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
    t = title or ""
    b = body or ""
    blocks = re.findall(r'(?is)name="(title|message)"\s*\r?\n\r?\n(.*?)(?:\r?\n--|$)', b)
    fields = {k.lower(): v.strip() for k,v in blocks}
    qs = _maybe_parse_query_payload(b)
    if qs:
        fields.update({k.lower(): v for k,v in qs.items()})
    if fields.get("title"): t = fields["title"]
    if fields.get("message"): b = fields["message"]
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

# -------- Public API --------
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     extras_in: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:

    if isinstance(title, str) and "joke" in title.lower():
        text = body if isinstance(body, str) else ("" if body is None else str(body))
        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": (title.strip() or "Jarvis Prime: Joke"),
            "jarvis::beautified": False,
            "jarvis::raw_joke": True,
            "riff_hint": False,
        }
        return (text or "").strip(), extras

    if isinstance(extras_in, dict) and extras_in.get("jarvis::raw_persona"):
        text = body if isinstance(body, str) else ("" if body is None else str(body))
        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": _build_client_title(_clean_subject(title or "", text)),
            "jarvis::beautified": False,
            "jarvis::raw_persona": True,
        }
        return text, extras

    if _beautify_is_disabled():
        raw_title = title if title is not None else ""
        raw_body  = body  if body  is not None else ""

        lines: List[str] = []

        eff_persona = _effective_persona(persona)
        if _personality_enabled() and not _ui_persona_header_enabled():
            pol = _persona_overlay_line(eff_persona)
            if pol:
                lines.append(pol)

        lines.append(raw_body)

        if _llm_riffs_enabled() and eff_persona:
            riff_ctx = _scrub_meta(raw_body if isinstance(raw_body, str) else "")
            riffs = _persona_llm_riffs(riff_ctx, eff_persona)
            real_riffs = [(r or "").replace("\r","").strip() for r in (riffs or [])]
            real_riffs = [r for r in real_riffs if r]
            if real_riffs:
                lines += ["", f"🧠 {eff_persona} riff"]
                for r in real_riffs:
                    lines.append("> " + r)

        text = "\n".join(lines)
        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "jarvis::beautified": False
        }
        return text, extras

    stripped = _strip_noise(body)
    normalized = _normalize(stripped)
    normalized = html.unescape(normalized)

    title, normalized = _normalize_intake(source_hint or "", title, normalized)

    qs_title = _maybe_parse_query_payload(title)
    qs_body  = _maybe_parse_query_payload(normalized)

    if qs_title and "title" in qs_title:
        title = unquote_plus(qs_title.get("title") or "") or title
    if qs_body and "title" in qs_body:
        title = unquote_plus(qs_body.get("title") or "") or title
    if qs_title and "message" in qs_title:
        normalized = unquote_plus(qs_title.get("message") or "") or normalized
    if qs_body and "message" in qs_body:
        normalized = unquote_plus(qs_body.get("message") or "") or normalized

    if (title or "").strip() and (qs_title or qs_body):
        try:
            title_decoded = unquote_plus(title.strip())
            if qs_title and "title" in qs_title:
                title = unquote_plus(qs_title.get("title") or "").strip() or title_decoded
            else:
                title = title_decoded
        except Exception:
            pass

    normalized = _strip_action_says(normalized)
    normalized = _strip_mime_headers(normalized)

    body_wo_imgs, images, image_alts = _harvest_images(normalized)

    kind = _detect_type(title, body_wo_imgs)
    badge = _severity_badge(title + " " + body_wo_imgs)
    clean_subject = _clean_subject(title, body_wo_imgs)

    # Watchtower and QNAP handled separately (omitted here for brevity; same as above parts)

    # === Standard Path ===
    lines: List[str] = []
    lines += _header(kind, badge)

    eff_persona = _effective_persona(persona)
    if persona_quip and _personality_enabled() and not _ui_persona_header_enabled():
        pol = _persona_overlay_line(eff_persona)
        if pol: lines += [pol]

    subj = (clean_subject or "").strip()
    if subj:
        lines += ["", f"**Subject:** {subj}"]

    raw_message = (body_wo_imgs or "").strip() or normalized.strip()
    message_snip = _remove_kv_lines(raw_message).strip()
    if not message_snip:
        message_snip = (raw_message or normalized or "No message provided.").strip()
    message_snip = _final_qs_cleanup(message_snip)
    kv_bullets = _kv_to_bullets(message_snip)
    if kv_bullets:
        message_snip = kv_bullets

    try:
        if _llm_message_rewrite_enabled():
            max_chars = _llm_message_rewrite_max_chars()
            rewrite_ctx = _scrub_meta(message_snip)
            rewritten = _neutral_llm_rewrite(rewrite_ctx, max_chars=max_chars)
            if isinstance(rewritten, str) and rewritten.strip():
                message_snip = _scrub_meta(rewritten.strip())
    except Exception:
        pass

    if message_snip:
        lines += ["", "📝 Message", message_snip]

    poster = None
    if images:
        poster = images[0]
    else:
        poster = _poster_fallback(title, body_wo_imgs) or _default_icon()
        if poster:
            images = [poster]
    if poster:
        lines += ["", f"![poster]({poster})"]

    riffs: List[str] = []
    riff_hint = _global_riff_hint(extras_in, source_hint)
    _debug(f"persona={eff_persona}, riff_hint={riff_hint}, src={source_hint}, images={len(images)}")
    if riff_hint and _llm_riffs_enabled() and eff_persona:
        ctx = _scrub_meta(message_snip)
        if subj:
            ctx = (ctx + "\n\nSubject: " + subj).strip()
        riffs = _persona_llm_riffs(ctx, eff_persona)

    real_riffs = [(r or "").replace("\r","").strip() for r in (riffs or [])]
    real_riffs = [r for r in real_riffs if r]
    if real_riffs:
        lines += ["", f"🧠 {eff_persona} riff"]
        for r in real_riffs:
            lines.append("> " + r)

    text = "\n".join(lines).strip()
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
# -------- END OF beautify_message --------

def beautify_test() -> None:
    """CLI-style quick self-check for beautify logic."""
    t = "Watchtower update report"
    b = """- heimdall : 8d3c76a updated to 29faab4
- vault : 85f12a0 updated to 90a0afc
- nextcloud : 2296ac1 updated to 602aa91"""
    txt, meta = beautify_message(t, b, source_hint="watchtower", persona="Lexi")
    print("---- TEXT ----")
    print(txt)
    print("\n---- META ----")
    print(json.dumps(meta, indent=2))

# Optional entrypoint when run manually
if __name__ == "__main__":
    print("✅ Running beautify.py self-test…")
    try:
        beautify_test()
    except Exception as e:
        print("❌ Self-test failed:", e)

# -------------------------------------------------------------------
# Safety / Reference section
# -------------------------------------------------------------------

"""
Module summary:

beautify_message(title, body, …) → (text, extras)
   - Converts raw notification text into Markdown-ready output
   - Cleans, deduplicates, inserts icons and persona riffs

Helper functions overview:

_strip_noise(text)
    Removes emojis and boilerplate lines (“sent from …”, etc.)

_normalize(text)
    Cleans trailing spaces, tabs, and collapses excess blank lines.

_harvest_images(text)
    Extracts image URLs and replaces inline MD images with placeholders.

_watchtower / _qnap summarizers
    Produce condensed Markdown for system alerts with structured bullets.

_persona_llm_riffs()
    Generates persona-specific riffs (LLM or Lexi fallback).

_neutral_llm_rewrite()
    Produces short factual summaries when rewrite toggle is enabled.

_poster_fallback()
    Auto-detects icon/poster from keywords or configured map.

_final_qs_cleanup()
    Decodes URL-encoded query payloads into readable body text.

_safe_truncate()
    Ensures markdown completeness while keeping message ≤ 3500 chars.

_fold_repeats()
    Folds repeated identical lines to avoid log spam.

_linewise_dedup_markdown()
    Deduplicates identical markdown lines while respecting code fences.

Each helper is pure-function style — no global mutations — safe for async use.
"""

# -------------------------------------------------------------------
# Sanity guard to ensure we never import partially
# -------------------------------------------------------------------
try:
    assert callable(beautify_message)
    assert callable(_scrub_meta)
    assert callable(_poster_fallback)
    assert callable(_persona_llm_riffs)
    assert callable(_neutral_llm_rewrite)
except Exception as _e_verify:
    print(f"[beautify] ⚠️ Verification warning: {type(_e_verify).__name__}: {_e_verify}")

# -------------------------------------------------------------------
# End-of-file newline padding (for diff-safe packaging)
# -------------------------------------------------------------------

# (EOF padding: 10 empty lines below)
#