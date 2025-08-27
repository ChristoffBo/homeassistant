# /app/beautify.py
from __future__ import annotations
import json, re
from typing import Tuple, Optional, List

try:
    import yaml
except Exception:
    yaml = None

# ---------- image discovery ----------
MD_IMG = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', re.I)
BARE_IMG = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)

LIKELY_POSTER_HOSTS = (
    "image.tmdb.org", "themoviedb.org", "tvdb.org", "trakt.tv",
    "fanart.tv", "githubusercontent.com", "gravatar.com"
)

def _all_image_urls(text: str) -> List[str]:
    if not text:
        return []
    urls = []
    urls += [m.group(1) for m in MD_IMG.finditer(text)]
    urls += [m.group(1) if hasattr(m, "group") else m for m in BARE_IMG.finditer(text)]
    # de-dupe, preserve order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def _best_image(urls: List[str]) -> Optional[str]:
    if not urls:
        return None
    # prefer “poster-ish” hosts
    for u in urls:
        try:
            from urllib.parse import urlparse
            host = urlparse(u).netloc.lower()
            if any(h in host for h in LIKELY_POSTER_HOSTS):
                return u
        except Exception:
            pass
    return urls[0]

def _strip_all_images(text: str) -> str:
    if not text:
        return ""
    # remove markdown images
    t = MD_IMG.sub("", text)
    # remove bare image urls
    t = BARE_IMG.sub("", t)
    # collapse excess whitespace
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

# ---------- text helpers ----------
def _extract_first_nonempty_line(s: str) -> str:
    for ln in (s or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln
    return ""

def _sentences(s: str) -> List[str]:
    # rough sentence splitter; good enough for dedupe
    s = s.replace("\r", "")
    parts = re.split(r'(?<=[.!?])\s+', s.strip())
    return [p.strip() for p in parts if p.strip()]

def _dedup_sentences(lines: List[str]) -> List[str]:
    seen = set()
    out = []
    for ln in lines:
        if not ln:
            if not out or out[-1] != "":
                out.append("")
            continue
        base = re.sub(r'\s+', ' ', ln.strip()).lower()
        if base not in seen:
            seen.add(base)
            out.append(ln)
    # trim leading/trailing blanks
    while out and out[0] == "": out.pop(0)
    while out and out[-1] == "": out.pop()
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

# ---------- Jarvis card helpers ----------
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

# ---------- source detectors ----------
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

# ---------- per-source formatters ----------
def _fmt_sonarr(title: str, body: str, hero_url: Optional[str]) -> Tuple[str, Optional[dict]]:
    clean = _strip_all_images(body)
    facts = []
    first = _extract_first_nonempty_line(clean)
    if first:
        facts.append(_kv("Info", first))

    # (Optional) timestamp-ish
    ts = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}.*\d{1,2}:\d{2})', clean)

    lines = _lines(_header("Generic Message"))
    if ts:
        lines.append(_kv("Time", ts.group(1)))
    lines += facts

    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]

    # sentence-level dedupe between facts and full body
    dedup_pool = _sentences(" ".join(facts))
    filtered_body = []
    for ln in body_lines:
        keep = True
        for s in _sentences(ln):
            if s in dedup_pool:
                keep = False
                break
        if keep:
            filtered_body.append(ln)

    combined = _dedup_sentences(lines + ([""] if lines else []) +
                                ([_section_title("Message")] if filtered_body else []) +
                                filtered_body)

    # append image as markdown (Web UI shows real image with markdown content type)
    if hero_url:
        combined += ["", f"![]({hero_url})"]

    text = "\n".join(combined).strip()
    extras = {
        "client::display": {"contentType": "text/markdown"}
    }
    if hero_url:
        extras["client::notification"] = {"bigImageUrl": hero_url}
    return text, extras

def _fmt_radarr(title: str, body: str, hero_url: Optional[str]) -> Tuple[str, Optional[dict]]:
    clean = _strip_all_images(body)
    facts = []
    first = _extract_first_nonempty_line(clean)
    if first:
        facts.append(_kv("Info", first))

    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]

    dedup_pool = _sentences(" ".join(facts))
    filtered_body = []
    for ln in body_lines:
        keep = True
        for s in _sentences(ln):
            if s in dedup_pool:
                keep = False
                break
        if keep:
            filtered_body.append(ln)

    combined = _dedup_sentences(_lines(_header("Generic Message"),
                                       *facts,
                                       "",
                                       _section_title("Message"),
                                       *filtered_body))

    if hero_url:
        combined += ["", f"![]({hero_url})"]

    text = "\n".join(combined).strip()
    extras = {"client::display": {"contentType": "text/markdown"}}
    if hero_url:
        extras["client::notification"] = {"bigImageUrl": hero_url}
    return text, extras

def _fmt_watchtower(title: str, body: str, hero_url: Optional[str]) -> Tuple[str, Optional[dict]]:
    clean = _strip_all_images(body)
    facts = []
    low = clean.lower()
    if "no new images" in low: facts.append("• All containers up-to-date")
    if "updated" in low:       facts.append("• Containers updated")
    combined = _dedup_sentences(_lines(_header("Watchtower Update"), *facts))
    if not facts:
        combined += ["", _section_title("Report"), clean]
    if hero_url:
        combined += ["", f"![]({hero_url})"]
    text = "\n".join(combined).strip()
    extras = {"client::display": {"contentType": "text/markdown"}}
    if hero_url:
        extras["client::notification"] = {"bigImageUrl": hero_url}
    return text, extras

def _fmt_speedtest(title: str, body: str, hero_url: Optional[str]) -> Tuple[str, Optional[dict]]:
    clean = _strip_all_images(body)
    dl = re.search(r'down(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    ul = re.search(r'up(?:load)?\D+([\d.]+)\s*([A-Za-z]+)', clean, re.I)
    pg = re.search(r'ping\D+([\d.]+)\s*ms', clean, re.I)
    facts = []
    if pg: facts.append(_kv("Ping", f"{pg.group(1)} ms"))
    if dl: facts.append(_kv("Down", f"{dl.group(1)} {dl.group(2)}"))
    if ul: facts.append(_kv("Up", f"{ul.group(1)} {ul.group(2)}"))
    combined = _dedup_sentences(_lines(_header("Speedtest"), *facts))
    if not facts:
        combined += ["", _section_title("Raw"), clean]
    if hero_url:
        combined += ["", f"![]({hero_url})"]
    text = "\n".join(combined).strip()
    extras = {"client::display": {"contentType": "text/markdown"}}
    if hero_url:
        extras["client::notification"] = {"bigImageUrl": hero_url}
    return text, extras

def _fmt_qnap(title: str, body: str, hero_url: Optional[str]) -> Tuple[str, Optional[dict]]:
    clean = _strip_all_images(body)
    nas  = re.search(r'NAS Name:\s*(.+)', clean, re.I)
    when = re.search(r'(?:Date/Time|Date):\s*([^\n]+)', clean, re.I)
    facts = []
    if nas:  facts.append(_kv("NAS", nas.group(1).strip()))
    if when: facts.append(_kv("Time", when.group(1).strip()))

    # details (dedup sentences)
    details = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    combined = _dedup_sentences(_lines(_header("QNAP Notice"), *facts))
    if details:
        combined += ["", _section_title("Details"), *details]
    if hero_url:
        combined += ["", f"![]({hero_url})"]

    text = "\n".join(combined).strip()
    extras = {"client::display": {"contentType": "text/markdown"}}
    if hero_url:
        extras["client::notification"] = {"bigImageUrl": hero_url}
    return text, extras

def _fmt_unraid(title: str, body: str, hero_url: Optional[str]) -> Tuple[str, Optional[dict]]:
    clean = _strip_all_images(body)
    first = _extract_first_nonempty_line(clean)
    facts = [_kv("Info", first)] if first else []
    combined = _dedup_sentences(_lines(_header("Unraid Event"), *facts, "", _section_title("Details"), clean))
    if hero_url:
        combined += ["", f"![]({hero_url})"]
    text = "\n".join(combined).strip()
    extras = {"client::display": {"contentType": "text/markdown"}}
    if hero_url:
        extras["client::notification"] = {"bigImageUrl": hero_url}
    return text, extras

def _fmt_generic(title: str, body: str, hero_url: Optional[str]) -> Tuple[str, Optional[dict]]:
    clean = _strip_all_images(body)
    facts = []
    first = _extract_first_nonempty_line(clean)
    if first:
        facts.append(_kv("Info", first))

    body_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]

    # sentence-level dedupe
    dedup_pool = _sentences(" ".join(facts))
    filtered_body = []
    for ln in body_lines:
        keep = True
        for s in _sentences(ln):
            if s in dedup_pool:
                keep = False
                break
        if keep:
            filtered_body.append(ln)

    combined = _dedup_sentences(_lines(_header("Generic Message"),
                                       *facts,
                                       "",
                                       _section_title("Message"),
                                       *filtered_body))
    if hero_url:
        combined += ["", f"![]({hero_url})"]

    text = "\n".join(combined).strip()
    extras = {"client::display": {"contentType": "text/markdown"}}
    if hero_url:
        extras["client::notification"] = {"bigImageUrl": hero_url}
    return text, extras

# ---------- public entry ----------
def beautify_message(title: str, body: str, *, mood: str = "serious", source_hint: str | None = None) -> Tuple[str, Optional[dict]]:
    title = title or ""
    body  = body or ""

    # Collect images from both title & body and pick one hero image
    imgs  = _all_image_urls(title) + _all_image_urls(body)
    hero  = _best_image(imgs)

    # Very tiny payload, no images → short card
    if len(body.strip()) < 2 and not hero:
        txt = "\n".join(_dedup_sentences(_lines(_header("Message"), body))).strip()
        extras = {"client::display": {"contentType": "text/markdown"}}
        return txt, extras

    if source_hint == "sonarr" or _is_sonarr(title, body):
        return _fmt_sonarr(title, body, hero)
    if source_hint == "radarr" or _is_radarr(title, body):
        return _fmt_radarr(title, body, hero)
    if source_hint == "watchtower" or _is_watchtower(title, body):
        return _fmt_watchtower(title, body, hero)
    if source_hint == "speedtest" or _is_speedtest(title, body):
        return _fmt_speedtest(title, body, hero)
    if source_hint == "qnap" or _is_qnap(title, body):
        return _fmt_qnap(title, body, hero)
    if source_hint == "unraid" or _is_unraid(title, body):
        return _fmt_unraid(title, body, hero)
    if _looks_json(body):
        # JSON/YAML formatters don’t append image; still enable markdown rendering
        txt, ex = _fmt_generic(title, body, hero)
        if ex is None: ex = {}
        ex.setdefault("client::display", {"contentType": "text/markdown"})
        return txt, ex
    if _looks_yaml(body):
        txt, ex = _fmt_generic(title, body, hero)
        if ex is None: ex = {}
        ex.setdefault("client::display", {"contentType": "text/markdown"})
        return txt, ex

    return _fmt_generic(title, body, hero)
