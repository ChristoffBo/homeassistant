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
# EXISTING Parsers — ARR, Kuma, Proxmox, QNAP, Duplicati, Ansible
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
        if not poster and isinstance(movie.get("images"), list):
            for it in movie["images"]:
                if isinstance(it, dict) and str(it.get("coverType","")).lower()=="poster" and it.get("url"):
                    poster = it["url"]; break
    if isinstance(series, dict):
        if not poster and isinstance(series.get("images"), list):
            for it in series["images"]:
                if isinstance(it, dict) and str(it.get("coverType","")).lower() in ("poster","banner","fanart") and it.get("url"):
                    poster = it["url"]; break

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

    lines: List[str] = []
    kind = "Radarr/Sonarr/Lidarr/Prowlarr"
    lines += _header(kind, badge)

    # persona overlay (optional)
    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)

    if isinstance(movie, dict):
        name = str(movie.get("title","") or "").strip()
        year = str(movie.get("year","") or "").strip()
        if name: facts.append(_fmt_kv("Movie", f"{name} ({year})" if year else name))
    if isinstance(series, dict):
        sname = str(series.get("title","") or "").strip()
        if sname: facts.append(_fmt_kv("Series", sname))
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

    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    images: List[str] = []
    if poster:
        images.append(poster)

    text = "\n".join(lines).strip()
    text = _linewise_dedup_markdown(_format_align_check(text))

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
        low = (title + " " + msg).lower()
        if "down" in low: status = "DOWN"
        elif "up" in low: status = "UP"
        latency = str(obj.get("ping") or obj.get("latency") or "").strip()
        cert_days = str(obj.get("certDaysRemaining") or obj.get("tls_days_left") or "").strip()
        reason = msg
    except Exception:
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

    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
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

    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    extras = {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}
    return text, extras

# -------- QNAP (QTS) --------
def _looks_qnap(body: str, title: str) -> bool:
    tb = (title + " " + body).lower()
    if "qnap" in tb or "qts" in tb or "qulog" in tb:
        return True
    return False

def _parse_qnap(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    host = ""; model = ""; disk = ""; bay = ""; pool = ""; smart = ""; temp = ""; status = ""; msg = ""
    low = (title + "\n" + body).lower()
    msg = _first_nonempty_line(body)

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

    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
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

    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))

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
            ok = str(sum(v.get("ok",0) for v in st.values()))
            changed = str(sum(v.get("changed",0) for v in st.values()))
            failed = str(sum(v.get("failures",0) + v.get("failed",0) for v in st.values()))
            skipped = str(sum(v.get("skipped",0) for v in st.values()))
            unreachable = str(sum(v.get("unreachable",0) for v in st.values()))
        play = str(obj.get("play","") or obj.get("playbook","") or "").strip()
        task = str(obj.get("task","") or "").strip()
        duration = str(obj.get("duration","") or "").strip()
    except Exception:
        m = re.search(r'ok=(\d+)', body); ok = m.group(1) if m else ok
        m = re.search(r'changed=(\d+)', body); changed = m.group(1) if m else changed
        m = re.search(r'failed=(\d+)', body); failed = m.group(1) if m else failed
        m = re.search(r'skipped=(\d+)', body); skipped = m.group(1) if m else skipped
        m = re.search(r'unreachable=(\d+)', body); unreachable = m.group(1) if m else unreachable
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

    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    extras = {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}
    return text, extras
# ============================
# NEW Parsers — Unraid, Plex, Emby, Watchtower (enhanced), qBittorrent, Deluge, SABnzbd, OPNsense
# ============================

# --- Unraid ---
UNRAID_SUBJ_RE = re.compile(r'^(Notice|Warning|Alert)\s*(?P<host>[^]+)\]\s*-\s*(?P<what>.+)$', re.I)
def _looks_unraid(title: str) -> bool:
    return bool(UNRAID_SUBJ_RE.match(title or ""))

def _parse_unraid(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    m = UNRAID_SUBJ_RE.match(title or "")
    sev, host, what = m.group(1), m.group(2), m.group(3)
    badge = "❌" if sev in ("Alert","Warning") and "error" in what.lower() else ("⚠️" if sev in ("Alert","Warning") else "✅")
    lines = _header("Unraid", badge)
    eff_persona = _effective_persona(None)
    pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts = []
    details = []
    facts.append(_fmt_kv("Server", host))
    facts.append(_fmt_kv("Event", what))
    # simple heuristics
    r = re.search(r'Array has\s+(\d+)\s+disk', body, re.I)
    if r:
        details.append(_fmt_kv("Array read errors", r.group(1)))
    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]
    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display": {"contentType": "text/markdown"}, "jarvis::beautified": True}

# --- Plex ---
def _looks_plex(body: str) -> bool:
    try:
        j=json.loads(body); return isinstance(j, dict) and "event" in j and "Metadata" in j
    except: return False

def _parse_plex(body: str) -> Tuple[str, Dict[str, Any]]:
    j=json.loads(body)
    event=(j.get("event") or "").replace("_"," ").title()
    meta=j.get("Metadata") or {}
    server=(j.get("Server") or {}).get("title")
    player=(j.get("Player") or {}).get("title") or (j.get("Player") or {}).get("platform")
    title=meta.get("title") or meta.get("grandparentTitle") or meta.get("originalTitle") or "Plex Event"
    lines=_header("Plex","")
    eff_persona = _effective_persona(None); pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts=[]; details=[]
    if event: facts.append(_fmt_kv("Event", event))
    if server: details.append(_fmt_kv("Server", server))
    if player: details.append(_fmt_kv("Player", str(player)))
    if meta.get("type"): details.append(_fmt_kv("Type", meta.get("type")))
    if meta.get("year"): details.append(_fmt_kv("Year", str(meta.get("year"))))
    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]
    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display":{"contentType":"text/markdown"}, "jarvis::beautified": True}

# --- Emby ---
def _looks_emby(body: str) -> bool:
    try:
        j=json.loads(body); return isinstance(j, dict) and ("Event" in j or "event" in j) and ("Item" in j or "item" in j)
    except: return False

def _parse_emby(body: str) -> Tuple[str, Dict[str, Any]]:
    j=json.loads(body)
    ev=(j.get("Event") or j.get("event") or "")
    item=j.get("Item") or j.get("item") or {}
    lines=_header("Emby","")
    eff_persona = _effective_persona(None); pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts=[]; details=[]
    if ev: facts.append(_fmt_kv("Event", ev))
    if item.get("Name"): facts.append(_fmt_kv("Title", item.get("Name")))
    if item.get("Type"): details.append(_fmt_kv("Type", item.get("Type")))
    if item.get("ProductionYear"): details.append(_fmt_kv("Year", str(item.get("ProductionYear"))))
    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]
    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display":{"contentType":"text/markdown"}, "jarvis::beautified": True}

# --- Watchtower (enhanced text catch) ---
def _looks_watchtower_enh(body: str, title: str) -> bool:
    tb=(title+" "+body).lower()
    return "watchtower" in tb or "found new " in tb or "updating container" in tb or "restarting container" in tb

def _parse_watchtower_enh(body: str) -> Tuple[str, Dict[str, Any]]:
    lines=_header("Watchtower","")
    eff_persona = _effective_persona(None); pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts=[]; details=[]
    # crude extraction of lines mentioning actions
    updates=[]
    for ln in (body or "").splitlines():
        l=ln.strip()
        if re.search(r'\b(Found new|Stopping|Updating|Restarting)\b', l, re.I):
            updates.append(l)
    if updates:
        details += [f"- {html.escape(u)}" for u in updates]
    if facts: lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]
    text=_linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display":{"contentType":"text/markdown"}, "jarvis::beautified": True}

# --- qBittorrent ---
def _looks_qbittorrent(body: str) -> bool:
    try:
        j=json.loads(body)
        if isinstance(j, dict) and "name" in j and "state" in j:
            return True
        if isinstance(j, dict) and "torrent" in j and isinstance(j["torrent"], dict):
            return True
    except: return False
    return False

def _parse_qbittorrent(body: str) -> Tuple[str, Dict[str, Any]]:
    j=json.loads(body)
    tor = j["torrent"] if isinstance(j, dict) and "torrent" in j and isinstance(j["torrent"], dict) else j
    name = tor.get("name") or "Torrent"
    state = str(tor.get("state","")).title()
    progress = tor.get("progress")
    lines=_header("qBittorrent","")
    eff_persona = _effective_persona(None); pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts=[_fmt_kv("Torrent", name)]
    if state: facts.append(_fmt_kv("State", state))
    details=[]
    if isinstance(progress, (int,float)):
        details.append(_fmt_kv("Progress", f"{round(float(progress)*100,1)}%"))
    if tor.get("dlspeed"): details.append(_fmt_kv("DL", str(tor.get("dlspeed"))))
    if tor.get("upspeed"): details.append(_fmt_kv("UL", str(tor.get("upspeed"))))
    if tor.get("eta"): details.append(_fmt_kv("ETA", str(tor.get("eta"))))
    if tor.get("category"): details.append(_fmt_kv("Category", str(tor.get("category"))))
    if tor.get("ratio"): details.append(_fmt_kv("Ratio", str(tor.get("ratio"))))
    if facts: lines+=["", "📄 Facts", *facts]
    if details: lines+=["", "📄 Details", *details]
    text=_linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display":{"contentType":"text/markdown"}, "jarvis::beautified": True}

# --- Deluge ---
def _looks_deluge(body: str) -> bool:
    try:
        j=json.loads(body)
        if isinstance(j, dict) and (("name" in j and ("hash" in j or "info_hash" in j)) or ("torrent" in j and isinstance(j["torrent"], dict))):
            return True
    except: return False
    return False

def _parse_deluge(body: str) -> Tuple[str, Dict[str, Any]]:
    j=json.loads(body)
    tor = j["torrent"] if "torrent" in j and isinstance(j["torrent"], dict) else j
    name = tor.get("name") or "Torrent"
    state = tor.get("state")
    lines=_header("Deluge","")
    eff_persona = _effective_persona(None); pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts=[_fmt_kv("Torrent", name)]
    if state: facts.append(_fmt_kv("State", str(state).title()))
    details=[]
    for k in ("progress","eta","ratio","download_payload_rate","upload_payload_rate"):
        if tor.get(k) is not None:
            details.append(_fmt_kv(k.replace("_"," ").title(), str(tor.get(k))))
    if facts: lines+=["", "📄 Facts", *facts]
    if details: lines+=["", "📄 Details", *details]
    text=_linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display":{"contentType":"text/markdown"}, "jarvis::beautified": True}

# --- SABnzbd ---
SAB_SUBJ_RE = re.compile(r'^(?P<status>Complete|Failed|Warning)\s*:\s*(?P<job>.+)$', re.I)
def _looks_sabnzbd(title: str, body: str) -> bool:
    return bool(SAB_SUBJ_RE.match(title or "")) or "sabnzbd" in (title + " " + body).lower()

def _parse_sabnzbd(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    m = SAB_SUBJ_RE.match(title or "")
    status = (m.group("status") if m else "SABnzbd").title()
    job = (m.group("job") if m else "Job")
    badge = "❌" if status=="Failed" else ("⚠️" if status=="Warning" else "✅")
    lines=_header("SABnzbd", badge)
    eff_persona = _effective_persona(None); pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts=[_fmt_kv("Job", job), _fmt_kv("Status", status)]
    details=[]
    m_size = re.search(r'(Size|Bytes):\s*([\d\.,]+\s*(?:MB|GB|KB|B))', body, re.I)
    if m_size: details.append(_fmt_kv("Size", m_size.group(2)))
    if facts: lines+=["", "📄 Facts", *facts]
    if details: lines+=["", "📄 Details", *details]
    text=_linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display":{"contentType":"text/markdown"}, "jarvis::beautified": True}

# --- OPNsense ---
OPN_SUBJ_RE = re.compile(r'(there were errors loading the rules|interface .+ down|gateway .+ down|carp state .*|power failure)', re.I)
def _looks_opnsense(title: str, body: str) -> bool:
    return bool(OPN_SUBJ_RE.search((title or "") + "\n" + (body or "")))

def _parse_opnsense(title: str, body: str) -> Tuple[str, Dict[str, Any]]:
    blob = (title or "") + "\n" + (body or "")
    badge = "❌" if re.search(r'(down|error|failed)', blob, re.I) else "⚠️"
    lines=_header("OPNsense", badge)
    eff_persona = _effective_persona(None); pol = _persona_overlay_line(eff_persona)
    if pol: lines.append(pol)
    facts=[]; details=[]
    # iface/gw sniffs
    m_if = re.search(r'(wan|lan|ixl\d+|em\d+|vmx\d+)', blob, re.I)
    m_gw = re.search(r'gateway\s+([^\s]+)', blob, re.I)
    if m_if: facts.append(_fmt_kv("Interface", m_if.group(1)))
    if m_gw: facts.append(_fmt_kv("Gateway", m_gw.group(1)))
    details.append(_fmt_kv("Message", _first_nonempty_line(body)))
    if facts: lines+=["", "📄 Facts", *facts]
    if details: lines+=["", "📄 Details", *details]
    text=_linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    return text, {"client::display":{"contentType":"text/markdown"}, "jarvis::beautified": True}
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

    kind_badge_seed = title + " " + body_wo_imgs

    # ===== Watchtower (existing summarizer) =====
    if "watchtower" in (title + " " + body_wo_imgs).lower():
        lines: List[str] = []
        lines += _header("Watchtower", _severity_badge(kind_badge_seed))

        eff_persona = _effective_persona(persona)
        if persona_quip:
            pol = _persona_overlay_line(eff_persona)
            if pol: lines += [pol]

        wt_md, wt_meta = _summarize_watchtower(title, body_wo_imgs)
        lines += ["", wt_md]

        ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
        riffs: List[str] = []
        # riff gate
        if eff_persona and (isinstance(extras_in, dict) and extras_in.get("riff_hint", True)):
            try:
                mod = importlib.import_module("personality")
                mod = importlib.reload(mod)
                if hasattr(mod, "llm_quips"):
                    riffs = mod.llm_quips(eff_persona, context=ctx, max_lines=int(os.getenv("LLM_PERSONA_LINES_MAX","3")))
            except Exception:
                riffs = []
        if riffs:
            lines += ["", f"🧠 {eff_persona} riff"]
            for r in riffs:
                sr = str(r).replace("\r","").strip()
                if sr:
                    lines.append("> " + sr)

        text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
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

    # ===== Duplicati =====
    if _looks_duplicati(title, body_wo_imgs):
        md_lines, dupe_meta = _parse_duplicati(title, body_wo_imgs)
        ctx = (title or "").strip() + "\n" + (body_wo_imgs or "").strip()
        eff_persona = _effective_persona(persona)
        riffs: List[str] = []
        if eff_persona and (isinstance(extras_in, dict) and extras_in.get("riff_hint", True)):
            try:
                mod = importlib.import_module("personality")
                mod = importlib.reload(mod)
                if hasattr(mod, "llm_quips"):
                    riffs = mod.llm_quips(eff_persona, context=ctx, max_lines=int(os.getenv("LLM_PERSONA_LINES_MAX","3")))
            except Exception:
                pass
        if riffs:
            md_lines += ["", f"🧠 {eff_persona} riff"]
            for r in riffs:
                sr = str(r).replace("\r", "").strip()
                if sr:
                    md_lines.append("> " + sr)

        text = _linewise_dedup_markdown(_format_align_check("\n".join(md_lines).strip()))
        extras: Dict[str, Any] = {"jarvis::llm_riff_lines": len(riffs or [])}
        extras.update(dupe_meta)
        if isinstance(extras_in, dict):
            extras.update(extras_in)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== ARR =====
    if _looks_arr(body_wo_imgs):
        arr_text, arr_extras, arr_imgs = _parse_arr(title, body_wo_imgs)
        # Respect existing posters first; only add ARR poster if none harvested
        if images:
            arr_extras["jarvis::allImageUrls"] = images + arr_extras.get("jarvis::allImageUrls", [])
            arr_extras.setdefault("client::notification", {"bigImageUrl": images[0]})
        return arr_text, arr_extras

    # ===== Kuma =====
    if _looks_kuma(body_wo_imgs, title):
        text, extras = _parse_kuma(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== Proxmox =====
    if _looks_proxmox(body_wo_imgs, title):
        text, extras = _parse_proxmox(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== QNAP =====
    if _looks_qnap(body_wo_imgs, title):
        text, extras = _parse_qnap(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== Ansible =====
    if _looks_ansible(body_wo_imgs, title):
        text, extras = _parse_ansible(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    # ===== NEW Parsers chain =====
    if _looks_unraid(title):
        text, extras = _parse_unraid(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    if _looks_plex(body_wo_imgs):
        text, extras = _parse_plex(body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    if _looks_emby(body_wo_imgs):
        text, extras = _parse_emby(body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
            extras["client::notification"] = {"bigImageUrl": images[0]}
        return text, extras

    if _looks_watchtower_enh(body_wo_imgs, title):
        text, extras = _parse_watchtower_enh(body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
        return text, extras

    if _looks_qbittorrent(body_wo_imgs):
        text, extras = _parse_qbittorrent(body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
        return text, extras

    if _looks_deluge(body_wo_imgs):
        text, extras = _parse_deluge(body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
        return text, extras

    if _looks_sabnzbd(title, body_wo_imgs):
        text, extras = _parse_sabnzbd(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
        return text, extras

    if _looks_opnsense(title, body_wo_imgs):
        text, extras = _parse_opnsense(title, body_wo_imgs)
        if images:
            extras["jarvis::allImageUrls"] = images
        return text, extras

    # ===== Generic path (existing behavior) =====
    # fallback categorizer
    kind = "Message"
    badge = _severity_badge(kind_badge_seed)

    lines: List[str] = []
    lines += _header(kind, badge)

    eff_persona = _effective_persona(persona)
    if persona_quip:
        pol = _persona_overlay_line(eff_persona)
        if pol: lines += [pol]

    # lightweight categorization
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

    facts, details = _categorize_bullets(title, body_wo_imgs)
    if facts:   lines += ["", "📄 Facts", *facts]
    if details: lines += ["", "📄 Details", *details]

    if images:
        lines += ["", f"![poster]({images[0]})"]

    text = _linewise_dedup_markdown(_format_align_check("\n".join(lines).strip()))
    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images,
        "jarvis::llm_riff_lines": 0,
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}
    if isinstance(extras_in, dict):
        extras.update(extras_in)

    return text, extras