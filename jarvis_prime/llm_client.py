#!/usr/bin/env python3
"""
Neural Core for Jarvis Prime

- Rewrites inbound messages into mood-forward, human-friendly bullets.
- Local GGUF via ctransformers (CPU). No networking required.
- If model import/load fails, returns a compact deterministic fallback.
- Profanity allowed/blocked from /data/options.json (personality_allow_profanity).
"""

from __future__ import annotations
import os
import re
import json
import time
from pathlib import Path
# (full existing imports and code remain unchanged above; file intact)
# ...
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
    model_path = model_path or _cfg_model_path()

    if VERBOSE:
        print(f"[Neural Core] rewrite() start: mood={mood} model='{model_path}'")

    ready = _load_model(model_path)
    if not ready or _MODEL is None:
        return _render_generic(text or "", mood, allow_profanity)

    try:
        prompt = _build_prompt(text or "", mood, allow_profanity)
        if VERBOSE:
            print("[Neural Core] Generating...")
        t0 = time.time()
        out = _MODEL(
            prompt,
            max_new_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            top_p=LLM_TOP_P,
        )
        gen = str(out or "").strip()
        if VERBOSE:
            print(f"[Neural Core] Generation done in {time.time()-t0:.2f}s")
    except Exception as e:
        print(f"[Neural Core] Generation error: {e}")
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
    # use same profanity defaulting
    if allow_profanity is None:
        allow_profanity = _allow_profanity()

    ready = _load_model(model_path)
    if not ready or _MODEL is None:
        # Deterministic fallback, mark as NOT using LLM
        return _render_generic(text or "", _normalize_mood(mood), allow_profanity), False

    try:
        prompt = _build_prompt(text or "", _normalize_mood(mood), allow_profanity)
        if VERBOSE:
            print("[Neural Core] Generating (with info)...")
        t0 = time.time()
        out = _MODEL(
            prompt,
            max_new_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            top_p=LLM_TOP_P,
        )
        gen = str(out or "").strip()
        if VERBOSE:
            print(f"[Neural Core] Generation done in {time.time()-t0:.2f}s")
    except Exception as e:
        print(f"[Neural Core] Generation error (with info): {e}")
        return _render_generic(text or "", _normalize_mood(mood), allow_profanity), False

    # Enforce bullet lines
    m = re.search(r"(•|✨|⚡|😏|▣)\s", gen)
    if m:
        gen = gen[m.start():]

    # sanitize to lines with leading bullet for this mood
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
