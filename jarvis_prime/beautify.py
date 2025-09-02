# /app/beautify.py
from __future__ import annotations

import re
import json
import importlib
import random
from typing import List, Tuple, Optional, Dict, Any, Set
from dataclasses import dataclass

# ====== Regex library ======
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)
KV_RE      = re.compile(r'^\s*[-*]?\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+?)\s*$')
PUNCT_SPLIT = re.compile(r'([.!?])')

# timestamps and types
TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
DATE_ONLY_RE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b')
TIME_ONLY_RE = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?(?:AM|PM|am|pm))?\b')

# Strict IPv4: each octet 0-255
IP_RE  = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b')
HOST_RE = re.compile(r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b')
VER_RE  = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')
URL_RE  = re.compile(r'\bhttps?://[^\s)]+', re.I)

# Broad but practical emoji match (keeps ZWJ clusters intact enough for stripping)
# NOTE: We avoid third-party deps and accept that some sequences may survive.
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

# ====== Data structures ======
@dataclass
class VerifyReport:
    kept: Set[str]
    missing: Set[str]
    coverage: float


# ====== Helpers ======
def _prefer_host_key(url: str) -> int:
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").lower()
        return 0 if any(k in host for k in LIKELY_POSTER_HOSTS) else 1
    except Exception:
        return 1


def _strip_noise(text: str) -> str:
    if not text: 
        return ""
    s = EMOJI_RE.sub("", text)
    NOISE = re.compile(r'^\s*(?:sent from .+|via .+ api|automated message|do not reply)\.?\s*$', re.I)
    kept = [ln for ln in s.splitlines() if not NOISE.match(ln)]
    return "\n".join(kept)


def _normalize(text: str) -> str:
    s = (text or "").replace("\t","  ")
    s = re.sub(r'[ \t]+$', "", s, flags=re.M)  # rstrip per line
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _linewise_dedup_markdown(text: str) -> str:
    """
    Deduplicate by normalized lines and list items, preserving Markdown structure.
    - Do not split by punctuation (protects IPs, versions).
    - Skip inside fenced code blocks.
    """
    lines = text.splitlines()
    out: List[str] = []
    seen: Set[str] = set()
    in_code = False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            out.append(ln)
            continue
        if in_code:
            out.append(ln)
            continue
        norm = re.sub(r'\s+', ' ', ln.strip()).lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(ln)
        elif ln.strip() == "":  # keep single blank lines
            if out and out[-1].strip() != "":
                out.append(ln)
    return "\n".join(out).strip()


def _harvest_images(text: str) -> tuple[str, List[str]]:
    if not text: 
        return "", []
    urls: List[str] = []
    def _md(m):  urls.append(m.group(1)); return ""
    def _bare(m): urls.append(m.group(1)); return ""
    text = MD_IMG_RE.sub(_md, text)
    text = IMG_URL_RE.sub(_bare, text)
    uniq=[]; seen=set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen: seen.add(u); uniq.append(u)
    return text.strip(), uniq


def _find_ips(*texts: str) -> List[str]:
    ips=[]; seen=set()
    for t in texts:
        if not t: 
            continue
        for m in IP_RE.finditer(t):
            ip = m.group(0)
            if ip not in seen: seen.add(ip); ips.append(ip)
    return ips


def _repair_ipv4(val: str, *contexts: str) -> str:
    cand = re.sub(r'\s*\.\s*', '.', (val or '').strip())
    m = IP_RE.search(cand)
    if m: 
        return m.group(0)
    parts = re.findall(r'\d{1,3}', cand)
    if len(parts) == 4:
        j = '.'.join(parts)
        if IP_RE.fullmatch(j): 
            return j
    for ctx in contexts:
        m = IP_RE.search(ctx or "")
        if m: 
            return m.group(0)
    return val.strip()


def _first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        t = ln.strip()
        if t: 
            return t
    return ""


def _fmt_kv(label: str, value: str) -> str:
    v = value.strip()
    if re.search(r'\d', v):  # emphasize numeric values
        v = f"`{v}`"
    return f"- **{label.strip()}:** {v}"


# ====== Persona overlay ======
def _persona_overlay_line(persona: Optional[str], *, enable_quip: bool) -> Optional[str]:
    if not persona: 
        return None
    try:
        mod = importlib.import_module("personality")
        # Avoid reload storm; attempt to use cached module if available.
        quip = ""
        if enable_quip and hasattr(mod, "quip"):
            try:
                quip = str(mod.quip(persona) or "").strip()
            except Exception:
                quip = ""
        return f"💬 {persona} says: {'— ' + quip if quip else ''}".rstrip()
    except Exception:
        return f"💬 {persona} says:"


# ====== Minimal header (no dash bars) ======
def _header(kind: str, badge: str = "") -> List[str]:
    return [f"📟 Jarvis Prime — {kind} {badge}".rstrip()]


def _severity_badge(text: str, kv_status: Optional[str] = None) -> str:
    # Prefer structured status
    if kv_status:
        low = kv_status.lower()
        if low in ("ok","success","online","completed","up"):
            return "✅"
        if low in ("warn","warning","degraded"):
            return "⚠️"
        if low in ("error","failed","down","critical"):
            return "❌"
    # Fallback heuristic
    low = text.lower()
    if re.search(r'\b(error|failed|critical)\b', low): return "❌"
    if re.search(r'\b(warn|warning)\b', low): return "⚠️"
    if re.search(r'\b(success|ok|online|completed|up)\b', low): return "✅"
    return ""


def _looks_pure_json(body: str) -> bool:
    if not body: 
        return False
    s = body.strip()
    if not ((s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))):
        return False
    try:
        json.loads(s)
        return True
    except Exception:
        return False


def _detect_type(title: str, body: str) -> str:
    tb = (title + " " + body).lower()
    # simple registry-ish
    if "speedtest" in tb: return "SpeedTest"
    if "apt" in tb or "dpkg" in tb: return "APT Update"
    if "watchtower" in tb: return "Watchtower"
    if "sonarr" in tb: return "Sonarr"
    if "radarr" in tb: return "Radarr"
    if _looks_pure_json(body): return "JSON"
    if "proxmox" in tb: return "Proxmox"
    if "uptime kuma" in tb or "kuma" in tb: return "Uptime"
    if "error" in tb or "warning" in tb or "failed" in tb: return "Log Event"
    return "Message"


def _harvest_timestamp(title: str, body: str) -> Optional[str]:
    for src in (title or "", body or ""):
        # TS_RE has the actual timestamp in group(1)
        m = TS_RE.search(src)
        if m:
            return m.group(1).strip()
        for rx in (DATE_ONLY_RE, TIME_ONLY_RE):
            m2 = rx.search(src)
            if m2:
                return m2.group(0).strip()
    return None


def _extract_keyvals(text: str) -> List[Tuple[str,str]]:
    out: List[Tuple[str,str]] = []
    for ln in (text or "").splitlines():
        m = KV_RE.match(ln)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def _categorize_bullets(title: str, body: str) -> Tuple[List[str], List[str], Optional[str]]:
    facts: List[str] = []
    details: List[str] = []

    ts = _harvest_timestamp(title, body)
    if ts: facts.append(_fmt_kv("Time", ts))
    subj = title.strip()
    if subj: facts.append(_fmt_kv("Subject", subj))

    kv_status: Optional[str] = None

    for k,v in _extract_keyvals(body):
        key = k.strip().lower()
        val = v
        if key in ("ip","ip address","address"):
            val = _repair_ipv4(v, title, body)
            details.append(_fmt_kv("IP", val))
        elif key in ("ping","download","upload","latency","jitter","loss","speed"):
            facts.append(_fmt_kv(k, v))
        elif key in ("status","result","state","ok","success","warning","error"):
            kv_status = kv_status or v
            facts.append(_fmt_kv(k, v))
        else:
            details.append(_fmt_kv(k, v))

    # also infer IPs/hosts/versions
    ip_list = _find_ips(title, body)
    for ip in ip_list:
        if f"`{ip}`" not in " ".join(details):  # avoid dup
            details.append(_fmt_kv("IP", ip))

    # Hosts are noisy; keep only those that aren't just part of URLs we already captured.
    used_hosts: Set[str] = set()
    for host in HOST_RE.findall(body or ""):
        if not IP_RE.match(host):
            used_hosts.add(host.lower())
    for host in sorted(used_hosts):
        details.append(_fmt_kv("host", host))

    for m in VER_RE.finditer(body or ""):
        ver = m.group(0)
        if any(ver in ip for ip in ip_list):  # skip if part of IP
            continue
        tail = (body or "")[m.end(): m.end()+2]
        if tail.startswith('.') and len(tail) > 1 and tail[1].isdigit():
            continue
        details.append(_fmt_kv("version", ver))

    if not facts:
        first = _first_nonempty_line(body)
        if first: facts.append(_fmt_kv("Info", first))

    # De-dup by line content
    def _uniq(lines: List[str]) -> List[str]:
        seen=set(); out=[]
        for ln in lines:
            key = re.sub(r'\s+',' ', ln.strip()).lower()
            if key and key not in seen: seen.add(key); out.append(ln)
        return out

    return _uniq(facts), _uniq(details), kv_status


def _format_align_check(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    # ensure zero leading blanks
    while lines and lines[0].strip() == "": 
        lines.pop(0)
    # ensure at most one blank between sections
    out=[]; 
    for ln in lines:
        if ln.strip() == "":
            if out and out[-1].strip() == "":
                continue
        out.append(ln)
    return "\n".join(out).strip()


# ====== Stage-6/7 verifier & failsafe ======
def _artifact_tokens(text: str) -> Set[str]:
    """Artifacts we insist must survive: numbers, IPs, URLs, timestamps, versions (short)."""
    toks: Set[str] = set()
    toks.update(IP_RE.findall(text or ""))
    toks.update(URL_RE.findall(text or ""))
    toks.update(re.findall(r'\b\d{1,4}(?:[./:-]\d{1,4}){1,3}\b', text or ""))  # times/dates-ish
    toks.update([m.group(0) for m in VER_RE.finditer(text or "")])
    # also keep quoted phrases
    toks.update([m.group(1) for m in re.finditer(r'"([^"]+)"', text or "")])
    return {t.strip() for t in toks if t and len(t.strip()) >= 2}


def _verify_preservation(original: str, beautified: str) -> VerifyReport:
    orig = _artifact_tokens(original)
    beau = _artifact_tokens(beautified)
    if not orig:
        return VerifyReport(set(), set(), 1.0)
    kept = orig.intersection(beau)
    missing = orig.difference(beau)
    coverage = len(kept) / max(1, len(orig))
    return VerifyReport(kept, missing, coverage)


# ====== Public API ======
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: str | None = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True) -> Tuple[str, Optional[dict]]:

    original_body = body or ""
    stripped = _strip_noise(original_body)
    normalized = _normalize(stripped)

    # images: strip from text, preserve list
    body_wo_imgs, images = _harvest_images(normalized)

    kind = _detect_type(title, body_wo_imgs)
    # kv_status comes from categorize pass for better badge
    facts, details, kv_status = _categorize_bullets(title, body_wo_imgs)
    badge = _severity_badge(title + " " + body_wo_imgs, kv_status)

    # ---- Compose card (attempt A) ----
    lines: List[str] = []
    lines += _header(kind, badge)

    # persona overlay line inside the card (respect persona_quip flag)
    pol = _persona_overlay_line(persona, enable_quip=persona_quip)
    if pol: 
        lines += [pol]

    if facts:
        lines += ["", "📄 Facts", *facts]
    if details:
        lines += ["", "📄 Details", *details]

    # render first image inline so clients that ignore extras still show posters
    if images:
        lines += ["", f"![poster]({images[0]})"]
        if len(images) > 1:
            # compact gallery links
            more = ", ".join(f"[img{i+1}]({u})" for i,u in enumerate(images[1:]))
            lines += [f"_Gallery_: {more}"]

    text = "\n".join(lines).strip()
    text = _format_align_check(text)
    text = _linewise_dedup_markdown(text)  # line-aware dedup (safe for MD)

    # ---- Stage 6: verify that important artifacts survived ----
    report = _verify_preservation(title + "\n" + original_body, text)
    # threshold tuned conservatively
    MIN_COVERAGE = 0.7

    # ---- Stage 6 retry (gentler) ----
    if report.coverage < MIN_COVERAGE or report.missing:
        # Retry with gentler approach: no dedup, include a "Raw Extract" section
        retry_lines = []
        retry_lines += _header(kind, badge)
        if pol:
            retry_lines += [pol]
        if facts:
            retry_lines += ["", "📄 Facts", *facts]
        if details:
            retry_lines += ["", "📄 Details", *details]
        retry_lines += ["", "📄 Raw Extract", "```text", original_body.strip(), "```"]
        retry_text = "\n".join(retry_lines).strip()
        retry_text = _format_align_check(retry_text)

        retry_report = _verify_preservation(title + "\n" + original_body, retry_text)

        if retry_report.coverage >= report.coverage:
            text = retry_text
            report = retry_report

    # ---- Stage 7 fail-safe ----
    status = "verified"
    if report.coverage < 0.5:
        # Push raw message minimally decorated
        status = "fallback_raw"
        raw_lines = []
        raw_lines += _header("Raw Message", badge)
        raw_lines += ["", f"**Subject:** {title.strip() or '(no title)'}", "", "```text", original_body.strip(), "```"]
        if images:
            raw_lines += ["", f"![poster]({images[0]})"]
        text = "\n".join(raw_lines).strip()

    extras: Dict[str, Any] = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::beautify_status": status,
        "jarvis::coverage_ratio": round(report.coverage, 3),
        "jarvis::missing_artifacts": sorted(list(report.missing)),
        "jarvis::allImageUrls": images
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}

    return text, extras