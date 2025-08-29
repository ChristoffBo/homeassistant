#!/usr/bin/env python3
# /app/llm_client.py — Ollama-only client with safe kwargs
from __future__ import annotations
import os, requests
from typing import Any, Dict, Optional

def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default

OLLAMA_BASE_URL = (_env("LLM_OLLAMA_BASE_URL") or _env("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
ACTIVE_TAG  = (_env("LLM_ACTIVE_TAG") or "").strip()
CTX_TOKENS  = int(_env("LLM_CTX_TOKENS", "1024") or "1024")
LLM_ENABLED = (_env("LLM_ENABLED","false").lower() in ("1","true","yes","on"))

def _post(path: str, body: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    url = f"{OLLAMA_BASE_URL}{path}"
    r = requests.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()

def engine_status() -> Dict[str, Any]:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=6)
        r.raise_for_status()
        j = r.json() or {}
        names = [m.get("name","") for m in (j.get("models") or []) if isinstance(m, dict)]
        ready = (ACTIVE_TAG and (ACTIVE_TAG in names)) or (len(names) > 0)
        return {"ready": ready, "name": ACTIVE_TAG.split(":")[0], "tag": ACTIVE_TAG}
    except Exception:
        return {"ready": False, "name": ACTIVE_TAG.split(":")[0], "tag": ACTIVE_TAG}

def prefetch_model() -> None:
    if not LLM_ENABLED: 
        return
    try:
        _post("/api/generate", {
            "model": ACTIVE_TAG,
            "prompt": "ping",
            "stream": False,
            "options": {"num_ctx": max(512, CTX_TOKENS)}
        }, timeout=8)
    except Exception:
        # ignore prefetch failures
        pass

def rewrite(**kwargs) -> str:
    if not LLM_ENABLED:
        return kwargs.get("text") or kwargs.get("src") or ""
    src = kwargs.get("text", kwargs.get("src", "")) or ""
    system_prompt = kwargs.get("system_prompt")
    if not src:
        return ""
    prompt = f"{system_prompt.strip()}\n\n{src}".strip() if system_prompt else src
    try:
        data = _post("/api/generate", {
            "model": ACTIVE_TAG,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": max(512, CTX_TOKENS)}
        }, timeout=int(kwargs.get("timeout", 12)) + 3)
        return (data.get("response") or "").strip() or src
    except Exception:
        return src
