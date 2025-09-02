# /app/beautify.py
# Jarvis Prime – Beautify Engine (Universal, image-preserving)
# Stages:
# 1) INGEST       : take raw title/body + optional hint (ignored for source)
# 2) NORMALIZE    : collect image URLs (WITHOUT removing from body); strip noise in facts
# 3) INTERPRET    : universal synthesis (header + facts + message)
# 4) RENDER       : assemble Jarvis card sections (leave markdown images intact)
# 5) DEDUPE LINES : remove duplicated lines (case/space-insensitive)
# 6) DEDUPE SENTS : remove duplicated sentences
# 7) HERO IMAGE   : attach a single big poster via extras.client::notification.bigImageUrl
#
# Notes:
# - Unlike earlier versions, we DO NOT strip images from the body. All image markdown/URLs remain.
# - We still choose one "hero" image for Gotify's bigImageUrl.
# - Persona quips are added outside this file.
#
from __future__ import annotations
import json, re
from typing import Tuple, Optional, List, Dict

try:
    import yaml  # optional, used only for sniffing
except Exception:
    yaml = None

# ---------------------------
# Shared regex & utils
# ---------------------------
IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
MD_IMG_RE  = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)
PUNCT_SPLIT = re.compile(r'([.!?])')

LIKELY_POSTER_HOSTS = (
    "githubusercontent.com", "fanart.tv", "themoviedb.org", "image.tmdb.org",
    "trakt.tv", "tvdb.org", "gravatar.com"
)

TS_RE = re.compile(
    r'(?:(?:date(?:\/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)',
    re.I
)

def _prefer_host_key(url: str) -> int:
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").lower()
        return 0 if any(k in host for k in LIKELY_POSTER_HOSTS) else 1
    except Exception:
        return 1

def _first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        t = ln.strip()
        if t:
            return t
    return ""

def _normline(s: str) -> str:
    # Strip noisy prefixes; condense whitespace; compare in lowercase for dedupe
    s = (s or "").strip()
    s = re.sub(r'^\s*\[?(info|message|note|status|debug|notice|warn|warning|error|err)\]?\s*[:\-]\s*', '', s, flags=re.I)
    s = re.sub(r'^\s*(DEBUG|INFO|NOTICE|WARN|WARNING|ERROR)\s*[:\-]\s*', '', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s)
    return s.lower()

def _dedup_lines(lines: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for ln in lines:
        base = _normline(ln)
        if base and base not in seen:
            seen.add(base)
            out.append(ln)
        elif not base and (not out or out[-1] != ""):
            out.append("")  # single blank keeper
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out

def _dedup_sentences(text: str) -> str:
    parts: List[str] = []
    buf = ""
    for piece in PUNCT_SPLIT.split(text):
        if PUNCT_SPLIT.fullmatch(piece):
            if buf:
                parts.append(buf + piece)
                buf = ""
        else:
            buf += piece
    if buf.strip():
        parts.append(buf)
    seen = set()
    out: List[str] = []
    for frag in parts:
        norm = re.sub(r'\s+', ' ', frag.strip()).lower()
        if norm and norm not in seen:
            seen.add(norm); out.append(frag)
    return "".join(out)

def _lines(*chunks) -> List[str]:
    out: List[str] = []
    for c in chunks:
        if not c: continue
        if isinstance(c, (list, tuple)):
            out.extend([x for x in c if x is not None])
        else:
            out.append(c)
    return out

def _harvest_timestamp(text: str, title: str) -> Optional[str]:
    for src in (text or "", title or ""):
        m = TS_RE.search(src)
        if m:
            return m.group(1).strip()
    return None

def _harvest_subject(title: str) -> Optional[str]:
    t = (title or "").strip()
    return t if t and not IMG_URL_RE.search(t) else None

def _looks_like_icon(url: str) -> bool:
    low = url.lower()
    if any(k in low for k in ("icon", "favicon", "logo", "sprite", "badge")):
        return True
    qs_dims = re.findall(r'[?&](?:w|width|h|height)=(\d{1,4})', low)
    if qs_dims and all(int(x) < 128 for x in qs_dims):
        return True
    m = re.search(r'[\-_](\d{1,3})x(\d{1,3})(?=\.)', low)
    if m:
        w, h = map(int, m.groups())
        if w < 128 or h < 128:
            return True
    return False

def _find_images_without_stripping(text: str) -> List[str]:
    urls: List[str] = []
    # markdown images
    for m in MD_IMG_RE.finditer(text or ""):
        urls.append(m.group(1))
    # bare URLs
    for m in IMG_URL_RE.finditer(text or ""):
        urls.append(m.group(1))
    # unique with preference, filtered for likely icons
    uniq = []
    seen = set()
    for u in sorted(urls, key=_prefer_host_key):
        if u not in seen and not _looks_like_icon(u):
            seen.add(u); uniq.append(u)
    return uniq

# ---------------------------
# Stage 1: INGEST
# ---------------------------
def _ingest(title: str, body: str, mood: str, source_hint: Optional[str]) -> Dict:
    return {
        "title": title or "",
        "body": body or "",
        "mood": (mood or "serious"),
        "hint": (source_hint or None),
    }

# ---------------------------
# Stage 2: UNIVERSAL (no per-source detection)
# ---------------------------
def _kind_universal() -> str:
    return "generic"

# ---------------------------
# Stage 3: NORMALIZE (collect images only; do NOT strip from text)
# ---------------------------
def _collect_only(text: str) -> List[str]:
    return _find_images_without_stripping(text)

# ---------------------------
# Stage 4: INTERPRET (universal)
# ---------------------------
def _header(title: str) -> List[str]:
    return ["———————————————", f"📟 Jarvis Prime — {title.strip()}", "———————————————"]

def _kv(label: str, value: str) -> str:   return f"⏺ {label}: {value}"
def _section(s: str) -> str:              return f"📄 {s}"

def _interpret_universal(title: str, body: str) -> List[str]:
    facts: List[str] = []
    ts = _harvest_timestamp(body, title)
    if ts: facts.append(_kv("Time", ts))
    subj = _harvest_subject(title)
    if subj: facts.append(_kv("Subject", subj))
    first = _first_nonempty_line(body)
    if first: facts.append(_kv("Info", first))
    lines = _lines(_header("Message"), *facts)
    body_lines = [ln.rstrip() for ln in body.splitlines() if ln.strip() or ln.strip()=="" ]
    if body_lines: lines += ["", _section("Message"), *body_lines]
    return lines

# ---------------------------
# Stage 5: RENDER (assemble)
# ---------------------------
def _render(lines: List[str]) -> str:
    return "\n".join(_dedup_lines(lines)).strip()

# ---------------------------
# Stage 6/7: DEDUPE SENTENCES + HERO IMAGE
# ---------------------------
def _finalize(text: str, images: List[str]) -> Tuple[str, Optional[dict]]:
    text = _dedup_sentences(text)
    hero = images[0] if images else None
    extras = None
    if hero:
        extras = {
            "client::display": {"contentType": "text/markdown"},
            "client::notification": {"bigImageUrl": hero},
        }
    return text, extras

# ---------------------------
# Public: full pipeline
# ---------------------------
def beautify_message(title: str, body: str, *, mood: str = "serious",
                     source_hint: str | None = None, mode: str = "standard") -> Tuple[str, Optional[dict]]:
    # Stage 1: INGEST
    ctx = _ingest(title, body, mood, source_hint)

    # Early tiny payloads: wrap minimal (still keep as-is, no image strip)
    if len(ctx["body"]) < 2 and not IMG_URL_RE.search(ctx["title"] + " " + ctx["body"]):
        return "\n".join(_dedup_lines(_lines(_header("Message"), ctx["body"]))).strip(), None

    # Stage 2: UNIVERSAL KIND
    kind = _kind_universal()

    # Stage 3: collect images without modifying body
    images = _collect_only(ctx["body"])

    # Stage 4: universal interpretation
    lines = _interpret_universal(ctx["title"], ctx["body"])

    # Stage 5: render
    text = _render(lines)

    # Optional verbosity modes
    if mode == "minimal":
        first_block = []
        for ln in text.splitlines():
            first_block.append(ln)
            if ln.startswith("📄 "):
                break
        text = "\n".join(first_block).strip()

    # Stage 6 & 7: de-dup sentences + hero
    return _finalize(text, images)
