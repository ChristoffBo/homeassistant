#!/usr/bin/env python3
"""
Neural Core (rules-first, optional local GGUF via ctransformers)

- Useful first: extract real fields from Sonarr/Radarr/APT/Host messages.
- Personality-forward: mood-shaded bullets; profanity optional.
- Longer when needed (≤10 lines, ≤160 chars/line), but still tidy.
- Never invents facts; preserves real links/posters.

Config (either env vars or /data/options.json keys):
  PERSONALITY_ALLOW_PROFANITY: "true"/"false"  (key: personality_allow_profanity)
  LLM_EXTRA_BULLET: "true"/"false"            (default false)
  LLM_DETAIL_LEVEL: "rich" or "normal"        (default rich)

This module does NOT require changes to bot.py; it reads config itself.
"""

from __future__ import annotations
import os, re, json
from pathlib import Path
from typing import Optional, Dict, List

# ---------------- Tunables ----------------
USE_LLM_EXTRA_BULLET = os.getenv("LLM_EXTRA_BULLET", "0").lower() in ("1", "true", "yes")
DETAIL_LEVEL = os.getenv("LLM_DETAIL_LEVEL", "rich").lower()
MAX_LINES = 10 if DETAIL_LEVEL == "rich" else 6
MAX_LINE_CHARS = 160

_MODEL = None
_MODEL_PATH: Optional[Path] = None


# ---------------- Config helpers ----------------
def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

def _cfg_allow_profanity() -> bool:
    """Order: env > /data/options.json > default False."""
    env = os.getenv("PERSONALITY_ALLOW_PROFANITY")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return bool(cfg.get("personality_allow_profanity", False))
    except Exception:
        return False


# ---------------- Optional model load (GGUF) ----------------
def _resolve_model_path(model_path: str) -> Path:
    if model_path:
        p = Path(os.path.expandvars(model_path.strip()))
        if p.exists():
            return p
    base = Path("/share/jarvis_prime/models")
    if base.exists():
        ggufs = sorted(base.glob("*.gguf"))
        if ggufs:
            return ggufs[0]
    raise FileNotFoundError(
        f"No GGUF model at '{model_path}' and no fallback in /share/jarvis_prime/models"
    )

def _load_model(path: Path):
    global _MODEL, _MODEL_PATH
    if _MODEL is not None and _MODEL_PATH == path:
        return
    try:
        from ctransformers import AutoModelForCausalLM
    except Exception as e:
        print(f"[Neural Core] ctransformers not available: {e}")
        return
    print(f"[Neural Core] Loading model: {path} (size={path.stat().st_size} bytes)")
    _MODEL = AutoModelForCausalLM.from_pretrained(
        str(path.parent),
        model_file=path.name,
        model_type="llama",
        gpu_layers=0,
    )
    _MODEL_PATH = path
    print("[Neural Core] Model ready")


# ---------------- Text utils ----------------
def _cut(s: str, n: int) -> str:
    s = (s or "").strip()
    return (s[: n - 1] + "…") if len(s) > n else s

# profanity scrub used only when profanity is NOT allowed
_PROF_RE = re.compile(
    r"\b(fuck|f\*+k|f\W?u\W?c\W?k|shit|bitch|cunt|asshole|motherf\w+|dick|prick|whore)\b",
    re.I,
)
def _clean_if_needed(text: str, allow_profanity: bool) -> str:
    return text if allow_profanity else _PROF_RE.sub("—", text or "")

def _dedupe(lines: List[str], limit: int) -> List[str]:
    out, seen = [], set()
    for ln in lines:
        ln = (ln or "").strip()
        if not ln:
            continue
        k = ln.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(_cut(ln, MAX_LINE_CHARS))
        if len(out) >= limit:
            break
    return out


# ---------------- Light extraction ----------------
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"https?://\S+", re.I)

def _links(text: str) -> List[str]:
    return URL_RE.findall(text or "")[:4]

def _kv(text: str, key: str) -> Optional[str]:
    pat = re.compile(rf"{key}\s*[:=]\s*(.+?)(?:[,;\n]|$)", re.I)
    m = pat.search(text or "")
    return m.group(1).strip() if m else None

def _kv_any(text: str, *keys: str) -> Optional[str]:
    for k in keys:
        v = _kv(text, k)
        if v:
            return v
    return None

def _num_after(text: str, word: str) -> Optional[str]:
    m = re.search(rf"{word}\s*[:=]?\s*(\d+)\b", text or "", re.I)
    return m.group(1) if m else None

def _list_after(text: str, label: str) -> List[str]:
    m = re.search(rf"{label}\s*[:=]\s*(.+)$", text or "", re.I | re.M)
    if not m:
        return []
    raw = m.group(1)
    parts = re.split(r"[;,•\u2022]\s+|\s{2,}|\s-\s", raw)
    return [p.strip() for p in parts if p.strip()][:12]

def _errors(text: str) -> List[str]:
    out = []
    for ln in (text or "").splitlines():
        if re.search(r"\b(error|failed|failure|timeout|unavailable|not\s+available|down)\b", ln, re.I):
            out.append(ln.strip())
            if len(out) >= 4:
                break
    return out

def _first_line(text: str) -> str:
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


# ---------------- Extractors ----------------
def _extract_common(text: str) -> Dict[str, object]:
    return {
        "poster": _kv_any(text, "poster", "image", "cover") or "",
        "links": _links(text),
        "ips": IP_RE.findall(text or "")[:4],
        "errors": _errors(text),
        "host": _kv_any(text, "host") or "",
        "title": _kv_any(text, "title") or "",
    }

def _extract_sonarr(text: str) -> Dict[str, object]:
    d = _extract_common(text)
    d.update({
        "event": _kv_any(text, "event") or ("episode downloaded" if "download" in (text or "").lower() else ""),
        "show": _kv_any(text, "show", "tv show") or "",
        "season": _num_after(text, "season") or "",
        "episode": _num_after(text, "episode") or "",
        "ep_title": _kv_any(text, "episode title", "title") or "",
        "quality": _kv_any(text, "quality") or "",
        "size": _kv_any(text, "size") or "",
        "release": _kv_any(text, "release group", "group") or "",
        "path": _kv_any(text, "path", "folder", "library path") or "",
        "indexer": _kv_any(text, "indexer") or "",
    })
    return d

def _extract_radarr(text: str) -> Dict[str, object]:
    d = _extract_common(text)
    d.update({
        "event": _kv_any(text, "event") or ("movie downloaded" if "download" in (text or "").lower() else ""),
        "movie": _kv_any(text, "movie", "film") or "",
        "year": _num_after(text, "year") or "",
        "quality": _kv_any(text, "quality") or "",
        "size": _kv_any(text, "size") or "",
        "release": _kv_any(text, "release group", "group") or "",
        "path": _kv_any(text, "path", "folder", "library path") or "",
        "indexer": _kv_any(text, "indexer") or "",
        "runtime": _kv_any(text, "runtime") or "",
    })
    return d

def _extract_apt(text: str) -> Dict[str, object]:
    d = _extract_common(text)
    if not d["host"]:
        d["host"] = (d["ips"][0] if d["ips"] else "")
    d.update({
        "finished": bool(re.search(r"\bapt\b.*\b(maintenance|update).*(finished|done|complete)", text or "", re.I)),
        "upgraded": _kv_any(text, "packages upgraded", "package(s) upgraded", "upgraded") or "",
        "reboot": bool(re.search(r"\breboot\s+required\b", text or "", re.I)),
        "kernel": _kv_any(text, "kernel") or "",
        "notes": _list_after(text, "notes"),
        "pkg_list": _list_after(text, "packages") or _list_after(text, "upgraded packages"),
    })
    return d

def _extract_host_status(text: str) -> Dict[str, object]:
    d = _extract_common(text)
    m = re.search(r"CPU\s*Load.*?:\s*([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)", text or "", re.I)
    d["cpu_load"] = m.groups() if m else ()
    m = re.search(r"Memory:\s*([\d\.]+\wB)\s+total,\s*([\d\.]+\wB)\s+used", text or "", re.I)
    d["mem"] = m.groups() if m else ()
    m = re.search(r"Disk\s*\(/.*?\):\s*([\d\.]+\w?)\s+total,\s*([\d\.]+\w?)\s+used.*?(\d+%|\d+\s*%|[\d\.]+\w?\s+free)", text or "", re.I)
    d["disk"] = m.groups() if m else ()
    d["services_up"] = len(re.findall(r"\bUp\s+\d+\s+(?:day|days|h|hours|m|min|minutes)", text or "", re.I))
    return d


# ---------------- Mood styling ----------------
def _bullet_for(mood: str) -> str:
    return {
        "serious": "•",
        "sarcastic": "😏",
        "playful": "✨",
        "hacker-noir": "▣",
        "angry": "⚡",
    }.get(mood, "•")

def _suffix(mood: str, allow_profanity: bool) -> str:
    if mood == "angry":
        return " Done." if not allow_profanity else " Done. No BS."
    if mood == "sarcastic":
        return " Noted." if not allow_profanity else " Obviously."
    if mood == "playful":
        return " Neat!" if not allow_profanity else " Heck yes!"
    if mood == "hacker-noir":
        return " Logged."
    return ""


# ---------------- Renderers ----------------
def _render_sonarr(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_sonarr(text)
    out: List[str] = []
    if d["show"]:
        se = ""
        if d["season"]: se += f"S{d['season']}"
        if d["episode"]: se += f"E{d['episode']}"
        label = f"{d['show']} — {se}" if se else d["show"]
        out.append(f"{b} 📺 {label}")
    if d["ep_title"]:
        out.append(f"{b} 🧾 {_cut(d['ep_title'], 150)}")
    if d["quality"] or d["size"]:
        combo = " | ".join(x for x in [d['quality'], d['size']] if x)
        out.append(f"{b} 🎚️ {combo}")
    if d["release"]:
        out.append(f"{b} 🏷️ {d['release']}")
    if d["path"]:
        out.append(f"{b} 📂 {_cut(d['path'], 150)}")
    if d["indexer"]:
        out.append(f"{b} 🕵️ Indexer: {d['indexer']}")
    if d["poster"]:
        out.append(f"{b} 🖼️ Poster: {d['poster']}")
    if d["links"]:
        out.append(f"{b} 🔗 {d['links'][0]}")
    if d["errors"]:
        out.append(f"{b} ⚠️ {_cut('; '.join(d['errors']), 150)}")
    if d["event"]:
        tail = _suffix(mood, allow_profanity)
        out.append(f"{b} ✅ {d['event'].capitalize()}.{tail}")
    else:
        tail = _suffix(mood, allow_profanity)
        out.append(f"{b} ✅ Added to library.{tail}")
    return out

def _render_radarr(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_radarr(text)
    out: List[str] = []
    title = " ".join(x for x in [d["movie"], f"({d['year']})" if d["year"] else ""] if x).strip()
    if title:
        out.append(f"{b} 🎬 {title}")
    if d["quality"] or d["size"]:
        combo = " | ".join(x for x in [d['quality'], d['size']] if x)
        out.append(f"{b} 🎚️ {combo}")
    if d["release"]:
        out.append(f"{b} 🏷️ {d['release']}")
    if d["runtime"]:
        out.append(f"{b} ⏱️ {d['runtime']}")
    if d["path"]:
        out.append(f"{b} 📂 {_cut(d['path'], 150)}")
    if d["indexer"]:
        out.append(f"{b} 🕵️ Indexer: {d['indexer']}")
    if d["poster"]:
        out.append(f"{b} 🖼️ Poster: {d['poster']}")
    if d["links"]:
        out.append(f"{b} 🔗 {d['links'][0]}")
    if d["errors"]:
        out.append(f"{b} ⚠️ {_cut('; '.join(d['errors']), 150)}")
    tail = _suffix(mood, allow_profanity)
    out.append(f"{b} ✅ Library updated.{tail}")
    return out

def _render_apt(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_apt(text)
    out: List[str] = []
    host = d["host"] or (d["ips"][0] if d["ips"] else "")
    if host:
        out.append(f"{b} 🛠️ APT maintenance finished on {host}")
    else:
        out.append(f"{b} 🛠️ APT maintenance finished")
    if d["upgraded"]:
        out.append(f"{b} 📦 Packages upgraded: {d['upgraded']}")
    if d["pkg_list"]:
        out.append(f"{b} 📦 {_cut(', '.join(d['pkg_list']), 150)}")
    if d["kernel"]:
        out.append(f"{b} 🧬 Kernel: {d['kernel']}")
    if d["reboot"]:
        out.append(f"{b} 🔁 Reboot required")
    if d["errors"]:
        out.append(f"{b} ⚠️ {_cut('; '.join(d['errors']), 150)}")
    if d["links"]:
        out.append(f"{b} 🔗 {d['links'][0]}")
    tail = _suffix(mood, allow_profanity)
    out.append(f"{b} ✅ System ready.{tail}")
    return out

def _render_host_status(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_host_status(text)
    out: List[str] = []
    if d["cpu_load"]:
        out.append(f"{b} 🧮 Load(1/5/15): {'/'.join(d['cpu_load'])}")
    if d["mem"]:
        out.append(f"{b} 🧠 Mem: total {d['mem'][0]}, used {d['mem'][1]}")
    if d["disk"]:
        out.append(f"{b} 💽 Root: total {d['disk'][0]}, used {d['disk'][1]}, free {d['disk'][2]}")
    if d["services_up"]:
        out.append(f"{b} 🧩 Services up: ~{d['services_up']}")
    if d["errors"]:
        out.append(f"{b} ⚠️ {_cut('; '.join(d['errors']), 150)}")
    tail = _suffix(mood, allow_profanity)
    out.append(f"{b} ✅ Host healthy.{tail}")
    return out

def _render_generic(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_common(text)
    out: List[str] = []
    first = _first_line(text)
    if first:
        out.append(f"{b} {_cut(first, 150)}")
    if d["host"]:
        out.append(f"{b} 🖥️ Host: {d['host']}")
    if d["ips"]:
        out.append(f"{b} 🌐 IP: {d['ips'][0]}")
    if d["errors"]:
        out.append(f"{b} ⚠️ {_cut('; '.join(d['errors']), 150)}")
    if d["poster"]:
        out.append(f"{b} 🖼️ Poster: {d['poster']}")
    if d["links"]:
        out.append(f"{b} 🔗 {d['links'][0]}")
    tail = _suffix(mood, allow_profanity)
    out.append(f"{b} ✅ Noted.{tail}")
    return out


# ---------------- Optional: 1 concise LLM bullet ----------------
def _llm_extra(text: str, mood: str, allow_profanity: bool) -> List[str]:
    if not USE_LLM_EXTRA_BULLET or _MODEL is None:
        return []
    try:
        tone = {
            "serious": "concise",
            "sarcastic": "dry",
            "playful": "friendly",
            "hacker-noir": "terse",
            "angry": "blunt",
        }.get(mood, "concise")
        prompt = (
            "Write ONE ultra-short bullet (<=160 chars) summarizing the MESSAGE. "
            "No hallucinations. "
            + ("Profanity ok if natural.\n" if allow_profanity else "No profanity.\n")
            + f"Tone: {tone}\nMESSAGE:\n{text}\nBullet:\n• "
        )
        out = _MODEL(prompt, max_new_tokens=120, temperature=0.2, top_p=0.9)
        line = str(out).strip()
        line = re.sub(r"^(bullet:|message:)\s*", "", line, flags=re.I).strip()
        if not line:
            return []
        return [f"{_bullet_for(mood)} {_cut(line, MAX_LINE_CHARS)}"]
    except Exception as e:
        print(f"[Neural Core] Extra bullet error: {e}")
        return []


# ---------------- Public API ----------------
def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 5,
    cpu_limit: int = 70,
    models_priority=None,
    base_url: str = "",
    model_path: str = "",
) -> str:
    """
    Returns a personality-forward, factual summary.
    On error, returns the original text (failsafe).
    """
    text = text or ""
    allow_profanity = _cfg_allow_profanity()

    # Optional local model load (not required)
    try:
        path = _resolve_model_path(model_path)
        _load_model(path)
    except Exception as e:
        print(f"[Neural Core] Model optional: {e}")

    try:
        tlow = text.lower()
        if "sonarr" in tlow:
            lines = _render_sonarr(text, mood, allow_profanity)
        elif "radarr" in tlow:
            lines = _render_radarr(text, mood, allow_profanity)
        elif "apt" in tlow or "maintenance" in tlow:
            # heuristics: if message looks like host stats, use host renderer
            if "cpu load" in tlow or "memory:" in tlow:
                lines = _render_host_status(text, mood, allow_profanity)
            else:
                lines = _render_apt(text, mood, allow_profanity)
        elif "cpu load" in tlow or "memory:" in tlow or "docker:" in tlow:
            lines = _render_host_status(text, mood, allow_profanity)
        else:
            lines = _render_generic(text, mood, allow_profanity)

        # Optional single AI bullet
        lines.extend(_llm_extra(text, mood, allow_profanity))

        # Final tidy
        lines = _dedupe(lines, MAX_LINES)
        out = "\n".join(lines) if lines else text
        return _clean_if_needed(out, allow_profanity)
    except Exception as e:
        print(f"[Neural Core] Compose error: {e}")
        return _clean_if_needed(text, allow_profanity)
