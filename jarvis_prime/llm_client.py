
#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations

import os, hashlib
from pathlib import Path
from typing import Optional, List

# Optional: ctransformers
try:
    from ctransformers import AutoModelForCausalLM
except Exception:
    AutoModelForCausalLM = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# Defaults (overridable by caller)
MODEL_PATH  = Path(os.getenv("LLM_MODEL_PATH", "/share/jarvis_prime/models/model.gguf"))
MODEL_URL   = os.getenv("LLM_MODEL_URL", "")
MODEL_SHA256 = os.getenv("LLM_MODEL_SHA256", "")

_loaded_model = None

def _ensure_model(path: Path = MODEL_PATH) -> Optional[Path]:
    if path and path.exists():
        return path
    if MODEL_URL:
        try:
            import requests
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            with requests.get(MODEL_URL, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1<<20):
                        if chunk:
                            f.write(chunk)
            os.replace(tmp, path)
            return path
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Model download failed: {e}", flush=True)
            return None
    return None

def _load_model(path: Path) -> Optional[object]:
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model
    if AutoModelForCausalLM is None:
        return None
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path), model_type="llama", gpu_layers=0
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

def _strip_numbered_reasoning(text: str) -> str:
    out_lines = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        # Drop analysis-style prefixes
        if re_match(r'^(input|output|explanation|reasoning)\s*[:\-]', t):
            continue
        # Drop obvious numbered points
        if re_match(r'^\d+[\.\)]\s+', t):
            continue
        out_lines.append(t)
    return "\n".join(out_lines)

def re_match(pat: str, s: str) -> bool:
    import re
    return re.match(pat, s, flags=re.I) is not None

def _cap(text: str, max_lines: int = 6, max_chars: int = 400) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out

def rewrite(text: str, mood: str = "serious", timeout: int = 8, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, allow_profanity: bool = False,
            model_path: Optional[str] = None, model_url: Optional[str] = None,
            model_sha256: Optional[str] = None) -> str:
    """
    Deterministic, clamped rewrite. If no model, returns original text.
    """
    src = (text or "").strip()
    if not src:
        return src

    # Try model
    p = _ensure_model(Path(model_path) if model_path else MODEL_PATH)
    model = _load_model(p) if p else None

    vibe_map = {
        "serious": "clinical, confident, concise",
        "playful": "cheeky, witty, upbeat",
        "angry":   "furious, clipped, no-nonsense",
        "happy":   "bright, helpful, warm",
        "sad":     "reserved, minimal, calm",
    }
    vibe = vibe_map.get((mood or "").lower(), "confident, concise")
    profanity = "neutral on profanity" if allow_profanity else "avoid profanity"

    if model:
        system = (
            f"You are Jarvis Prime. Rewrite the input with {vibe}. "
            f"Keep facts/URLs/numbers exactly. No lists. No 'Input/Output/Explanation'. "
            f"2–6 short lines max. {profanity}. No concluding labels."
        )
        prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
        try:
            out = model(prompt, max_new_tokens=160, temperature=0.8, top_p=0.92, repetition_penalty=1.1)
            out = str(out or "").strip()
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ LLM generation failed: {e}", flush=True)
            out = src
    else:
        out = src  # no model available

    # Sanitize + clamp
    out = _strip_numbered_reasoning(out)
    out = _cap(out, 6, 400)
    # Guarantee at least something meaningful
    if not out or len(out) < 2:
        out = src[:200]
    return out
