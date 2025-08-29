#!/usr/bin/env python3
from __future__ import annotations

import os, requests
from typing import Optional, Dict, Any

def _bool_env(name: str, default: bool=False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1","true","yes","on")

# Env from run.sh
OLLAMA_BASE_URL = os.getenv("LLM_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
ACTIVE_TAG      = os.getenv("LLM_ACTIVE_TAG", "").strip()  # empty means disabled
LLM_ENABLED     = _bool_env("LLM_ENABLED", False)

def _post(path: str, json_body: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    url = f"{OLLAMA_BASE_URL}{path}"
    r = requests.post(url, json=json_body, timeout=timeout)
    r.raise_for_status()
    return r.json()

def status() -> Dict[str, Any]:
    """Return readiness and active tag."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m.get("name","") for m in (r.json().get("models") or []) if isinstance(m, dict)]
        ready = bool(ACTIVE_TAG) and (ACTIVE_TAG in names)
        return {"ready": ready, "active": ACTIVE_TAG, "available": names}
    except Exception:
        return {"ready": False, "active": ACTIVE_TAG, "available": []}

def rewrite(src: str, system_prompt: Optional[str] = None, timeout: int = 12, **_) -> str:
    """Return LLM rewrite of text or the original if disabled/unavailable."""
    if (not LLM_ENABLED) or (not ACTIVE_TAG):
        return src
    prompt = src if not system_prompt else f"{system_prompt.strip()}\n\n{src}"
    try:
        body = {"model": ACTIVE_TAG, "prompt": prompt, "stream": False, "options": {"num_ctx": 1024}}
        data = _post("/api/generate", body, timeout=max(10, timeout + 3))
        return (data.get("response") or "").strip() or src
    except Exception:
        return src
