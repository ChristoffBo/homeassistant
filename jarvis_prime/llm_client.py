#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (FULL)
# - GGUF local loading via llama-cpp (if available)
# - Optional Ollama HTTP generation (if base_url provided & reachable)
# - Hugging Face downloads with Authorization header preserved across redirects
# - SHA256 optional integrity check
# - Hard timeouts; best-effort, never crash callers
# - Message checks (max lines / soft-length guard)
# - Persona riffs (1–3 short lines)
#
# Public entry points expected by the rest of Jarvis:
#   ensure_loaded(...)
#   rewrite(...)
#   riff(...)

from __future__ import annotations
import os
import sys
import json
import time
import math
import hashlib
import socket
import random
import urllib.request
import urllib.error
import http.client
from typing import Optional, Dict, Any, Tuple, List

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama" | "ollama"
LLM = None               # llama_cpp.Llama instance if LLM_MODE == "llama"
LOADED_MODEL_PATH = None
OLLAMA_URL = ""          # base url if using ollama (e.g., http://127.0.0.1:11434)
DEFAULT_CTX = 4096

# ============================
# Logging
# ============================
def _log(msg: str):
    print(f"[llm] {msg}", flush=True)

# ============================
# Small utils
# ============================
def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _coerce_model_path(model_url: str, model_path: str) -> str:
    """If model_path is a directory or empty, derive filename from URL."""
    if not model_path or model_path.endswith("/"):
        fname = model_url.split("/")[-1] if model_url else "model.gguf"
        base = model_path or "/share/jarvis_prime/models"
        return os.path.join(base, fname)
    return model_path

# ============================
# HTTP helpers (with HF auth)
# ============================
class _AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Keep Authorization header across redirects (Hugging Face needs this).
    Python's urllib strips 'Authorization' on redirect by default.
    """
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        # Copy Authorization if original had it
        auth = req.headers.get("Authorization")
        if auth:
            new.add_unredirected_header("Authorization", auth)
        # Also propagate cookies if any
        cookie = req.headers.get("Cookie")
        if cookie:
            new.add_unredirected_header("Cookie", cookie)
        return new

def _build_opener_with_headers(headers: Dict[str, str]):
    handlers = [_AuthRedirectHandler()]
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = list(headers.items())
    return opener

def _http_get(url: str, headers: Dict[str, str], timeout: int = 180) -> bytes:
    opener = _build_opener_with_headers(headers)
    with opener.open(url, timeout=timeout) as r:
        return r.read()

def _http_post(url: str, data: bytes, headers: Dict[str, str], timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = _build_opener_with_headers({})
    with opener.open(req, timeout=timeout) as r:
        return r.read()

def _download(url: str, dst_path: str, token: Optional[str], retries: int = 3, backoff: float = 1.5) -> bool:
    """Download to dst_path, sending HF token if provided; retry on transient errors."""
    try:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    except Exception:
        pass

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    # HF likes this; also helps proxies
    headers["User-Agent"] = "JarvisPrime/1.1 (urllib)"

    for attempt in range(1, max(1, retries) + 1):
        try:
            _log(f"downloading: {url} -> {dst_path} (try {attempt}/{retries})")
            buf = _http_get(url, headers=headers, timeout=180)
            with open(dst_path, "wb") as f:
                f.write(buf)
            _log("downloaded ok")
            return True
        except urllib.error.HTTPError as e:
            _log(f"download failed: HTTP {e.code} {getattr(e, 'reason', '')}")
            # 401/403 → don't keep retrying unless token might have propagated
            if e.code in (401, 403, 404):
                return False
        except Exception as e:
            _log(f"download failed: {e}")
        # backoff
        time.sleep(backoff ** attempt)
    return False

def _ensure_local_model(model_url: str, model_path: str, token: Optional[str], want_sha256: str) -> Optional[str]:
    """
    Ensure a local GGUF file exists; download if missing; verify optional sha256.
    """
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
# llama-cpp path (local GGUF)
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
    # simple heuristic: 10% per thread; cap to cpu count
    t = max(1, min(cores, max(1, int(limit_pct / 10))))
    return t

def _load_llama(model_path: str, ctx_tokens: int, cpu_limit: int) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp:
        return False
    try:
        threads = _threads_from_cpu_limit(cpu_limit)
        # use chat template inference defaults that are widely compatible
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

# ============================
# Ollama path (HTTP)
# ============================
def _ollama_ready(base_url: str, timeout: int = 2) -> bool:
    try:
        # crude health check via socket connect
        hp = base_url
        if base_url.startswith("http://"):
            hp = base_url[7:]
        elif base_url.startswith("https://"):
            hp = base_url[8:]
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
    if not model_url:
        return "llama3"
    tail = model_url.strip("/").split("/")[-1]
    if "." in tail:
        tail = tail.split(".")[0]
    return tail or "llama3"

# ============================
# Message checks / guards
# ============================
def _trim_lines(text: str, max_lines: int) -> str:
    lines = (text or "").splitlines()
    if max_lines and len(lines) > max_lines:
        keep = lines[:max_lines]
        if keep:
            keep[-1] = keep[-1].rstrip() + " …"
        return "\n".join(keep)
    return text

def _soft_trim_chars(text: str, max_chars: int) -> str:
    if max_chars and len(text) > max_chars:
        return text[: max(0, max_chars - 1)].rstrip() + "…"
    return text

# ============================
# Ensure loaded
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
# Prompt builders
# ============================
def _prompt_for_rewrite(text: str, mood: str, allow_profanity: bool) -> str:
    sys_prompt = "You are a concise rewrite assistant. Improve clarity and tone. Keep factual content."
    if not allow_profanity:
        sys_prompt += " Avoid profanity."
    user = (
        "Rewrite the text clearly. Keep short, readable sentences.\n"
        f"Mood (subtle): {mood or 'neutral'}\n\n"
        f"Text:\n{text}"
    )
    return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

def _prompt_for_riff(persona: str, subject: str, allow_profanity: bool) -> str:
    vibe = {
        "rager": "gritty, no-nonsense, ruthless brevity",
        "nerd": "clever, techy, one-liner",
        "dude": "chill, upbeat",
        "ops": "blunt, incident-commander tone",
        "jarvis": "polished, butler",
        "comedian": "wry, dry"
    }.get((persona or "").lower(), "neutral, light")
    guard = "" if allow_profanity else " Avoid profanity."
    sys_prompt = f"You write a single punchy riff line (<=20 words). Style: {vibe}.{guard}"
    user = f"Subject: {subject or 'Status update'}\nWrite 1 to 3 short lines. No emojis unless they fit."
    return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

# ============================
# Core generation (shared)
# ============================
def _llama_generate(prompt: str, timeout: int = 12) -> str:
    """
    Generate text via local llama-cpp (non-streaming).
    """
    try:
        import signal

        def _alarm_handler(signum, frame):
            raise TimeoutError("gen timeout")

        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(max(1, int(timeout)))

        out = LLM(
            prompt,
            max_tokens=256,
            temperature=0.35,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=["</s>"]
        )

        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

        txt = (out.get("choices") or [{}])[0].get("text", "")
        return (txt or "").strip()
    except TimeoutError as e:
        _log(f"llama timeout: {e}")
        return ""
    except Exception as e:
        _log(f"llama error: {e}")
        return ""

def _do_generate(prompt: str, *, timeout: int, base_url: str, model_url: str, model_name_hint: str) -> str:
    """
    Route to Ollama or llama-cpp, depending on LLM_MODE.
    """
    # Ollama path
    if LLM_MODE == "ollama" and OLLAMA_URL:
        name = ""
        cand = (model_name_hint or "").strip()
        if cand and "/" not in cand and not cand.endswith(".gguf"):
            name = cand
        else:
            name = _model_name_from_url(model_url)
        return _ollama_generate(OLLAMA_URL, name, prompt, timeout=max(4, int(timeout)))

    # Local path
    if LLM_MODE == "llama" and LLM is not None:
        return _llama_generate(prompt, timeout=max(4, int(timeout)))

    return ""

# ============================
# Public: rewrite
# ============================
def rewrite(
    *,
    text: str,
    mood: str = "neutral",
    timeout: int = 12,
    cpu_limit: int = 80,
    models_priority: Optional[str] = None,   # kept for compat; unused in this client
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: bool = False,
    ctx_tokens: int = 4096,
    hf_token: Optional[str] = None,
    # message checks
    max_lines: int = 0,
    max_chars: int = 0
) -> str:
    """
    Best-effort rewrite. If LLM unavailable, returns input text.
    """
    global LLM_MODE, LLM, LOADED_MODEL_PATH, OLLAMA_URL, DEFAULT_CTX

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
    out = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path)

    # Fallback: return original text on empty
    final = out if out else text

    # Message checks
    if max_lines:
        final = _trim_lines(final, max_lines)
    if max_chars:
        final = _soft_trim_chars(final, max_chars)

    return final

# ============================
# Public: riff
# ============================
def riff(
    *,
    subject: str,
    persona: str = "neutral",
    timeout: int = 8,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    allow_profanity: bool = False
) -> str:
    """
    Generate 1–3 very short riff lines for the bottom of a card.
    Returns empty string if engine unavailable.
    """
    if LLM_MODE not in ("llama", "ollama"):
        # no engine loaded → empty riff (non-fatal)
        return ""

    prompt = _prompt_for_riff(persona, subject, allow_profanity)
    out = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path)
    if not out:
        return ""

    # Keep 1–3 short lines
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    cleaned: List[str] = []
    for ln in lines:
        # kill markdown bullets if the model added them
        ln = ln.lstrip("-•* ").strip()
        if ln:
            cleaned.append(ln)
        if len(cleaned) >= 3:
            break

    # Hard limit to ~120 chars for riff block
    joined = "\n".join(cleaned[:3]) if cleaned else ""
    if len(joined) > 120:
        joined = joined[:119].rstrip() + "…"
    return joined

# ============================
# Quick self-test (optional)
# ============================
if __name__ == "__main__":
    # Minimal no-crash check (does not download unless envs provided)
    print("llm_client self-check start")
    try:
        ok = ensure_loaded(
            model_url=os.getenv("TEST_MODEL_URL",""),
            model_path=os.getenv("TEST_MODEL_PATH","/share/jarvis_prime/models/test.gguf"),
            model_sha256=os.getenv("TEST_MODEL_SHA256",""),
            ctx_tokens=int(os.getenv("TEST_CTX","2048")),
            cpu_limit=int(os.getenv("TEST_CPU","80")),
            hf_token=os.getenv("TEST_HF_TOKEN",""),
            base_url=os.getenv("TEST_OLLAMA","").strip()
        )
        print(f"ensure_loaded -> {ok} mode={LLM_MODE}")
        if ok:
            txt = rewrite(
                text="Status synchronized; elegance maintained.",
                mood="jarvis",
                timeout=6,
                base_url=os.getenv("TEST_OLLAMA","").strip(),
                model_url=os.getenv("TEST_MODEL_URL",""),
                model_path=os.getenv("TEST_MODEL_NAME",""),
                ctx_tokens=2048
            )
            print("rewrite sample ->", txt[:120])
            r = riff(subject="Sonarr ingestion nominal", persona="rager", base_url=os.getenv("TEST_OLLAMA","").strip())
            print("riff sample ->", r)
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")