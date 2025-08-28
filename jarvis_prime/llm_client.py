#!/usr/bin/env python3
"""
Neural Core (rules-first, optional local GGUF via ctransformers)

- Extract real facts from Sonarr/Radarr/APT/Host messages.
- Mood-forward bullets with variety (no repetitive closers).
- Falls back to Generic if Sonarr/Radarr fields are missing.
- Profanity optional (reads personality_allow_profanity from /data/options.json or env).
- Always appends an engine footer so you know if Neural Core fired.
"""

from __future__ import annotations
import os, re, json, hashlib
from pathlib import Path
from typing import Optional, Dict, List

USE_LLM_EXTRA_BULLET = os.getenv("LLM_EXTRA_BULLET", "0").lower() in ("1", "true", "yes")
DETAIL_LEVEL = os.getenv("LLM_DETAIL_LEVEL", "rich").lower()
MAX_LINES = 10 if DETAIL_LEVEL == "rich" else 6
MAX_LINE_CHARS = 160

_MODEL = None
_MODEL_PATH: Optional[Path] = None

# ---------- Config ----------
def _cfg_allow_profanity() -> bool:
    env = os.getenv("PERSONALITY_ALLOW_PROFANITY")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return bool(cfg.get("personality_allow_profanity", False))
    except Exception:
        return False

# ---------- Optional model load ----------
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
    raise FileNotFoundError("No GGUF model found")

def _load_model(path: Path):
    global _MODEL, _MODEL_PATH
    if _MODEL is not None and _MODEL_PATH == path:
        return
    try:
        from ctransformers import AutoModelForCausalLM
    except Exception as e:
        print(f"[Neural Core] ctransformers not available: {e}")
        return
    print(f"[Neural Core] Loading model: {path}")
    _MODEL = AutoModelForCausalLM.from_pretrained(
        str(path.parent), model_file=path.name, model_type="llama", gpu_layers=0
    )
    _MODEL_PATH = path
    print("[Neural Core] Model ready")

# ---------- Utils ----------
def _cut(s: str, n: int) -> str:
    s = (s or "").strip()
    return (s[: n - 1] + "…") if len(s) > n else s

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

def _variety(seed: str, options: List[str]) -> str:
    if not options:
        return ""
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]

# ---------- Light extraction ----------
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

# ---------- Extractors ----------
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

# ---------- Mood ----------
def _normalize_mood(mood: str) -> str:
    """Map many personalities to the core renderer set so everything 'oozes' a tone."""
    m = (mood or "serious").strip().lower()
    table = {
        "ai": "serious",
        "calm": "serious",
        "tired": "serious",
        "depressed": "serious",
        "excited": "playful",
        "happy": "playful",
        "playful": "playful",
        "sarcastic": "sarcastic",
        "snarky": "sarcastic",
        "angry": "angry",
        "hacker-noir": "hacker-noir",
        "noir": "hacker-noir",
        "serious": "serious",
    }
    return table.get(m, "serious")

def _bullet_for(mood: str) -> str:
    return {
        "serious": "•",
        "sarcastic": "😏",
        "playful": "✨",
        "hacker-noir": "▣",
        "angry": "⚡",
    }.get(mood, "•")

def _closer(mood: str, seed: str, allow_profanity: bool) -> str:
    choices = {
        "angry": ["Done.", "Done. No BS.", "Handled.", "We’re good."],
        "sarcastic": ["Noted.", "Obviously.", "Ground-breaking.", "Shocking."],
        "playful": ["Neat!", "Nice!", "All set!", "Wrapped!"],
        "hacker-noir": ["Logged.", "Filed.", "In the ledger.", "Trace saved."],
        "serious": ["Complete.", "All set.", "OK.", "Done."],
    }.get(mood, ["Done."])
    line = _variety(seed, choices)
    if allow_profanity and mood == "angry":
        line = _variety(seed, ["Done. No BS.", "Done."])
    return line

# ---------- Renderers ----------
def _render_generic(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    out: List[str] = []
    first = _first_line(text)
    if first:
        out.append(f"{b} {_cut(first, 150)}")
    out.append(f"{b} ✅ Noted. {_closer(mood, text, allow_profanity)}")
    return out

def _render_sonarr(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_sonarr(text)
    strong = bool(d["show"] or (d["season"] and d["episode"]) or d["path"])
    if not strong:
        return _render_generic(text, mood, allow_profanity)
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
        combo = " ".join(x for x in [d['quality'], d['size']] if x)
        out.append(f"{b} 🎚️ {combo}")
    if d["release"]:
        out.append(f"{b} 🏷️ {d['release']}")
    if d["path"]:
        out.append(f"{b} 📂 {_cut(d['path'], 150)}")
    if d["indexer"]:
        out.append(f"{b} 🕵️ Indexer: {d['indexer']}")
    if d["poster"]:
        out.append(f"{b} 🖼️ {d['poster']}")
    if d["links"]:
        out.append(f"{b} 🔗 {d['links'][0]}")
    if d["errors"]:
        out.append(f"{b} ⚠️ {_cut('; '.join(d['errors']), 150)}")
    tail = _closer(mood, text, allow_profanity)
    out.append(f"{b} ✅ {d['event'].capitalize() if d['event'] else 'Processed.'} {tail}")
    return out

def _render_radarr(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_radarr(text)
    if not (d["movie"] or d["path"]):
        return _render_generic(text, mood, allow_profanity)
    out: List[str] = []
    title = " ".join(x for x in [d["movie"], f"({d['year']})" if d["year"] else ""] if x).strip()
    if title:
        out.append(f"{b} 🎬 {title}")
    if d["quality"] or d["size"]:
        combo = " ".join(x for x in [d["quality"], d["size"]] if x)
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
        out.append(f"{b} 🖼️ {d['poster']}")
    if d["links"]:
        out.append(f"{b} 🔗 {d['links'][0]}")
    if d["errors"]:
        out.append(f"{b} ⚠️ {_cut('; '.join(d['errors']), 150)}")
    out.append(f"{b} ✅ Library updated. {_closer(mood, text, allow_profanity)}")
    return out

def _render_apt(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    d = _extract_apt(text)
    out: List[str] = []
    host = d["host"] or (d["ips"][0] if d["ips"] else "")
    out.append(f"{b} 🛠️ APT maintenance finished" + (f" on {host}" if host else ""))
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
    out.append(f"{b} ✅ System ready. {_closer(mood, text, allow_profanity)}")
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
    out.append(f"{b} ✅ Host healthy. {_closer(mood, text, allow_profanity)}")
    return out

# ---------- Optional: one concise LLM bullet ----------
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

# ---------- Public API ----------
def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 5,
    cpu_limit: int = 70,
    models_priority=None,
    base_url: str = "",
    model_path: str = "",
) -> str:
    text = text or ""
    allow_profanity = _cfg_allow_profanity()
    mood = _normalize_mood(mood)

    # Optional local model load (non-blocking to main I/O)
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
            if "cpu load" in tlow or "memory:" in tlow or "docker:" in tlow:
                lines = _render_host_status(text, mood, allow_profanity)
            else:
                lines = _render_apt(text, mood, allow_profanity)
        elif "cpu load" in tlow or "memory:" in tlow or "docker:" in tlow:
            lines = _render_host_status(text, mood, allow_profanity)
        else:
            lines = _render_generic(text, mood, allow_profanity)

        lines.extend(_llm_extra(text, mood, allow_profanity))
        lines = _dedupe(lines, MAX_LINES)
        out = "\n".join(lines) if lines else text
        return _clean_if_needed(out, allow_profanity) + "\n[Neural Core ✓]"
    except Exception as e:
        print(f"[Neural Core] Compose error: {e}")
        return _clean_if_needed(text, allow_profanity) + "\n[Beautify fallback]"
