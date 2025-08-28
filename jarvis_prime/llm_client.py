#!/usr/bin/env python3
"""
Neural Core (local GGUF via ctransformers)

Targets:
- Preserve real facts (Show/Movie, S/E, Poster, Links, Errors)
- Output ≤5 short bullets (≤120 chars each)
- Light mood personality (no profanity, no insults)
- Deterministic-ish (low temperature)
"""

import os
import re
from pathlib import Path
from typing import Optional, Dict, List

_MODEL = None
_MODEL_PATH: Optional[Path] = None

# --------------------------
# Model resolve/load
# --------------------------
def _resolve_model_path(model_path: str) -> Path:
    """Return an existing GGUF path or first *.gguf in /share/jarvis_prime/models."""
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
        f"No GGUF model found at '{model_path}' and no fallback in /share/jarvis_prime/models"
    )

def _load_model(path: Path):
    """Load the GGUF model once."""
    global _MODEL, _MODEL_PATH
    if _MODEL is not None and _MODEL_PATH == path:
        return
    print(f"[Neural Core] Loading model: {path} (size={path.stat().st_size} bytes)")
    from ctransformers import AutoModelForCausalLM
    _MODEL = AutoModelForCausalLM.from_pretrained(
        str(path.parent),
        model_file=path.name,
        model_type="llama",
        gpu_layers=0,  # CPU-friendly
    )
    _MODEL_PATH = path
    print("[Neural Core] Model ready")

# --------------------------
# Light fact extraction to reduce hallucination
# --------------------------
_LINK_RE = re.compile(r"https?://\S+", re.I)
def _links(text: str) -> List[str]:
    return _LINK_RE.findall(text or "")[:5]

def _kv(text: str, key: str) -> Optional[str]:
    pat = re.compile(rf"{key}\s*[:=]\s*(.+?)(?:[,;\n]|$)", re.I)
    m = pat.search(text or "")
    return m.group(1).strip() if m else None

def _num_after(text: str, word: str) -> Optional[str]:
    m = re.search(rf"{word}\s*[:=]?\s*(\d+)\b", text or "", re.I)
    return m.group(1) if m else None

def _errors(text: str) -> List[str]:
    out = []
    for line in (text or "").splitlines():
        ll = line.strip()
        if re.search(r"\b(error|failed|unavailable|not\s+available|timeout|down)\b", ll, re.I):
            out.append(ll)
        if len(out) >= 2:
            break
    return out

def _extract(text: str) -> Dict[str, str]:
    d: Dict[str, str] = {}
    d["show"] = _kv(text, "show") or _kv(text, "tv show") or ""
    d["movie"] = _kv(text, "movie") or ""
    d["poster"] = _kv(text, "poster") or _kv(text, "image") or _kv(text, "cover") or ""
    d["season"] = _num_after(text, "season") or ""
    d["episode"] = _num_after(text, "episode") or ""
    d["links"] = _links(text)
    errs = _errors(text)
    d["errors"] = errs
    return d

# --------------------------
# Clean-up & safety
# --------------------------
_PROF_RE = re.compile(
    r"\b(fuck|f\*+k|f\W?u\W?c\W?k|shit|bitch|cunt|asshole|motherf\w+|dick|prick|whore)\b",
    re.I,
)
def _strip_profane(text: str) -> str:
    return _PROF_RE.sub("—", text)

def _cut(s: str, n: int) -> str:
    return (s[: n - 1] + "…") if len(s) > n else s

def _dedupe(lines: List[str], limit: int) -> List[str]:
    out, seen = [], set()
    for ln in lines:
        k = ln.strip().lower()
        if k and k not in seen:
            seen.add(k); out.append(ln.strip())
        if len(out) >= limit:
            break
    return out

# --------------------------
# Mood styling
# --------------------------
def _bullet_for(mood: str) -> str:
    return {
        "serious": "•",
        "sarcastic": "😏",
        "playful": "✨",
        "hacker-noir": "▣",
        "angry": "⚡",
    }.get(mood, "•")

# --------------------------
# Prompt + inference (for 1–2 extra summary bullets)
# --------------------------
def _build_prompt(text: str, mood: str, facts: Dict[str, str]) -> str:
    tone = {
        "serious": "serious and concise",
        "sarcastic": "dry and witty (never rude)",
        "playful": "light and friendly",
        "hacker-noir": "terse and stylish",
        "angry": "blunt but professional",
    }.get(mood, "serious and concise")

    return (
        "You are Jarvis Prime's Neural Core.\n"
        "Rewrite the MESSAGE into 1-2 ultra-short bullets (≤120 chars each).\n"
        "Rules: preserve real details only; no fluff; no profanity; no insults.\n"
        f"Tone: {tone}.\n"
        f"Facts (may be empty): {facts}\n"
        "MESSAGE:\n"
        f"{text}\n"
        "Bullets:\n"
        "• "
    )

def _llm_bullets(text: str, mood: str, model) -> List[str]:
    try:
        facts = _extract(text)
        prompt = _build_prompt(text, mood, facts)
        out = model(
            prompt,
            max_new_tokens=120,
            temperature=0.2,
            top_p=0.9,
        )
        s = _strip_profane(str(out).strip())
        # Split into lines that start with a bullet-ish marker
        parts = re.split(r"\n+|\s*•\s*", s)
        bullets = [p.strip() for p in parts if p.strip()]
        lines = []
        for b in bullets:
            if not b:
                continue
            if any(b.lower().startswith(x) for x in ("message:", "rewrite:", "bullets:")):
                continue
            lines.append(_cut(b, 120))
            if len(lines) >= 2:
                break
        return lines
    except Exception as e:
        print(f"[Neural Core] LLM bullets error: {e}")
        return []

# --------------------------
# Compose final bullets
# --------------------------
def _compose(text: str, mood: str, model) -> str:
    b = _bullet_for(mood)
    facts = _extract(text)
    out: List[str] = []

    # Facts first (most important)
    if facts.get("show"):
        se = ""
        if facts.get("season"): se += f"S{facts['season']}"
        if facts.get("episode"): se += f"E{facts['episode']}"
        if se:
            out.append(f"{b} 📺 {facts['show']} — {se}")
        else:
            out.append(f"{b} 📺 {facts['show']}")
    if facts.get("movie"):
        out.append(f"{b} 🎬 {facts['movie']}")

    if facts.get("errors"):
        out.append(f"{b} ⚠️ " + _cut("; ".join(facts["errors"]), 120))

    if facts.get("poster"):
        out.append(f"{b} 🖼️ Poster: {facts['poster']}")

    if facts.get("links"):
        out.append(f"{b} 🔗 {facts['links'][0]}")

    # Add 0–2 compact LLM bullets for extra context
    llm_extra = _llm_bullets(text, mood, model)
    for ex in llm_extra:
        out.append(f"{b} {ex}")

    # Dedupe and limit to 5 lines
    out = _dedupe(out, limit=5)
    return "\n".join(out) if out else text

# --------------------------
# Public API
# --------------------------
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
    Returns short, personality-flavored bullets. On error, returns original text.
    """
    try:
        path = _resolve_model_path(model_path)
        _load_model(path)
    except Exception as e:
        print(f"[Neural Core] Model load error: {e}")
        return text

    try:
        final = _compose(text, mood, _MODEL)
        final = _strip_profane(final)
        # extra guard: enforce per-line length
        lines = [_cut(ln, 120) for ln in final.splitlines() if ln.strip()]
        return "\n".join(lines[:5]) if lines else text
    except Exception as e:
        print(f"[Neural Core] Inference/compose error: {e}")
        return text
