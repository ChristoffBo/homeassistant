#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (EnviroGuard-first, lean riffs, Phi3-aware chat format)
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
    Return ONLY the '### RIFF TRAINING' section from system_prompt.txt.
    If not found, return empty string.
    """
    if not full_text:
        return ""
    txt = full_text
    m = re.search(r'^\s*#{2,}\s*RIFF\s*TRAINING.*$', txt, flags=re.I | re.M)
    if not m:
        return ""
    start = m.start()
    m2 = re.search(r'^\s*#{2,}\s*[A-Z].*$', txt[m.end():], flags=re.I | re.M)
    end = (m.end() + m2.start()) if m2 else len(txt)
    block = txt[start:end].strip()
    if len(block) > 12000:
        block = block[:12000]
    return block

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
    enviroguard_active = False  # <— we will log this explicitly

    # 1) EnviroGuard (sovereign)
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

    # Explicit flag
    _log(f"EnviroGuard active: {enviroguard_active}")
    _log(f"profile: src={source or 'defaults'} active='{prof_name}' cpu_percent={cpu_percent} ctx_tokens={ctx_tokens} timeout_seconds={timeout_seconds}")
    return prof_name, cpu_percent, ctx_tokens, timeout_seconds

# ============================
# CPU / Threads (derived from percent; EnviroGuard-first)
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

def _threads_from_cpu_limit(limit_pct: int) -> int:
    cores = _available_cpus()
    try:
        pct = max(1, min(100, int(limit_pct or 100)))
    except Exception:
        pct = 100
    t = max(1, min(cores, int(math.ceil(cores * (pct / 100.0)))))
    _log(f"cpu_limit={pct}% -> threads={t} (avail_cpus={cores})")
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
            got = hashlib.sha256(open(path, "rb").read()).hexdigest()
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
    global LLM_MODE, LLM, LOADED_MODEL_PATH
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp:
        return False
    try:
        threads = _threads_from_cpu_limit(cpu_limit)
        os.environ["OMP_NUM_THREADS"] = str(threads)
        os.environ["LLAMA_THREADS"] = str(threads)
        LLM = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=ctx_tokens,
            n_threads=threads,
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
                "temperature": 0.3,
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
        r'^\s*you\s+are\s+(?:a|the)?\s*.*?\s*rewriter\.?\s*$',
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
        ln = _strip_meta_markers(ln)
        ln = ln.strip().strip('"').strip("'")
        ln = re.sub(r'^\s*[-•*]\s*', '', ln)
        if ln:
            cleaned.append(ln)
    return cleaned

# ============================
# Core generation (shared)
# ============================
def _sigalrm_handler(signum, frame):
    raise TimeoutError("gen timeout")

def _llama_generate(prompt: str, timeout: int, max_tokens: int, with_grammar: bool = False) -> str:
    try:
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _sigalrm_handler)
            signal.alarm(max(1, int(timeout)))

        params = dict(
            prompt=prompt,
            max_tokens=max(1, int(max_tokens)),
            temperature=0.35,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=_stops_for_model(),
        )
        params = _maybe_with_grammar(params, with_grammar)

        t0 = time.time()
        out = LLM(**params)
        ttft = time.time() - t0
        _log(f"TTFT ~ {ttft:.2f}s")

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

def _do_generate(prompt: str, *, timeout: int, base_url: str, model_url: str, model_name_hint: str, max_tokens: int, with_grammar_auto: bool=False) -> str:
    use_grammar = _should_use_grammar_auto() if with_grammar_auto else False

    if LLM_MODE == "ollama" and OLLAMA_URL:
        cand = (model_name_hint or "").strip()
        name = cand if (cand and "/" not in cand and not cand.endswith(".gguf")) else _model_name_from_url(model_url)
        return _ollama_generate(OLLAMA_URL, name, prompt, timeout=max(4, int(timeout)), max_tokens=max_tokens, stops=_stops_for_model())

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

    # EnviroGuard-first profile
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
    autodl = bool(opts.get("llm_autodownload", True))
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
            _log(f"options resolver -> choice={choice or 'auto'} url={os.path.basename(u) if u else ''} path={os.path.basename(p)} autodownload={autodl}")
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
        "rager": "short, intense bursts; may be edgy.",
        "comedian": "quippy and playful; jokes allowed.",
        "jarvis": "polished, butler tone; concise.",
        "ops": "terse, incident commander; direct.",
        "action": "stoic mission-brief style; clipped."
    }
    return mapping.get(p, "neutral, subtle tone.")

def _prompt_for_riff(persona: str, subject: str, allow_profanity: bool) -> str:
    sys_full = _load_system_prompt() or ""
    riff_training = _extract_riff_training_block(sys_full)
    persona_line = f"Persona style: { _persona_descriptor(persona) }"
    guard = "" if allow_profanity else " Avoid profanity."
    rules = "Write 1–3 short one-liners (≤20 words). No bullets, lists, or meta." + guard
    sys_parts = [persona_line, rules]
    if riff_training:
        sys_parts.append(riff_training)
    sys_prompt = "\n\n".join(sys_parts).strip()
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
    prof_name, prof_cpu, prof_ctx, prof_timeout = _current_profile()
    ctx_tokens = prof_ctx
    cpu_limit = prof_cpu
    timeout = prof_timeout

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
        out = _do_generate(prompt, timeout=timeout, base_url=base_url, model_url=model_url, model_name_hint=model_path, max_tokens=256, with_grammar_auto=False)
        final = out if out else text

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
    if allow_profanity is None:
        allow_profanity = (
            (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
            and (persona or "").lower().strip() == "rager"
        )

    prof_name, prof_cpu, prof_ctx, prof_timeout = _current_profile()
    ctx_tokens = prof_ctx
    cpu_limit = prof_cpu
    timeout = prof_timeout

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
                return []

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

        # Build lean riff sys prompt
        sys_full = _load_system_prompt() or ""
        riff_training = _extract_riff_training_block(sys_full)
        persona_line = f"Persona style: { _persona_descriptor(persona) }"
        sys_parts = [
            persona_line,
            "Write up to {N} distinct one-liners. Each ≤ 140 chars. No bullets, numbering, lists, labels, JSON, or meta.",
        ]
        if allow_profanity is False:
            sys_parts.append("Avoid profanity.")
        if daypart:
            sys_parts.append(f"Daypart vibe (subtle): {daypart}.")
        if intensity:
            sys_parts.append(f"Persona intensity (subtle): {intensity}.")
        if riff_training:
            sys_parts.append(riff_training)
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

        _log(f"persona_riff: effective timeout={timeout}s")
        # Debug: show prompt token count
        try:
            n_in = len(LLM.tokenize(prompt.encode("utf-8"), add_bos=True))
            _log(f"persona_riff: prompt_tokens={n_in}")
        except Exception as e:
            _log(f"persona_riff: tokenize debug skipped: {e}")

        raw = _do_generate(
            prompt,
            timeout=timeout,
            base_url=base_url,
            model_url=model_url,
            model_name_hint=model_path,
            max_tokens=64,
            with_grammar_auto=False
        )
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
        prof_name, prof_cpu, prof_ctx, prof_timeout = _current_profile()
        _log(f"SELFTEST profile -> name={prof_name} cpu={prof_cpu} ctx={prof_ctx} timeout={prof_timeout}")
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")
