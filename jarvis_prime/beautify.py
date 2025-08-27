# /app/beautify.py
# Jarvis Prime — Beautify Engine (7 stages)
#  1) Ingest     -> title/body in, optional source_hint/mood
#  2) Detect     -> classify source (sonarr/radarr/watchtower/speedtest/qnap/unraid/json/yaml/generic)
#  3) Normalize  -> strip image markdown/URLs, basic token cleanup
#  4) Extract    -> pull concise facts (Info, Time, NAS, speeds, etc.)
#  5) Render     -> Jarvis Card lines (header, facts, optional “Message” block)
#  6) De-dupe    -> remove duplicated sentences/lines between facts and body
#  7) Image UX   -> DO NOT print image URLs; attach one poster via extras.bigImageUrl
#
# Notes:
#  • No “Mood:” line here. Personality/quip is appended by send_message() outside this file.
#  • Works for any source; Sonarr/Radarr get nice generic treatment when payloads are simple.
#  • If a payload contains multiple images/markdown-embeds, we pick the first best poster-like URL
#    and never echo it in text.

from __future__ import annotations
import json
import re
from typing import Dict, List, Tuple, Optional

try:
    import yaml  # optional (used only for tiny yaml bulletization)
except Exception:
    yaml = None

# ---- Image helpers -----------------------------------------------------------

IMG_URL_RE = re.compile(
    r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)',
    re.IGNORECASE,
)

# Prefer common poster/CDN hosts when present
LIKELY_POSTER_HOSTS = (
    "githubusercontent.com",
    "fanart.tv",
    "themoviedb.org",
    "image.tmdb.org",
    "trakt.tv",
    "tvdb.org",
    "gravatar.com",
)

def _first_image_url(text: str) -> Optional[str]:
    """Find the first image URL (favoring known poster hosts)."""
    if not text:
        return None
    matches = list(IMG_URL_RE.finditer(text))
    if not matches:
        return None
    # Prefer a known poster host if we can
    try:
        from urllib.parse import urlparse
        for m in matches:
            url = m.group(1)
            host = urlparse(url).netloc.lower()
            if any(h in host for h in LIKELY_POSTER_HOSTS):
                return url
    except Exception:
        pass
    return matches[0].group(1)

def _strip_inline_images(text: str) -> str:
    """Remove inline images/markdown and bare image URLs from text."""
    if not text:
        return ""
    # remove markdown images ![...](http...)
    text = re.sub(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', '', text, flags=re.IGNORECASE)
    # remove bare image URLs
    text = IMG_URL_RE.sub('', text)
    # collapse whitespace and huge gaps
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ---- Common text helpers -----------------------------------------------------

def _first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln
    return ""

def _normline(s: str) -> str:
    """Normalize a line for de-dup: trim common prefixes/suffix noise."""
    s = (s or "").strip()
    # Strip “Info:”, “Message:”, “Status:”, etc.
    s = re.sub(r'^(info|message|note|status)\s*[:\-]\s*', '', s, flags=re.I)
    # Trim trailing punctuation/noise
    s = re.sub(r'[!.:\s]+$', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s.lower()

def _dedup_keep_order(lines: List[str]) -> List[str]:
    """De-duplicate lines while preserving order and removing blank padding."""
    seen = set()
    out: List[str] = []
    for ln in lines:
        base = _normline(ln)
        if base:
            if base in seen:
                continue
            seen.add(base)
            out.append(ln)
        else:
            # keep single blank separators
            if not out or out[-1] != "":
                out.append("")
    # trim leading/trailing blanks
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out

def _drop_body_duplicates(body_lines: List[str], *fact_lines: str) -> List[str]:
    """Remove body lines that duplicate any fact lines (normalized comparison)."""
    fact_set = {_normline(x) for x in fact_lines if x}
    if not fact_set:
        return body_lines
    filtered: List[str] = []
    for ln in body_lines:
        if _normline(ln) in fact_set:
            continue
        filtered.append(ln)
    return filtered

def _lines(*chunks):
    out: List[str] = []
    for c in chunks:
        if not c:
            continue
        if isinstance(c, (list, tuple)):
            out.extend([x for x in c if x is not None])
        else:
            out.append(str(c))
    return out

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

# ---- UI helpers --------------------------------------------------------------

def _header(title: str) -> List[str]:
    return [
        "———————————————",
        f"📟 Jarvis Prime — {title.strip()}",
        "———————————————",
    ]

def _kv(label: str, value: str) -> str:
    return f"⏺ {label}: {value}"

def _section_title(s: str) -> str:
    return f"📄 {s}"

# ---- Source detectors ---------------------------------------------------------

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

# ---- Per-source formatters ----------------------------------------------------

def _fmt_sonarr(title: str, body: str) -> Tuple[str, Optional[dict]]:
    img = _first_image_url(title) or _first_image_url(body)
    clean = _strip_inline_images(body)

    # Facts
    facts: List[str] = []
    first = _first_nonempty_line(clean)
    if first:
        facts.append(_kv("Info", first))

    # Optional timestamp (best effort)
    ts = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}.*\d{1,2}:\d{2})', clean)
    lines = _lines(_header("Generic Message"))
    if ts:
        lines.append(_kv("Time", ts.group(1)))
    lines += facts

    # Body
    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    # Stage 6: remove duplicates present in facts
    body_lines = _drop_body_duplicates(body_lines, first)

    combined = _dedup_keep_order(
        lines + ([""] if lines else []) + ([_section_title("Message")] if body_lines else []) + body_lines
    )
    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

def _fmt_radarr(title: str, body: str) -> Tuple[str, Optional[dict]]:
    img = _first_image_url(title) or _first_image_url(body)
    clean = _strip_inline_images(body)

    facts: List[str] = []
    first = _first_nonempty_line(clean)
    if first:
        facts.append(_kv("Info", first))

    lines = _lines(_header("Generic Message"), *facts)

    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    body_lines = _drop_body_duplicates(body_lines, first)

    combined = _dedup_keep_order(
        lines + ([""] if lines else []) + ([_section_title("Message")] if body_lines else []) + body_lines
    )
    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

def _fmt_watchtower(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_inline_images(body)
    facts: List[str] = []
    lc = clean.lower()
    if "no new images" in lc:
        facts.append("• All containers up-to-date")
    if "updated" in lc:
        facts.append("• Containers updated")

    lines = _lines(_header("Watchtower Update"), *facts)
    if not facts:
        lines += ["", _section_title("Report"), clean]
    text = "\n".join(_dedup_keep_order(lines))
    return text, None

def _fmt_speedtest(title: str, body: str) -> Tuple[str, Optional[dict]]:
    img = _first_image_url(title) or _first_image_url(body)
    clean = _strip_inline_images(body)

    dl = re.search(r'down(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    ul = re.search(r'up(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    pg = re.search(r'ping\D+([\d.]+)\s*ms', clean, re.I)

    facts: List[str] = []
    if pg: facts.append(_kv("Ping", f"{pg.group(1)} ms"))
    if dl: facts.append(_kv("Down", f"{dl.group(1)} {dl.group(2)}"))
    if ul: facts.append(_kv("Up", f"{ul.group(1)} {ul.group(2)}"))

    lines = _lines(_header("Speedtest"), *facts)
    if not facts:
        lines += ["", _section_title("Raw"), clean]
    text = "\n".join(_dedup_keep_order(lines))
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

def _fmt_json(title: str, body: str) -> Tuple[str, Optional[dict]]:
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

def _fmt_qnap(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_inline_images(body)
    nas = re.search(r'NAS Name:\s*(.+)', clean, re.I)
    when = re.search(r'(?:Date/Time|Date):\s*([^\n]+)', clean, re.I)

    facts: List[str] = []
    if nas: facts.append(_kv("NAS", nas.group(1).strip()))
    if when: facts.append(_kv("Time", when.group(1).strip()))

    first = _first_nonempty_line(clean)
    if first and not any(_normline(first) == _normline(x) for x in facts):
        facts.append(_kv("Info", first))

    lines = _lines(_header("QNAP Notice"), *facts)
    tail = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    tail = _drop_body_duplicates(tail, first)

    if tail:
        lines += ["", _section_title("Details"), *_dedup_keep_order(tail)]

    text = "\n".join(_dedup_keep_order(lines))
    return text, None

def _fmt_unraid(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_inline_images(body)
    first = _first_nonempty_line(clean)
    facts = [_kv("Info", first)] if first else []

    lines = _lines(_header("Unraid Event"), *facts)

    tail = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    tail = _drop_body_duplicates(tail, first)

    if tail:
        lines += ["", _section_title("Details"), *tail]

    text = "\n".join(_dedup_keep_order(lines))
    return text, None

def _fmt_generic(title: str, body: str) -> Tuple[str, Optional[dict]]:
    img = _first_image_url(title) or _first_image_url(body)
    clean = _strip_inline_images(body)

    facts: List[str] = []
    first = _first_nonempty_line(clean)
    if first:
        facts.append(_kv("Info", first))

    lines = _lines(_header("Generic Message"), *facts)

    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    body_lines = _drop_body_duplicates(body_lines, first)

    combined = _dedup_keep_order(
        lines + ([""] if lines else []) + ([_section_title("Message")] if body_lines else []) + body_lines
    )
    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

# ---- Public entrypoint --------------------------------------------------------

def beautify_message(
    title: str,
    body: str,
    *,
    mood: str = "serious",
    source_hint: str | None = None
) -> Tuple[str, Optional[dict]]:
    """
    Return (message_text, extras_dict or None).
     • Removes inline image markdown/URLs from text.
     • Emits at most one poster via extras.client::notification.bigImageUrl.
     • De-duplicates repeated sentences/lines between “Info” facts and the body.
     • Keeps everything compact and consistent across sources.
    """
    title = title or ""
    body = body or ""

    # ultra-short payloads (no content)
    if len(body.strip()) < 2 and not _first_image_url(title + " " + body):
        return "\n".join(_dedup_keep_order(_lines(_header("Message"), body))).strip(), None

    # choose formatter
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
