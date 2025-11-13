#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (EnviroGuard-first, hard caps, Phi-family chat format, Lexi fallback riffs)
#
# FIXED: Thread-safe timeout using threading.Timer instead of signal.alarm
#
# Public entry points:
#   ensure_loaded(...)
#   rewrite(...)
#   riff(...)         → routes to persona_riff()
#   persona_riff(...)
#   submit_task(...)  → async task submission
#   get_task_status(...)

from __future__ import annotations
import os
import sys
import json
import time
import math
import hashlib
import socket
import urllib.request
import urllib.error
import http.client
import re
import threading
import uuid
from typing import Optional, Dict, Any, Tuple, List
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import signal
import traceback
import subprocess
import select

# ============================
# CRASH PROTECTION - Install signal handlers FIRST
# ============================
_LLM_CRASHED = False
_CRASH_COUNT = 0
_CRASH_TIMESTAMPS = deque(maxlen=10)

def _handle_segfault(signum, frame):
    """Catch segfault and disable LLM instead of dying"""
    global _LLM_CRASHED, _CRASH_COUNT
    _LLM_CRASHED = True
    _CRASH_COUNT += 1
    _CRASH_TIMESTAMPS.append(time.time())
    
    print("\n" + "="*60, file=sys.stderr)
    print("[LLM CRASH PROTECTION] Segmentation fault caught!", file=sys.stderr)
    print(f"[LLM CRASH PROTECTION] Crash #{_CRASH_COUNT} detected", file=sys.stderr)
    print("[LLM CRASH PROTECTION] LLM disabled - falling back to Lexicon", file=sys.stderr)
    print("[LLM CRASH PROTECTION] All other Jarvis services continue normally", file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)
    
    # Set environment flag so all modules know LLM is dead
    os.environ["LLM_EMERGENCY_DISABLED"] = "true"
    os.environ["LLM_ENABLED"] = "false"
    
    # Don't exit - let Python exception handling take over
    raise RuntimeError("LLM segmentation fault - emergency disabled")

def _handle_sigbus(signum, frame):
    """Catch bus error (memory alignment issues)"""
    global _LLM_CRASHED, _CRASH_COUNT
    _LLM_CRASHED = True
    _CRASH_COUNT += 1
    _CRASH_TIMESTAMPS.append(time.time())
    
    print("\n" + "="*60, file=sys.stderr)
    print("[LLM CRASH PROTECTION] Bus error caught!", file=sys.stderr)
    print(f"[LLM CRASH PROTECTION] Crash #{_CRASH_COUNT} detected", file=sys.stderr)
    print("[LLM CRASH PROTECTION] LLM disabled - falling back to Lexicon", file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)
    
    os.environ["LLM_EMERGENCY_DISABLED"] = "true"
    os.environ["LLM_ENABLED"] = "false"
    raise RuntimeError("LLM bus error - emergency disabled")

def _handle_sigabrt(signum, frame):
    """Catch abort signal (out of memory, etc)"""
    global _LLM_CRASHED, _CRASH_COUNT
    _LLM_CRASHED = True
    _CRASH_COUNT += 1
    _CRASH_TIMESTAMPS.append(time.time())
    
    print("\n" + "="*60, file=sys.stderr)
    print("[LLM CRASH PROTECTION] Abort signal caught!", file=sys.stderr)
    print(f"[LLM CRASH PROTECTION] Crash #{_CRASH_COUNT} detected", file=sys.stderr)
    print("[LLM CRASH PROTECTION] LLM disabled - falling back to Lexicon", file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)
    
    os.environ["LLM_EMERGENCY_DISABLED"] = "true"
    os.environ["LLM_ENABLED"] = "false"
    raise RuntimeError("LLM abort - emergency disabled")

# Install handlers
signal.signal(signal.SIGSEGV, _handle_segfault)
signal.signal(signal.SIGBUS, _handle_sigbus)
signal.signal(signal.SIGABRT, _handle_sigabrt)

print("[LLM] Crash protection installed (SIGSEGV, SIGBUS, SIGABRT)", file=sys.stderr)

# ============================
# Worker Process Management
# ============================
def _start_worker_process(model_path: str, ctx_tokens: int, threads: int) -> bool:
    """Start isolated worker process for LLM"""
    global _WORKER_PROCESS, LLM_MODE, LOADED_MODEL_PATH
    
    if _is_llm_crashed():
        _log("Worker start blocked - previous crash")
        return False
    
    worker_path = "/app/llm_worker.py"
    if not os.path.exists(worker_path):
        _log(f"Worker not found at {worker_path}")
        return False
    
    try:
        _log(f"Starting LLM worker process")
        _WORKER_PROCESS = subprocess.Popen(
            [sys.executable, worker_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,  # Worker logs go to main stderr
            bufsize=1,
            universal_newlines=True
        )
        
        _log(f"Worker started (PID: {_WORKER_PROCESS.pid})")
        
        # Test with ping
        response = _call_worker("ping", {}, timeout=5.0)
        if not response or not response.get("success"):
            _log("Worker ping failed")
            _stop_worker_process()
            return False
        
        # Load model
        _log(f"Loading model in worker: {model_path}")
        response = _call_worker("load", {
            "model_path": model_path,
            "ctx_tokens": ctx_tokens,
            "threads": threads
        }, timeout=60.0)
        
        if not response or not response.get("success"):
            error = response.get("error") if response else "No response"
            _log(f"Worker model load failed: {error}")
            _stop_worker_process()
            return False
        
        LLM_MODE = "worker"
        LOADED_MODEL_PATH = model_path
        _log(f"Worker loaded model successfully")
        return True
        
    except Exception as e:
        _log(f"Failed to start worker: {e}")
        _stop_worker_process()
        return False

def _stop_worker_process():
    """Stop worker process"""
    global _WORKER_PROCESS
    
    if _WORKER_PROCESS is None:
        return
    
    try:
        _WORKER_PROCESS.terminate()
        _WORKER_PROCESS.wait(timeout=5)
    except Exception:
        try:
            _WORKER_PROCESS.kill()
        except Exception:
            pass
    
    _WORKER_PROCESS = None
    _log("Worker stopped")

def _check_worker_alive() -> bool:
    """Check if worker is still alive"""
    global _WORKER_PROCESS, _LLM_CRASHED, _CRASH_COUNT, _CRASH_TIMESTAMPS
    
    if _WORKER_PROCESS is None:
        return False
    
    # Check if died
    if _WORKER_PROCESS.poll() is not None:
        exit_code = _WORKER_PROCESS.returncode
        
        _log("="*60)
        _log(f"WORKER PROCESS DIED (exit code: {exit_code})")
        _log("LLM disabled - falling back to Lexicon")
        _log("All other Jarvis services continue normally")
        _log("="*60)
        
        _LLM_CRASHED = True
        _CRASH_COUNT += 1
        _CRASH_TIMESTAMPS.append(time.time())
        _WORKER_PROCESS = None
        
        os.environ["LLM_EMERGENCY_DISABLED"] = "true"
        os.environ["LLM_ENABLED"] = "false"
        
        return False
    
    return True

def _call_worker(method: str, params: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    """Call worker with JSON-RPC"""
    global _WORKER_PROCESS
    
    if not _check_worker_alive():
        return None
    
    try:
        # Send request
        request = json.dumps({"method": method, "params": params})
        _WORKER_PROCESS.stdin.write(request + "\n")
        _WORKER_PROCESS.stdin.flush()
        
        # Read response with timeout
        start = time.time()
        while time.time() - start < timeout:
            if not _check_worker_alive():
                return None
            
            # Non-blocking read
            ready, _, _ = select.select([_WORKER_PROCESS.stdout], [], [], 0.1)
            
            if ready:
                line = _WORKER_PROCESS.stdout.readline()
                if line:
                    return json.loads(line.strip())
        
        _log(f"Worker call timeout: {method}")
        return None
        
    except Exception as e:
        _log(f"Worker call failed: {e}")
        return None

def _worker_generate(prompt: str, max_tokens: int, temperature: float, stops: List[str]) -> Optional[str]:
    """Generate text via worker process"""
    response = _call_worker("generate", {
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stops": stops
    }, timeout=max(30.0, max_tokens * 0.5))
    
    if response and response.get("success"):
        return response.get("text")
    return None

# ---------------------------
# EnviroGuard safety sync
# ---------------------------
try:
    with open("/data/options.json", "r", encoding="utf-8") as f:
        _opts = json.load(f)
    if not _opts.get("llm_enabled", True):
        os.environ["LLM_ENABLED"] = "false"
    else:
        os.environ["LLM_ENABLED"] = "true"
except Exception as e:
    print(f"[llm_client] EnviroGuard sync failed: {e}", flush=True)

# ---- RAG (optional) ----
try:
    from rag import inject_context  # /app/rag.py
except Exception:
    def inject_context(user_msg: str, top_k: int = 5) -> str:
        return "(RAG unavailable)"
# ------------------------

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama" | "ollama" | "worker"
LLM = None               # llama_cpp.Llama instance if LLM_MODE == "llama"
LOADED_MODEL_PATH = None
OLLAMA_URL = ""          # base url if using ollama (e.g., http://127.0.0.1:11434)
DEFAULT_CTX = 4096
OPTIONS_PATH = "/data/options.json"
SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"

# Model metadata (for auto grammar & stops)
_MODEL_ARCH = ""
_CHAT_TEMPLATE = ""
_MODEL_NAME_HINT = ""

# Global reentrant lock so multiple incoming messages don't collide
_GEN_LOCK = threading.RLock()

# ============================
# Worker Process State
# ============================
_WORKER_PROCESS: Optional[subprocess.Popen] = None
_WORKER_LOCK = threading.Lock()
_WORKER_AVAILABLE = os.path.exists("/app/llm_worker.py")

# ============================
# Async Task Queue (NEW)
# ============================
# Single worker = only 1 LLM call at a time (prevents CPU overheating)
_LLM_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_TASK_RESULTS: Dict[str, Dict[str, Any]] = {}
_TASK_LOCK = threading.Lock()

def submit_task(func, *args, **kwargs) -> str:
    """
    Submit LLM task to background worker. Returns task_id immediately.
    UI can poll get_task_status(task_id) for results.
    """
    task_id = str(uuid.uuid4())
    
    def _run():
        try:
            result = func(*args, **kwargs)
            with _TASK_LOCK:
                _TASK_RESULTS[task_id] = {'status': 'complete', 'result': result}
        except Exception as e:
            with _TASK_LOCK:
                _TASK_RESULTS[task_id] = {'status': 'error', 'error': str(e)}
    
    with _TASK_LOCK:
        _TASK_RESULTS[task_id] = {'status': 'processing'}
    
    _LLM_EXECUTOR.submit(_run)
    _log(f"task submitted: {task_id}")
    return task_id

def get_task_status(task_id: str) -> Dict[str, Any]:
    """Get status of submitted task."""
    with _TASK_LOCK:
        return _TASK_RESULTS.get(task_id, {'status': 'not_found'})

# ============================
# Lock timeout and critical section
# ============================
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

def _extract_riff_training_block(full_text: str) -> str:
    """
    Legacy stub: we no longer inject RIFF TRAINING for riffs to keep prompts lean.
    """
    return ""

# ============================
# Persona-token scrubbing
# ============================
_PERSONA_TOKENS = ("dude","chick","nerd","rager","comedian","jarvis","ops","action","tappit","neutral")
_PERS_LEAD_SEQ_RX = re.compile(r'^(?:\s*(?:' + "|".join(_PERSONA_TOKENS) + r')\.\s*)+', flags=re.I)
_PERS_AFTER_COLON_RX = re.compile(r'(:\s*)(?:(?:' + "|".join(_PERSONA_TOKENS) + r')\.\s*)+', flags=re.I)
_PERS_AFTER_BREAK_RX = re.compile(r'([.!?]\s+|[;,\-–—]\s+)(?:(?:' + "|".join(_PERSONA_TOKENS) + r')\.\s*)+', flags=re.I)

def _scrub_persona_tokens(s: str) -> str:
    """
    Remove persona name tokens when they appear at the very start, after any colon,
    or after sentence/separator breaks. Iterates until stable to handle chains like
    'jarvis. jarvis.' or 'nerd. comedian.' anywhere in the line.
    """
    if not s:
        return s
    prev = None
    cur = s
    while prev != cur:
        prev = cur
        cur = _PERS_LEAD_SEQ_RX.sub("", cur).lstrip()
        cur = _PERS_AFTER_COLON_RX.sub(r"\1", cur)
        cur = _PERS_AFTER_BREAK_RX.sub(r"\1", cur)
    cur = re.sub(r"\s{2,}", " ", cur).strip()
    return cur

# ----------------------------
# NEW: transport tag stripper
# ----------------------------
_TRANSPORT_TAG_RX = re.compile(
    r'^\s*(?:\[(?:smtp|proxy|http|https|gotify|webhook|apprise|ntfy|email|mailer|forward|poster)\]\s*)+',
    flags=re.I
)
def _strip_transport_tags(s: str) -> str:
    if not s:
        return s
    prev = None
    cur = s
    while prev != cur:
        prev = cur
        cur = _TRANSPORT_TAG_RX.sub("", cur).lstrip()
    cur = re.sub(r'^\s*\[(?:smtp|proxy|http|https|gotify|webhook|apprise|ntfy|email|mailer|forward|poster)\]\s*$',
                 '', cur, flags=re.I|re.M)
    return cur

# NEW: subject extractor
def _extract_subject_from_context(ctx: str) -> str:
    m = re.search(r"Subject:\s*(.+)", ctx, flags=re.I)
    subj = (m.group(1) if m else ctx or "").strip()
    subj = _strip_transport_tags(subj)
    return re.sub(r"\s+", " ", subj)[:140]

def _sanitize_context_subject(ctx: str) -> str:
    """Find 'Subject: ...' inside context and scrub persona tokens and transport tags from the subject."""
    if not ctx:
        return ctx
    m = re.search(r"(Subject:\s*)(.+)", ctx, flags=re.I)
    if not m:
        return ctx
    prefix, raw = m.group(1), m.group(2)
    cleaned = _strip_transport_tags(_scrub_persona_tokens(raw))
    return ctx[:m.start(1)] + prefix + cleaned + ctx[m.end(2):]

# ============================
# Options helpers
# ============================
def _read_options() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"options read failed ({OPTIONS_PATH}): {e}")
        return {}

def _is_llm_crashed() -> bool:
    """Check if LLM has crashed and should be disabled"""
    global _LLM_CRASHED
    return _LLM_CRASHED or os.getenv("LLM_EMERGENCY_DISABLED") == "true"

def _get_int_opt(opts: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(opts.get(key, default))
    except Exception:
        return default

# ============================
# Profile resolution (EnviroGuard-first)
# ============================
def _current_profile() -> Tuple[str, int, int, int]:
    """
    Resolve active profile (EnviroGuard-first) and return:
      (name, cpu_percent, ctx_tokens, timeout_seconds)
    Precedence:
      1) EnviroGuard table: llm_enviroguard_profiles (string or dict)
      2) Flat/nested (manual/hot/normal/boost or llm_profiles/profiles)
      3) Global knobs (llm_max_cpu_percent / llm_ctx_tokens / llm_timeout_seconds)
      4) Hard defaults
    """
    opts = _read_options()
    prof_name = (opts.get("llm_power_profile")
                 or opts.get("power_profile")
                 or os.getenv("LLM_POWER_PROFILE")
                 or "normal").strip().lower()

    try:
        _log(f"opts keys: {sorted(list(opts.keys()))[:12]}{' ...' if len(opts.keys())>12 else ''}")
    except Exception:
        pass

    profiles: Dict[str, Dict[str, Any]] = {}
    source = ""
    enviroguard_active = False

    # 1) EnviroGuard sovereign
    eg = opts.get("llm_enviroguard_profiles")
    if isinstance(eg, str) and eg.strip():
        try:
            eg_dict = json.loads(eg)
            if isinstance(eg_dict, dict) and eg_dict:
                for k, v in eg_dict.items():
                    if isinstance(v, dict):
                        profiles[k.strip().lower()] = v
                if profiles:
                    source = "enviroguard(string)"
                    enviroguard_active = True
        except Exception as e:
            _log(f"enviroguard profiles parse error: {e}")
    elif isinstance(eg, dict) and eg:
        for k, v in eg.items():
            if isinstance(v, dict):
                profiles[k.strip().lower()] = v
        if profiles:
            source = "enviroguard(dict)"
            enviroguard_active = True

    # 2) Flat/nested only if EnviroGuard not present
    if not profiles:
        for key in ("manual", "hot", "normal", "boost"):
            v = opts.get(key)
            if isinstance(v, dict):
                profiles[key] = v
        nested = opts.get("llm_profiles") or opts.get("profiles")
        if isinstance(nested, dict):
            for k, v in nested.items():
                if isinstance(v, dict):
                    profiles[k.strip().lower()] = v
        if profiles and not source:
            source = "flat/nested"

    # 3) Global knobs fallback
    if not profiles:
        cpu = opts.get("llm_max_cpu_percent")
        ctx = opts.get("llm_ctx_tokens")
        to  = opts.get("llm_timeout_seconds")
        if cpu is not None or ctx is not None or to is not None:
            def _maybe_int(x, d):
                try:
                    return int(str(x).strip())
                except Exception:
                    return d
            profiles[prof_name] = {
                "cpu_percent": _maybe_int(cpu, 80),
                "ctx_tokens": _maybe_int(ctx, 4096),
                "timeout_seconds": _maybe_int(to, 25),
            }
            source = "global_knobs"

    pdata = (profiles.get(prof_name)
             or profiles.get("normal")
             or (next(iter(profiles.values()), {}) if profiles else {}))

    if not pdata:
        _log("profile resolution: NO profiles found -> using hard defaults (80/4096/25)")
    cpu_percent = int(pdata.get("cpu_percent", 80))
    ctx_tokens = int(pdata.get("ctx_tokens", 4096))
    timeout_seconds = int(pdata.get("timeout_seconds", 25))

    _log(f"EnviroGuard active: {enviroguard_active}")
    _log(f"profile: src={source or 'defaults'} active='{prof_name}' cpu_percent={cpu_percent} ctx_tokens={ctx_tokens} timeout_seconds={timeout_seconds}")
    return prof_name, cpu_percent, ctx_tokens, timeout_seconds

# ============================
# CPU / Threads / Affinity
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
                int(part)
                total += 1
            except Exception:
                pass
    return total or 0

def _available_cpus() -> int:
    # cgroup / affinity aware detection
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

def _pin_affinity(n: int) -> List[int]:
    """
    Hard-cap scheduler to the first n CPUs from current affinity set.
    Returns the list we pinned to.
    """
    if not hasattr(os, "sched_getaffinity") or not hasattr(os, "sched_setaffinity"):
        return []
    try:
        current = sorted(list(os.sched_getaffinity(0)))
        if n >= len(current):
            _log(f"affinity: keeping existing CPUs {current}")
            return current
        target = set(current[:max(1, n)])
        os.sched_setaffinity(0, target)
        pinned = sorted(list(os.sched_getaffinity(0)))
        _log(f"affinity: pinned to CPUs {pinned}")
        return pinned
    except Exception as e:
        _log(f"affinity pin failed (continuing): {e}")
        return []

def _threads_from_cpu_limit(limit_pct: int) -> int:
    cores = _available_cpus()
    opts = _read_options()

    eg = opts.get("llm_enviroguard_profiles")
    eg_enabled = bool(opts.get("llm_enviroguard_enabled", True))
    eg_active = False
    if eg_enabled:
        try:
            if isinstance(eg, str) and eg.strip():
                eg_active = isinstance(json.loads(eg), dict)
            elif isinstance(eg, dict):
                eg_active = True
        except Exception:
            eg_active = False

    if eg_active:
        try:
            pct = max(1, min(100, int(limit_pct or 100)))
        except Exception:
            pct = 100
        t = max(1, min(cores, int(math.floor(cores * (pct / 100.0)))))
        _log(f"threads: EnviroGuard enforced -> {t} (avail={cores}, limit={pct}%)")
        return t

    try:
        forced_threads = int(opts.get("llm_threads", 0) or 0)
    except Exception:
        forced_threads = 0
    if forced_threads > 0:
        t = max(1, min(cores, forced_threads))
        _log(f"threads: override via llm_threads={forced_threads} -> using {t} (avail={cores})")
        return t

    try:
        pct = max(1, min(100, int(limit_pct or 100)))
    except Exception:
        pct = 100
    t = max(1, min(cores, int(math.floor(cores * (pct / 100.0)))))
    _log(f"threads: derived from limit -> {t} (avail={cores}, limit={pct}%)")
    return t

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

def _http_post(url: str, data: bytes, headers: Dict[str, str], timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = urllib.request.build_opener()
    with opener.open(req, timeout=timeout) as r:
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

def _coerce_model_path(model_url: str, model_path: str) -> str:
    if not model_path or model_path.endswith("/"):
        fname = model_url.split("/")[-1] if model_url else "model.gguf"
        base = model_path or "/share/jarvis_prime/models"
        return os.path.join(base, fname)
    return model_path

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
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            got = h.hexdigest()
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

def _update_model_metadata():
    global _MODEL_ARCH, _CHAT_TEMPLATE
    try:
        meta = getattr(LLM, "metadata", None)
        if callable(meta):
            meta = LLM.metadata()
        if isinstance(meta, dict):
            _MODEL_ARCH = str(meta.get("general.architecture") or "")
            _CHAT_TEMPLATE = str(meta.get("tokenizer.chat_template") or "")
            if _CHAT_TEMPLATE:
                _log(f"Using gguf chat template: {_CHAT_TEMPLATE[:120]}...")
    except Exception:
        pass

def _is_phi3_family() -> bool:
    s = " ".join([_MODEL_ARCH, _CHAT_TEMPLATE]).lower()
    return ("phi3" in s) or ("<|user|>" in s and "<|assistant|>" in s and "<|end|>" in s)

def _stops_for_model() -> List[str]:
    if _is_phi3_family():
        return ["<|end|>", "<|endoftext|>"]
    return ["</s>", "[/INST]"]

def _should_use_grammar_auto() -> bool:
    if _is_phi3_family():
        return False
    if "INST" in _CHAT_TEMPLATE or "llama" in (_CHAT_TEMPLATE or "").lower():
        return True
    return False

def _load_llama(model_path: str, ctx_tokens: int, cpu_limit: int) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH, _LLM_CRASHED
    
    # Check if already crashed
    if _is_llm_crashed():
        _log("_load_llama: blocked - previous crash detected")
        return False
    
    threads = _threads_from_cpu_limit(cpu_limit)
    
    # Try worker process first (safest - crash isolation)
    if _WORKER_AVAILABLE:
        _log("Attempting worker process (isolated)")
        with _WORKER_LOCK:
            if _start_worker_process(model_path, ctx_tokens, threads):
                return True
            _log("Worker process failed - falling back to in-process")
    
    # Fallback to in-process (old behavior - no crash protection)
    _log("Loading model in-process (NOT crash-protected)")
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp:
        return False
    
    # Check memory before load
    try:
        with open('/proc/meminfo') as f:
            meminfo = dict((line.split()[0].rstrip(':'), int(line.split()[1])) 
                          for line in f.readlines() if len(line.split()) > 1)
            available_mb = meminfo.get('MemAvailable', 0) // 1024
            required_mb = 3000  # Minimum for Phi-4
            
            if available_mb < required_mb:
                _log(f"WARNING: Low memory ({available_mb}MB < {required_mb}MB required)")
                _log("Reducing context window to save memory")
                ctx_tokens = min(ctx_tokens, 4096)  # Emergency reduction
    except Exception as e:
        _log(f"Memory check failed: {e}")
    
    try:
        # HARD caps & pinning to prevent oversubscription
        pinned = _pin_affinity(threads)  # may be [] if unsupported
        os.environ["OMP_NUM_THREADS"] = str(threads)
        os.environ["OMP_DYNAMIC"] = "FALSE"
        os.environ["OMP_PROC_BIND"] = "TRUE"
        os.environ["OMP_PLACES"] = "cores"
        os.environ["LLAMA_THREADS"] = str(threads)
        os.environ["GGML_NUM_THREADS"] = str(threads)
        _log(f"thread env -> OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')} "
             f"OMP_DYNAMIC={os.environ.get('OMP_DYNAMIC')} "
             f"OMP_PROC_BIND={os.environ.get('OMP_PROC_BIND')} "
             f"OMP_PLACES={os.environ.get('OMP_PLACES')} "
             f"GGML_NUM_THREADS={os.environ.get('GGML_NUM_THREADS')} "
             f"affinity={'/'.join(map(str, pinned)) if pinned else 'unchanged'}")

        LLM = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=ctx_tokens,
            n_threads=threads,
            n_threads_batch=threads,   # keep batch path aligned with main threads
            n_batch=128,
            n_ubatch=128
        )
        _update_model_metadata()
        LOADED_MODEL_PATH = model_path
        LLM_MODE = "llama"
        _log(f"loaded GGUF model (in-process): {model_path} (ctx={ctx_tokens}, threads={threads})")
        return True
        
    except Exception as e:
        _log(f"llama load FAILED: {e}")
        _log(f"Traceback: {traceback.format_exc()}")
        
        # Mark as crashed and disable
        _LLM_CRASHED = True
        os.environ["LLM_EMERGENCY_DISABLED"] = "true"
        os.environ["LLM_ENABLED"] = "false"
        
        LLM = None
        LOADED_MODEL_PATH = None
        LLM_MODE = "none"
        
        _log("LLM permanently disabled - falling back to Lexicon")
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

def _ollama_generate(base_url: str, model_name: str, prompt: str, timeout: int = 20, max_tokens: int = 0, stops: Optional[List[str]] = None) -> str:
    try:
        url = base_url.rstrip("/") + "/api/generate"
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.35,
                "top_p": 0.9,
                "repeat_penalty": 1.1
            }
        }
        if max_tokens and max_tokens > 0:
            payload["options"]["num_predict"] = int(max_tokens)
        if stops:
            payload["stop"] = stops
        data = json.dumps(payload).encode("utf-8")
        out = _http_post(url, data=data, headers={"Content-Type": "application/json"}, timeout=timeout)
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

# Clean sentence cut-off: prefer last . ! ? within 140 chars
def _trim_to_sentence_140(s: str) -> str:
    if not s:
        return s
    s = s.strip()
    if len(s) <= 140:
        cut = max(s.rfind("."), s.rfind("!"), s.rfind("?"))
        return s[:cut+1] if cut != -1 else s
    t = s[:140].rstrip()
    cut = max(t.rfind("."), t.rfind("!"), t.rfind("?"))
    if cut >= 40:  # avoid cutting too early; crude guard
        return t[:cut+1]
    return t

# ===== NEW: token/overflow helpers ==========================================
def _estimate_tokens(text: str) -> int:
    # Heuristic if tokenizer is unavailable
    return max(1, len(text) // 4)

def _would_overflow(n_in: int, n_predict: int, max_ctx: int, reserve: int = 256) -> bool:
    """
    True if (prompt tokens + planned output) exceeds context capacity.
    'reserve' leaves space for BOS/EOS/stop/system bits to avoid edge crashes.
    """
    budget = max_ctx - max(64, reserve)
    return (n_in + max(0, n_predict)) > max(1, budget)

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
    out = re.sub(
        r'^\s*you\s+are\s+(?:a|the)?\s*rewriter\.?\s*$',
        '',
        out,
        flags=re.I | re.M
    )

    # Strip leaked rewrite markers
    out = re.sub(r'^\s*message you are a neutral, terse rewriter.*$', '', out, flags=re.I | re.M)
    out = re.sub(r'^\s*rewrite neutrally:.*$', '', out, flags=re.I | re.M)
    out = re.sub(r'(?mi)^[^\w\n]*message\b.*\byou\s+are\b.*\bneutral\b.*\bterse\b.*\brewriter\b.*$', '', out)
    out = re.sub(r'(?mi)^\s*rewrite\s+neutrally\s*:.*$', '', out, flags=re.I | re.M)
    # Extra safety: catch leaks anywhere in the string
    out = re.sub(r'you\s+are\s+a?\s*neutral.*?terse\s*rewriter\.?', '', out, flags=re.I | re.M)
    out = re.sub(r'message\s+you\s+are\s+a?\s*neutral.*?terse\s*rewriter\.?', '', out, flags=re.I | re.M)
    out = re.sub(r'rewrite\s+neutrally\s*:.*', '', out, flags=re.I | re.M)
    out = out.strip().strip('`').strip('"').strip("'").strip()
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out

# ============================
# Grammar for riffs (≤3 lines, ≤140 chars)
# ============================
_RIFF_GBNF = r"""
root  ::= line ( "\n" line ){0,2}
line  ::= char{1,140}
char  ::= [\x20-\x7E]
"""
def _maybe_with_grammar(kwargs: dict, use_grammar: bool):
    if not use_grammar:
        return kwargs
    try:
        import llama_cpp  # lazy import
        if hasattr(llama_cpp, "LlamaGrammar"):
            kwargs["grammar"] = llama_cpp.LlamaGrammar.from_string(_RIFF_GBNF)
        else:
            _log("grammar: LlamaGrammar not available; skipping")
    except Exception as e:
        _log(f"grammar setup failed; skipping: {e}")
    return kwargs

def _clean_riff_lines(lines: List[str]) -> List[str]:
    cleaned = []
    for ln in lines:
        ln = _strip_transport_tags(ln)
        ln = _scrub_persona_tokens(ln)
        ln = _strip_meta_markers(ln)
        ln = ln.strip().strip('"').strip("'")
        ln = re.sub(r'^\s*[-•*]\s*', '', ln)
        if ln:
            cleaned.append(ln)
    return cleaned

# ============================
# Lexi fallback (fast, subject-aware phrases)
# ============================
_LEXI_LRU_MAX = 32
_LEXI_LRU: deque[str] = deque(maxlen=_LEXI_LRU_MAX)
_LEXI_SEEN: set[str] = set()

def _lexi_seed(subj: str) -> int:
    h = hashlib.sha1((subj or "").lower().encode("utf-8")).hexdigest()
    return int(h[:8], 16)

def _lexi_phrase_banks(allow_profanity: bool) -> Dict[str, List[str]]:
    ack = [
        "noted", "synced", "logged", "captured", "tracked", "queued",
        "recorded", "acknowledged", "on file", "in the book", "added to ledger", "received"
    ]
    status = [
        "backup verified", "run completed", "snapshot created", "no changes", "deltas applied",
        "errors detected", "all clear", "integrity check passed", "checksum ok", "retention rotated"
    ]
    action = [
        "will retry", "escalating", "re-queueing", "throttling IO", "cooldown engaged",
        "next window scheduled", "compacting catalogs", "purging temp", "rotating keys", "rebuilding index"
    ]
    humor = [
        "beep boop paperwork", "robots hate dust", "bits behaving", "sleep is for disks",
        "coffee-fueled checksum", "backups doing backups"
    ]
    if not allow_profanity:
        pass
    return {"ack": ack, "status": status, "action": action, "humor": humor}

def _lexi_templates() -> List[str]:
    return [
        "{subj}: {ack}. {status}.",
        "{subj}: {status}. {action}.",
        "{subj}: {ack} — {status}.",
        "{subj}: {status}."
    ]

def _lexi_weight_for_subject(subj: str) -> Dict[str, float]:
    s = (subj or "").lower()
    if re.search(r"(duplicati|backup|snapshot|restore|archive)", s):
        return {"ack": 1.2, "status": 1.6, "action": 1.0, "humor": 0.5}
    if re.search(r"(uptime|monitor|alert|incident|sev|failure|error)", s):
        return {"ack": 1.1, "status": 1.4, "action": 1.3, "humor": 0.4}
    return {"ack": 1.0, "status": 1.0, "action": 1.0, "humor": 0.6}

def _lexi_pick(rnd, items: List[str], avoid: set[str]) -> str:
    for _ in range(5):
        cand = rnd.choice(items)
        if cand not in avoid:
            return cand
    return rnd.choice(items)

def _lexi_compose_line(subject: str, allow_profanity: bool) -> str:
    subj = subject.strip()
    banks = _lexi_phrase_banks(allow_profanity)
    weights = _lexi_weight_for_subject(subj)
    rnd = __import__("random").Random(_lexi_seed(subj))

    ack_pool = banks["ack"] * int(max(1, round(3 * weights["ack"])))
    status_pool = banks["status"] * int(max(1, round(4 * weights["status"])))
    action_pool = banks["action"] * int(max(1, round(3 * weights["action"])))
    humor_pool = banks["humor"] * int(max(1, round(2 * weights["humor"])))

    tpl = rnd.choice(_lexi_templates())
    pick_map = {
        "ack": _lexi_pick(rnd, ack_pool, set(_LEXI_LRU)),
        "status": _lexi_pick(rnd, status_pool, set(_LEXI_LRU)),
        "action": _lexi_pick(rnd, action_pool, set(_LEXI_LRU)),
        "humor": _lexi_pick(rnd, humor_pool, set(_LEXI_LRU)) if "{humor}" in tpl else None
    }
    line = tpl.format(
        subj=subj,
        ack=pick_map["ack"],
        status=pick_map["status"],
        action=pick_map["action"],
        humor=pick_map["humor"] or ""
    )
    line = re.sub(r"\s{2,}", " ", line).strip()
    if len(line) > 140:
        line = line[:140].rstrip()
    for k in ("ack", "status", "action", "humor"):
        v = pick_map.get(k)
        if v:
            _LEXI_LRU.append(v)
            _LEXI_SEEN.add(v)
    return line

def _lexicon_fallback_lines(persona: str, subject: str, max_lines: int, allow_profanity: bool) -> List[str]:
    subj = _strip_transport_tags(_scrub_persona_tokens(subject or "Update")).strip()
    lines: List[str] = []
    used: set[str] = set()
    for _ in range(max(1, int(max_lines or 3))):
        ln = _lexi_compose_line(subj, allow_profanity)
        if ln in used:
            continue
        used.add(ln)
        lines.append(ln)
    return lines[:max_lines]

# ============================
# RAG prompt helper
# ============================
def _build_prompt_with_rag_messages(messages: List[Dict[str, str]], system_preamble: str = "") -> Tuple[List[Dict[str, str]], str]:
    """
    Returns (messages_with_context, system_prompt_with_context).
    Injects a small 'Context' block from RAG (top-5 facts) without touching the rest.
    """
    last_user = ""
    for m in reversed(messages or []):
        if (m.get("role") or "").lower() == "user" and (m.get("content") or "").strip():
            last_user = m["content"].strip()
            break

    ctx = inject_context(last_user, top_k=5) if last_user else inject_context("", top_k=5)
    sys_line = (
        "Prefer the supplied facts over stale memory. "
        "If facts include times, mention freshness. "
        "Do not invent entities not present in Context."
    )
    sys_prompt = (system_preamble or "").strip()
    sys_prompt = (sys_prompt + ("\n\n" if sys_prompt else "")) + sys_line
    sys_prompt += f"\n\nContext:\n{ctx}" if ctx else "\n\nContext:\n(none)"

    return messages, sys_prompt

# ============================
# Core generation (FIXED: thread-safe timeout)
# ============================
class _TimeoutException(Exception):
    pass

def _llama_generate(prompt: str, timeout: int, max_tokens: int, with_grammar: bool = False) -> str:
    """
    Thread-safe LLM generation with timeout.
    Uses threading.Timer instead of signal.alarm for worker thread compatibility.
    """
    result = {"output": None, "error": None}
    
    def _generate():
        try:
            params = dict(
                prompt=prompt,
                max_tokens=max(1, int(max_tokens)),
                temperature=0.35,
                top_p=0.9,
                repeat_penalty=1.10,
                stop=_stops_for_model(),
            )
            params = _maybe_with_grammar(params, with_grammar)

            t0 = time.time()
            out = LLM(**params)
            ttft = time.time() - t0
            _log(f"TTFT ~ {ttft:.2f}s")

            txt = (out.get("choices") or [{}])[0].get("text", "")
            result["output"] = (txt or "").strip()
        except Exception as e:
            result["error"] = str(e)
    
    # Run generation in a separate thread with timeout
    gen_thread = threading.Thread(target=_generate, daemon=True)
    gen_thread.start()
    gen_thread.join(timeout=max(1, int(timeout)))
    
    if gen_thread.is_alive():
        _log(f"llama timeout after {timeout}s (thread still running, will be abandoned)")
        return ""
    
    if result["error"]:
        _log(f"llama error: {result['error']}")
        return ""
    
    return result["output"] or ""

def _do_generate(prompt: str, *, timeout: int, base_url: str, model_url: str, model_name_hint: str, max_tokens: int, with_grammar_auto: bool=False) -> str:
    use_grammar = _should_use_grammar_auto() if with_grammar_auto else False

    if LLM_MODE == "ollama" and OLLAMA_URL:
        cand = (model_name_hint or "").strip()
        name = cand if (cand and "/" not in cand and not cand.endswith(".gguf")) else _model_name_from_url(model_url)
        return _ollama_generate(OLLAMA_URL, name, prompt, timeout=max(4, int(timeout)), max_tokens=max_tokens, stops=_stops_for_model())

    if LLM_MODE == "worker":
        result = _worker_generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.35,
            stops=_stops_for_model()
        )
        return result or ""

    if LLM_MODE == "llama" and LLM is not None:
        return _llama_generate(prompt, timeout=max(4, int(timeout)), max_tokens=max_tokens, with_grammar=use_grammar)

    return ""

# ============================
# Ensure loaded
# ============================
def ensure_loaded(
    *,
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    ctx_tokens: int = 4096,
    cpu_limit: int = 80,
    hf_token: Optional[str] = None,
    base_url: str = ""
) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH, OLLAMA_URL, DEFAULT_CTX, _MODEL_NAME_HINT

    # EnviroGuard profile (priority)
    prof_name, prof_cpu, prof_ctx, _ = _current_profile()
    ctx_tokens = prof_ctx
    cpu_limit = prof_cpu
    DEFAULT_CTX = max(1024, int(ctx_tokens or 4096))
    _log(f"ensure_loaded using profile='{prof_name}' ctx={ctx_tokens} cpu_limit%={cpu_limit}")

    with _GenCritical():
        base_url = (base_url or "").strip()
        if base_url:
            OLLAMA_URL = base_url
            if _ollama_ready(base_url):
                LLM_MODE = "ollama"
                LLM = None
                LOADED_MODEL_PATH = None
                _MODEL_NAME_HINT = model_path or ""
                _log(f"using Ollama at {base_url}")
                return True
            else:
                _log(f"Ollama not reachable at {base_url}; falling back to local mode")

        LLM_MODE = "none"
        OLLAMA_URL = ""
        LLM = None
        LOADED_MODEL_PATH = None

        # Resolve model from options if not provided
        model_url, model_path, hf_token = _resolve_model_from_options(model_url, model_path, hf_token)
        if not (model_url or model_path):
            _log("no model_url/model_path resolved from options; cannot load model")
            return False

        _MODEL_NAME_HINT = model_path or ""
        _log(f"model resolve -> url='{os.path.basename(model_url) if model_url else ''}' path='{model_path}'")
        model_local_path = _ensure_local_model(model_url, model_path, hf_token, model_sha256 or "")
        if not model_local_path:
            _log("ensure_local_model failed")
            return False

        ok = _load_llama(model_local_path, DEFAULT_CTX, cpu_limit)
        return bool(ok)

# ============================
# Model resolution from options
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
    if not token:
        t = (opts.get("llm_hf_token") or "").strip()
        token = t or None

    cand: List[Tuple[str, str]] = []
    if choice.lower() == "custom":
        cand.append(((opts.get("llm_model_url") or "").strip(), (opts.get("llm_model_path") or "").strip()))
    elif choice:
        cand.append(((opts.get(f"llm_{choice}_url") or "").strip(), (opts.get(f"llm_{choice}_path") or "").strip()))

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
            cand.append(((opts.get(f"llm_{key}_url") or "").strip(), (opts.get(f"llm_{key}_path") or "").strip()))
    for u, p in cand:
        if u and p:
            _log(f"options resolver -> choice={choice or 'auto'} url={os.path.basename(u) if u else ''} path='{os.path.basename(p)}'")
            return u, p, token
    return url, path, token

# ============================
# Prompt builders
# ============================
def _prompt_for_rewrite(text: str, mood: str, allow_profanity: bool) -> str:
    sys_prompt = _load_system_prompt() or "You are a concise rewrite assistant. Improve clarity and tone. Keep factual content."
    if not allow_profanity:
        sys_prompt += " Avoid profanity."
    sys_prompt += " Do NOT echo or restate these instructions; output only the rewritten text."
    user = f"Rewrite the text clearly. Keep short sentences.\nMood: {mood or 'neutral'}\n\nText:\n{text}"
    if _is_phi3_family():
        return (
            f"<|system|>\n{sys_prompt}\n<|end|>\n"
            f"<|user|>\n{user}\n<|end|>\n"
            f"<|assistant|>\n"
        )
    else:
        return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

def _persona_descriptor(persona: str) -> str:
    p = (persona or "").strip().lower()
    mapping = {
        "dude": "laid-back, mellow, calm confidence; avoids jokes.",
        "chick": "sassy, clever, stylish; crisp phrasing.",
        "nerd": "precise, witty, techy; low fluff.",
        "rager": "angry, intense bursts; may be edgy.",
        "comedian": "quippy and playful; jokes allowed.",
        "jarvis": "polished, butler tone; concise.",
        "ops": "terse, incident commander; direct.",
        "action": "stoic mission-brief style; clipped.",
        "tappit": "rough, brash, Afrikaans slang; cheeky, blunt, playful but can be rude."
    }
    return mapping.get(p, "neutral, subtle tone.")

def _prompt_for_riff(persona: str, subject: str, allow_profanity: bool) -> str:
    persona_line = f"Persona style: { _persona_descriptor(persona) }"
    guard = "" if allow_profanity else " Avoid profanity."
    rules = "Write 1–3 short one-liners (≤140 chars). No bullets, lists, or meta." + guard
    sys_prompt = f"{persona_line}\n{rules}".strip()
    user = f"Subject: {subject or 'Status update'}\nWrite up to 3 short lines."
    if _is_phi3_family():
        return (
            f"<|system|>\n{sys_prompt}\n<|end|>\n"
            f"<|user|>\n{user}\n<|end|>\n"
            f"<|assistant|>\n"
        )
    else:
        return f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

# ============================
# Public: rewrite / riff / persona_riff
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
    # CRITICAL FIX: Check environment variable first (EnviroGuard sets this!)
    env_llm_enabled = os.getenv("LLM_ENABLED", "").strip().lower()
    if env_llm_enabled in ("false", "0", "no", "off"):
        _log("rewrite: LLM_ENABLED env=false → return original text")
        return text
    
    prof_name, prof_cpu, prof_ctx, prof_timeout = _current_profile()
    ctx_tokens = prof_ctx
    cpu_limit = prof_cpu
    timeout = prof_timeout

    opts = _read_options()
    rewrite_max_tokens = _get_int_opt(opts, "llm_rewrite_max_tokens", 256)
    _log(f"rewrite: effective max_tokens={rewrite_max_tokens}")

    with _GenCritical(timeout):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_tokens,
                cpu_limit=cpu_limit,
                hf_token=hf_token,
                base_url=base_url
            )
            if not ok:
                return text

        prompt = _prompt_for_rewrite(text, mood, allow_profanity)
        _log(f"rewrite: effective timeout={timeout}s")

        try:
            n_in = len(LLM.tokenize(prompt.encode("utf-8"), add_bos=True))
            _log(f"rewrite: prompt_tokens={n_in}")
        except Exception as e:
            _log(f"rewrite: tokenize debug skipped: {e}")
            n_in = _estimate_tokens(prompt)

        if _would_overflow(n_in, rewrite_max_tokens, ctx_tokens, reserve=256):
            _log(f"rewrite: ctx precheck overflow (prompt={n_in}, out={rewrite_max_tokens}, ctx={ctx_tokens}) → return original text")
            return text

        # CRITICAL FIX: Wrap generation in try-except to catch timeouts/exceptions
        try:
            out = _do_generate(
                prompt,
                timeout=timeout,
                base_url=base_url,
                model_url=model_url,
                model_name_hint=model_path,
                max_tokens=rewrite_max_tokens,
                with_grammar_auto=False
            )
            final = out if out else text
        except Exception as e:
            _log(f"rewrite: LLM generation exception ({e}) → return original text")
            final = text

    final = _strip_meta_markers(final)
    if max_lines:
        final = _trim_lines(final, max_lines)
    if max_chars:
        final = _soft_trim_chars(final, max_chars)
    return final

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
    subject = _strip_transport_tags(_scrub_persona_tokens(subject or ""))
    lines = persona_riff(
        persona=persona,
        context=f"Subject: {subject}",
        max_lines=3,
        timeout=timeout,
        base_url=base_url,
        model_url=model_url,
        model_path=model_path,
        allow_profanity=allow_profanity
    )
    joined = "\n".join(lines[:3]) if lines else ""
    if len(joined) > 120:
        joined = joined[:119].rstrip() + "…"
    return joined

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
    FIXED: Now checks LLM_ENABLED environment variable that EnviroGuard sets.
    Decision logic:
      - llm_enabled=false + riffs=true  → Lexi riff
      - llm_enabled=true + riffs=true   → LLM riff
      - riffs=false                     → No riff
    """
    if allow_profanity is None:
        allow_profanity = (
            (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
            and (persona or "").lower().strip() == "rager"
        )

    context = _sanitize_context_subject(context)
    opts = _read_options()
    
    # CRITICAL FIX: Check environment variable FIRST (EnviroGuard sets this!)
    env_llm_enabled = os.getenv("LLM_ENABLED", "").strip().lower()
    if env_llm_enabled in ("false", "0", "no", "off"):
        llm_enabled = False
        _log("persona_riff: LLM_ENABLED env=false → forcing LLM off")
    elif env_llm_enabled in ("true", "1", "yes", "on"):
        llm_enabled = True
    else:
        # Fallback to config file
        llm_enabled = bool(opts.get("llm_enabled", True))
    
    riffs_enabled = bool(opts.get("llm_persona_riffs_enabled", True))
    
    subj = _extract_subject_from_context(context or "")
    
    # Decision logic (FIXED)
    if not riffs_enabled:
        # Riffs disabled → return empty
        _log("persona_riff: riffs disabled → no riff")
        return []
    
    if not llm_enabled:
        _log("persona_riff: llm_enabled=false → calling personality.lexi_riffs()")
        try:
            import personality
            return personality.lexi_riffs(persona_name=persona, n=max_lines, with_emoji=False, subject=subj, body=context or "")
        except Exception as e:
            _log(f"personality.lexi_riffs failed: {e}")
            return _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity)
    
    # LLM on, riffs on → try LLM riff
    _log("persona_riff: llm_enabled=true + riffs=true → using LLM")
    
    riff_max_tokens = _get_int_opt(opts, "llm_riff_max_tokens", 32)
    prof_name, prof_cpu, prof_ctx, prof_timeout = _current_profile()
    ctx_tokens = prof_ctx
    cpu_limit = prof_cpu
    timeout = prof_timeout

    with _GenCritical(timeout):
        # Ensure LLM is loaded
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_tokens,
                cpu_limit=cpu_limit,
                hf_token=hf_token,
                base_url=base_url
            )
            if not ok:
                _log("persona_riff: LLM load failed → fallback to Lexi")
                return _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity)

        if LLM_MODE not in ("llama", "ollama"):
            _log("persona_riff: LLM_MODE invalid → fallback to Lexi")
            return _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity)

        # Build LLM prompt
        persona_line = f"Persona style: { _persona_descriptor(persona) }"
        sys_parts = [
            persona_line,
            "Write up to {N} distinct one-liners. Each ≤ 140 chars. No bullets, numbering, lists, labels, JSON, or meta.",
        ]
        if allow_profanity is False:
            sys_parts.append("Avoid profanity.")
        sys_prompt = " ".join([s for s in sys_parts if s]).strip()

        user = (
            f"{context.strip()}\n\n"
            f"Write up to {max_lines} short lines in the requested voice."
        )

        if _is_phi3_family():
            prompt = (
                f"<|system|>\n{sys_prompt}\n<|end|>\n"
                f"<|user|>\n{user}\n<|end|>\n"
                f"<|assistant|>\n"
            )
        else:
            prompt = f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

        try:
            n_in = len(LLM.tokenize(prompt.encode("utf-8"), add_bos=True))
            _log(f"persona_riff: prompt_tokens={n_in}")
        except Exception as e:
            _log(f"persona_riff: tokenize debug skipped: {e}")
            n_in = _estimate_tokens(prompt)

        if _would_overflow(n_in, riff_max_tokens, ctx_tokens, reserve=256):
            _log(f"persona_riff: ctx overflow → fallback to Lexi")
            return _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity)

        # CRITICAL FIX: Wrap generation in try-except to catch timeouts/exceptions
        try:
            raw = _do_generate(
                prompt,
                timeout=timeout,
                base_url=base_url,
                model_url=model_url,
                model_name_hint=model_path,
                max_tokens=riff_max_tokens,
                with_grammar_auto=False
            )
            
            if not raw:
                _log("persona_riff: LLM returned empty → fallback to Lexi")
                return _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity)
                
        except Exception as e:
            _log(f"persona_riff: LLM generation exception ({e}) → fallback to Lexi")
            return _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity)

    # Clean LLM output
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
        ln2 = _trim_to_sentence_140(ln2)
        key = ln2.lower()
        if key in seen or not ln2:
            continue
        seen.add(key)
        cleaned.append(ln2)
        if len(cleaned) >= max(1, int(max_lines or 3)):
            break

    if not cleaned:
        _log("persona_riff: LLM output empty after cleaning → fallback to Lexi")
        lines = _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity)
        if not lines:
            lines = [f"{subj or 'Update'} completed."]
        return lines

    if isinstance(cleaned, str):
        return [cleaned]
    return cleaned or [f"{subj or 'Update'} acknowledged."]

# ============================
# Extended riff (with source flag) — ADDITIVE ONLY
# ============================
def persona_riff_ex(
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
) -> Tuple[List[str], str]:
    """
    Extended riff that also reports its source:
      - source == "llm"     → generated by the LLM
      - source == "lexicon" → generated by Lexi fallback
    """
    opts = _read_options()
    
    # Check environment first
    env_llm_enabled = os.getenv("LLM_ENABLED", "").strip().lower()
    if env_llm_enabled in ("false", "0", "no", "off"):
        llm_enabled = False
    elif env_llm_enabled in ("true", "1", "yes", "on"):
        llm_enabled = True
    else:
        llm_enabled = bool(opts.get("llm_enabled", True))
    
    riffs_enabled = bool(opts.get("llm_persona_riffs_enabled", True))
    context = _sanitize_context_subject(context)
    subj = _extract_subject_from_context(context or "")

    if not riffs_enabled:
        return [], "none"
    
    if not llm_enabled:
        return _lexicon_fallback_lines(persona, subj, max_lines, allow_profanity if allow_profanity is not None else False), "lexicon"

    lines = persona_riff(
        persona=persona,
        context=context,
        max_lines=max_lines,
        timeout=timeout,
        cpu_limit=cpu_limit,
        models_priority=models_priority,
        base_url=base_url,
        model_url=model_url,
        model_path=model_path,
        model_sha256=model_sha256,
        allow_profanity=allow_profanity,
        ctx_tokens=ctx_tokens,
        hf_token=hf_token
    )
    
    # Determine source based on whether LLM was actually used
    source = "lexicon" if not lines else "llm"
    return lines, source

# ============================
# Pure Chat (no riff/persona, now RAG-aware)
# ============================
def chat_generate(
    *,
    messages: List[Dict[str, str]],
    system_prompt: str = "",
    max_new_tokens: int = 384,
    timeout: Optional[int] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    hf_token: Optional[str] = None
) -> str:
    """
    Minimal chat:
      - Uses same profile (ctx/tokens/timeout/cpu) as rewrite/riff
      - Adds a small RAG 'Context' block to the system prompt (top-5 facts)
      - No separate config keys; if llm_enabled is false, returns ""
    """
    opts = _read_options()
    
    # CRITICAL FIX: Check environment first (EnviroGuard sets this)
    env_llm_enabled = os.getenv("LLM_ENABLED", "").strip().lower()
    if env_llm_enabled in ("false", "0", "no", "off"):
        _log("chat_generate: LLM_ENABLED env=false → refusing chat")
        return ""
    
    if not bool(opts.get("llm_enabled", True)):
        return ""

    if not messages or not isinstance(messages, list):
        return ""

    last = messages[-1]
    if (last.get("role") or "").lower() != "user" or not (last.get("content") or "").strip():
        return ""

    prof_name, prof_cpu, prof_ctx, prof_timeout = _current_profile()
    ctx_tokens = prof_ctx
    eff_timeout = timeout if timeout is not None else prof_timeout

    def _build_prompt(msgs: List[Dict[str, str]], sys_prompt: str) -> str:
        sys_txt = (sys_prompt or _load_system_prompt() or "You are a helpful assistant.").strip()
        if _is_phi3_family():
            parts = []
            if sys_txt:
                parts.append(f"<|system|>\n{sys_txt}\n<|end|>")
            for m in msgs:
                role = (m.get("role") or "").lower()
                content = (m.get("content") or "").strip()
                if not content:
                    continue
                if role == "user":
                    parts.append(f"<|user|>\n{content}\n<|end|>")
                elif role == "assistant":
                    parts.append(f"<|assistant|>\n{content}\n<|end|>")
            parts.append("<|assistant|>\n")
            return "\n".join(parts)
        else:
            convo = []
            if sys_txt:
                convo.append(f"<<SYS>>{sys_txt}<</SYS>>")
            for m in msgs:
                role = (m.get("role") or "").lower()
                content = (m.get("content") or "").strip()
                if not content:
                    continue
                if role == "user":
                    convo.append(f"[USER]\n{content}")
                elif role == "assistant":
                    convo.append(f"[ASSISTANT]\n{content}")
            return "<s>[INST] " + "\n".join(convo + ["[/INST]"]) + "\n[ASSISTANT]\n"

    with _GenCritical(eff_timeout):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_tokens,
                cpu_limit=prof_cpu,
                hf_token=hf_token,
                base_url=base_url
            )
            if not ok:
                return ""

        # RAG injection
        messages, system_prompt = _build_prompt_with_rag_messages(messages, system_preamble=system_prompt)

        prompt = _build_prompt(messages, system_prompt)

        try:
            n_in = len(LLM.tokenize(prompt.encode("utf-8"), add_bos=True))
        except Exception:
            n_in = _estimate_tokens(prompt)
        if _would_overflow(n_in, max_new_tokens, ctx_tokens, reserve=256):
            _log("chat_generate: ctx overflow → refuse generation")
            return ""

        # CRITICAL FIX: Wrap generation in try-except to catch timeouts/exceptions
        try:
            out = _do_generate(
                prompt,
                timeout=max(4, int(eff_timeout)),
                base_url=base_url,
                model_url=model_url,
                model_name_hint=model_path,
                max_tokens=max_new_tokens,
                with_grammar_auto=False
            )
        except Exception as e:
            _log(f"chat_generate: LLM generation exception ({e}) → return empty")
            out = ""

    return _strip_meta_markers(out or "").strip()

# ============================
# Quick self-test (optional)
# ============================
if __name__ == "__main__":
    print("llm_client self-check start")
    try:
        prof_name, prof_cpu, prof_ctx, prof_timeout = _current_profile()
        _log(f"SELFTEST profile -> name={prof_name} cpu={prof_cpu} ctx={prof_ctx} timeout={prof_timeout}")
        demo = _lexicon_fallback_lines("jarvis", "Duplicati Backup report for misc: nerd. comedian.", 2, allow_profanity=False)
        for d in demo:
            _log(f"LEXI: {d}")
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")
