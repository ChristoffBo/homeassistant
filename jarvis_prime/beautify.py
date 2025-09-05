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
# Narrower version detector: prefer semantic-looking versions; ignore lone floats like 0.86
VER_RE  = re.compile(r'\bv?(?:\d+\.\d+\.\d+|\d+\.\d+(?:\s*(?:LTS|beta|rc\d*)|\b))\b', re.I)

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
    """Safe de-dup that never splits on '.' so IPs like 10.0.0.249 remain intact."""
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
    if "lidarr" in tb: return "Lidarr"
    if "prowlarr" in tb: return "Prowlarr"
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

    # also infer IPs/hosts/versions
    ip_list = _find_ips(title, body)
    for ip in ip_list:
        if f"`{ip}`" not in " ".join(details):
            details.append(_fmt_kv("IP", ip))
    for host in HOST_RE.findall(body or ""):
        if not IP_RE.match(host):
            details.append(_fmt_kv("host", host))

    # semantic-like versions only (avoid plain floats like 0.86)
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

# --------- Persona helpers ----------
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
        "sonarr","radarr","watchtower","speedtest","apt","syslog","proxmox","qnap","duplicati","ansible","kuma"
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

# ============================
# Watchtower-aware summarizer (existing)
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

# ============================
# NEW Parsers — helpers & detectors
# ============================

# -------- ARR (Radarr/Sonarr/Lidarr/Prowlarr) --------
def _looks_arr(body: str) -> bool:
    try:
        obj = json.loads(body)
        if isinstance(obj, dict):
            low = {k.lower(): k for k in obj.keys()}
            if ("eventtype" in low) and (("movie" in low) or ("series" in low) or ("artist" in low) or ("release" in low)):
                return True
    except Exception:
        pass
    return False

def _parse_arr(title: str, body: str) -> Tuple[str, Dict[str, Any], List[str]]:
    obj = {}
    try:
        obj = json.loads(body)
    except Exception:
        return "", {}, []

    # Normalize keys
    low = {k.lower(): k for k in obj.keys()}
    event = str(obj.get(low.get("eventtype", ""), "") or obj.get(low.get("event", ""), "")).strip()
    application = str(obj.get(low.get("instanceName",""), "") or obj.get(low.get("application",""), "")).strip()  # optional
    # Entities
    movie = obj.get(low.get("movie",""), None)
    series = obj.get(low.get("series",""), None)
    episodes = obj.get(low.get("episodes",""), None)
    release = obj.get(low.get("release",""), None)

    # Common fields
    quality = ""
    size = ""
    indexer = ""
    poster = ""

    if isinstance(release, dict):
        quality = str(release.get("quality","") or "").strip() or quality
        size = str(release.get("size","") or "").strip() or size
        indexer = str(release.get("indexer","") or release.get("releaseGroup","") or "").strip() or indexer
    if isinstance(movie, dict):
        poster = (movie.get("images",{}) or {}).get("poster","") if isinstance(movie.get("images",{}), dict) else ""
        # some payloads: movie['images'] is a list of dicts with 'coverType':'poster','url':...
        if not poster and isinstance(movie.get("images"), list):
            for it in movie["images"]:
                if isinstance(it, dict) and str(it.get("coverType","")).lower()=="poster" and it.get("url"):
                    poster = it["url"]; break
    if isinstance(series, dict):
        if not poster and isinstance(series.get("images"), list):
            for it in series["images"]:
                if isinstance(it, dict) and str(it.get("coverType","")).lower() in ("poster","banner","fanart") and it.get("url"):
                    poster = it["url"]; break

    # Compose
    facts: List[str] = []
    details: List[str] = []

    badge = ""
    evl = (event or "").lower()
    if evl in ("downloadfailed","episodefiledelete","healthissue","renamefailed","importfailed","movefailed","indexerdown"):
        badge = "❌"
    elif evl in ("warning","healthwarning"):
        badge = "⚠️"
    elif evl in ("grab","grabbed","downloadcompleted","imported","renamed","test","onhealthrestored"):
        badge = "✅"
    else:
        badge = _severity_badge(title + " " + body)

    # Title line
    lines: List[str] = []
    kind = "Radarr/Sonarr/Lidarr/Prowlarr"
    lines += _header(kind, badge)

    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)

    # Entity-specific
    if isinstance(movie, dict):
        name = str(movie.get("title","") or "").strip()
        year = str(movie.get("year","") or "").strip()
        if name: facts.append(_fmt_kv("Movie", f"{name} ({year})" if year else name))
    if isinstance(series, dict):
        sname = str(series.get("title","") or "").strip()
        if sname: facts.append(_fmt_kv("Series", sname))
        # Episodes array → SxxEyy summary
        if isinstance(episodes, list) and episodes:
            try:
                first = episodes[0]
                s = int(first.get("seasonNumber", 0))
                e = int(first.get("episodeNumber", 0))
                facts.append(_fmt_kv("Episode", f"S{s:02d}E{e:02d}"))
            except Exception:
                pass

    if event: facts.append(_fmt_kv("Event", event))
    if quality: details.append(_fmt_kv("Quality", quality))
    if size: details.append(_fmt_kv("Size", size))
    if indexer: details.append(_fmt_kv("Indexer", indexer))

    # Build final
    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    images: List[str] = []
    if poster:
        images.append(poster)

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)

    extras: Dict[str, Any] = {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}
    if images:
        extras["jarvis::allImageUrls"] = images
        extras["client::notification"] = {"bigImageUrl": images[0]}
    return text, extras, images

# -------- Uptime Kuma --------
def _looks_kuma(body: str, title: str) -> bool:
    tb = (title + " " + body).lower()
    if "uptime kuma" in tb or "kuma" in tb:
        return True
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and ("title" in obj or "msg" in obj or "message" in obj):
            # Kuma often sends simple title/body JSON via custom/webhook notifications
            return True
    except Exception:
        pass
    return False

def _parse_kuma(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    name = ""; status = ""; latency = ""; reason = ""; cert_days = ""
    badge = ""
    try:
        obj = json.loads(body)
        name = str(obj.get("title") or obj.get("monitor") or "").strip()
        msg  = str(obj.get("msg") or obj.get("message") or "").strip()
        # heuristics
        low = (title + " " + msg).lower()
        if "down" in low: status = "DOWN"
        elif "up" in low: status = "UP"
        # optional fields
        latency = str(obj.get("ping") or obj.get("latency") or "").strip()
        cert_days = str(obj.get("certDaysRemaining") or obj.get("tls_days_left") or "").strip()
        reason = msg
    except Exception:
        # text path
        low = (title + " " + body).lower()
        if "down" in low: status = "DOWN"
        elif "up" in low: status = "UP"
        name = title.strip() or "Kuma Monitor"
        reason = _first_nonempty_line(body)

    badge = "❌" if status=="DOWN" else ("✅" if status=="UP" else _severity_badge(title + " " + body))

    lines = []
    lines += _header("Uptime Kuma", badge)
    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)

    facts = []
    details = []
    if name:   facts.append(_fmt_kv("Monitor", name))
    if status: facts.append(_fmt_kv("Status", status))
    if latency: details.append(_fmt_kv("Latency", f"{latency} ms" if latency and latency.isdigit() else latency))
    if cert_days: details.append(_fmt_kv("Cert days", cert_days))
    if reason: details.append(_fmt_kv("Reason", reason))

    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)
    extras = {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}
    return text, extras

# -------- Proxmox --------
def _looks_proxmox(body: str, title: str) -> bool:
    tb = (title + " " + body).lower()
    if "proxmox" in tb or "pve" in tb:
        return True
    try:
        obj = json.loads(body)
        if isinstance(obj, dict):
            keys = {k.lower() for k in obj.keys()}
            if {"node","severity"} & keys or {"vmid","ctid"} & keys or "message" in keys:
                return True
    except Exception:
        pass
    return False

def _parse_proxmox(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    node = ""; vmid = ""; ctid = ""; event = ""; severity = ""; message = ""; task = ""; duration = ""
    try:
        obj = json.loads(body)
        low = {k.lower(): k for k in obj.keys()}
        def g(k): 
            kk = low.get(k.lower()); 
            return obj.get(kk) if kk else None
        node = str(g("node") or "").strip()
        vmid = str(g("vmid") or "").strip()
        ctid = str(g("ctid") or "").strip()
        event = str(g("event") or g("type") or "").strip()
        severity = str(g("severity") or "").strip()
        message = str(g("message") or "").strip()
        task = str(g("taskid") or g("upid") or "").strip()
        duration = str(g("duration") or "").strip()
    except Exception:
        pass

    sev = (severity or title).lower()
    badge = "❌" if "error" in sev or "failed" in sev else ("⚠️" if "warn" in sev else ("✅" if "success" in sev or "ok" in sev or "finished" in sev else _severity_badge(title + " " + body)))

    lines=[]
    lines += _header("Proxmox", badge)
    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)

    facts=[]; details=[]
    if node: facts.append(_fmt_kv("Node", node))
    if event: facts.append(_fmt_kv("Event", event))
    if vmid: details.append(_fmt_kv("VMID", vmid))
    if ctid: details.append(_fmt_kv("CTID", ctid))
    if task: details.append(_fmt_kv("Task", task))
    if duration: details.append(_fmt_kv("Duration", duration))
    if message: details.append(_fmt_kv("Message", message))

    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)
    extras = {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}
    return text, extras

# -------- QNAP (QTS) --------
def _looks_qnap(body: str, title: str) -> bool:
    tb = (title + " " + body).lower()
    if "qnap" in tb or "qts" in tb or "qulog" in tb:
        return True
    return False

def _parse_qnap(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    # QNAP typically forwards Syslog-like lines; we’ll pull device/bay/disk/severity if present
    host = ""; model = ""; disk = ""; bay = ""; pool = ""; smart = ""; temp = ""; status = ""; msg = ""
    low = (title + "\n" + body).lower()
    msg = _first_nonempty_line(body)

    # Heuristics
    m = re.search(r'(model|device)\s*[:=]\s*([A-Za-z0-9\-]+)', body, re.I)
    if m: model = m.group(2).strip()
    m = re.search(r'(host|hostname)\s*[:=]\s*([A-Za-z0-9\.\-]+)', body, re.I)
    if m: host = m.group(2).strip()
    m = re.search(r'(disk|hdd)\s*[:=]\s*([A-Za-z0-9/ _\-]+)', body, re.I)
    if m: disk = m.group(2).strip()
    m = re.search(r'(bay)\s*[:=]\s*([A-Za-z0-9]+)', body, re.I)
    if m: bay = m.group(2).strip()
    m = re.search(r'(pool|volume)\s*[:=]\s*([A-Za-z0-9_\-]+)', body, re.I)
    if m: pool = m.group(2).strip()
    m = re.search(r'(smart)\s*[:=]\s*([A-Za-z]+)', body, re.I)
    if m: smart = m.group(2).strip()
    m = re.search(r'(temp(?:erature)?)\s*[:=]\s*([0-9.]+)\s*°?C', body, re.I)
    if m: temp = m.group(2).strip()
    if "critical" in low or "error" in low or "failed" in low:
        status = "CRITICAL"
    elif "warning" in low:
        status = "WARNING"
    elif "recovered" in low or "ok" in low:
        status = "OK"

    badge = "❌" if status=="CRITICAL" else ("⚠️" if status=="WARNING" else ("✅" if status=="OK" else _severity_badge(title + " " + body)))

    lines=[]
    lines += _header("QNAP", badge)
    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)

    facts=[]; details=[]
    if host: facts.append(_fmt_kv("Host", host))
    if model: facts.append(_fmt_kv("Model", model))
    if status: facts.append(_fmt_kv("Status", status))
    if disk: details.append(_fmt_kv("Disk", disk))
    if bay: details.append(_fmt_kv("Bay", bay))
    if pool: details.append(_fmt_kv("Pool", pool))
    if smart: details.append(_fmt_kv("SMART", smart))
    if temp: details.append(_fmt_kv("Temp (C)", temp))
    if msg: details.append(_fmt_kv("Message", msg))

    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)
    extras = {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}
    return text, extras

# -------- Duplicati --------
DUPLIK_KEYS_MIN = {"parsedresult", "operationname"}

def _looks_duplicati(title: str, body: str) -> bool:
    tb = (title + " " + body).lower()
    if "%parsedresult%" in tb or "%operationname%" in tb:
        return True
    try:
        obj = json.loads(body)
        keys = set(map(str.lower, obj.keys()))
        if DUPLIK_KEYS_MIN.issubset(keys) or "result" in keys or "backupname" in keys or "taskname" in keys:
            return True
    except Exception:
        pass
    if "duplicati" in tb and ("backup report" in tb or "parsedresult" in tb or "result:" in tb):
        return True
    return False

def _parse_duplicati(title: str, body: str) -> Tuple[List[str], Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    job = "unknown"
    parsed = ""; op = ""; backend = ""; local = ""; duration = ""; files = ""; size = ""; warns = ""; errs = ""

    try:
        obj = json.loads(body)
        low = {k.lower(): k for k in obj.keys()}
        def g(k):
            kk = low.get(k.lower())
            return obj.get(kk) if kk else None
        parsed = str(g("ParsedResult") or g("parsed_result") or "").strip()
        op     = str(g("OperationName") or g("operation") or "").strip()
        job    = str(g("TaskName") or g("BackupName") or g("job") or "").strip() or job
        backend = str(g("BackendURL") or g("backend") or "").strip()
        local   = str(g("LocalPath") or g("source") or "").strip()
        duration = str(g("Duration") or g("duration") or "").strip()
        files = str(g("FilesUploaded") or g("ExaminedFiles") or g("FilesProcessed") or "").strip()
        b = g("BytesUploaded") or g("SizeOfModifiedFiles") or g("SizeUploaded") or g("SizeProcessed") or ""
        size = str(b).strip()
        warns = str(g("Warnings") or g("WarningCount") or "").strip()
        errs  = str(g("Errors") or g("ErrorCount") or "").strip()
    except Exception:
        text = _normalize(body)
        rx = {
            "parsed": re.compile(r'(?:ParsedResult|Result)\s*[:=]\s*([A-Za-z]+)', re.I),
            "op":     re.compile(r'(?:OperationName|Operation)\s*[:=]\s*([A-Za-z]+)', re.I),
            "job":    re.compile(r'(?:TaskName|BackupName|Job)\s*[:=]\s*(.+)', re.I),
            "backend":re.compile(r'(?:BackendURL|RemoteURL|Backend)\s*[:=]\s*(.+)', re.I),
            "local":  re.compile(r'(?:LocalPath|Source|Local)\s*[:=]\s*(.+)', re.I),
            "duration":re.compile(r'(?:Duration)\s*[:=]\s*([0-9:.\sA-Za-z]+)', re.I),
            "files":  re.compile(r'(?:Files(?:Uploaded|Processed|Examined)?)\s*[:=]\s*([\d,]+)', re.I),
            "size":   re.compile(r'(?:Bytes(?:Uploaded)?|Size(?:Uploaded|Processed)?)\s*[:=]\*?([\d,.]+)', re.I),
            "warns":  re.compile(r'(?:Warnings?|WarningCount)\s*[:=]\s*([\d,]+)', re.I),
            "errs":   re.compile(r'(?:Errors?|ErrorCount)\s*[:=]\s*([\d,]+)', re.I),
        }
        def mcap(n):
            m = rx[n].search(text)
            return (m.group(1).strip() if m else "")
        parsed = mcap("parsed"); op = mcap("op"); job = mcap("job") or job
        backend= mcap("backend"); local = mcap("local"); duration = mcap("duration")
        files  = mcap("files"); size = mcap("size"); warns = mcap("warns"); errs = mcap("errs")

    sev = (parsed or "").lower()
    badge = "✅" if sev == "success" else ("⚠️" if sev == "warning" else ("❌" if sev == "error" else _severity_badge(title + " " + body)))

    lines: List[str] = []
    lines += _header("Duplicati", badge)
    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)

    facts: List[str] = []
    details: List[str] = []

    if parsed:  facts.append(_fmt_kv("Result", parsed))
    if op:      facts.append(_fmt_kv("Operation", op))
    if job.strip(): facts.append(_fmt_kv("Job", job.strip()))
    if duration: facts.append(_fmt_kv("Duration", duration))

    if backend: details.append(_fmt_kv("Backend", backend))
    if local:   details.append(_fmt_kv("Source", local))
    if files:   details.append(_fmt_kv("Files", files))
    if size:    details.append(_fmt_kv("Size", size))
    if warns:   details.append(_fmt_kv("Warnings", warns))
    if errs:    details.append(_fmt_kv("Errors", errs))

    if facts:  lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)

    meta: Dict[str, Any] = {}
    meta["client::display"] = {"contentType": "text/markdown"}
    meta["jarvis::beautified"] = True
    meta["duplicati::result"] = parsed or ""
    meta["duplicati::job"] = job or ""
    return [text], meta

# -------- Ansible --------
def _looks_ansible(body: str, title: str) -> bool:
    tb = (title + " " + body).lower()
    if "ansible" in tb and ("ok=" in tb or "changed=" in tb or "failed=" in tb):
        return True
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and ("plays" in obj or "stats" in obj or "changed" in obj or "failed" in obj):
            return True
    except Exception:
        pass
    return False

def _parse_ansible(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    play = ""; task = ""; hosts = ""; ok=""; changed=""; failed=""; skipped=""; unreachable=""; duration=""
    message = ""
    try:
        obj = json.loads(body)
        if "stats" in obj and isinstance(obj["stats"], dict):
            st = obj["stats"]
            # Aggregate totals
            ok = str(sum(v.get("ok",0) for v in st.values()))
            changed = str(sum(v.get("changed",0) for v in st.values()))
            failed = str(sum(v.get("failures",0) + v.get("failed",0) for v in st.values()))
            skipped = str(sum(v.get("skipped",0) for v in st.values()))
            unreachable = str(sum(v.get("unreachable",0) for v in st.values()))
        # Optional metadata
        play = str(obj.get("play","") or obj.get("playbook","") or "").strip()
        task = str(obj.get("task","") or "").strip()
        duration = str(obj.get("duration","") or "").strip()
    except Exception:
        # Parse recap-like strings: "PLAY RECAP ... ok=10 changed=2 failed=0 skipped=1 unreachable=0"
        m = re.search(r'ok=(\d+)', body); ok = m.group(1) if m else ok
        m = re.search(r'changed=(\d+)', body); changed = m.group(1) if m else changed
        m = re.search(r'failed=(\d+)', body); failed = m.group(1) if m else failed
        m = re.search(r'skipped=(\d+)', body); skipped = m.group(1) if m else skipped
        m = re.search(r'unreachable=(\d+)', body); unreachable = m.group(1) if m else unreachable
        # pick first error line if present
        em = re.search(r'ERROR!\s*(.+)', body)
        if em: message = em.group(1).strip()

    badge = "❌" if failed and failed != "0" else ("⚠️" if unreachable and unreachable != "0" else "✅")
    lines=[]
    lines += _header("Ansible", badge)
    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)

    facts=[]; details=[]
    if play: facts.append(_fmt_kv("Play", play))
    if task: facts.append(_fmt_kv("Task", task))
    if duration: facts.append(_fmt_kv("Duration", duration))

    if ok: details.append(_fmt_kv("OK", ok))
    if changed: details.append(_fmt_kv("Changed", changed))
    if failed: details.append(_fmt_kv("Failed", failed))
    if skipped: details.append(_fmt_kv("Skipped", skipped))
    if unreachable: details.append(_fmt_kv("Unreachable", unreachable))
    if message: details.append(_fmt_kv("Message", message))

    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)
    extras = {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}
    return text, extras

# ============================
# Public API
# ============================
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     extras_in: Optional[Dict[str, Any]] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    extras_in: may carry riff_hint and other intake-provided metadata
    """
    stripped = _strip_noise(body)
    normalized = _normalize(stripped)
    normalized = html.unescape(normalized)

    # images from raw text (keep FIRST — we won't override existing posters)
    body_wo_imgs, images = _harvest_images(normalized)

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
        if riffs:
            lines += ["", f"🧠 {eff_persona} riff"]
            for r in riffs:
                sr = r.replace("\r", "").strip()
                if sr:
                    lines.append("> " + sr)

        text = "\n".join(lines).strip()
        text = _format_align_check(text)
        text = _linewise_dedup_markdown(text)

        extras: Dict[str, Any] = {
            "client::display": {"contentType": "text/markdown"},
            "jarvis::beautified": True,
            "jarvis::llm_riff_lines": len(riffs or []),
            "watchtower::host": wt_meta.get("watchtower::host"),
            "watchtower::updated_count": wt_meta.get("watchtower::updated_count"),
        }
        if wt_meta.get("watchtower::truncated"):
            extras["watchtower::truncated"] = True
        if isinstance(extras_in, dict):
            extras.update(extras_in)
        if images:
            extras["jarvis::allImageUrls"] = images
        return text, extras

    # ===== Duplicati special-case =====
    if _looks_duplicati(title, body_wo_imgs):
        md_lines, dupe_meta = _parse_duplicati(title, body_wo_imgs)
        ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
        eff_persona = _effective_persona(persona)
        riff_hint = _global_riff_hint(extras_in, source_hint)
        riffs: List[str] = []
        if eff_persona and riff_hint:
            riffs = _persona_llm_riffs(ctx, eff_persona)
        if riffs:
            md_lines += ["", f"🧠 {eff_persona} riff"]
            for r in riffs:
                sr = r.replace("\r", "").strip()
                if sr:
                    md_lines.append("> " + sr)

        text = "\n".join(md_lines).strip()
        extras: Dict[str, Any] = {"jarvis::llm_riff_lines": len(riffs or [])}
        extras.update(dupe_meta)
        if isinstance(extras_in, dict):
            extras.update(extras_in)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== ARR special-case =====
    if _looks_arr(body_wo_imgs):
        arr_text, arr_extras, arr_imgs = _parse_arr(title, body_wo_imgs)
        # Respect existing posters first; only add ARR poster if none harvested
        if images:
            arr_extras["jarvis::allImageUrls"] = images + arr_extras.get("jarvis::allImageUrls", [])
            arr_extras.setdefault("client::notification", {"bigImageUrl": images[0]})
        return arr_text, arr_extras

    # ===== Kuma special-case =====
    if _looks_kuma(body_wo_imgs, title):
        text, extras = _parse_kuma(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== Proxmox special-case =====
    if _looks_proxmox(body_wo_imgs, title):
        text, extras = _parse_proxmox(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== QNAP special-case =====
    if _looks_qnap(body_wo_imgs, title):
        text, extras = _parse_qnap(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== Ansible special-case =====
    if _looks_ansible(body_wo_imgs, title):
        text, extras = _parse_ansible(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== Generic path (existing behavior) =====
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

    if images:
        lines += ["", f"![poster]({images[0]})"]

    ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
    riffs: List[str] = []
    riff_hint = _global_riff_hint(extras_in, source_hint)
    _debug(f"persona={eff_persona}, riff_hint={riff_hint}, src={source_hint}, images={len(images)}")
    if eff_persona and riff_hint:
        riffs = _persona_llm_riffs(ctx, eff_persona)

    if riffs:
        lines += ["", f"🧠 {eff_persona} riff"]
        for r in riffs:
            sr = r.replace("\r", "").strip()
            if sr:
                lines.append("> " + sr)

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)

    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images,
        "jarvis::llm_riff_lines": len(riffs or []),
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}

    if isinstance(extras_in, dict):
        extras.update(extras_in)

    return text, extras