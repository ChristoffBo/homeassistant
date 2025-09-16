#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (EnviroGuard-first, hard caps, Phi-family chat format, Lexi fallback riffs)
#
# Public entry points:
#   ensure_loaded(...)
#   rewrite(...)
#   riff(...)         → routes to persona_riff()
#   persona_riff(...)

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
import signal
from typing import Optional, Dict, Any, Tuple, List
from collections import deque

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama" | "ollama"
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
```0
def _load_llama(model_path: str, ctx_tokens: int, cpu_limit: int) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp:
        return False
    try:
        threads = _threads_from_cpu_limit(cpu_limit)

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

    # ADDITIVE: strip noisy injected lines that burn tokens in incoming messages
    # Examples:
    #   "📝 Message YOU ARE A NEUTRAL, TERSE REWRITER"
    #   "Message YOU ARE A NEUTRAL, TERSE REWRITER"
    #   "YOU ARE A NEUTRAL, TERSE REWRITER"
    #   "Rewrite neutrally:"
    out = re.sub(
        r'^\s*(?:📝\s*)?Message\s+YOU\s+ARE\s+A\s+NEUTRAL,\s+TERSE\s+REWRITER\.?\s*$',
        '',
        out,
        flags=re.I | re.M
    )
    out = re.sub(
        r'^\s*YOU\s+ARE\s+A\s+NEUTRAL,\s+TERSE\s+REWRITER\.?\s*$',
        '',
        out,
        flags=re.I | re.M
    )
    out = re.sub(
        r'^\s*Rewrite\s+neutrally:?\s*$',
        '',
        out,
        flags=re.I | re.M
    )

    out = out.strip().strip('`').strip().strip('"').strip("'").strip()
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
        llama_cpp = _try_import_llama_cpp()
        if llama_cpp and hasattr(llama_cpp, "LlamaGrammar"):
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
    # profanity banks could be added later; keep branch for policy
    if not allow_profanity:
        pass
    return {"ack": ack, "status": status, "action": action, "humor": humor}

def _lexi_templates() -> List[str]:
    return [
        "{subj}: {ack}. {status}. Lexi.",
        "{subj}: {status}. {action}. Lexi.",
        "{subj}: {ack} — {status}. Lexi.",
        "{subj}: {status}. Lexi."
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
    # Subject-aware, phrase-based Lexi fallback (fast, deterministic-ish)
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
```0
# ============================
# Public API
# ============================
def ensure_loaded(model_url: str, model_path: str, ctx_tokens: int, cpu_percent: int) -> bool:
    if not model_path or not os.path.exists(model_path):
        _log(f"model path missing: {model_path}")
        return False
    return _load_llama(model_path, ctx_tokens, cpu_percent)

def rewrite(text: str, opts: Dict[str, Any]) -> str:
    prof = _current_profile()
    prof_timeout = int(prof.get("timeout_seconds", 20))
    max_tokens = opts.get("rewrite_max_tokens", 256)
    ctx_tokens = opts.get("ctx_tokens", 4096)

    n_in = _estimate_tokens(text)
    if _would_overflow(n_in, max_tokens, ctx_tokens):
        _log("rewrite: overflow predicted, falling back to Lexi")
        return _strip_meta_markers(text)

    if LLM_MODE == "ollama":
        model_name = _model_name_from_url(LOADED_MODEL_PATH or "llama3")
        raw = _ollama_generate(OLLAMA_URL, model_name, text, timeout=prof_timeout, max_tokens=max_tokens)
    elif LLM_MODE == "llama" and LLM:
        try:
            out = LLM(
                text,
                max_tokens=max_tokens,
                stop=["</s>"],
                echo=False,
                temperature=0.35,
                top_p=0.9,
                repeat_penalty=1.1
            )
            raw = out["choices"][0]["text"]
        except Exception as e:
            _log(f"rewrite llama error: {e}")
            raw = ""
    else:
        raw = ""

    if not raw:
        return _strip_meta_markers(text)
    return _strip_meta_markers(raw)

def riff(persona: str, subject: str, opts: Dict[str, Any]) -> List[str]:
    prof = _current_profile()
    prof_timeout = int(prof.get("timeout_seconds", 20))
    max_tokens = opts.get("riff_max_tokens", 32)
    ctx_tokens = opts.get("ctx_tokens", 4096)

    n_in = _estimate_tokens(subject)
    if _would_overflow(n_in, max_tokens, ctx_tokens):
        _log("riff: overflow predicted, falling back to Lexi")
        return _lexicon_fallback_lines(persona, subject, 3, allow_profanity=True)

    if LLM_MODE == "ollama":
        model_name = _model_name_from_url(LOADED_MODEL_PATH or "llama3")
        raw = _ollama_generate(OLLAMA_URL, model_name, subject, timeout=prof_timeout, max_tokens=max_tokens)
    elif LLM_MODE == "llama" and LLM:
        try:
            kwargs = dict(
                max_tokens=max_tokens,
                stop=["</s>"],
                echo=False,
                temperature=0.7,
                top_p=0.9,
                repeat_penalty=1.05
            )
            out = LLM(subject, **_maybe_with_grammar(kwargs, True))
            raw = out["choices"][0]["text"]
        except Exception as e:
            _log(f"riff llama error: {e}")
            raw = ""
    else:
        raw = ""

    if not raw:
        return _lexicon_fallback_lines(persona, subject, 3, allow_profanity=True)

    lines = raw.splitlines()
    return _clean_riff_lines(lines)

def persona_riff(persona: str, subject: str, opts: Dict[str, Any]) -> List[str]:
    try:
        return riff(persona, subject, opts)
    except Exception as e:
        _log(f"persona_riff error: {e}")
        return _lexicon_fallback_lines(persona, subject, 3, allow_profanity=True)