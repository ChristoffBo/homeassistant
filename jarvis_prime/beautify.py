
# /app/beautify.py
from __future__ import annotations
import re, json, importlib
from typing import List, Tuple, Optional, Dict

# ---------- Regexes ----------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)

# Strict IPv4 (0-255 each octet)
OCT = r'(?:25[0-5]|2[0-4]\d|1?\d{1,2})'
IPV4_STRICT_RE = re.compile(rf'\b{OCT}\.{OCT}\.{OCT}\.{OCT}\b')

PUNCT_SPLIT = re.compile(r'([.!?])')

# ---------- Helpers ----------
def _dedup_lines(lines: List[str]) -> List[str]:
    seen = set(); out: List[str] = []
    for ln in lines:
        base = re.sub(r'\s+', ' ', (ln or '').strip()).lower()
        if base and base not in seen:
            seen.add(base); out.append(ln)
        elif not base and (not out or out[-1] != ''):
            out.append('')
    while out and out[0] == '': out.pop(0)
    while out and out[-1] == '': out.pop()
    return out

def _dedup_sentences(text: str) -> str:
    parts: List[str] = []
    buf = ''
    for piece in PUNCT_SPLIT.split(text):
        if PUNCT_SPLIT.fullmatch(piece):
            if buf:
                parts.append(buf + piece); buf = ''
        else:
            buf += piece
    if buf.strip(): parts.append(buf)
    seen = set(); out = []
    for frag in parts:
        norm = re.sub(r'\s+',' ',frag.strip()).lower()
        if norm and norm not in seen:
            seen.add(norm); out.append(frag)
    return ''.join(out)

def _harvest_images(text: str) -> Tuple[str, List[str]]:
    if not text: return '', []
    urls: List[str] = []
    def _md(m):
        urls.append(m.group(1)); return ''
    text = MD_IMG_RE.sub(_md, text)
    def _bare(m):
        urls.append(m.group(1)); return ''
    text = IMG_URL_RE.sub(_bare, text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    # unique preserve order
    seen=set(); uniq=[]
    for u in urls:
        if u not in seen:
            seen.add(u); uniq.append(u)
    return text, uniq

def _find_ipv4s(*chunks: str) -> List[str]:
    buf = ' '.join([c for c in chunks if c])
    return IPV4_STRICT_RE.findall(buf)

def _repair_ipv4(value: str, title: str, body: str) -> str:
    # If already strict, return
    if IPV4_STRICT_RE.fullmatch((value or '').strip()): return value.strip()
    # Collapse stray spaces around dots
    compact = re.sub(r'\s*\.\s*', '.', (value or '').strip())
    if IPV4_STRICT_RE.fullmatch(compact): return compact
    # If looks like 2-3 octets, try to find a strict IPv4 in title/body
    found = _find_ipv4s(title, body)
    if found: return found[0]
    return value.strip()

def _section_title(label: str) -> str:
    return f"\n📄 {label}\n"

def _b_fact(label: str, value: str) -> str:
    return f"• - **{label}:** {value}"

def _persona_overlay(persona: Optional[str], allow_quip: bool=True) -> str:
    if not persona: return ''
    quip = ''
    try:
        mod = importlib.import_module('personality')
        mod = importlib.reload(mod)
        if allow_quip and hasattr(mod, 'quip'):
            q = mod.quip(persona) or ''
            quip = (' — ' + str(q).strip()) if str(q).strip() else ''
    except Exception:
        pass
    return f"💬 {persona} says:{quip}".rstrip()

def _header(kind: str) -> str:
    return f"📟 Jarvis Prime — {kind}".rstrip()

# ---------- Public API ----------
def beautify_message(title: str, body: str, *, mood: str='serious',
                     mode: str='standard', persona: Optional[str]=None,
                     persona_quip: bool=True) -> Tuple[str, Optional[dict]]:
    # 1) strip & harvest images
    clean_body, images = _harvest_images(body or '')
    # 2) header + persona one-liner
    lines: List[str] = []
    lines.append(_header('Message'))
    pol = _persona_overlay(persona, allow_quip=persona_quip)
    if pol: lines.append(pol)

    # 3) build Facts
    facts: List[str] = []
    subj = (title or '').strip()
    if subj: facts.append(_b_fact('Subject', subj))

    # time (best-effort simple extraction)
    dt = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', body or '')
    if not dt:
        dt = re.search(r'\b(\d{2}[\-/]\d{2}[\-/]\d{2,4})\b', body or '')
    if dt: facts.append(_b_fact('Time', dt.group(1)))

    # 4) details: parse simple k:v lines
    details: List[str] = []
    for raw in (clean_body or '').splitlines():
        s = raw.strip()
        if not s: continue
        m = re.match(r'\s*[-•\u2022]*\s*([A-Za-z0-9_ ./()]+?)\s*[:：]\s*(.+)$', s)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            # normalize IP label
            if k.lower() in ('ip','ip address','host ip','addr','address'):
                v = _repair_ipv4(v, title or '', body or '')
                k = 'IP'
            details.append(_b_fact(k, v))
        else:
            # fall back: keep as bullet line
            details.append(_b_fact('Info', s))

    # If we saw no details but we do have numbers like speedtest, try to extract
    if not details:
        # speed items
        p = re.search(r'ping\D+([\d.]+)\s*ms', body or '', re.I)
        up = re.search(r'up(?:load)?\D+([\d.]+)\s*([A-Za-z/]+)', body or '', re.I)
        dn = re.search(r'down(?:load)?\D+([\d.]+)\s*([A-Za-z/]+)', body or '', re.I)
        if p: details.append(_b_fact('Ping', f"{p.group(1)} ms"))
        if up: details.append(_b_fact('Upload', f"{up.group(1)} {up.group(2)}"))
        if dn: details.append(_b_fact('Download', f"{dn.group(1)} {dn.group(2)}"))

    # 5) Assemble
    out: List[str] = []
    out.extend(_dedup_lines(lines))
    if facts:
        out.append(_section_title('Facts').strip())
        out.extend(facts)
    if details:
        out.append(_section_title('Details').strip())
        out.extend(details)

    text = '\n'.join(out).strip()
    text = _dedup_sentences(text)

    # 6) extras (hero + full list)
    extras = {
        "client::display": {"contentType": "text/markdown"},
        "jarvis::beautified": True,
        "jarvis::allImageUrls": images
    }
    if images:
        extras["client::notification"] = {"bigImageUrl": images[0]}

    return text, extras
