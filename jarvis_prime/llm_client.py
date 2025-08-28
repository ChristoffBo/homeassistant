#!/usr/bin/env python3
"""
Neural Core for Jarvis Prime (robust GGUF loader for ctransformers==0.2.27)

- Rewrites inbound messages into mood-forward, human-friendly bullets.
- Local GGUF via ctransformers (CPU). No networking required.
- If model import/load fails, returns a compact deterministic fallback.
- Profanity allowed/blocked from /data/options.json (personality_allow_profanity).

This version makes loading **bulletproof** across the common ctransformers cases:
- Accepts either a **file path** to .gguf or a **directory** containing .gguf files
- First tries the simple `LLM(model_path=...)` constructor (fast path)
- If that fails, falls back to `AutoModelForCausalLM.from_pretrained(dir, model_file=filename, ...)`
- Adds loud logs so you can *see* what's happening at runtime
"""

from __future__ import annotations
import os
import re
import json
import time
from pathlib import Path
from typing import Optional, List

# ============================ Tunables ============================
DETAIL_LEVEL = os.getenv("LLM_DETAIL_LEVEL", "rich").lower()
MAX_LINES = 10 if DETAIL_LEVEL == "rich" else 6
MAX_LINE_CHARS = 160

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
LLM_TOP_P      = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "320"))

# Loud logs so you can see it *fire*
VERBOSE = True

# ============================ Globals =============================
_MODEL = None
_MODEL_PATH: Optional[Path] = None
_CTRANS_AVAILABLE = False

# ====================== Config / helpers ==========================
def _cfg_allow_profanity() -> bool:
    env = os.getenv("PERSONALITY_ALLOW_PROFANITY")
    if env is not None:
        return env.lower() in ("1", "true", "yes")
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("personality_allow_profanity", False))
    except Exception:
        return False

def _normalize_mood(mood: str) -> str:
    m = (mood or "").strip().lower()
    return m or "serious"

def _bullet_for(mood: str) -> str:
    m = _normalize_mood(mood)
    return {"serious": "•", "cheeky": "😏", "relaxed": "✨", "urgent": "⚡"}.get(m, "•")

def _clean_if_needed(text: str, allow_profanity: bool) -> str:
    if allow_profanity:
        return text
    # mild profanity filter – keep family friendly by default
    return re.sub(r"\b(fuck|shit|bitch|bastard)\b", "****", text, flags=re.I)

# -------------------- ctransformers import -----------------------
def _import_ctransformers() -> bool:
    global _CTRANS_AVAILABLE
    if _CTRANS_AVAILABLE:
        return True
    try:
        # Import both facades; we may use either depending on path style
        from ctransformers import AutoModelForCausalLM  # noqa: F401
        from ctransformers import LLM  # noqa: F401
        _CTRANS_AVAILABLE = True
        if VERBOSE:
            print("[Neural Core] ctransformers import: OK", flush=True)
        return True
    except Exception as e:
        print(f"[Neural Core] ctransformers import FAILED: {e}", flush=True)
        _CTRANS_AVAILABLE = False
        return False

# -------------------- GGUF path resolution -----------------------
def _pick_gguf_in_dir(d: Path) -> Optional[Path]:
    """Pick a .gguf file inside directory `d`. If LLM_MODELS_PRIORITY env is set
    (comma-separated substrings), prefer files that contain any of those terms."""
    if not d.is_dir():
        return None
    files = list(sorted(p for p in d.iterdir() if p.suffix.lower() == ".gguf"))
    if not files:
        return None
    priority = os.getenv("LLM_MODELS_PRIORITY", "")
    if priority:
        prefs = [s.strip().lower() for s in priority.split(",") if s.strip()]
        for pref in prefs:
            for f in files:
                if pref in f.name.lower():
                    return f
    # default to first .gguf (sorted)
    return files[0]

# -------------------- Model loader (robust) ----------------------
def _load_model(model_path: str) -> bool:
    """
    Load GGUF once. Returns True if the model is ready.
    Handles *both* direct file path and directory path.
    """
    global _MODEL, _MODEL_PATH
    if not model_path:
        print("[Neural Core] No model path configured.", flush=True)
        return False

    p = Path(os.path.expandvars(model_path)).expanduser()
    if VERBOSE:
        print(f"[Neural Core] _load_model('{p}')", flush=True)

    # Already loaded?
    if _MODEL is not None and _MODEL_PATH == p:
        return True

    if not _import_ctransformers():
        return False

    # Resolve to an actual .gguf file + parent dir
    model_file: Optional[Path] = None
    model_dir: Optional[Path] = None

    if p.is_file() and p.suffix.lower() == ".gguf":
        model_file = p
        model_dir = p.parent
    elif p.is_dir():
        picked = _pick_gguf_in_dir(p)
        if picked:
            model_file = picked
            model_dir = picked.parent
        else:
            print(f"[Neural Core] No .gguf found in directory: {p}", flush=True)
            return False
    else:
        # Path does not exist; let user know quickly
        print(f"[Neural Core] Path not found: {p}", flush=True)
        return False

    try:
        # 1) Fast path: LLM(file) (works with local .gguf paths in 0.2.27)
        from ctransformers import LLM
        t0 = time.time()
        print(f"[Neural Core] Loading GGUF via LLM(): '{model_file}' ...", flush=True)
        _MODEL = LLM(model_path=str(model_file), model_type="llama")
        _MODEL_PATH = p
        print(f"[Neural Core] Model ready in {time.time()-t0:.2f}s (LLM())", flush=True)
        return True
    except Exception as e1:
        print(f"[Neural Core] LLM() load failed: {e1}", flush=True)

    try:
        # 2) Fallback: AutoModelForCausalLM.from_pretrained(dir, model_file=...)
        from ctransformers import AutoModelForCausalLM
        t0 = time.time()
        print(f"[Neural Core] Loading GGUF via from_pretrained(dir, model_file): dir='{model_dir}', file='{model_file.name}' ...", flush=True)
        _MODEL = AutoModelForCausalLM.from_pretrained(
            model_path_or_repo_id=str(model_dir),
            model_file=model_file.name,
            model_type="llama",
            local_files_only=True,
            gpu_layers=0,         # CPU in HA container
        )
        _MODEL_PATH = p
        print(f"[Neural Core] Model ready in {time.time()-t0:.2f}s (from_pretrained)", flush=True)
        return True
    except Exception as e2:
        print(f"[Neural Core] from_pretrained load failed: {e2}", flush=True)
        _MODEL = None
        _MODEL_PATH = None
        return False

# ============================ Text utils ==========================
def _cut(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[: max(0, n - 1)].rstrip() + "…")

def _allow_profanity() -> bool:
    return _cfg_allow_profanity()

def _build_prompt(text: str, mood: str, allow_profanity: bool) -> str:
    tone = {
        "serious": "succinct, confident, professional, no filler",
        "cheeky": "playful, witty, lightly sarcastic, but helpful",
        "relaxed": "friendly, calm, conversational",
        "urgent": "terse, high-priority, crisp"
    }[_normalize_mood(mood)]
    filters = "" if allow_profanity else "Keep it family-friendly; avoid profanity."
    return (
        "You rewrite the following message into a few short, human-friendly bullet lines.\n"
        "Output ONLY bullet lines (no headings, no labels).\n"
        f"Tone: {tone}. {filters}\n"
        "Bullets should feel like my homelab is speaking.\n\n"
        f"MESSAGE:\n{text}\n"
        "REWRITE:\n"
    )

# ============================ Public API ==========================
def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 5,          # (caller enforces timeouts with thread pools)
    cpu_limit: int = 70,       # kept for signature compatibility
    models_priority=None,      # kept for signature compatibility
    base_url: str = "",        # kept for signature compatibility
    model_path: str = "",
) -> str:
    """
    Returns ONLY the rewritten body (no footer). Callers add the footer.
    """
    allow_profanity = _cfg_allow_profanity()
    mood = _normalize_mood(mood)
    model_path = model_path or os.getenv("LLM_MODEL_PATH", "")

    if VERBOSE:
        print(f"[Neural Core] rewrite() start: mood={mood} model='{model_path}'", flush=True)

    ready = _load_model(model_path)
    if not ready or _MODEL is None:
        return _render_generic(text or "", mood, allow_profanity)

    try:
        prompt = _build_prompt(text or "", mood, allow_profanity)
        if VERBOSE:
            print("[Neural Core] Generating...", flush=True)
        t0 = time.time()
        out = _MODEL(
            prompt,
            max_new_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            top_p=LLM_TOP_P,
        )
        gen = str(out or "").strip()
        if VERBOSE:
            print(f"[Neural Core] Generation done in {time.time()-t0:.2f}s", flush=True)
    except Exception as e:
        print(f"[Neural Core] Generation error: {e}", flush=True)
        return _render_generic(text or "", mood, allow_profanity)

    m = re.search(r"(•|✨|⚡|😏|▣)\s", gen)
    if m:
        gen = gen[m.start():]

    lines: List[str] = []
    for raw in gen.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.search(r"(REWRITE:|MESSAGE:|Example|Tone:|Rules:|Output ONLY)", s, re.I):
            continue
        if not re.match(r"^(•|✨|⚡|😏|▣)\s", s):
            s = f"{_bullet_for(mood)} {s}"
        lines.append(_cut(s, MAX_LINE_CHARS))
        if len(lines) >= MAX_LINES:
            break

    if not lines:
        return _render_generic(text or "", mood, allow_profanity)

    result = "\n".join(lines)
    return _clean_if_needed(result, allow_profanity)

# ============================ Public API (extended) ==========================
def rewrite_with_info(
    text: str,
    mood: str = "serious",
    timeout: int = 5,
    cpu_limit: int = 70,
    models_priority=None,
    base_url: str = "",
    allow_profanity: Optional[bool] = None,
    model_path: str = ""
) -> tuple[str, bool]:
    """
    Like rewrite(), but returns (output_text, used_llm).
    used_llm == True only if a GGUF model was loaded and used for generation.
    """
    if allow_profanity is None:
        allow_profanity = _allow_profanity()
    model_path = model_path or os.getenv("LLM_MODEL_PATH", "")

    ready = _load_model(model_path)
    if not ready or _MODEL is None:
        return _render_generic(text or "", _normalize_mood(mood), allow_profanity), False

    try:
        prompt = _build_prompt(text or "", _normalize_mood(mood), allow_profanity)
        if VERBOSE:
            print("[Neural Core] Generating (with info)...", flush=True)
        t0 = time.time()
        out = _MODEL(
            prompt,
            max_new_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            top_p=LLM_TOP_P,
        )
        gen = str(out or "").strip()
        if VERBOSE:
            print(f"[Neural Core] Generation done in {time.time()-t0:.2f}s", flush=True)
    except Exception as e:
        print(f"[Neural Core] Generation error (with info): {e}", flush=True)
        return _render_generic(text or "", _normalize_mood(mood), allow_profanity), False

    m = re.search(r"(•|✨|⚡|😏|▣)\s", gen)
    if m:
        gen = gen[m.start():]

    lines: List[str] = []
    for raw in gen.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.search(r"(REWRITE:|MESSAGE:|Example|Tone:|Rules:|Output ONLY)", s, re.I):
            continue
        if not re.match(r"^(•|✨|⚡|😏|▣)\s", s):
            s = f"{_bullet_for(_normalize_mood(mood))} {s}"
        lines.append(_cut(s, MAX_LINE_CHARS))
        if len(lines) >= MAX_LINES:
            break

    if not lines:
        return _render_generic(text or "", _normalize_mood(mood), allow_profanity), False

    result = "\n".join(lines)
    return _clean_if_needed(result, allow_profanity), True

# ======================== Fallback renderer ======================
def _render_generic(text: str, mood: str, allow_profanity: bool) -> str:
    mood = _normalize_mood(mood)
    bullet = _bullet_for(mood)
    base = (text or "").strip().replace("\r", "")
    lines = []
    for i, raw in enumerate(base.splitlines()):
        s = raw.strip()
        if not s:
            continue
        if not s.startswith(bullet + " "):
            s = f"{bullet} {s}"
        lines.append(_cut(s, MAX_LINE_CHARS))
        if len(lines) >= MAX_LINES:
            break
    if not lines:
        lines = [f"{bullet} (no content)"]
    return _clean_if_needed("\n".join(lines), allow_profanity)

# ============================ CLI self-test =======================
if __name__ == "__main__":
    # Try to load the model at startup to surface any errors in logs.
    mp = os.getenv("LLM_MODEL_PATH", "")
    mood = os.getenv("CHAT_MOOD", "serious")
    print(f"[Neural Core] SELF-TEST: model_path='{mp}'", flush=True)
    ok = _load_model(mp)
    if not ok:
        print("[Neural Core] SELF-TEST: model not ready", flush=True)
        raise SystemExit(2)
    try:
        out, used = rewrite_with_info("Boot self-test: say hello in bullet points.", mood=mood, model_path=mp)
        print(f"[Neural Core] SELF-TEST: used_llm={used}, chars={len(out)}", flush=True)
    except Exception as e:
        print(f"[Neural Core] SELF-TEST: generation failed: {e}", flush=True)
        raise SystemExit(3)
