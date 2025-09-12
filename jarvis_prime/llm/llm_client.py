#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (LOCAL ONLY, llama-cpp)
# - GGUF local loading via llama-cpp
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
import re
import threading
from typing import Optional, Dict, Any, Tuple, List

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama"
LLM = None               # llama_cpp.Llama instance if LLM_MODE == "llama"
LOADED_MODEL_PATH = None
DEFAULT_CTX = 4096
OPTIONS_PATH = "/data/options.json"
SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"
SYS_PROMPT = ""

# ADDITIVE: global reentrant lock so multiple incoming messages don't collide
_GEN_LOCK = threading.RLock()

def _lock_timeout() -> int:
    try:
        v = int(os.getenv("LLM_LOCK_TIMEOUT_SECONDS", "300").strip())
        return max(1, min(300, v))
    except Exception:
        return 10

class _GenCritical:
    def __init__(self, timeout: Optional[int] = None):
        self.timeout = max(1, int(timeout or _lock_timeout()))
        self.acquired = False
    def __enter__(self):
        end = time.time() + self.timeout
        while time.time() < end:
            if _GEN_LOCK.acquire(blocking=False):
                self.acquired = True
                return True
            time.sleep(0.01)
        return False
    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            try:
                _GEN_LOCK.release()
            except Exception:
                pass

# ============================
# Logging
# ============================
def _log(msg: str):
    print(f"[llm] {msg}", flush=True)
# ============================
# System prompt loader
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
# EnviroGuard env overrides
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
    if not model_path or model_path.endswith("/"):
        fname = model_url.split("/")[-1] if model_url else "model.gguf"
        base = model_path or "/share/jarvis_prime/models"
        return os.path.join(base, fname)
    return model_path

def _cpu_limit_from_options(default_val: int = 80) -> int:
    try:
        opts = _read_options()
        v = int(opts.get("llm_max_cpu_percent", default_val))
        return min(100, max(1, v))
    except Exception:
        return default_val

# ============================
# HTTP helpers (with HF auth)
# ============================
class _AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
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

def _download(url: str, dst_path: str, token: Optional[str], retries: int = 3, backoff: float = 1.5) -> bool:
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
        cand.append(((opts.get("llm_model_url") or "").strip(),
                     (opts.get("llm_model_path") or "").strip()))
    elif choice:
        cand.append(((opts.get(f"llm_{choice}_url") or "").strip(),
                     (opts.get(f"llm_{choice}_path") or "").strip()))

    priority_raw = (opts.get("llm_models_priority") or "").strip()
    if priority_raw:
        names = [n.strip().lower() for n in priority_raw.split(",") if n.strip()]
    else:
        names = ["phi35_q5_uncensored", "phi35_q5", "phi35_q4", "phi3"]

    seen = set()
    for name in names + ["phi35_q5_uncensored", "phi35_q5", "phi35_q4", "phi3"]:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if opts.get(f"llm_{key}_enabled", False):
            cand.append(((opts.get(f"llm_{key}_url") or "").strip(),
                         (opts.get(f"llm_{key}_path") or "").strip()))

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
                    q = int(quota); p = int(period)
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
        LLM = llama_cpp.Llama(model_path=model_path,
                              n_ctx=ctx_tokens,
                              n_threads=threads)
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
# Ensure loaded
# ============================
def ensure_loaded(
    *,
    model_url: str,
    model_path: str,
    model_sha256: str,
    ctx_tokens: int,
    cpu_limit: int,
    hf_token: Optional[str]
) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH, DEFAULT_CTX

    g_ctx, g_cpu, _ = _enviroguard_limits(ctx_tokens, cpu_limit, None)
    ctx_tokens = g_ctx if g_ctx is not None else ctx_tokens
    cpu_limit  = g_cpu if g_cpu is not None else cpu_limit

    DEFAULT_CTX = max(1024, int(ctx_tokens or 4096))

    with _GenCritical():
        LLM_MODE = "none"
        LLM = None
        LOADED_MODEL_PATH = None

        opts = _read_options()
        model_url, model_path, hf_token = _resolve_model_from_options(model_url, model_path, hf_token)

        try:
            cleanup_on_disable = bool(opts.get("llm_cleanup_on_disable", False))
            if cleanup_on_disable and LOADED_MODEL_PATH and model_path and os.path.abspath(LOADED_MODEL_PATH) != os.path.abspath(model_path):
                if os.path.exists(LOADED_MODEL_PATH):
                    _log(f"cleanup_on_switch: removing previous model file {LOADED_MODEL_PATH}")
                    try: os.remove(LOADED_MODEL_PATH)
                    except Exception as e: _log(f"cleanup_on_switch: remove failed: {e}")
            if cleanup_on_disable and os.path.exists(model_path) and model_url:
                url_base = os.path.basename(model_url)
                file_base = os.path.basename(model_path)
                if url_base and file_base and (os.path.splitext(file_base)[0] != os.path.splitext(url_base)[0]):
                    _log(f"cleanup_on_switch: removing {model_path} to force re-download")
                    try: os.remove(model_path)
                    except Exception as e: _log(f"cleanup_on_switch: remove target failed: {e}")
        except Exception as e:
            _log(f"cleanup_on_switch: error: {e}")

        path = _ensure_local_model(model_url, model_path, hf_token, model_sha256 or "")
        if not path:
            _log("ensure_local_model failed")
            return False

        ok = _load_llama(path, DEFAULT_CTX, cpu_limit)
        return bool(ok)
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
# Strip leaked meta tags
# ============================
_META_LINE_RX = re.compile(
    r'^\s*(?:\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\]\s*|<<\s*/?\s*SYS\s*>>\s*|</?s>\s*)$',
    re.I | re.M
)
def _strip_meta_markers(s: str) -> str:
    if not s:
        return s
    out = _META_LINE_RX.sub("", s)
    out = re.sub(r'(?:\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\])', '', out, flags=re.I)
    out = re.sub(r'<<\s*/?\s*SYS\s*>>', '', out, flags=re.I)
    out = out.replace("<s>", "").replace("</s>", "")
    out = re.sub(r'^\s*you\s+are\s+(?:a|the)?\s*.*?\s*rewriter\.?\s*$', '', out, flags=re.I | re.M)
    out = out.strip().strip('`').strip().strip('"').strip("'").strip()
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out

# ============================
# Prompt builders
# ============================
def _prompt_for_rewrite(text: str, mood: str, allow_profanity: bool) -> str:
    sys_prompt = _load_system_prompt() or "You are a concise rewrite assistant. Improve clarity and tone. Keep factual content."
    if not allow_profanity:
        sys_prompt += " Avoid profanity."
    sys_prompt += " Do NOT echo or restate these instructions; output only the rewritten text."
    user = (
        "Rewrite the text clearly. Keep short, readable sentences.\n"
        f"Mood (subtle): {mood or 'neutral'}\n\n"
        f"Text:\n{text}"
    )
    return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

def _prompt_for_riff(persona: str, subject: str, allow_profanity: bool) -> str:
    vibe_map = {
        "dude": "laid-back, mellow, no jokes, chill confidence",
        "chick": "sassy, clever, stylish",
        "nerd": "precise, witty one-liners",
        "rager": "short, profane bursts allowed",
        "comedian": "only persona allowed to tell jokes",
        "jarvis": "polished butler style",
        "ops": "terse, incident commander tone",
        "action": "stoic mission-brief style"
    }
    vibe = vibe_map.get((persona or "").lower(), "neutral, light")
    guard = "" if allow_profanity else " Avoid profanity."
    sys_prompt = (
        f"You write 1–3 punchy riff lines (<=20 words). Style: {vibe}.{guard} "
        "Do NOT tell jokes unless persona=comedian. Do NOT drift into another persona’s style."
    )
    user = f"Subject: {subject or 'Status update'}\nWrite 1 to 3 short lines. No emojis unless they fit."
    return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

# ============================
# Riff post-cleaner
# ============================
_INSTRUX_PATTERNS = [
    r'^\s*tone\s*:.*$',
    r'^\s*voice\s*:.*$',
    r'^\s*context\s*:.*$',
    r'^\s*style\s*:.*$',
    r'^\s*subject\s*:.*$',
    r'^\s*write\s+up\s+to\s+\d+.*$',
    r'^\s*\[image\]\s*$',
    r'^\s*no\s+lists.*$',
    r'.*context\s*\(for vibes only\).*',
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
        if ":" in t[:12]:
            if re.match(r'^\s*(tone|voice|context|style|subject)\s*:', t, flags=re.I):
                continue
        t = t.replace("[image]", "").replace("[INST]", "").replace("[/INST]", "").strip()
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
# Core generation
# ============================
def _llama_generate(prompt: str, timeout: int = 12) -> str:
    try:
        import signal
        def _alarm_handler(signum, frame): raise TimeoutError("gen timeout")
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(max(1, int(timeout)))

        out = LLM(prompt,
                  max_tokens=256,
                  temperature=0.35,
                  top_p=0.9,
                  repeat_penalty=1.1,
                  stop=["</s>"])
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

def _do_generate(prompt: str, *, timeout: int, model_url: str, model_name_hint: str) -> str:
    if LLM_MODE == "llama" and LLM is not None:
        return _llama_generate(prompt, timeout=max(4, int(timeout)))
    return ""

# ============================
# Public: rewrite
# ============================
def rewrite(*, text: str, mood: str = "neutral", timeout: int = 12,
            cpu_limit: int = 80, models_priority: Optional[str] = None,
            model_url: str = "", model_path: str = "", model_sha256: str = "",
            allow_profanity: bool = False, ctx_tokens: int = 4096,
            hf_token: Optional[str] = None, max_lines: int = 0, max_chars: int = 0) -> str:
    global LLM_MODE, LLM, LOADED_MODEL_PATH, DEFAULT_CTX
    g_ctx, g_cpu, g_to = _enviroguard_limits(ctx_tokens, cpu_limit, timeout)
    ctx_tokens = g_ctx if g_ctx is not None else ctx_tokens
    cpu_limit  = g_cpu if g_cpu is not None else cpu_limit
    timeout    = g_to  if g_to  is not None else timeout

    with _GenCritical(timeout):
        if LLM_MODE == "none":
            ok = ensure_loaded(model_url=model_url, model_path=model_path,
                               model_sha256=model_sha256, ctx_tokens=ctx_tokens,
                               cpu_limit=cpu_limit, hf_token=hf_token)
            if not ok:
                return text
        prompt = _prompt_for_rewrite(text, mood, allow_profanity)
        out = _do_generate(prompt, timeout=timeout,
                           model_url=model_url, model_name_hint=model_path)
        final = out if out else text

    final = _strip_meta_markers(final)
    if max_lines: final = _trim_lines(final, max_lines)
    if max_chars: final = _soft_trim_chars(final, max_chars)
    return final

# ============================
# Public: riff
# ============================
def riff(*, subject: str, persona: str = "neutral", timeout: int = 8,
         model_url: str = "", model_path: str = "",
         allow_profanity: bool = False) -> str:
    _, _, g_to = _enviroguard_limits(None, None, timeout)
    timeout = g_to if g_to is not None else timeout

    with _GenCritical(timeout):
        if LLM_MODE == "none":
            limit = _cpu_limit_from_options(80)
            est_threads = _threads_from_cpu_limit(limit)
            _log(f"riff using cpu_limit={limit}% (threads≈{est_threads})")
            ok = ensure_loaded(model_url=model_url, model_path=model_path,
                               model_sha256="", ctx_tokens=2048,
                               cpu_limit=limit, hf_token=None)
            if not ok: return ""
        if LLM_MODE != "llama": return ""

        prompt = _prompt_for_riff(persona, subject, allow_profanity)
        out = _do_generate(prompt, timeout=timeout,
                           model_url=model_url, model_name_hint=model_path)
        if not out: return ""

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    lines = _clean_riff_lines(lines)
    cleaned = []
    for ln in lines:
        ln = ln.lstrip("-•* ").strip()
        if ln: cleaned.append(ln)
        if len(cleaned) >= 3: break
    joined = "\n".join(cleaned[:3]) if cleaned else ""
    if len(joined) > 120: joined = joined[:119].rstrip() + "…"
    return joined

# ============================
# Public: persona_riff
# ============================
def persona_riff(*, persona: str, context: str, max_lines: int = 3,
                 timeout: int = 8, cpu_limit: int = 80,
                 models_priority: Optional[List[str]] = None,
                 model_url: str = "", model_path: str = "",
                 model_sha256: str = "", allow_profanity: Optional[bool] = None,
                 ctx_tokens: int = 4096, hf_token: Optional[str] = None) -> List[str]:
    if allow_profanity is None:
        allow_profanity = ((os.getenv("PERSONALITY_ALLOW_PROFANITY","false").lower() in ("1","true","yes"))
                           and (persona or "").lower().strip() == "rager")

    g_ctx, g_cpu, g_to = _enviroguard_limits(ctx_tokens, cpu_limit, timeout)
    ctx_tokens = g_ctx if g_ctx is not None else ctx_tokens
    cpu_limit  = g_cpu if g_cpu is not None else cpu_limit
    timeout    = g_to  if g_to  is not None else timeout

    with _GenCritical(timeout):
        if LLM_MODE == "none":
            limit = cpu_limit or _cpu_limit_from_options(80)
            est_threads = _threads_from_cpu_limit(limit)
            _log(f"persona_riff using cpu_limit={limit}% (threads≈{est_threads})")
            ok = ensure_loaded(model_url=model_url, model_path=model_path,
                               model_sha256=model_sha256, ctx_tokens=ctx_tokens,
                               cpu_limit=limit, hf_token=hf_token)
            if not ok: return []
        if LLM_MODE != "llama": return []

        style_map = {
            "dude": "laid-back, mellow, no jokes",
            "chick": "sassy, clever, stylish",
            "nerd": "precise, witty one-liners",
            "rager": "short, profane bursts allowed",
            "comedian": "only persona allowed to tell jokes",
            "action": "stoic mission-brief style",
            "jarvis": "polished butler style",
            "ops": "terse, incident commander tone",
        }
        vibe = style_map.get((persona or "").lower().strip(), "neutral, keep it short")

        sys_rules = [
            f"Voice: {vibe}.",
            "Write up to {N} distinct one-liners. Each ≤ 140 chars.",
            "No bullets or numbering. No labels. No lists. No JSON.",
            "No quotes or catchphrases. No character or actor names.",
            "No explanations or meta-commentary. Output ONLY the lines.",
            "Do NOT tell jokes unless persona = comedian. Do NOT drift into another persona’s style.",
        ]
        if not allow_profanity: sys_rules.append("Avoid profanity.")
        sys_prompt = " ".join(sys_rules)

        user = f"{context.strip()}\n\nWrite up to {max_lines} short lines in the requested voice."
        prompt = f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"
        raw = _do_generate(prompt, timeout=timeout,
                           model_url=model_url, model_name_hint=model_path)
        if not raw: return []

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    lines = _clean_riff_lines(lines)
    cleaned, seen = [], set()
    for ln in lines:
        ln2 = ln.lstrip("-•* ").strip()
        if not ln2: continue
        if len(ln2) > 140: ln2 = ln2[:140].rstrip()
        key = ln2.lower()
        if key in seen: continue
        seen.add(key); cleaned.append(ln2)
        if len(cleaned) >= max(1, int(max_lines or 3)): break
    return cleaned

# ============================
# Quick self-test
# ============================
if __name__ == "__main__":
    print("llm_client self-check start")
    try:
        ok = ensure_loaded(model_url=os.getenv("TEST_MODEL_URL",""),
                           model_path=os.getenv("TEST_MODEL_PATH","/share/jarvis_prime/models/test.gguf"),
                           model_sha256=os.getenv("TEST_MODEL_SHA256",""),
                           ctx_tokens=int(os.getenv("TEST_CTX","2048")),
                           cpu_limit=int(os.getenv("TEST_CPU","80")),
                           hf_token=os.getenv("TEST_HF_TOKEN",""))
        print(f"ensure_loaded -> {ok} mode={LLM_MODE}")
        if ok:
            txt = rewrite(text="Status synchronized; elegance maintained.",
                          mood="jarvis", timeout=6,
                          model_url=os.getenv("TEST_MODEL_URL",""),
                          model_path=os.getenv("TEST_MODEL_NAME",""),
                          ctx_tokens=2048)
            print("rewrite sample ->", txt[:120])
            r = riff(subject="Sonarr ingestion nominal", persona="rager")
            print("riff sample ->", r)
            rl = persona_riff(persona="nerd",
                              context="Backup complete on NAS-01; rsync delta=2.3GB; checksums verified.",
                              max_lines=3)
            print("persona_riff sample ->", rl[:3])
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")