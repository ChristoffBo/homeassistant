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
SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"  # ADDITIVE: external system prompt file
SYS_PROMPT = ""  # ADDITIVE: cached system prompt contents

# ============================
# Logging
# ============================
def _log(msg: str):
    print(f"[llm] {msg}", flush=True)

# ============================
# ADDITIVE: System prompt loader
# ============================
def _load_system_prompt() -> str:
    try:
        if os.path.exists(SYSTEM_PROMPT_PATH):
            with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        _log(f"system_prompt load failed: {e}")
    return ""

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
# ADDITIVE: riff validator
# ============================
def _is_invalid_riff(s: str) -> bool:
    """Reject meta/instructional junk that should never surface as a riff."""
    if not s:
        return True
    t = s.strip().lower()
    bad_starts = ("tone:", "context:", "style:", "system:", "instructions:")
    if any(t.startswith(bs) for bs in bad_starts):
        return True
    if "json" in t or "schema" in t or "output must" in t:
        return True
    return False
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

# ... [UNCHANGED CONTENT OMITTED FOR BREVITY — stays identical until riff()] ...

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
    _, _, g_to = _enviroguard_limits(None, None, timeout)
    timeout = g_to if g_to is not None else timeout

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

    # ADDITIVE: validate & fallback
    if _is_invalid_riff(joined):
        try:
            from personality import quip  # fallback to lexicon quip
            return quip((persona or "neutral").lower(), with_emoji=False) or ""
        except Exception:
            return ""

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

    # [UNCHANGED prompt builder logic]

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
        if _is_invalid_riff(ln2):
            continue
        key = ln2.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(ln2)
        if len(cleaned) >= max(1, int(max_lines or 3)):
            break

    # ADDITIVE: fallback if nothing survived
    if not cleaned:
        try:
            from personality import quip
            q = quip((persona or "neutral").lower(), with_emoji=False)
            return [q] if q else []
        except Exception:
            return []

    return cleaned