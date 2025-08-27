# /app/beautify.py
# Jarvis Prime — Beautify Engine (5 Layers)
# 1) Ingest     -> title/body + optional source_hint/mood
# 2) Detect     -> classify source (sonarr/radarr/qnap/unraid/watchtower/speedtest/json/yaml/generic)
# 3) Normalize  -> extract facts, strip boilerplate, remove raw image URLs and markdown image syntax
# 4) Interpret  -> concise, AI-ish summary lines, no “Mood:” text here
# 5) Render     -> Jarvis Card text + extras (client::notification.bigImageUrl)
#
# Guarantees:
# - No duplicate lines (“Info: …” in facts + same sentence in body).
# - No raw image links; posters/logos become big images via extras.
# - Works for generic payloads and specific sources.
# - Personality/quip is NOT added here (that happens in send_message).

from __future__ import annotations
import json
import re
from typing import Tuple, Optional

try:
    import yaml  # optional
except Exception:
    yaml = None

# ---------------------------------------------
# Image handling
# ---------------------------------------------
IMG_URL_RE = re.compile(
    r'(https?://[^\s)]+?\.(?:png|jpe?g|gif|webp)(?:\?[^\s)]*)?)',
    re.IGNORECASE,
)

LIKELY_POSTER_HOSTS = (
    "githubusercontent.com",
    "fanart.tv",
    "themoviedb.org",
    "image.tmdb.org",
    "trakt.tv",
    "tvdb.org",
    "gravatar.com",
    "plex.tv",
    "plex.direct",
)

def _first_image_url(text: str) -> Optional[str]:
    """Find first image URL; prefer known poster domains if present."""
    if not text:
        return None
    matches = list(IMG_URL_RE.finditer(text))
    if not matches:
        return None
    try:
        from urllib.parse import urlparse
        # Prefer known poster hosts
        for m in matches:
            url = m.group(1)
            host = urlparse(url).netloc.lower()
            if any(h in host for h in LIKELY_POSTER_HOSTS):
                return url
    except Exception:
        pass
    return matches[0].group(1)

def _strip_image_urls(text: str) -> str:
    """Remove markdown image syntax and bare image URLs from text."""
    if not text:
        return ""
    # Remove markdown image syntax ![alt](URL)
    text = re.sub(r'!\[[^\]]*]\((https?://[^\s)]+)\)', '', text, flags=re.IGNORECASE)
    # Remove bare image URLs
    text = IMG_URL_RE.sub('', text)
    # Clean spacing
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ---------------------------------------------
# Line helpers & dedup
# ---------------------------------------------
def _extract_first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln
    return ""

def _normline(s: str) -> str:
    """Normalize a line for de-duplication."""
    s = (s or "").strip()
    # Drop common prefixes
    s = re.sub(r'^(info|message|note|status)\s*[:\-]\s*', '', s, flags=re.I)
    # Collapse punctuation/whitespace at end
    s = re.sub(r'[!\.\s]+$', '', s)
    # Collapse internal whitespace
    s = re.sub(r'\s+', ' ', s)
    return s.lower()

def _dedup_lines(lines):
    """Deduplicate while preserving human-friendly spacing."""
    seen = set()
    out = []
    for ln in lines:
        base = _normline(ln)
        if base:
            if base not in seen:
                seen.add(base)
                out.append(ln)
        else:
            # keep single blank lines (no runs)
            if not out or out[-1] != "":
                out.append("")
    # Trim leading/trailing blanks
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out

def _lines(*chunks):
    out = []
    for c in chunks:
        if not c:
            continue
        if isinstance(c, (list, tuple)):
            out.extend([x for x in c if x is not None])
        else:
            out.append(c)
    return out

# ---------------------------------------------
# Quick structure detectors
# ---------------------------------------------
def _looks_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False

def _looks_yaml(s: str) -> bool:
    if not yaml:
        return False
    try:
        obj = yaml.safe_load(s)
        return isinstance(obj, (dict, list))
    except Exception:
        return False

# ---------------------------------------------
# Source detectors
# ---------------------------------------------
def _is_sonarr(title: str, body: str) -> bool:
    t = (title + " " + body).lower()
    return "sonarr" in t

def _is_radarr(title: str, body: str) -> bool:
    t = (title + " " + body).lower()
    return "radarr" in t

def _is_watchtower(title: str, body: str) -> bool:
    t = (title + " " + body).lower()
    return "watchtower" in t

def _is_speedtest(title: str, body: str) -> bool:
    t = (title + " " + body).lower()
    return ("speedtest" in t) or ("ookla" in t)

def _is_qnap(title: str, body: str) -> bool:
    t = (title + " " + body).lower()
    return ("qnap" in t) or ("nas name" in t and "qnap" in t)

def _is_unraid(title: str, body: str) -> bool:
    t = (title + " " + body).lower()
    return "unraid" in t

# ---------------------------------------------
# Rendering helpers
# ---------------------------------------------
def _header(title: str) -> list[str]:
    return [
        "———————————————",
        f"📟 Jarvis Prime — {title.strip()}",
        "———————————————",
    ]

def _kv(label: str, value: str) -> str:
    return f"⏺ {label}: {value}"

def _section_title(s: str) -> str:
    return f"📄 {s}"

# ---------------------------------------------
# Formatters (per source)
# ---------------------------------------------
def _fmt_sonarr(title: str, body: str) -> Tuple[str, Optional[dict]]:
    """
    Sonarr generic/test messages often repeat the same sentence in multiple places.
    - We pull a single 'Info' line from the first content sentence.
    - We strip inline logos/posters and place them into bigImageUrl.
    - We dedup between 'Info' and 'Message' sections.
    """
    img = _first_image_url(title) or _first_image_url(body)
    clean_body = _strip_image_urls(body)

    # Extract facts
    facts = []
    # First line as info
    first = _extract_first_nonempty_line(clean_body)
    if first:
        facts.append(_kv("Info", first))

    # Optional timestamp token (very lenient)
    ts = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}.*?\d{1,2}:\d{2}(?::\d{2})?)', clean_body)
    lines = _lines(_header("Generic Message"))
    if ts:
        lines.append(_kv("Time", ts.group(1).strip()))
    lines += facts

    # Message body (only non-empty lines, deduped from facts)
    body_lines = [ln.strip() for ln in clean_body.splitlines() if ln.strip()]
    combined = _dedup_lines(
        lines
        + ([""] if lines else [])
        + ([_section_title("Message")] if body_lines else [])
        + body_lines
    )

    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

def _fmt_radarr(title: str, body: str) -> Tuple[str, Optional[dict]]:
    img = _first_image_url(title) or _first_image_url(body)
    clean_body = _strip_image_urls(body)

    facts = []
    first = _extract_first_nonempty_line(clean_body)
    if first:
        facts.append(_kv("Info", first))

    lines = _lines(_header("Generic Message"), *facts)

    body_lines = [ln.strip() for ln in clean_body.splitlines() if ln.strip()]
    combined = _dedup_lines(
        lines
        + ([""] if lines else [])
        + ([_section_title("Message")] if body_lines else [])
        + body_lines
    )

    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

def _fmt_watchtower(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_image_urls(body)
    facts = []
    low = clean.lower()
    if "no new images" in low:
        facts.append("• All containers up-to-date")
    if "updated" in low:
        facts.append("• One or more containers updated")

    lines = _lines(_header("Watchtower Update"), *facts)
    if not facts:
        lines += ["", _section_title("Report"), clean]
    text = "\n".join(_dedup_lines(lines))
    return text, None

def _fmt_speedtest(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_image_urls(body)
    dl = re.search(r'down(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    ul = re.search(r'up(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    pg = re.search(r'ping\D+([\d.]+)\s*ms', clean, re.I)

    facts = []
    if pg: facts.append(_kv("Ping", f"{pg.group(1)} ms"))
    if dl: facts.append(_kv("Down", f"{dl.group(1)} {dl.group(2)}"))
    if ul: facts.append(_kv("Up", f"{ul.group(1)} {ul.group(2)}"))

    lines = _lines(_header("Speedtest"), *facts)
    if not facts:
        lines += ["", _section_title("Raw"), clean]
    text = "\n".join(_dedup_lines(lines))
    return text, None

def _fmt_qnap(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_image_urls(body)
    nas = re.search(r'NAS Name:\s*(.+)', clean, re.I)
    when = re.search(r'(?:Date/Time|Date):\s*([^\n]+)', clean, re.I)

    facts = []
    if nas: facts.append(_kv("NAS", nas.group(1).strip()))
    if when: facts.append(_kv("Time", when.group(1).strip()))

    first = _extract_first_nonempty_line(clean)
    if first and not any(_normline(first) == _normline(x) for x in facts):
        facts.append(_kv("Info", first))

    lines = _lines(_header("QNAP Notice"), *facts)

    tail = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if tail:
        lines += ["", _section_title("Details"), *_dedup_lines(tail)]
    text = "\n".join(_dedup_lines(lines))
    return text, None

def _fmt_unraid(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_image_urls(body)
    first = _extract_first_nonempty_line(clean)
    facts = [_kv("Info", first)] if first else []
    lines = _lines(_header("Unraid Event"), *facts, "", _section_title("Details"), clean)
    text = "\n".join(_dedup_lines(lines))
    return text, None

def _fmt_json(title: str, body: str) -> Tuple[str, Optional[dict]]:
    """Compact JSON bullet view for small dicts; otherwise fallback to generic."""
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and 0 < len(obj) <= 10:
            bullets = [f"• {k}: {obj[k]}" for k in obj]
            text = "\n".join(_lines(_header("JSON Payload"), "", *bullets))
            return text, None
    except Exception:
        pass
    return _fmt_generic(title, body)

def _fmt_yaml(title: str, body: str) -> Tuple[str, Optional[dict]]:
    try:
        if yaml:
            obj = yaml.safe_load(body)
            if isinstance(obj, dict) and 0 < len(obj) <= 10:
                bullets = [f"• {k}: {obj[k]}" for k in obj]
                text = "\n".join(_lines(_header("YAML Payload"), "", *bullets))
                return text, None
    except Exception:
        pass
    return _fmt_generic(title, body)

def _fmt_generic(title: str, body: str) -> Tuple[str, Optional[dict]]:
    """Generic fallback with dedup + poster/logo extraction."""
    img = _first_image_url(title) or _first_image_url(body)
    clean_body = _strip_image_urls(body)

    facts = []
    first = _extract_first_nonempty_line(clean_body)
    if first:
        facts.append(_kv("Info", first))

    lines = _lines(_header("Generic Message"), *facts)
    body_lines = [ln.strip() for ln in clean_body.splitlines() if ln.strip()]

    combined = _dedup_lines(
        lines
        + ([""] if lines else [])
        + ([_section_title("Message")] if body_lines else [])
        + body_lines
    )
    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

# ---------------------------------------------
# Public entrypoint
# ---------------------------------------------
def beautify_message(
    title: str,
    body: str,
    *,
    mood: str = "serious",             # reserved; not used here (personality added by caller)
    source_hint: str | None = None     # optional nudges: "sonarr", "radarr", "qnap", "watchtower", etc.
) -> Tuple[str, Optional[dict]]:
    """
    Returns: (message_text, extras_dict_or_None)

    Behaviors:
    - Deduplicates overlapping lines across facts/body.
    - Removes inline image URLs and markdown image blocks from text.
    - Sets extras.client::notification.bigImageUrl when an image URL is found.
    - Never appends mood/quip; personality layer happens in send_message().
    """
    title = title or ""
    body = body or ""

    # Very short payloads: still wrap in a minimal card
    if len(body.strip()) < 2 and not _first_image_url(title + " " + body):
        return "\n".join(_dedup_lines(_lines(_header("Message"), body))).strip(), None

    # Route based on hint or detector
    if source_hint == "sonarr" or _is_sonarr(title, body):
        return _fmt_sonarr(title, body)
    if source_hint == "radarr" or _is_radarr(title, body):
        return _fmt_radarr(title, body)
    if source_hint == "watchtower" or _is_watchtower(title, body):
        return _fmt_watchtower(title, body)
    if source_hint == "speedtest" or _is_speedtest(title, body):
        return _fmt_speedtest(title, body)
    if source_hint == "qnap" or _is_qnap(title, body):
        return _fmt_qnap(title, body)
    if source_hint == "unraid" or _is_unraid(title, body):
        return _fmt_unraid(title, body)
    if _looks_json(body):
        return _fmt_json(title, body)
    if _looks_yaml(body):
        return _fmt_yaml(title, body)

    return _fmt_generic(title, body)
