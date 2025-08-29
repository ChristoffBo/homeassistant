#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import requests
from typing import Dict

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
ACTIVE_TAG = os.getenv("LLM_ACTIVE_TAG", "").strip()
ACTIVE_NAME = os.getenv("LLM_ACTIVE_NAME", "").strip() or "—"

# Conservative decoding for accurate/obedient rewrites
TEMP = float(os.getenv("LLM_TEMP", "0.25"))
TOP_P = float(os.getenv("LLM_TOP_P", "0.9"))
REPEAT_P = float(os.getenv("LLM_REPEAT_P", "1.25"))
CTX = int(os.getenv("LLM_CTX", "1024"))
GEN_TOKENS = int(os.getenv("LLM_GEN", "224"))
ALLOW_MULTILINE = (os.getenv("ALLOW_MULTILINE", "true").lower() in ("1","true","yes"))

def engine_status() -> Dict[str, object]:
    """Return readiness and current model selection."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if not r.ok:
            return {"ready": False, "model": ACTIVE_TAG, "name": ACTIVE_NAME, "model_path": ""}
        have = {m.get("name","") for m in r.json().get("models",[])}
        ok = (ACTIVE_TAG in have) if ACTIVE_TAG else True
        return {"ready": bool(ok), "model": ACTIVE_TAG, "name": ACTIVE_NAME, "model_path": ""}
    except Exception:
        return {"ready": False, "model": ACTIVE_TAG, "name": ACTIVE_NAME, "model_path": ""}

def _finalize(text: str) -> str:
    if not text:
        return ""
    # Trim if single-line mode
    if not ALLOW_MULTILINE:
        return " ".join(text.splitlines()).strip()
    return text.strip()

def rewrite(src: str=None, system_prompt: str=None, timeout: int=8, **kwargs) -> str:
    """Call Ollama /api/generate with system + prompt. Returns plain text."""
    if src is None and isinstance(kwargs.get("text"), str):
        src = kwargs.get("text")
    if system_prompt is None:
        system_prompt = os.getenv("SYSTEM_PROMPT","")
    if not ACTIVE_TAG:
        return src or ""  # passthrough if no model selected

    prompt = f"{system_prompt}\n\nINPUT:\n{src}\n\nOUTPUT:\n"

    try:
        payload = {
            "model": ACTIVE_TAG,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": TEMP,
                "top_p": TOP_P,
                "repeat_penalty": REPEAT_P,
                "num_ctx": CTX,
                "num_predict": GEN_TOKENS
            }
        }
        r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=timeout)
        if r.ok:
            data = r.json()
            out = data.get("response","" )
            return _finalize(out)
        return src
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Ollama call failed: {e}", flush=True)
        return src
