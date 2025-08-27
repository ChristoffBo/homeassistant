# /app/beautify.py
# Jarvis Prime Beautify Engine (5 layers):
# 1) Ingest     -> title/body in, optional source_hint/mood
# 2) Detect     -> classify source (arr/sonarr/radarr/qnap/unraid/watchtower/json/yaml/generic)
# 3) Normalize  -> pull out facts (time, host, status, etc.), strip boilerplate
# 4) Interpret  -> short natural-language synthesis (no explicit "Mood:" line here)
# 5) Render     -> Jarvis Card text + extras (bigImageUrl)
#
# Goals:
# - No duplicate lines (e.g., Sonarr test message showing twice)
# - No raw image URLs/markdown in the body; images go to extras.bigImageUrl
# - Keep output compact, AI-ish, and consistent across sources
#
# NOTE: Personality quips are added OUTSIDE by send_message(...). We do not
# append mood or quips here to avoid double "mood" noise.

from __future__ import annotations
import json
import re
from typing import Dict, Tuple, Optional

try:
    import yaml  # optional, for YAML formatting
except Exception:
    yaml = None

IMG_URL_RE = re.compile(
    r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)',
    re.IGNORECASE,
)

# Helpful domains commonly used by media servers for posters/logos
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
    if not text:
        return None
    m = IMG_URL_RE.search(text)
    if not m:
        return None
    url = m.group(1)
    # Prefer known poster hosts if multiple
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if any(h in host for h in LIKELY_POSTER_HOSTS):
            return url
    except Exception:
        pass
    return url

def _strip_image_urls(text: str) -> str:
    if not text:
        return text or ""
    # Remove markdown image syntax ![...](URL)
    text = re.sub(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', '', text, flags=re.IGNORECASE)
    # Remove bare image URLs
    text = IMG_URL_RE.sub('', text)
    # Clean double spaces/lines
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _dedup_lines(lines):
    seen = set()
    out = []
    for ln in lines:
        norm = re.sub(r'\s+', ' ', (ln or '').strip()).lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(ln)
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

# ---------------------------
# Source detectors
# ---------------------------
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

def _extract_first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln
    return ""

# ---------------------------
# Render helpers
# ---------------------------
def _header(title: str) -> list[str]:
    return [
        "———————————————",
        f"📟 Jarvis Prime — {title.strip()}",
        "———————————————",
    ]

def _kv(label: str, value: str) -> str:
    return f"⏺ {label}: {value}"

def _bullet(s: str) -> str:
    return f"◆ {s}"

def _section_title(s: str) -> str:
    return f"📄 {s}"

# ---------------------------
# Per-source formatters
# ---------------------------
def _fmt_sonarr(title: str, body: str) -> Tuple[str, Optional[dict]]:
    """
    Generic Sonarr messages sometimes repeat the same line in different places
    (e.g., "This is a test message from Sonarr"). We dedup facts vs body.
    Also migrate any image URL to extras.bigImageUrl.
    """
    img = _first_image_url(title) or _first_image_url(body)
    clean_title = _strip_image_urls(title)
    clean_body = _strip_image_urls(body)

    # Facts (light)
    facts = []
    # If body has a first non-empty line, capture as 'Info'
    first = _extract_first_nonempty_line(clean_body)
    if first:
        facts.append(_kv("Info", first))

    # Build
    lines = _lines(
        _header("Generic Message"),
        _kv("Time", _extract_first_nonempty_line(re.sub(r".*?(\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}).*", r"\1", clean_body, flags=re.DOTALL)) or ""),
        *facts,
    )

    # Body (only if it adds new information vs facts)
    body_lines = []
    for ln in clean_body.splitlines():
        if not ln.strip():
            continue
        body_lines.append(ln.strip())

    combined = _dedup_lines(lines + ([""] if lines else []) + ([_section_title("Message")] if body_lines else []) + body_lines)

    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

def _fmt_radarr(title: str, body: str) -> Tuple[str, Optional[dict]]:
    img = _first_image_url(title) or _first_image_url(body)
    clean_title = _strip_image_urls(title)
    clean_body = _strip_image_urls(body)

    facts = []
    first = _extract_first_nonempty_line(clean_body)
    if first:
        facts.append(_kv("Info", first))

    lines = _lines(
        _header("Generic Message"),
        *facts,
    )

    body_lines = []
    for ln in clean_body.splitlines():
        if not ln.strip():
            continue
        body_lines.append(ln.strip())

    combined = _dedup_lines(lines + ([""] if lines else []) + ([_section_title("Message")] if body_lines else []) + body_lines)

    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

def _fmt_watchtower(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_image_urls(body)
    facts = []
    if "no new images" in clean.lower():
        facts.append(_bullet("All containers up-to-date"))
    if "updated" in clean.lower():
        facts.append(_bullet("One or more containers updated"))

    lines = _lines(
        _header("Watchtower Update"),
        *facts,
        "",
        _section_title("Report"),
        clean,
    )
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

    lines = _lines(
        _header("Speedtest"),
        *facts,
    )
    if not facts:
        lines += ["", _section_title("Raw"), clean]
    text = "\n".join(_dedup_lines(lines))
    return text, None

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
    clean = _strip_image_urls(body)
    nas = re.search(r'NAS Name:\s*(.+)', clean, re.I)
    when = re.search(r'(?:Date/Time|Date):\s*([^\n]+)', clean, re.I)
    facts = []
    if nas: facts.append(_kv("NAS", nas.group(1).strip()))
    if when: facts.append(_kv("Time", when.group(1).strip()))
    first = _extract_first_nonempty_line(clean)
    if first and not any(first in x for x in facts):
        facts.append(_kv("Info", first))
    lines = _lines(_header("QNAP Notice"), *facts)
    tail = clean.splitlines()
    extra_block = []
    for ln in tail:
        if ln.strip():
            extra_block.append(ln.strip())
    if extra_block:
        lines += ["", _section_title("Details"), *_dedup_lines(extra_block)]
    text = "\n".join(_dedup_lines(lines))
    return text, None

def _fmt_unraid(title: str, body: str) -> Tuple[str, Optional[dict]]:
    clean = _strip_image_urls(body)
    first = _extract_first_nonempty_line(clean)
    facts = [_kv("Info", first)] if first else []
    lines = _lines(_header("Unraid Event"), *facts, "", _section_title("Details"), clean)
    text = "\n".join(_dedup_lines(lines))
    return text, None

def _fmt_generic(title: str, body: str) -> Tuple[str, Optional[dict]]:
    # Try to detect an image URL anywhere and move it to extras
    img = _first_image_url(title) or _first_image_url(body)
    clean_title = _strip_image_urls(title)
    clean_body = _strip_image_urls(body)

    facts = []
    first = _extract_first_nonempty_line(clean_body)
    if first:
        facts.append(_kv("Info", first))

    lines = _lines(
        _header("Generic Message"),
        *facts,
    )

    body_lines = []
    for ln in clean_body.splitlines():
        if not ln.strip():
            continue
        body_lines.append(ln.strip())

    combined = _dedup_lines(lines + ([""] if lines else []) + ([_section_title("Message")] if body_lines else []) + body_lines)
    text = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": img}} if img else None
    return text, extras

# ---------------------------
# Public entrypoint
# ---------------------------
def beautify_message(title: str, body: str, *, mood: str = "serious", source_hint: str | None = None) -> Tuple[str, Optional[dict]]:
    """
    Return (message_text, extras_dict or None).
    - Removes duplicated lines between facts and body
    - Removes raw image URLs / markdown image syntax from text
    - Emits images via extras.client::notification.bigImageUrl
    - Does NOT include mood text; personality is applied outside
    """
    title = title or ""
    body = body or ""

    # Short-circuit payloads that are already very short
    if len(body) < 2 and not _first_image_url(title + " " + body):
        return "\n".join(_dedup_lines(_lines(_header("Message"), body))).strip(), None

    # Decide formatter
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
