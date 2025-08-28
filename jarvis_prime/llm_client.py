#!/usr/bin/env python3
"""
Neural Core (local GGUF via ctransformers)
- Loads once (singleton), logs path + size
- Resolves model path robustly (expands vars, trims, and falls back to first .gguf)
- rewrite(text, mood, ...) returns a concise, personality-flavored version
"""

import os
from pathlib import Path
from typing import Optional

_MODEL = None
_MODEL_PATH: Optional[Path] = None

def _resolve_model_path(model_path: str) -> Path:
    """
    Normalize + resolve a usable GGUF path.
    If the exact file is missing, fall back to the first *.gguf in /share/jarvis_prime/models.
    """
    if model_path:
        p = Path(os.path.expandvars(model_path.strip()))
        if p.exists():
            return p

    base = Path("/share/jarvis_prime/models")
    if base.exists():
        ggufs = sorted(base.glob("*.gguf"))
        if ggufs:
            return ggufs[0]
    raise FileNotFoundError(f"No GGUF model found at '{model_path}' and no fallback in {base}")

def _load_model(path: Path):
    global _MODEL, _MODEL_PATH
    if _MODEL is not None and _MODEL_PATH == path:
        return
    print(f"[Neural Core] Loading model: {path} (size={path.stat().st_size} bytes)")
    from ctransformers import AutoModelForCausalLM
    # ctransformers expects a directory + model_file
    _MODEL = AutoModelForCausalLM.from_pretrained(
        str(path.parent),
        model_file=path.name,
        model_type="llama",
        gpu_layers=0,  # CPU-friendly by default
    )
    _MODEL_PATH = path
    print("[Neural Core] Model ready")

def _build_prompt(text: str, mood: str) -> str:
    mood_line = {
        "serious": "tone=serious, concise",
        "sarcastic": "tone=sarcastic, witty",
        "playful": "tone=playful, friendly",
        "hacker-noir": "tone=hacker-noir, terse, stylish",
        "angry": "tone=brutally-honest, blunt",
    }.get(mood, "tone=serious, concise")

    return (
        "You are Jarvis Prime's Neural Core.\n"
        "Task: rewrite the following message to be human-friendly and compact while preserving key facts "
        "(titles, links, posters, Show/Movie names, seasons/episodes, errors). Do not invent details. "
        "Never remove content in brackets like URLs. Add light personality based on tone.\n"
        f"Style: {mood_line}. Format with short lines.\n"
        "Message:\n"
        f"{text}\n"
        "Rewrite:\n"
    )

def rewrite(text: str,
            mood: str = "serious",
            timeout: int = 5,
            cpu_limit: int = 70,
            models_priority=None,
            base_url: str = "",
            model_path: str = "") -> str:
    """
    Returns rewritten text. On any error, returns the original text unchanged.
    """
    try:
        path = _resolve_model_path(model_path)
    except Exception as e:
        print(f"[Neural Core] Model resolve error: {e}")
        return text

    try:
        _load_model(path)
    except Exception as e:
        print(f"[Neural Core] Load error: {e}")
        return text

    try:
        prompt = _build_prompt(text, mood)
        # Typical small local models: ~150-220 tokens is enough for rewrite
        out = _MODEL(
            prompt,
            max_new_tokens=220,
            temperature=0.6,
            top_p=0.9,
        )
        # ctransformers returns only the completion (no need to strip the prompt)
        cleaned = str(out).strip()
        # Basic sanity: if the result is extremely short, keep original
        if len(cleaned) < 4:
            return text
        return cleaned
    except Exception as e:
        print(f"[Neural Core] Inference error: {e}")
        return text
