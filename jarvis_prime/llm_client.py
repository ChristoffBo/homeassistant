#!/usr/bin/env python3
from __future__ import annotations

import os, time
from typing import Optional, Dict, Any
import requests

# Configuration via env (run.sh exports these)
OLLAMA_BASE_URL = os.getenv("LLM_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
ACTIVE_TAG      = os.getenv("LLM_ACTIVE_TAG", "").strip() or "phi3:mini"
ACTIVE_NAME     = os.getenv("LLM_ACTIVE_NAME", "Phi3")

def _post(path: str, json_body: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    url = f"{OLLAMA_BASE_URL}{path}"
    r = requests.post(url, json=json_body, timeout=timeout)
    r.raise_for_status()
    return r.json()

def engine_status() -> Dict[str, Any]:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        tags = r.json().get("models", [])
        names = [m.get("name","") for m in tags]
        ready = any(name == ACTIVE_TAG for name in names) or bool(tags)
        return {"ready": ready, "name": ACTIVE_NAME, "tag": ACTIVE_TAG}
    except Exception:
        return {"ready": False, "name": ACTIVE_NAME, "tag": ACTIVE_TAG}

def rewrite(src: str, system_prompt: Optional[str] = None, timeout: int = 12, **_) -> str:
    prompt = src.strip()
    if system_prompt:
        prompt = f"{system_prompt.strip()}

{src.strip()}"
    try:
        body = {"model": ACTIVE_TAG, "prompt": prompt, "stream": False, "options": {"num_ctx": 2048}}
        data = _post("/api/generate", body, timeout=max(10, timeout+3))
        return (data.get("response") or "").strip() or src
    except Exception:
        return src
