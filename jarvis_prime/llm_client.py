#!/usr/bin/env python3
# /app/llm_client.py
#
# Engine-agnostic LLM client with:
# - GGUF local loading via llama-cpp (if installed in image)
# - Optional Ollama HTTP fallback (if base_url provided)
# - Hugging Face token support for secure downloads (Authorization: Bearer ...)
# - Autodownload-and-load path with optional SHA256 integrity check
# - Hard timeouts; never blocks forever
# - Safe no-op: returns original text if model/engine unavailable
#
# Public functions:
#   ensure_loaded(...)
#   rewrite(...)
#
# Usage pattern (from bot/proxy/smtp):
#   ok = ensure_loaded(
#       model_url=merged.get("llm_model_url",""),
#       model_path=merged.get("llm_model_path",""),
#       model_sha256=merged.get("llm_model_sha256",""),
#       ctx_tokens=int(merged.get("llm_ctx_tokens", 4096)),
#       cpu_limit=int(merged.get("llm_max_cpu_percent", 80)),
#       hf_token=merged.get("llm_hf_token",""),
#       base_url=merged.get("llm_ollama_base_url","").strip()
#   )
#   out = rewrite(
#       text=final,
#       mood=CHAT_MOOD,
#       timeout=int(merged.get("llm_timeout_seconds", 12)),
#       cpu_limit=int(merged.get("llm_max_cpu_percent", 80)),
#       models_priority=merged.get("llm_models_priority", []),
#       base_url=merged.get("llm_ollama_base_url",""),
#       model_url=merged.get("llm_model_url",""),
#       model_path=merged.get("llm_model_path",""),
#       model_sha256=merged.get("llm_model_sha256",""),
#       allow_profanity=bool(merged.get("personality_allow_profanity", False)),
#       ctx_tokens=int(merged.get("llm_ctx_tokens", 4096)),
#       hf_token=merged.get("llm_hf_token","")
#   )
#
# Notes:
# - If base_url is non-empty (e.g. "http://localhost:11434"), Ollama mode is used for generation.
# - Otherwise we attempt local GGUF via llama-cpp. If llama-cpp not installed or load fails: no-op.
# - For HF 401 errors, make sure "llm_hf_token" is set in options (we send the header).
# - For 404 errors, verify the model URL is exact (case/filename).

import os
import sys
import json
import time
import math
import hashlib
import socket
import urllib.request
import urllib.error
from typing import Optional, Dict, Any

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama" | "ollama"
LLM = None               # llama_cpp.Llama instance if LLM_MODE == "llama"
LOADED_MODEL_PATH = None
OLLAMA_URL = ""          # base url if using ollama (e.g., http://127.0.0.1:11434)
DEFAULT_CTX = 4096

# ============================
# Utils / Logging
# ============================
def _log(msg: str):
    print(f"[llm] {msg}", flush=True)

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _http_get(url: str, headers: Dict[str, str], timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def _http_post(url: str, data: bytes, headers: Dict[str, str], timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def _download(url: str, dst_path: str, token: Optional[str]) -> bool:
    """Download to dst_path, sending HF token if provided."""
    try:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token.strip()}"
        _log(f"downloading: {url} -> {dst_path}")
        buf = _http_get(url, headers=headers, timeout=180)
        with open(dst_path, "wb") as f:
            f.write(buf)
        _log("downloaded ok")
        return True
    except urllib.error.HTTPError as e:
        _log(f"download failed: HTTP {e.code} {getattr(e, 'reason', '')}")
        return False
    except Exception as e:
        _log(f"download failed: {e}")
        return False

def _coerce_model_path(model_url: str, model_path: str) -> str:
    """If model_path is a directory or empty, derive filename from URL."""
    if not model_path or model_path.endswith("/"):
        fname = model_url.split("/")[-1] if model_url else "model.gguf"
        return os.path.join(model_path or "/share/jarvis_prime/models", fname)
    return model_path

# ============================
# Local GGUF (llama-cpp) path
# ============================
def _try_import_llama_cpp():
    try:
        import llama_cpp
        return llama_cpp
    except Exception as e:
        _log(f"llama-cpp not available: {e}")
        return None

def _threads_from_cpu_limit(limit_pct: int) -> int:
    try:
        import multiprocessing
        cores = max(1, multiprocessing.cpu_count())
    except Exception:
        cores = 2
    # simple heuristic: 10% per thread, but cap to cpu count
    t = max(1, min(cores, max(1, int(limit_pct / 10))))
    return t

def _load_llama(model_path: str, ctx_tokens: int, cpu_limit: int) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp:
        return False

    try:
        threads = _threads_from_cpu_limit(cpu_limit)
        LLM = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=ctx_tokens,
            n_threads=threads,
        )
        LOADED_MODEL_PATH = model_path
        LLM_MODE = "llama"
        _log(f"loaded GGUF model: {model_path} (ctx={ctx_tokens}, threads={threads})")
        return True
    except Exception as e:
        _log(f"llama load failed: {e}")
        LLM = None
        LOADED_MODEL_PATH = None
        LLM_MODE = "none"
        return False

def _ensure_local_model(model_url: str, model_path: str, token: Optional[str], want_sha256: str) -> Optional[str]:
    """Ensure a local GGUF file exists; download if missing; verify optional sha256."""
    path = _coerce_model_path(model_url, model_path)
    if not os.path.exists(path):
        if not model_url:
            _log("no model file on disk and no model_url to download")
            return None
        if not _download(model_url, path, token):
            return None

    if want_sha256:
        try:
            got = _sha256_file(path)
            if got.lower() != want_sha256.lower():
                _log(f"sha256 mismatch: got={got} want={want_sha256} (refusing to load)")
                return None
        except Exception as e:
            _log(f"sha256 check failed (continuing without): {e}")
    return path

# ============================
# Ollama path (HTTP)
# ============================
def _ollama_ready(base_url: str, timeout: int = 2) -> bool:
    try:
        host, port = None, None
        # crude health check via socket connect to speed_fail quickly
        if base_url.startswith("http://"):
            hp = base_url[7:]
        elif base_url.startswith("https://"):
            hp = base_url[8:]
        else:
            hp = base_url
        hp = hp.strip("/").split("/")[0]
        if ":" in hp:
            host, port = hp.split(":", 1)
            port = int(port)
        else:
            host, port = hp, 80
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _ollama_generate(base_url: str, model_name: str, prompt: str, timeout: int = 20) -> str:
    """
    Minimal Ollama /api/generate call. Non-streaming.
    """
    try:
        url = base_url.rstrip("/") + "/api/generate"
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "top_p": 0.9,
                "repeat_penalty": 1.1
            }
        }
        data = json.dumps(payload).encode("utf-8")
        out = _http_post(url, data, headers={"Content-Type": "application/json"}, timeout=timeout)
        obj = json.loads(out.decode("utf-8"))
        return obj.get("response", "") or ""
    except urllib.error.HTTPError as e:
        _log(f"ollama HTTP {e.code}: {getattr(e, 'reason', '')}")
        return ""
    except Exception as e:
        _log(f"ollama error: {e}")
        return ""

def _model_name_from_url(model_url: str) -> str:
    """
    Best effort to derive a model name (only used for Ollama if user passes a name in model_url).
    If the URL isn't an Ollama name, caller should pass base_url and put the ACTUAL Ollama
    model name into 'model_path' or 'model_url' (we'll try both).
    """
    if not model_url:
        return "llama3"
    tail = model_url.strip("/").split("/")[-1]
    # Strip extension
    if "." in tail:
        tail = tail.split(".")[0]
    return tail or "llama3"

# ============================
# Public: ensure_loaded
# ============================
def ensure_loaded(
    *,
    model_url: str,
    model_path: str,
    model_sha256: str,
    ctx_tokens: int,
    cpu_limit: int,
    hf_token: Optional[str],
    base_url: str = ""
) -> bool:
    """
    Decide engine and load (or prepare) it.
    - If base_url provided and reachable: use Ollama mode (no local download needed here).
    - Else: local GGUF via llama-cpp, with optional HF download/check.
    """
    global LLM_MODE, LLM, LOADED_MODEL_PATH, OLLAMA_URL, DEFAULT_CTX
    DEFAULT_CTX = max(1024, int(ctx_tokens or 4096))

    base_url = (base_url or "").strip()
    if base_url:
        OLLAMA_URL = base_url
        if _ollama_ready(base_url):
            LLM_MODE = "ollama"
            LLM = None
            LOADED_MODEL_PATH = None
            _log(f"using Ollama at {base_url}")
            return True
        else:
            _log(f"Ollama not reachable at {base_url}; falling back to local mode")

    # Local mode
    LLM_MODE = "none"
    OLLAMA_URL = ""
    LLM = None
    LOADED_MODEL_PATH = None

    path = _ensure_local_model(model_url, model_path, hf_token, model_sha256 or "")
    if not path:
        _log("ensure_local_model failed")
        return False

    ok = _load_llama(path, DEFAULT_CTX, cpu_limit)
    return bool(ok)

# ============================
# Prompting
# ============================
def _prompt_for_rewrite(text: str, mood: str, allow_profanity: bool) -> str:
    # Keep it tiny + deterministic; good for small models too.
    sys_prompt = "You are a concise rewrite assistant. Improve clarity and tone. Keep factual content."
    if not allow_profanity:
        sys_prompt += " Avoid profanity."
    user = (
        "Rewrite the text clearly. Keep short, readable sentences.\n"
        f"Mood (light touch only): {mood or 'neutral'}\n\n"
        f"Text:\n{text}"
    )
    # Generic chat template that works well with many instruct models
    return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

# ============================
# Public: rewrite
# ============================
def rewrite(
    *,
    text: str,
    mood: str = "neutral",
    timeout: int = 12,
    cpu_limit: int = 80,
    models_priority: Optional[str] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: bool = False,
    ctx_tokens: int = 4096,
    hf_token: Optional[str] = None
) -> str:
    """
    Best-effort rewrite. Never crashes the caller. If LLM unavailable, returns input text.
    - If base_url is provided and reachable, use Ollama.
    - Else try local llama-cpp with GGUF (downloading first if needed).
    """
    global LLM_MODE, LLM, LOADED_MODEL_PATH, OLLAMA_URL, DEFAULT_CTX

    # Ensure engine ready once
    if LLM_MODE == "none":
        ensure_loaded(
            model_url=model_url,
            model_path=model_path,
            model_sha256=model_sha256,
            ctx_tokens=ctx_tokens,
            cpu_limit=cpu_limit,
            hf_token=hf_token,
            base_url=base_url
        )

    prompt = _prompt_for_rewrite(text, mood, allow_profanity)

    # OLLAMA path
    if LLM_MODE == "ollama" and OLLAMA_URL:
        # Pick a model name: prefer model_path (if it looks like a name), else derive from URL
        model_name = ""
        cand = (model_path or "").strip()
        if cand and "/" not in cand and not cand.endswith(".gguf"):
            model_name = cand
        else:
            model_name = _model_name_from_url(model_url)
        try:
            out = _ollama_generate(OLLAMA_URL, model_name, prompt, timeout=max(4, int(timeout)))
            out = (out or "").strip()
            return out if out else text
        except Exception as e:
            _log(f"ollama generate failed: {e}")
            return text

    # LLAMA-CPP path
    if LLM_MODE != "llama" or LLM is None:
        # try once to prepare local again
        ok = ensure_loaded(
            model_url=model_url,
            model_path=model_path,
            model_sha256=model_sha256,
            ctx_tokens=ctx_tokens,
            cpu_limit=cpu_limit,
            hf_token=hf_token,
            base_url=""  # force local
        )
        if not ok or LLM is None:
            _log("rewrite fallback: model not available")
            return text

    try:
        import signal

        def _alarm_handler(signum, frame):
            raise TimeoutError("rewrite timeout")

        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(max(1, int(timeout)))

        out = LLM(
            prompt,
            max_tokens=256,
            temperature=0.3,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=["</s>"]
        )

        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

        txt = (out.get("choices") or [{}])[0].get("text", "")
        return txt.strip() if txt else text

    except TimeoutError as e:
        _log(f"rewrite timeout: {e}")
        return text
    except Exception as e:
        _log(f"rewrite error: {e}")
        return text