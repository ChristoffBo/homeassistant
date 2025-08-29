#!/usr/bin/env python3
from __future__ import annotations

import os, re, time, json
from pathlib import Path
from typing import Optional, List, Dict

try:
    import requests
except Exception:
    requests = None  # type: ignore

# -----------------------------
# Config
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# Conservative decoding for accuracy/obedience
TEMP   = float(os.getenv("LLM_TEMPERATURE", "0.25"))
TOP_P  = float(os.getenv("LLM_TOP_P", "0.9"))
REPEAT_P = float(os.getenv("LLM_REPEAT_PENALTY", "1.25"))
CTX    = int(os.getenv("LLM_CTX_TOKENS", os.getenv("LLM_CTX","1024")))
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "192"))
MAX_LINES  = int(os.getenv("LLM_MAX_LINES","10"))

# Internal flag: whether last generation actually used LLM
_LAST_USED = False

# -----------------------------
# Helpers
# -----------------------------
def _short_family(tag: str) -> str:
    t = (tag or "").lower()
    if "phi3" in t: return "Phi3"
    if "phi:" in t: return "Phi2"
    if "gemma2" in t: return "Gemma2"
    if "tinyllama" in t: return "TinyLlama"
    if "qwen" in t: return "Qwen"
    return "—"

def _load_system_prompt() -> str:
    sp = os.getenv("LLM_SYSTEM_PROMPT")
    if sp: return sp
    for p in [Path("/share/jarvis_prime/memory/system_prompt.txt"),
              Path("/app/memory/system_prompt.txt")]:
        try:
            if p.exists():
                return p.read_text(encoding="utf-8")
        except Exception:
            pass
    return "YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."

def _trim_to_ctx(src: str, system: str) -> str:
    if not src: return src
    # rough char budget
    budget_tokens = max(256, CTX - GEN_TOKENS - 64)
    budget_chars = max(1000, budget_tokens * 3)
    remaining = max(500, budget_chars - len(system))
    if len(src) <= remaining:
        return src
    return src[-remaining:]

def _extract_images(text: str) -> List[str]:
    # future: return data URIs or HTTP links if present
    return []

def _finalize(out: str, imgs: List[str], allow_multiline: bool=True) -> str:
    s = (out or "").strip()
    if not allow_multiline:
        # lock to one line
        s = re.sub(r'[\r\n]+',' ', s).strip()
    # truncate to line count
    if allow_multiline:
        lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
        if len(lines) > MAX_LINES:
            lines = lines[:MAX_LINES]
        s = "\n".join(lines)
    # moderate runaway
    max_chars = 4000
    if len(s) > max_chars:
        s = s[:max_chars].rstrip()
    return s

def _active_model() -> (str, str):
    base = (os.getenv("OLLAMA_BASE_URL","").strip() or "http://127.0.0.1:11434").rstrip("/")
    tag  = os.getenv("OLLAMA_MODEL_TAG","").strip() or "tinyllama:latest"
    return base, tag

# -----------------------------
# Public API
# -----------------------------
def rewrite(text: str, mood: str="serious", timeout: int=10, cpu_limit: int=70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str]=None,
            model_url: Optional[str]=None, model_path: Optional[str]=None,
            model_sha256: Optional[str]=None, allow_profanity: bool=False) -> str:
    global _LAST_USED
    src = (text or "").strip()
    if not src: return src

    imgs = _extract_images(src)
    system = _load_system_prompt().format(mood=mood)
    src = _trim_to_ctx(src, system)

    base, tag = _active_model()
    if models_priority and isinstance(models_priority, list) and len(models_priority) > 0:
        # allow caller to override model tag
        tag = models_priority[0]

    # Prefer provided base_url if any
    if base_url and base_url.strip():
        base = base_url.strip().rstrip("/")

    if not requests:
        return _finalize(src, imgs, allow_multiline=True)

    payload = {
        "model": tag,
        "prompt": f"{system}\n\nINPUT:\n{src}\n\nOUTPUT:\n",
        "stream": False,
        "options": {
            "temperature": TEMP,
            "top_p": TOP_P,
            "repeat_penalty": REPEAT_P,
            "num_ctx": CTX,
            "num_predict": GEN_TOKENS,
            "stop": ["[SYSTEM]","[INPUT]","[OUTPUT]"]
        }
    }
    try:
        r = requests.post(base + "/api/generate", json=payload, timeout=timeout)
        if r.ok:
            _LAST_USED = True
            out = str(r.json().get("response",""))
            allow_multi = os.getenv("LLM_ALLOW_MULTILINE","true").lower() in ("1","true","yes","on")
            return _finalize(out, imgs, allow_multiline=allow_multi)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Ollama call failed: {e}", flush=True)

    _LAST_USED = False
    return _finalize(src, imgs, allow_multiline=True)

def engine_status() -> Dict[str,object]:
    base, tag = _active_model()
    if not requests:
        return {"ready": False, "model_path": "", "backend": "ollama", "model": "", "used": False}
    ok = False
    model_present = False
    try:
        rv = requests.get(base + "/api/version", timeout=2)
        ok = bool(rv.ok)
    except Exception:
        ok = False
    if ok:
        try:
            rt = requests.get(base + "/api/tags", timeout=2)
            if rt.ok:
                model_present = any( (m.get('name')==tag) for m in rt.json().get('models',[]) )
        except Exception:
            pass
    return {"ready": bool(ok and model_present), "model_path": tag, "backend": "ollama", "model": tag, "used": _LAST_USED}
