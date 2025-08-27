# /app/beautify.py
# Jarvis Prime Beautify Engine — 7 stages
# 1) Ingest     -> title/body, optional source_hint/mood
# 2) Detect     -> source classification (sonarr/radarr/qnap/unraid/watchtower/json/yaml/generic)
# 3) Normalize  -> strip boilerplate, pull facts, extract ALL images from title+body
# 4) Interpret  -> concise fact block + body block
# 5) Render     -> Jarvis Card text + extras (bigImageUrl)
# 6) Polish     -> sentence-level dedupe across the whole message
# 7) Echo Img   -> if original had images, append a Markdown image so Gotify renders the actual image
#
# Guarantees:
# - No raw image links left in the main text (we re-insert a Markdown image in Stage 7).
# - First image also goes to extras.client::notification.bigImageUrl.
# - Duplicates like “Info: This is a test message” vs “This is a test message” are removed.

from __future__ import annotations
import json
import re
from typing import Tuple, Optional, List

try:
    import yaml  # optional
except Exception:
    yaml = None

# ---------- Image detection / stripping (robust) ----------
# Bare image URLs
IMG_URL_RE = re.compile(
    r'(https?://[^)\s]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)',
    re.IGNORECASE,
)

# Markdown images, permissive (allows spaces and optional title):
MD_IMG_RE = re.compile(
    r'!\s*\[[^\]]*\]\s*\(\s*([^)\s]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\)]*)?)\s*(?:"[^"]*")?\s*\)',
    re.IGNORECASE | re.DOTALL,
)

LIKELY_POSTER_HOSTS = (
    "githubusercontent.com",
    "fanart.tv",
    "themoviedb.org",
    "image.tmdb.org",
    "trakt.tv",
    "tvdb.org",
    "gravatar.com",
)

def _find_all_images(*parts: str) -> List[str]:
    seen, out = set(), []
    for text in parts:
        if not text:
            continue
        for m in MD_IMG_RE.finditer(text):
            url = m.group(1).strip()
            if url not in seen:
                seen.add(url); out.append(url)
        for m in IMG_URL_RE.finditer(text):
            url = m.group(1).strip()
            if url not in seen:
                seen.add(url); out.append(url)
    return out

def _strip_images(text: str) -> str:
    if not text:
        return ""
    text = MD_IMG_RE.sub("", text)
    text = IMG_URL_RE.sub("", text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ---------- Sentence/line helpers ----------
_LEADING_NOISE = re.compile(r'^[\W_]+', re.UNICODE)                # emojis/bullets/punct
_LABELS = re.compile(r'^(info|message|note|status)\s*[:\-]\s*', re.IGNORECASE)

def _normline_for_compare(s: str) -> str:
    s = (s or "").strip()
    s = _LEADING_NOISE.sub("", s)
    s = _LABELS.sub("", s)
    s = re.sub(r'[!\.\s]+$', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s.lower()

def _dedup_lines(lines: List[str]) -> List[str]:
    seen, out = set(), []
    for ln in lines:
        norm = _normline_for_compare(ln)
        if norm:
            if norm in seen: 
                continue
            seen.add(norm); out.append(ln)
        else:
            if not out or out[-1] != "":
                out.append("")
    while out and out[0] == "": out.pop(0)
    while out and out[-1] == "": out.pop()
    return out

_SENT_SPLIT = re.compile(r'(?<=[\.\!\?])\s+')

def _dedup_sentences_in_lines(lines: List[str]) -> List[str]:
    seen, out = set(), []
    for ln in lines:
        if not ln.strip():
            out.append(""); continue
        parts, kept = _SENT_SPLIT.split(ln), []
        for sent in parts:
            base = _normline_for_compare(sent)
            if not base: 
                continue
            if base in seen:
                continue
            seen.add(base); kept.append(sent)
        if kept:
            out.append(" ".join(kept))
    return _dedup_lines(out)

def _extract_first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln
    return ""

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
    try: json.loads(s); return True
    except Exception: return False

def _looks_yaml(s: str) -> bool:
    if not yaml: return False
    try:
        obj = yaml.safe_load(s)
        return isinstance(obj, (dict, list))
    except Exception:
        return False

# ---------- Detectors ----------
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

# ---------- Per-source formatters ----------
def _fmt_generic_like(title_label: str, title: str, body: str) -> Tuple[str, Optional[dict], List[str]]:
    # Stage 3: collect + strip
    all_imgs = _find_all_images(title, body)
    clean_title = _strip_images(title)
    clean_body  = _strip_images(body)

    facts = []
    first = _extract_first_nonempty_line(clean_body)
    if first: facts.append(_kv("Info", first))

    lines = _lines(
        _header(title_label),
        *facts,
    )

    body_lines = [ln.strip() for ln in clean_body.splitlines() if ln.strip()]
    combined = lines + ([""] if lines else []) + ([_section_title("Message")] if body_lines else []) + body_lines

    # Stage 6: sentence-level dedupe
    combined = _dedup_sentences_in_lines(combined)
    # Stage 7: echo first image back as Markdown so Gotify renders the actual image
    if all_imgs:
        combined += ["", "🖼️", f"![image]({all_imgs[0]})"]

    text   = "\n".join(combined).strip()
    extras = {"client::notification": {"bigImageUrl": all_imgs[0]}} if all_imgs else None
    return text, extras, all_imgs

def _fmt_sonarr(title: str, body: str):
    return _fmt_generic_like("Generic Message", title, body)

def _fmt_radarr(title: str, body: str):
    return _fmt_generic_like("Generic Message", title, body)

def _fmt_watchtower(title: str, body: str):
    # Keep short; still benefit from dedupe + echo
    return _fmt_generic_like("Watchtower Update", title, body)

def _fmt_speedtest(title: str, body: str):
    return _fmt_generic_like("Speedtest", title, body)

def _fmt_qnap(title: str, body: str):
    all_imgs = _find_all_images(title, body)
    clean = _strip_images(body)
    nas  = re.search(r'NAS Name:\s*(.+)', clean, re.I)
    when = re.search(r'(?:Date/Time|Date):\s*([^\n]+)', clean, re.I)
    facts = []
    if nas:  facts.append(_kv("NAS",  nas.group(1).strip()))
    if when: facts.append(_kv("Time", when.group(1).strip()))
    first = _extract_first_nonempty_line(clean)
    if first and not any(first in x for x in facts): facts.append(_kv("Info", first))
    lines = _lines(_header("QNAP Notice"), *facts, "", _section_title("Details"), clean)
    lines = _dedup_sentences_in_lines(lines)
    if all_imgs:
        lines += ["", "🖼️", f"![image]({all_imgs[0]})"]
    text   = "\n".join(lines).strip()
    extras = {"client::notification": {"bigImageUrl": all_imgs[0]}} if all_imgs else None
    return text, extras

def _fmt_unraid(title: str, body: str):
    all_imgs = _find_all_images(title, body)
    clean = _strip_images(body)
    first = _extract_first_nonempty_line(clean)
    facts = [_kv("Info", first)] if first else []
    lines = _lines(_header("Unraid Event"), *facts, "", _section_title("Details"), clean)
    lines = _dedup_sentences_in_lines(lines)
    if all_imgs:
        lines += ["", "🖼️", f"![image]({all_imgs[0]})"]
    text   = "\n".join(lines).strip()
    extras = {"client::notification": {"bigImageUrl": all_imgs[0]}} if all_imgs else None
    return text, extras

# ---------- Public entry ----------
def beautify_message(title: str, body: str, *, mood: str = "serious", source_hint: str | None = None) -> Tuple[str, Optional[dict]]:
    title = title or ""
    body  = body or ""

    # Super-short bodies → just show header + body
    if len(body.strip()) < 2 and not _find_all_images(title, body):
        out = _dedup_sentences_in_lines(_lines(_header("Message"), body.strip()))
        return "\n".join(out).strip(), None

    if source_hint == "sonarr" or _is_sonarr(title, body):
        text, extras, _ = _fmt_sonarr(title, body);   return text, extras
    if source_hint == "radarr" or _is_radarr(title, body):
        text, extras, _ = _fmt_radarr(title, body);   return text, extras
    if source_hint == "watchtower" or _is_watchtower(title, body):
        text, extras, _ = _fmt_watchtower(title, body); return text, extras
    if source_hint == "speedtest" or _is_speedtest(title, body):
        text, extras, _ = _fmt_speedtest(title, body);  return text, extras
    if source_hint == "qnap" or _is_qnap(title, body):
        return _fmt_qnap(title, body)
    if source_hint == "unraid" or _is_unraid(title, body):
        return _fmt_unraid(title, body)
    if _looks_json(body):
        # Compact JSON bullets, then echo image if any:
        text, extras, imgs = _fmt_generic_like("JSON Payload", title, body)
        return text, extras
    if _looks_yaml(body):
        text, extras, imgs = _fmt_generic_like("YAML Payload", title, body)
        return text, extras

    text, extras, _ = _fmt_generic_like("Generic Message", title, body)
    return text, extras
