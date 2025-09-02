
# /app/beautify.py
# Jarvis Prime — Universal Beautifier (clean, bullets, images kept)
from __future__ import annotations
import re, json
from typing import List, Tuple, Optional

# -------- Regex --------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)

OCT = r'(?:25[0-5]|2[0-4]\d|1?\d{1,2})'
IPV4 = re.compile(rf'\b{OCT}\.{OCT}\.{OCT}\.{OCT}\b')

# -------- Helpers --------
def _first_nonempty_line(s: str) -> str:
    for ln in (s or '').splitlines():
        ln = ln.strip()
        if ln: return ln
    return ''

def _harvest_images(text: str) -> tuple[str, List[str]]:
    if not text: return '', []
    urls: List[str] = []
    def _md(m):
        urls.append(m.group(1)); return ''
    text = MD_IMG_RE.sub(_md, text)
    def _bare(m):
        urls.append(m.group(1)); return ''
    text = IMG_URL_RE.sub(_bare, text)
    # tidy whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    # unique preserve order
    seen=set(); uniq=[]
    for u in urls:
        if u not in seen:
            seen.add(u); uniq.append(u)
    return text, uniq

def _dedup_lines(lines: List[str]) -> List[str]:
    seen=set(); out=[]
    for ln in lines:
        key = re.sub(r'\s+', ' ', (ln or '').strip()).lower()
        if key and key not in seen:
            seen.add(key); out.append(ln)
        elif not key and (not out or out[-1] != ''):
            out.append('')
    while out and out[0]=='': out.pop(0)
    while out and out[-1]=='': out.pop()
    return out

def _b(label: str, value: str) -> str:
    return f"- **{label}:** {value}"

def _kv_from_line(s: str) -> Optional[tuple[str,str]]:
    m = re.match(r'\s*[-•\u2022]*\s*([A-Za-z0-9_ ./()]+?)\s*[:：]\s*(.+)\s*$', s)
    if m: return m.group(1).strip(), m.group(2).strip()
    return None

def _repair_ipv4(value: str, hay1: str, hay2: str) -> str:
    v = (value or '').strip()
    if IPV4.fullmatch(v): return v
    v2 = re.sub(r'\s*\.\s*', '.', v)
    if IPV4.fullmatch(v2): return v2
    found = IPV4.findall(' '.join([hay1 or '', hay2 or '']))
    return found[0] if found else v

# -------- Public --------
def beautify_message(title: str, body: str, *, mood: str="serious", source_hint: str | None=None) -> Tuple[str, Optional[dict]]:
    # Stage 1+2: strip & images
    clean, images = _harvest_images(body or '')
    subj = (title or '').strip()

    # Stage 3: build sections
    lines: List[str] = []
    # Header (plain; persona overlay comes from bot.py)
    lines += [
        "———————————————",
        "📟 Jarvis Prime — Message",
        "———————————————",
        ""
    ]

    facts: List[str] = []
    if subj: facts.append(_b("Subject", subj))

    # time (simple best-effort)
    t1 = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', body or '')
    if not t1: t1 = re.search(r'\b(\d{2}[\-/]\d{2}[\-/]\d{2,4})\b', body or '')
    if t1: facts.append(_b("Time", t1.group(1)))

    # details from body
    details: List[str] = []
    for raw in (clean or '').splitlines():
        s = raw.strip()
        if not s: continue
        kv = _kv_from_line(s)
        if kv:
            k,v = kv
            if k.lower() in ("ip","ip address","address","addr","host ip"):
                v = _repair_ipv4(v, title or "", body or "")
                k = "IP"
            details.append(_b(k, v))
        else:
            # keep free text as Info
            details.append(_b("Info", s))

    # If we didn't see an IP kv, but a valid IP exists anywhere, add it once
    if not any(x.startswith("- **IP:**") for x in details):
        found = IPV4.findall(' '.join([title or '', body or '']))
        if found:
            details.append(_b("IP", found[0]))

    # Speedtest normalization (optional enrichment)
    low = (body or '').lower()
    if "speedtest" in low or "ping" in low:
        p = re.search(r'ping\D+([\d.]+)\s*ms', body or '', re.I)
        up = re.search(r'up(?:load)?\D+([\d.]+)\s*([A-Za-z/]+)', body or '', re.I)
        dn = re.search(r'down(?:load)?\D+([\d.]+)\s*([A-Za-z/]+)', body or '', re.I)
        if p and not any(l.startswith("- **Ping:**") for l in details): details.append(_b("Ping", f"{p.group(1)} ms"))
        if up and not any(l.startswith("- **Upload:**") for l in details): details.append(_b("Upload", f"{up.group(1)} {up.group(2)}"))
        if dn and not any(l.startswith("- **Download:**") for l in details): details.append(_b("Download", f"{dn.group(1)} {dn.group(2)}"))

    # Stage 4: assemble with clean newlines (no sentence de-dup to keep layout)
    if facts:
        lines += ["📄 Facts", *facts, ""]
    if details:
        lines += ["📄 Details", *details, ""]

    text = "\n".join(_dedup_lines(lines)).strip()

    # Stage 5: extras (hero + list)
    extras = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}

    return text, extras
