# /app/beautify.py
# Jarvis Prime – Beautify Engine
# Universal, image‑preserving, with dynamic Persona Overlays loaded from personality.py
#
# Stages:
# 1) INGEST       : wrap raw inputs
# 2) NORMALIZE    : collect image URLs (do NOT remove from body)
# 3) INTERPRET    : universal synthesis (header + facts + body)
# 4) RENDER       : assemble card (header, facts, sections)
# 5) DEDUPE LINES : case/space-insensitive
# 6) DEDUPE SENTS : punctuation-aware sentence dedupe
# 7) HERO IMAGE   : choose one poster and attach as extras.client::notification.bigImageUrl
# 8) PERSONA      : overlay loaded at runtime from personality.py (hot‑reload on each call)
#
# Notes:
# - This file no longer hardcodes personas. It defers to /app/personalilty.py (module name: personality).
# - Keep persona definitions in that file (legacy ones still active; new edits picked up without restart).
#
from __future__ import annotations
import json, re, random, importlib
from typing import Tuple, Optional, List, Dict, Any

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
    body_lines = [ln.rstrip() for ln in body.splitlines()]
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
# Stage 8: PERSONA OVERLAY (dynamic from personality.py)
# ---------------------------
def _load_persona_from_module(persona_name: Optional[str]) -> Dict[str, Any]:
    """
    Looks for a 'personality' module alongside this file and tries, in order:
      1) personality.get_persona(name) -> dict
      2) personality.PERSONAS[name_lower] -> dict
      3) personality.PERSONA_STYLES[name_lower] -> dict
      4) personality.STYLES[name_lower] -> dict
    Expected dict keys: 'label' (str) and optional 'quips' (List[str]).
    Returns {} for neutral/ops/unknown.
    Hot‑reloads the module each call so edits take effect immediately.
    """
    if not persona_name:
        return {}
    key = (persona_name or "").strip().lower()
    if key in ("neutral", "ops", "operations", "ops_mode", "none"):
        return {}
    try:
        mod = importlib.import_module("personality")
        mod = importlib.reload(mod)
    except Exception:
        return {}
    # 1) get_persona function
    try:
        if hasattr(mod, "get_persona"):
            data = mod.get_persona(key)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    # 2..4) dict lookups across common names
    for attr in ("PERSONAS", "PERSONA_STYLES", "STYLES", "profiles", "overlays"):
        data = getattr(mod, attr, None)
        if isinstance(data, dict):
            obj = data.get(key) or data.get(key.lower())
            if isinstance(obj, dict):
                return obj
    return {}

def _apply_persona_overlay(text: str, persona_name: Optional[str], add_quip: bool) -> str:
    data = _load_persona_from_module(persona_name)
    label = (data.get("label") or "").strip() if isinstance(data, dict) else ""
    quips = data.get("quips") if isinstance(data, dict) else None

    if not label:
        return text  # neutral/ops/unknown -> no overlay

    quip_line = ""
    if add_quip and isinstance(quips, (list, tuple)) and quips:
        try:
            quip_line = f'“{random.choice(list(quips))}”'
        except Exception:
            quip_line = ""

    lines = text.splitlines()
    # Insert persona label after the header block if present
    insert_at = 3 if len(lines) >= 3 and lines[0].startswith("—") and "Jarvis Prime" in lines[1] else 0
    overlay_lines = [f"{label}"] + ([quip_line] if quip_line else [])
    new_lines = lines[:insert_at] + overlay_lines + lines[insert_at:]
    return "\n".join(new_lines)

# ---------------------------
# Public: full pipeline
# ---------------------------
def beautify_message(title: str, body: str, *, mood: str = "serious",
                     source_hint: str | None = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True) -> Tuple[str, Optional[dict]]:
    # Stage 1: INGEST
    ctx = _ingest(title, body, mood, source_hint)

    # Early tiny payloads: wrap minimal (keep body intact; no image stripping)
    if len(ctx["body"]) < 2 and not IMG_URL_RE.search(ctx["title"] + " " + ctx["body"]):
        base = "\n".join(_dedup_lines(_lines(_header("Message"), ctx["body"]))).strip()
        text = _apply_persona_overlay(base, persona, persona_quip)
        return text, None

    # Stage 2: UNIVERSAL KIND (kept for future)
    _ = _kind_universal()

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
    text, extras = _finalize(text, images)

    # Stage 8: persona overlay (dynamic from personality.py)
    text = _apply_persona_overlay(text, persona, persona_quip)

    return text, extras
