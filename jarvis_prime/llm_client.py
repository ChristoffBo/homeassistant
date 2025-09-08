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
#   persona_riff(...)

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
import re  # ADDITIVE: for riff post-cleaning
from typing import Optional, Dict, Any, Tuple, List

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama" | "ollama"
LLM = None               # llama_cpp.Llama instance if LLM_MODE == "llama"
LOADED_MODEL_PATH = None
OLLAMA_URL = ""          # base url if using ollama (e.g., http://127.0.0.1:11434)
DEFAULT_CTX = 4096
OPTIONS_PATH = "/data/options.json"

# ============================
# Logging
# ============================
def _log(msg: str):
    print(f"[llm] {msg}", flush=True)

# ============================
# ADDITIVE: EnviroGuard env overrides
# ============================
def _int_env(name: str, default: Optional[int]) -> Optional[int]:
    try:
        v = os.getenv(name, "").strip()
        if not v:
            return default
        return int(v)
    except Exception:
        return default

def _enviroguard_limits(default_ctx: Optional[int],
                        default_cpu: Optional[int],
                        default_timeout: Optional[int]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    ctx = _int_env("ENVGUARD_CTX_TOKENS", default_ctx)
    cpu = _int_env("ENVGUARD_CPU_PERCENT", default_cpu)
    to  = _int_env("ENVGUARD_TIMEOUT_SECONDS", default_timeout)
    if ctx is not None:
        try:
            ctx = max(256, int(ctx))
        except Exception:
            ctx = default_ctx
    if cpu is not None:
        try:
            cpu = min(100, max(1, int(cpu)))
        except Exception:
            cpu = default_cpu
    if to is not None:
        try:
            to = max(2, int(to))
        except Exception:
            to = default_timeout
    if (ctx != default_ctx) or (cpu != default_cpu) or (to != default_timeout):
        _log(f"EnviroGuard override -> ctx={ctx} cpu={cpu} timeout={to}")
    return ctx, cpu, to

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
        auth = req.headers.get("Authorization")
        if auth:
            new.add_unredirected_header("Authorization", auth)
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
            if e.code in (401, 403, 404):
                return False
        except Exception as e:
            _log(f"download failed: {e}")
        time.sleep(backoff ** attempt)
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
# Options resolver (add-on config awareness)
# ============================
def _read_options() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"options read failed ({OPTIONS_PATH}): {e}")
        return {}

def _resolve_model_from_options(
    model_url: str,
    model_path: str,
    hf_token: Optional[str]
) -> Tuple[str, str, Optional[str]]:
    """
    If caller didn't pass model_url/path, derive them from /data/options.json.
    Supports:
      - llm_choice == "custom" -> llm_model_url/path
      - llm_choice == "<name>" -> llm_<name>_url/path
      - Fallback to first enabled of our known set, in llm_models_priority order
    """
    url = (model_url or "").strip()
    path = (model_path or "").strip()
    token = (hf_token or "").strip() or None

    if url and path:
        return url, path, token

    opts = _read_options()
    choice = (opts.get("llm_choice") or "").strip()
    autodl = bool(opts.get("llm_autodownload", True))
    if not token:
        t = (opts.get("llm_hf_token") or "").strip()
        token = t or None

    cand: List[Tuple[str, str]] = []
    if choice.lower() == "custom":
        cand.append((
            (opts.get("llm_model_url") or "").strip(),
            (opts.get("llm_model_path") or "").strip()
        ))
    elif choice:
        cand.append((
            (opts.get(f"llm_{choice}_url") or "").strip(),
            (opts.get(f"llm_{choice}_path") or "").strip()
        ))

    # Build order from priority string (if present), else default to include uncensored too
    priority_raw = (opts.get("llm_models_priority") or "").strip()
    if priority_raw:
        names = [n.strip().lower() for n in priority_raw.split(",") if n.strip()]
    else:
        names = ["phi35_q5_uncensored", "phi35_q5", "phi35_q4", "phi3"]

    # Collect enabled candidates in order (with a safe tail)
    seen = set()
    for name in names + ["phi35_q5_uncensored", "phi35_q5", "phi35_q4", "phi3"]:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if opts.get(f"llm_{key}_enabled", False):
            cand.append((
                (opts.get(f"llm_{key}_url") or "").strip(),
                (opts.get(f"llm_{key}_path") or "").strip()
            ))

    for u, p in cand:
        if u and p:
            _log(f"options resolver -> choice={choice or 'auto'} url={os.path.basename(u)} path={os.path.basename(p)} autodownload={autodl}")
            return u, p, token

    return url, path, token

# ============================
# CPU / Threads (throttling)
# ============================
def _parse_cpuset_list(s: str) -> int:
    total = 0
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                total += int(b) - int(a) + 1
            except Exception:
                pass
        else:
            try:
                total += 1
            except Exception:
                pass
    return total or 0

def _available_cpus() -> int:
    """Best-effort count of CPUs available to this process (cgroups/affinity-aware)."""
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except Exception:
        pass
    try:
        with open("/sys/fs/cgroup/cpu.max", "r", encoding="utf-8") as f:
            raw = f.read().strip().split()
            if len(raw) == 2:
                quota, period = raw
                if quota != "max":
                    q = int(quota)
                    p = int(period)
                    if q > 0 and p > 0:
                        return max(1, q // p)
    except Exception:
        pass
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r", encoding="utf-8") as f:
            q = int(f.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r", encoding="utf-8") as f:
            p = int(f.read().strip())
        if q > 0 and p > 0:
            return max(1, q // p)
    except Exception:
        pass
    for p in ("/sys/fs/cgroup/cpuset.cpus", "/sys/fs/cgroup/cpuset/cpuset.cpus"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                n = _parse_cpuset_list(f.read().strip())
                if n > 0:
                    return n
        except Exception:
            pass
    return max(1, os.cpu_count() or 1)

def _threads_from_cpu_limit(limit_pct: int) -> int:
    """Map a CPU percentage to an integer thread count, respecting cgroup limits."""
    for env_var in ("LLAMA_THREADS", "OMP_NUM_THREADS"):
        v = os.getenv(env_var, "").strip()
        if v.isdigit():
            t = max(1, int(v))
            _log(f"env override {env_var} -> threads={t}")
            return t
    cores = _available_cpus()
    try:
        pct = max(1, min(100, int(limit_pct or 100)))
    except Exception:
        pct = 100
    t = max(1, int(math.ceil(cores * (pct / 100.0))))
    t = min(cores, t)
    _log(f"cpu_limit={pct}% -> threads={t} (avail_cpus={cores})")
    return t

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

def _load_llama(model_path: str, ctx_tokens: int, cpu_limit: int) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp:
        return False
    try:
        threads = _threads_from_cpu_limit(cpu_limit)
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        os.environ.setdefault("LLAMA_THREADS", str(threads))
        # llama-cpp params verified in docs (n_ctx, n_threads)
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
        hp = base_url
        if base_url.startswith("http://"):
            hp = base_url[7:]
        elif base_url.startswith("https://"):
            hp = base_url[8:]
        hp = hp.strip("/").split("/")[0]
        if ":" in hp:
            host, port = hp.split(":", 1); port = int(port)
        else:
            host, port = hp, 80
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _ollama_generate(base_url: str, model_name: str, prompt: str, timeout: int = 20) -> str:
    """Minimal Ollama /api/generate call. Non-streaming."""
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

    g_ctx, g_cpu, _ = _enviroguard_limits(ctx_tokens, cpu_limit, None)
    ctx_tokens = g_ctx if g_ctx is not None else ctx_tokens
    cpu_limit  = g_cpu if g_cpu is not None else cpu_limit

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

    LLM_MODE = "none"
    OLLAMA_URL = ""
    LLM = None
    LOADED_MODEL_PATH = None

    # Read options to check cleanup behavior and priority resolution
    opts = _read_options()

    # Resolve URL/path/Token from options if not provided
    model_url, model_path, hf_token = _resolve_model_from_options(model_url, model_path, hf_token)

    # --- CLEANUP ON SWITCH ----------------------------------------------
    # If a previous model is loaded and target path differs, optionally delete the old file
    try:
        cleanup_on_disable = bool(opts.get("llm_cleanup_on_disable", False))
        if cleanup_on_disable and LOADED_MODEL_PATH and model_path and os.path.abspath(LOADED_MODEL_PATH) != os.path.abspath(model_path):
            if os.path.exists(LOADED_MODEL_PATH):
                _log(f"cleanup_on_switch: removing previous model file {LOADED_MODEL_PATH}")
                try:
                    os.remove(LOADED_MODEL_PATH)
                except Exception as e:
                    _log(f"cleanup_on_switch: remove failed: {e}")
        # If target path exists but filename doesn't align with URL basename, optionally refresh it
        if cleanup_on_disable and os.path.exists(model_path) and model_url:
            url_base = os.path.basename(model_url)
            file_base = os.path.basename(model_path)
            if url_base and file_base and (os.path.splitext(file_base)[0] != os.path.splitext(url_base)[0]):
                _log(f"cleanup_on_switch: target path exists with different basename; removing {model_path} to force re-download")
                try:
                    os.remove(model_path)
                except Exception as e:
                    _log(f"cleanup_on_switch: remove target failed: {e}")
    except Exception as e:
        _log(f"cleanup_on_switch: error: {e}")
    # --------------------------------------------------------------------

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
# ADDITIVE: Riff post-cleaner to remove leaked instructions/boilerplate
# ============================
_INSTRUX_PATTERNS = [
    r'^\s*no\s+lists.*$',
    r'.*context\s*\(for vibes only\).*',
    r'^\s*subject\s*:.*$',
    r'^\s*style\s*:.*$',
    r'^\s*you\s+write\s+a\s+single.*$',
    r'^\s*write\s+1.*lines?.*$',
    r'^\s*avoid\s+profanity.*$',
    r'^\s*<<\s*sys\s*>>.*$',
    r'^\s*\[/?\s*inst\s*\]\s*$',
    r'^\s*<\s*/?\s*s\s*>\s*$',
]
_INSTRUX_RX = [re.compile(p, re.I) for p in _INSTRUX_PATTERNS]

def _clean_riff_lines(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        skip = False
        for rx in _INSTRUX_RX:
            if rx.search(t):
                skip = True
                break
        if skip:
            continue
        t = re.sub(r'\bcontext\s*:.*$', '', t, flags=re.I).strip()
        t = t.replace("</s>", "").replace("<s>", "").strip()
        if t:
            cleaned.append(t)
    return cleaned

# ============================
# Core generation (shared)
# ============================
def _llama_generate(prompt: str, timeout: int = 12) -> str:
    """Generate text via local llama-cpp (non-streaming)."""
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
    """Route to Ollama or llama-cpp, depending on LLM_MODE."""
    if LLM_MODE == "ollama" and OLLAMA_URL:
        name = ""
        cand = (model_name_hint or "").strip()
        if cand and "/" not in cand and not cand.endswith(".gguf"):
            name = cand
        else:
            name = _model_name_from_url(model_url)
        return _ollama_generate(OLLAMA_URL, name, prompt, timeout=max(4, int(timeout)))

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
    models_priority: Optional[str] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: bool = False,
    ctx_tokens: int = 4096,
    hf_token: Optional[str] = None,
    max_lines: int = 0,
    max_chars: int = 0
) -> str:
    """Best-effort rewrite. If LLM unavailable, returns input text."""
    global LLM_MODE, LLM, LOADED_MODEL_PATH, OLLAMA_URL, DEFAULT_CTX

    g_ctx, g_cpu, g_to = _enviroguard_limits(ctx_tokens, cpu_limit, timeout)
    ctx_tokens = g_ctx if g_ctx is not None else ctx_tokens
    cpu_limit  = g_cpu if g_cpu is not None else cpu_limit
    timeout    = g_to  if g_to  is not None else timeout

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
    final = out if out else text

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
    # ADD: EnviroGuard timeout override
    _, _, g_to = _enviroguard_limits(None, None, timeout)
    timeout = g_to if g_to is not None else timeout

    # NEW: ensure engine ready (lazy-load)
    if LLM_MODE == "none":
        ensure_loaded(
            model_url=model_url,
            model_path=model_path,
            model_sha256="",
            ctx_tokens=2048,
            cpu_limit=80,
            hf_token=None,
            base_url=base_url
        )

    if LLM_MODE not in ("llama", "ollama"):
        return ""

    prompt = _prompt_for_riff(persona, subject, allow_profanity)
    out = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path)
    if not out:
        return ""

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    lines = _clean_riff_lines(lines)

    cleaned: List[str] = []
    for ln in lines:
        ln = ln.lstrip("-•* ").strip()
        if ln:
            cleaned.append(ln)
        if len(cleaned) >= 3:
            break

    joined = "\n".join(cleaned[:3]) if cleaned else ""
    if len(joined) > 120:
        joined = joined[:119].rstrip() + "…"
    return joined

# ============================
# Public: persona_riff
# ============================
def persona_riff(
    *,
    persona: str,
    context: str,
    max_lines: int = 3,
    timeout: int = 8,
    cpu_limit: int = 80,
    models_priority: Optional[List[str]] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: Optional[bool] = None,
    ctx_tokens: int = 4096,
    hf_token: Optional[str] = None
) -> List[str]:
    """
    Generate 1–N SHORT persona-flavored lines from context (title + body). Returns a list of lines.
    """
    if allow_profanity is None:
        allow_profanity = (
            (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
            and (persona or "").lower().strip() == "rager"
        )

    g_ctx, g_cpu, g_to = _enviroguard_limits(ctx_tokens, cpu_limit, timeout)
    ctx_tokens = g_ctx if g_ctx is not None else ctx_tokens
    cpu_limit  = g_cpu if g_cpu is not None else cpu_limit
    timeout    = g_to  if g_to  is not None else timeout

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

    if LLM_MODE not in ("llama", "ollama"):
        return []

    # Optional embedded style hint
    daypart = None
    intensity = None
    try:
        m = re.search(r"\[style_hint\s+daypart=(\w+)\s+intensity=([0-9.]+)\s+persona=([\w-]+)\]", context, flags=re.I)
        if m:
            daypart = m.group(1)
            intensity = m.group(2)
            context = re.sub(r"\[style_hint.*?\]", "", context).strip()
    except Exception:
        pass

    style_map = {
        "dude":      "laid-back, surfer-slacker zen, breezy optimism; never quote movies; mellow confidence",
        "chick":     "glam-savvy, sassy, clever, Elle-style corporate sparkle; playful but sharp; no name-drops",
        "nerd":      "precise, witty, engineering one-liners; strongly typed humor; no jargon dumps",
        "rager":     "brutally direct, high-agency, colorful profanity allowed; zero politeness; keep it terse",
        "comedian":  "deadpan, meta-humor, self-aware; punchlines without setup; dry and tight",
        "action":    "stoic, hard-cut action one-liners; mission tone; no catchphrases from films",
        "jarvis":    "polished butler AI, calm and poised; subtle HAL-like serenity; never mention HAL or films",
        "ops":       "terse, operational, incident-commander brevity; factual bite; no fluff",
    }
    vibe = style_map.get((persona or "").lower().strip(), "neutral, keep it short")

    sys_rules = [
        f"Voice: {vibe}.",
        "Write up to {N} distinct one-liners. Each ≤ 140 chars.",
        "No bullets or numbering. No labels. No lists. No JSON.",
        "No quotes or catchphrases. No character or actor names.",
        "No explanations or meta-commentary. Output ONLY the lines.",
    ]
    if not allow_profanity:
        sys_rules.append("Avoid profanity.")
    if daypart:
        sys_rules.append(f"Daypart vibe (subtle): {daypart}.")
    if intensity:
        sys_rules.append(f"Persona intensity (subtle): {intensity}.")
    sys_prompt = " ".join(sys_rules)

    user = (
        "Context (for vibe only; do NOT summarize it verbosely):\n"
        f"{context.strip()}\n\n"
        f"Write up to {max_lines} short lines in the requested voice."
    )
    prompt = f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

    raw = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path)
    if not raw:
        return []

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    lines = _clean_riff_lines(lines)
    cleaned: List[str] = []
    seen: set = set()
    for ln in lines:
        ln2 = ln.lstrip("-•* ").strip()
        if not ln2:
            continue
        if len(ln2) > 140:
            ln2 = ln2[:140].rstrip()
        key = ln2.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(ln2)
        if len(cleaned) >= max(1, int(max_lines or 3)):
            break
    return cleaned

# ============================
# Quick self-test (optional)
# ============================
if __name__ == "__main__":
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
            rl = persona_riff(persona="nerd", context="Backup complete on NAS-01; rsync delta=2.3GB; checksums verified. [style_hint daypart=evening intensity=1.2 persona=nerd]", base_url=os.getenv("TEST_OLLAMA","").strip())
            print("persona_riff sample ->", rl[:3])
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")
