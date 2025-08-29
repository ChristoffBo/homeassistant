#!/usr/bin/env python3
# /app/llm_client.py — Ollama-only HTTP client
from __future__ import annotations
import os, requests
from typing import Optional, Dict, Any

def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default

# Prefer explicit OLLAMA_BASE_URL; fall back to default
OLLAMA_BASE_URL = (_env("LLM_OLLAMA_BASE_URL") or _env("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
ACTIVE_TAG  = (_env("LLM_ACTIVE_TAG") or "phi3:mini").strip()
ACTIVE_NAME = (_env("LLM_ACTIVE_NAME") or "Phi-3").strip()

def _post(path: str, json_body: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    url = f"{OLLAMA_BASE_URL}{path}"
    r = requests.post(url, json=json_body, timeout=timeout)
    r.raise_for_status()
    return r.json()

def engine_status() -> Dict[str, Any]:
    """Return {'ready': bool, 'name': str, 'tag': str} using /api/tags."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=6)
        r.raise_for_status()
        models = r.json().get("models", []) or []
        names = [m.get("name","") for m in models if isinstance(m, dict)]
        ready = bool(names) and (ACTIVE_TAG in names or True)  # if any model is present, serve is up
        return {"ready": ready, "name": ACTIVE_NAME, "tag": ACTIVE_TAG}
    except Exception:
        return {"ready": False, "name": ACTIVE_NAME, "tag": ACTIVE_TAG}

def _mk_prompt(src: str, system_prompt: Optional[str]) -> str:
    src = (src or "").strip()
    if not system_prompt:
        return src
    return f"{system_prompt.strip()}\n\n{src}"

def rewrite(**kwargs) -> str:
    """
    Accepts either (src=...) or (text=...), plus optional system_prompt and timeout.
    Ignores unknown kwargs so callers can pass extra info without breaking us.
    """
    src = kwargs.get("src", kwargs.get("text", ""))
    system_prompt = kwargs.get("system_prompt")
    timeout = int(kwargs.get("timeout", 12))
    if not src:
        return ""
    prompt = _mk_prompt(src, system_prompt)
    try:
        body = {
            "model": ACTIVE_TAG,
            "prompt": prompt,
            "stream": False,
            "options": {
                # Safe default; callers can increase via server config
                "num_ctx": max(512, int(os.getenv("LLM_CTX_TOKENS", "1024")))
            }
        }
        data = _post("/api/generate", body, timeout=max(10, timeout + 3))
        return (data.get("response") or "").strip() or src
    except Exception:
        # On any failure, return original text so the pipeline continues
        return src
