#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (FULL, with EnviroGuard profiles + guaranteed riff fallback)
# - GGUF local loading via llama-cpp (if available)
# - Optional Ollama HTTP generation (if base_url provided & reachable)
# - Hugging Face downloads with Authorization header preserved across redirects
# - SHA256 optional integrity check
# - Hard timeouts (SIGALRM for local llama); best-effort, never crash callers
# - Message checks (max lines / soft-length guard)
# - Persona riffs (1–3 short lines), now with guaranteed fallback (lexicon/personality)
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
import re  # riff post-cleaning
import threading  # concurrency lock
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
CONFIG_PATH  = "/data/config.json"  # NEW: EnviroGuard profiles
SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"
SYS_PROMPT = ""

# global reentrant lock so multiple incoming messages don't collide
_GEN_LOCK = threading.RLock()

def _lock_timeout() -> int:
    """Env-configurable lock wait. Defaults to 300s to match your last working file."""
    try:
        v = int(os.getenv("LLM_LOCK_TIMEOUT_SECONDS", "300").strip())
        return max(1, min(300, v))
    except Exception:
        return 10

class _GenCritical:
    """Serialize LLM load/generation sections without deadlocks (best-effort; no raise)."""
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
# Files
# ============================
def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _read_options() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"options read failed ({OPTIONS_PATH}): {e}")
        return {}

def _read_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# ============================
# EnviroGuard env overrides + profiles
# ============================
def _int_env(name: str, default: Optional[int]) -> Optional[int]:
    try:
        v = os.getenv(name, "").strip()
        if not v:
            return default
        return int(v)
    except Exception:
        return default

def _resolve_enviroguard_from_config() -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], str]:
    """
    Read /data/config.json:
    {
      "enviroguard": {
        "profile": "manual"|"normal"|"hot"|"boost"|"auto",
        "temperature_c": 26,
        "threads": 3,   # optional explicit threads
        "profiles": {
          "manual":{"cpu_percent":20,"ctx_tokens":4096,"timeout_seconds":25},
          "normal":{"cpu_percent":30,"ctx_tokens":4096,"timeout_seconds":25},
          "hot":   {"cpu_percent":10,"ctx_tokens":4096,"timeout_seconds":25},
          "boost": {"cpu_percent":6, "ctx_tokens":4096,"timeout_seconds":25}
        },
        "thresholds": { "hot_c": 35, "boost_c": 18 }
      }
    }
    Returns (cpu, ctx, timeout, threads, chosen_profile_label)
    """
    cfg = (_read_config().get("enviroguard") or {})
    if not cfg:
        return None, None, None, None, "none"

    profiles = cfg.get("profiles") or {}
    profile = str(cfg.get("profile") or "auto").strip().lower()

    # temperature for auto
    temp_c = None
    try:
        env_temp = os.getenv("ENVGUARD_TEMP_C", "").strip()
        temp_c = float(env_temp) if env_temp else float(cfg.get("temperature_c"))
    except Exception:
        pass

    def _vals(name: str):
        p = profiles.get(name) or {}
        return p.get("cpu_percent"), p.get("ctx_tokens"), p.get("timeout_seconds")

    chosen = profile
    if profile in ("manual","normal","hot","boost"):
        cpu, ctx, to = _vals(profile)
    else:
        th = cfg.get("thresholds") or {}
        hot_c   = float(th.get("hot_c",   35.0))
        boost_c = float(th.get("boost_c", 18.0))
        if temp_c is None:
            chosen = "normal"
        elif temp_c >= hot_c:
            chosen = "hot"
        elif temp_c <= boost_c:
            chosen = "boost"
        else:
            chosen = "normal"
        cpu, ctx, to = _vals(chosen)

    # sanitize
    if cpu is not None: cpu = min(100, max(1, int(cpu)))
    if ctx  is not None: ctx  = max(256, int(ctx))
    if to   is not None: to   = max(2,   int(to))

    # explicit threads
    threads = None
    try:
        t = cfg.get("threads")
        if t is not None:
            threads = max(1, int(t))
    except Exception:
        pass

    # env overrides for threads win
    for var in ("LLAMA_THREADS","OMP_NUM_THREADS","ENVGUARD_THREADS"):
        v = os.getenv(var, "").strip()
        if v.isdigit():
            threads = max(1, int(v))
            break

    return cpu, ctx, to, threads, chosen

def _enviroguard_limits(default_ctx: Optional[int],
                        default_cpu: Optional[int],
                        default_timeout: Optional[int]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Original function retained for compatibility. Now merges:
      ENV → config profile → options.json (CPU only) → defaults.
    """
    # ENV first
    ctx_env = _int_env("ENVGUARD_CTX_TOKENS", None)
    cpu_env = _int_env("ENVGUARD_CPU_PERCENT", None)
    to_env  = _int_env("ENVGUARD_TIMEOUT_SECONDS", None)

    # Config profile
    cpu_cfg, ctx_cfg, to_cfg, _, which = _resolve_enviroguard_from_config()

    # options.json (CPU only) if still missing
    cpu_opt = None
    if cpu_env is None and cpu_cfg is None:
        try:
            cpu_opt = int(_read_options().get("llm_max_cpu_percent", 80))
        except Exception:
            cpu_opt = None

    cpu = (cpu_env if cpu_env is not None else (cpu_cfg if cpu_cfg is not None else (cpu_opt if cpu_opt is not None else default_cpu)))
    ctx = (ctx_env if ctx_env is not None else (ctx_cfg if ctx_cfg is not None else default_ctx))
    to  = (to_env  if to_env  is not None else (to_cfg  if to_cfg  is not None else default_timeout))

    if ctx is not None:
        try: ctx = max(256, int(ctx))
        except Exception: ctx = default_ctx
    if cpu is not None:
        try: cpu = min(100, max(1, int(cpu)))
        except Exception: cpu = default_cpu
    if to is not None:
        try: to = max(2, int(to))
        except Exception: to = default_timeout

    if (ctx != default_ctx) or (cpu != default_cpu) or (to != default_timeout):
        _log(f"EnviroGuard override -> ctx={ctx} cpu={cpu} timeout={to} (profile={which})")
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

# NEW: read CPU limit from options.json (used when config/env absent)
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
    """Keep Authorization header across redirects (Hugging Face needs this)."""
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
        cand.append((
            (opts.get("llm_model_url") or "").strip(),
            (opts.get("llm_model_path") or "").strip()
        ))
    elif choice:
        cand.append((
            (opts.get(f"llm_{choice}_url") or "").strip(),
            (opts.get(f"llm_{choice}_path") or "").strip()
        ))

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
# strip leaked meta tags from model output
# ============================
_META_LINE_RX = re.compile(
    r'^\s*(?:\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\]\s*|<<\s*/?\s*SYS\s*>>\s*|</?s>\s*)$',
    re.I | re.M
)
def _strip_meta_markers(s: str) -> str:
    if not s:
        return s
    # Drop pure marker lines
    out = _META_LINE_RX.sub("", s)
    # Remove inline fragments
    out = re.sub(r'(?:\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\])', '', out, flags=re.I)
    out = re.sub(r'<<\s*/?\s*SYS\s*>>', '', out, flags=re.I)
    out = out.replace("<s>", "").replace("</s>", "")
    # strip leaked "YOU ARE … REWRITER" echoes
    out = re.sub(
        r'^\s*you\s+are\s+(?:a|the)?\s*.*?\s*rewriter\.?\s*$',
        '',
        out,
        flags=re.I | re.M
    )
    # Clean leftover quotes/backticks-only wrappers
    out = out.strip().strip('`').strip().strip('"').strip("'").strip()
    # Collapse extra blank lines
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out

# ============================
# Core generation (shared)
# ============================
def _llama_generate(prompt: str, timeout: int = 12) -> str:
    """Generate text via local llama-cpp (non-streaming) with SIGALRM timeout."""
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
# Riff fallback (lexicon/personality)
# ============================
def _lexicon_default(persona: str, subject: str) -> str:
    p = (persona or "").lower().strip()
    if p == "rager":
        return "Send it. No flinch."
    if p == "nerd":
        return "Parsed, verified, shipped."
    if p == "jarvis":
        return "At your service."
    if p == "ops":
        return "On it. Eyes up."
    if p == "action":
        return "Objective locked."
    if p == "chick":
        return "Clean, sharp, done."
    if p == "dude":
        return "Chill. It’s handled."
    if p == "comedian":
        return "All good—no punchline needed."
    return subject or "Done."

def _riff_fallback(persona: str, subject: str) -> str:
    try:
        import personality  # optional
        q = None
        if hasattr(personality, "quip"):
            q = personality.quip(persona, with_emoji=False)
        elif hasattr(personality, "riff"):
            q = personality.riff(persona, subject, max_lines=1, with_emoji=False)
        if q:
            return (q if isinstance(q, str) else "\n".join(q)).strip()
    except Exception as e:
        _log(f"fallback riff (personality) failed: {e}")
    return _lexicon_default(persona, subject)

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
    g_ctx, g_cpu, g_to = _enviroguard_limits(ctx_tokens, cpu_limit, timeout)
    ctx_tokens = g_ctx if g_ctx is not None else ctx_tokens
    cpu_limit  = g_cpu if g_cpu is not None else cpu_limit
    timeout    = g_to  if g_to  is not None else timeout

    with _GenCritical(timeout):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_tokens,
                cpu_limit=cpu_limit,
                hf_token=hf_token,
            )
            if not ok:
                return text

        prompt = _prompt_for_rewrite(text, mood, allow_profanity)
        out = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path)
        final = out if out else text

    final = _strip_meta_markers(final)

    if max_lines:
        final = _trim_lines(final, max_lines)
    if max_chars:
        final = _soft_trim_chars(final, max_chars)

    return final

# ============================
# Public: riff  (guaranteed non-empty)
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
    Generate 1–3 very short riff lines. Always returns something (LLM or fallback).
    """
    _, _, g_to = _enviroguard_limits(None, None, timeout)
    timeout = g_to if g_to is not None else timeout

    with _GenCritical(timeout):
        if LLM_MODE == "none":
            limit = _cpu_limit_from_options(80)
            est_threads = _threads_from_cpu_limit(limit)
            _log(f"riff using cpu_limit={limit}% (threads≈{est_threads})")
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256="",
                ctx_tokens=2048,
                cpu_limit=limit,
                hf_token=None,
            )
            if not ok:
                return _riff_fallback(persona, subject)

        if LLM_MODE not in ("llama", "ollama"):
            return _riff_fallback(persona, subject)

        prompt = _prompt_for_riff(persona, subject, allow_profanity)
        out = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path)
        if not out:
            return _riff_fallback(persona, subject)

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    # Keep your original cleaning for riff output (simpler variant)
    cleaned: List[str] = []
    for ln in lines:
        ln = ln.lstrip("-•* ").strip()
        if ln:
            cleaned.append(ln)
        if len(cleaned) >= 3:
            break

    joined = "\n".join(cleaned[:3]) if cleaned else ""
    if not joined:
        return _riff_fallback(persona, subject)
    if len(joined) > 120:
        joined = joined[:119].rstrip() + "…"
    return joined

# ============================
# Public: persona_riff
# ============================
_INSTRUX_PATTERNS = [
    r'^\s*tone\s*:.*$',            # remove "Tone: ..." lines
    r'^\s*voice\s*:.*$',           # remove "Voice: ..." lines
    r'^\s*context\s*:.*$',         # remove "Context: ..." lines
    r'^\s*style\s*:.*$',           # remove "Style: ..." lines
    r'^\s*subject\s*:.*$',         # remove "Subject: ..." lines
    r'^\s*write\s+up\s+to\s+\d+.*$', # remove "Write up to ..." echoes
    r'^\s*\[image\]\s*$',          # remove bare [image]
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
        # Drop label-looking lines (colon in first 12 chars)
        if ":" in t[:12]:
            if re.match(r'^\s*(tone|voice|context|style|subject)\s*:', t, flags=re.I):
                continue
        # Strip common leak tokens inline
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
    Always returns at least one line via fallback if generation fails.
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

    with _GenCritical(timeout):
        if LLM_MODE == "none":
            limit = cpu_limit or _cpu_limit_from_options(80)
            est_threads = _threads_from_cpu_limit(limit)
            _log(f"persona_riff using cpu_limit={limit}% (threads≈{est_threads})")
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_tokens,
                cpu_limit=limit,
                hf_token=hf_token,
            )
            if not ok:
                return [_riff_fallback(persona, context.strip().splitlines()[0] if context else "Status")]

        if LLM_MODE not in ("llama", "ollama"):
            return [_riff_fallback(persona, context.strip().splitlines()[0] if context else "Status")]

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

        # persona style
        style_map = {
            "dude":      "laid-back, mellow, no jokes",
            "chick":     "sassy, clever, stylish",
            "nerd":      "precise, witty one-liners",
            "rager":     "short, profane bursts allowed",
            "comedian":  "only persona allowed to tell jokes",
            "action":    "stoic mission-brief style",
            "jarvis":    "polished butler style",
            "ops":       "terse, incident commander tone",
        }
        vibe = style_map.get((persona or "").lower().strip(), "neutral, keep it short")

        sys_rules = [
            f"Voice: {vibe}.",
            f"Write up to {max(1,int(max_lines or 3))} distinct one-liners. Each ≤ 140 chars.",
            "No bullets or numbering. No labels. No lists. No JSON.",
            "No quotes or catchphrases. No character or actor names.",
            "No explanations or meta-commentary. Output ONLY the lines.",
            "Do NOT tell jokes unless persona = comedian. Do NOT drift into another persona’s style.",
        ]
        if not allow_profanity:
            sys_rules.append("Avoid profanity.")
        if daypart:
            sys_rules.append(f"Daypart vibe (subtle): {daypart}.")
        if intensity:
            sys_rules.append(f"Persona intensity (subtle): {intensity}.")
        sys_prompt = " ".join(sys_rules)

        # Removed "Context:" label to prevent echo-leak
        user = (
            f"{context.strip()}\n\n"
            f"Write up to {max_lines} short lines in the requested voice."
        )
        prompt = f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

        raw = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path)
        if not raw:
            return [_riff_fallback(persona, context.strip().splitlines()[0] if context else "Status")]

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
    if not cleaned:
        return [_riff_fallback(persona, context.strip().splitlines()[0] if context else "Status")]
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
            rl = persona_riff(
                persona="nerd",
                context="Backup complete on NAS-01; rsync delta=2.3GB; checksums verified. [style_hint daypart=evening intensity=1.2 persona=nerd]",
                base_url=os.getenv("TEST_OLLAMA","").strip()
            )
            print("persona_riff sample ->", rl[:3])
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")