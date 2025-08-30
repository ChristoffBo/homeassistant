#!/usr/bin/env python3
"""
Jarvis Prime — LLM Client (local only)

- Uses ctransformers to run local GGUF models (CPU).
- No Ollama, no external calls.
- Honors timeout and CPU usage limits.
- Strict formatter: rewrites neatly, does not add/remove meaning.
"""

from __future__ import annotations
import os, time, re, psutil
from typing import Optional, List, Dict
from ctransformers import AutoModelForCausalLM

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# Defaults (can be overridden by /data/options.json)
CTX = int(os.getenv("LLM_CTX_TOKENS", "4096"))
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "180"))
CHARS_PER_TOKEN = 4
SAFETY_TOKENS = 32

MODEL_CACHE: Dict[str, AutoModelForCausalLM] = {}
CURRENT_PATH: Optional[str] = None

def _budget_chars(system: str) -> int:
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * CHARS_PER_TOKEN)
    return max(500, budget_chars - len(system or ""))

def _trim_to_ctx(src: str, system: str) -> str:
    if not src:
        return src
    remaining = _budget_chars(system)
    if len(src) <= remaining:
        return src
    return src[-remaining:]

# Simple text cleaners
ZWSP_RE   = re.compile(r'[\u200B\u200C\u200D\uFEFF]')
TRAIL_WS  = re.compile(r'[ \t]+\n')
MULTIBLNK = re.compile(r'(?:\n[ \t]*){3,}', flags=re.M)
BULLET_RE = re.compile(r'^(?P<pre>[ \t]*)(?P<bullet>[-*•])([ \t]{2,})(?P<rest>\S)', flags=re.M)

def strict_format(text: str) -> str:
    if not text:
        return text
    s = text.replace('\r\n','\n').replace('\r','\n')
    s = ZWSP_RE.sub('', s)
    s = TRAIL_WS.sub('\n', s)
    s = MULTIBLNK.sub('\n\n', s)
    s = BULLET_RE.sub(lambda m: f"{m.group('pre')}{m.group('bullet')} {m.group('rest')}", s)
    if s and not s.endswith('\n'):
        s = s + '\n'
    return s

def _resolve_model_path(preferred: Optional[str] = None) -> Optional[str]:
    """
    Decide which model to load based on env/config.
    """
    # Option order: direct path > env var > default TinyLlama
    if preferred and os.path.exists(preferred):
        return preferred
    env_path = os.getenv("LLM_MODEL_PATH", "")
    if env_path and os.path.exists(env_path):
        return env_path
    default_path = "/share/jarvis_prime/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    if os.path.exists(default_path):
        return default_path
    return None

def _load_local_model(model_path: str) -> Optional[AutoModelForCausalLM]:
    """
    Load model with ctransformers and cache it.
    """
    global MODEL_CACHE, CURRENT_PATH
    if not model_path:
        return None
    if model_path in MODEL_CACHE:
        return MODEL_CACHE[model_path]
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            model_type="llama",
            gpu_layers=0
        )
        MODEL_CACHE[model_path] = model
        CURRENT_PATH = model_path
        print(f"[{BOT_NAME}] ✅ Loaded local model {os.path.basename(model_path)}")
        return model
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to load model {model_path}: {e}")
        return None

def prefetch_model(*args, **kwargs) -> None:
    path = _resolve_model_path()
    if path:
        _load_local_model(path)

def engine_status() -> Dict[str, object]:
    return {
        "ready": CURRENT_PATH is not None,
        "model_path": CURRENT_PATH or "",
        "backend": "ctransformers"
    }

def _cpu_overloaded(limit: int) -> bool:
    try:
        return psutil.cpu_percent(interval=0.1) > limit
    except Exception:
        return False

def rewrite(text: str,
            mood: str = "serious",
            timeout: int = 8,
            cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None,
            base_url: Optional[str] = None,
            model_url: Optional[str] = None,
            model_path: Optional[str] = None,
            model_sha256: Optional[str] = None,
            allow_profanity: bool = False) -> str:
    """
    Pass text through local model → return strictly formatted result.
    """
    src = (text or "").strip()
    if not src:
        return src

    path = _resolve_model_path(model_path)
    model = _load_local_model(path)
    if not model:
        print(f"[{BOT_NAME}] ⚠️ No local model available.")
        return src

    # Guard: CPU usage
    if _cpu_overloaded(cpu_limit):
        print(f"[{BOT_NAME}] ⚠️ CPU limit exceeded ({cpu_limit}%), skipping rewrite")
        return src

    # Build prompt (no personality, just neat formatting)
    system_prompt = "Rewrite the following text neatly and concisely without altering meaning:"
    user_prompt = src
    prompt = f"{system_prompt}\n\n{user_prompt}"

    try:
        start = time.time()
        output = model(prompt, max_new_tokens=GEN_TOKENS)
        dur = time.time() - start
        if dur > timeout:
            print(f"[{BOT_NAME}] ⚠️ Rewrite timeout ({dur:.1f}s > {timeout}s)")
            return src
        if output:
            formatted = strict_format(output)
            return formatted
        return src
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Rewrite error: {e}")
        return src
