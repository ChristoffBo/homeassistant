#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (FULL, EnviroGuard + Profiles + Stable Riffs)
# - Local GGUF via llama-cpp only (Ollama removed)
# - EnviroGuard: respects ENV vars and /data/config.json profiles (manual/hot/normal/boost/auto)
# - CPU → threads mapping (or explicit threads via env/config)
# - No SIGALRM for local gen (avoids proxy insta-timeouts)
# - Riff / persona_riff with lexicon fallback
# - Rewrite with meta/marker cleanup
#
# Public entry points:
#   ensure_loaded(...)
#   rewrite(...)
#   riff(...)
#   persona_riff(...)

from __future__ import annotations
import os
import json
import time
import math
import hashlib
import re
import socket
import urllib.request
import urllib.error
import threading
from typing import Optional, Dict, Any, Tuple, List

# ============================
# Globals / Paths
# ============================
LLM_MODE = "none"        # "none" | "llama"
LLM = None               # llama_cpp.Llama instance if LLM_MODE == "llama"
LOADED_MODEL_PATH = None
DEFAULT_CTX = 4096

OPTIONS_PATH = "/data/options.json"   # legacy Jarvis options
CONFIG_PATH  = "/data/config.json"    # EnviroGuard profiles + temp + optional threads
SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"

_GEN_LOCK = threading.RLock()

def _log(msg: str):
    print(f"[llm] {msg}", flush=True)

# ============================
# Lock (no raising on timeout)
# ============================
def _lock_timeout() -> int:
    try:
        v = int(os.getenv("LLM_LOCK_TIMEOUT_SECONDS", "300").strip())
        return max(1, min(300, v))
    except Exception:
        return 10

class _GenCritical:
    """Serialize load/gen. If lock not acquired in time, proceed best-effort (no raise)."""
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
# Files
# ============================
def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _read_options() -> Dict[str, Any]:
    return _read_json(OPTIONS_PATH)

def _read_config() -> Dict[str, Any]:
    return _read_json(CONFIG_PATH)

def _load_system_prompt() -> str:
    try:
        if os.path.exists(SYSTEM_PROMPT_PATH):
            with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        _log(f"system_prompt load failed: {e}")
    return ""

# ============================
# EnviroGuard (env + config)
# ============================
def _int_env(name: str) -> Optional[int]:
    try:
        v = os.getenv(name, "").strip()
        return int(v) if v else None
    except Exception:
        return None

def _resolve_enviroguard_from_config() -> Tuple[Optional[int], Optional[int], Optional[int], Optional[str]]:
    """
    Pull profile & values from /data/config.json if present.
    Expected shape:
      {
        "enviroguard": {
          "profile": "manual" | "normal" | "hot" | "boost" | "auto",
          "temperature_c": 26,
          "threads": 3,                # optional explicit threads
          "profiles": {
            "manual": {"cpu_percent":20,"ctx_tokens":4096,"timeout_seconds":25},
            "normal": {"cpu_percent":30,"ctx_tokens":4096,"timeout_seconds":25},
            "hot":    {"cpu_percent":10,"ctx_tokens":4096,"timeout_seconds":25},
            "boost":  {"cpu_percent":6, "ctx_tokens":4096,"timeout_seconds":25}
          },
          "thresholds": { "hot_c": 35, "boost_c": 18 }  # optional for auto
        }
      }
    Returns: (cpu_percent, ctx_tokens, timeout_seconds, chosen_profile)
    """
    cfg = _read_config().get("enviroguard") or {}
    if not cfg:
        return None, None, None, None

    profiles = cfg.get("profiles") or {}
    profile  = (cfg.get("profile") or "auto").strip().lower()
    temp_c   = None
    try:
        env_temp = os.getenv("ENVGUARD_TEMP_C", "").strip()
        temp_c = float(env_temp) if env_temp else float(cfg.get("temperature_c"))
    except Exception:
        temp_c = None

    def _vals(pname: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        p = profiles.get(pname) or {}
        return p.get("cpu_percent"), p.get("ctx_tokens"), p.get("timeout_seconds")

    chosen = profile
    cpu = ctx = to = None

    if profile in ("manual", "normal", "hot", "boost"):
        cpu, ctx, to = _vals(profile)
    else:
        th = cfg.get("thresholds") or {}
        hot_c   = float(th.get("hot_c",   35.0))
        boost_c = float(th.get("boost_c", 18.0))
        if temp_c is not None:
            if temp_c >= hot_c:
                chosen = "hot"
            elif temp_c <= boost_c:
                chosen = "boost"
            else:
                chosen = "normal"
            cpu, ctx, to = _vals(chosen)
        else:
            chosen = "normal"
            cpu, ctx, to = _vals("normal")

    if cpu is not None: cpu = min(100, max(1, int(cpu)))
    if ctx is not None: ctx = max(256, int(ctx))
    if to  is not None: to  = max(2,   int(to))
    return cpu, ctx, to, chosen

def _enviroguard(ctx_default: int, cpu_default: int, to_default: int) -> Tuple[int, int, int, Optional[int], str]:
    """
    Final resolution order:
      1) ENV overrides (ENVGUARD_CPU_PERCENT, ENVGUARD_CTX_TOKENS, ENVGUARD_TIMEOUT_SECONDS)
      2) /data/config.json enviroguard profiles (manual/normal/hot/boost/auto)
      3) options.json llm_max_cpu_percent (CPU only, if still None)
      4) function defaults
    Also returns explicit_threads if config/env asked for it.
    """
    cpu_env = _int_env("ENVGUARD_CPU_PERCENT")
    ctx_env = _int_env("ENVGUARD_CTX_TOKENS")
    to_env  = _int_env("ENVGUARD_TIMEOUT_SECONDS")

    cpu_cfg, ctx_cfg, to_cfg, which = _resolve_enviroguard_from_config()

    explicit_threads = None
    try:
        eg = _read_config().get("enviroguard") or {}
        t = eg.get("threads")
        if t is not None:
            explicit_threads = max(1, int(t))
    except Exception:
        pass

    for var in ("LLAMA_THREADS", "OMP_NUM_THREADS", "ENVGUARD_THREADS"):
        v = os.getenv(var, "").strip()
        if v.isdigit():
            explicit_threads = max(1, int(v))
            break

    cpu_opt = None
    if cpu_env is None and cpu_cfg is None:
        try:
            cpu_opt = int(_read_options().get("llm_max_cpu_percent", 80))
        except Exception:
            cpu_opt = None

    cpu_final = (cpu_env if cpu_env is not None else (cpu_cfg if cpu_cfg is not None else (cpu_opt if cpu_opt is not None else cpu_default)))
    ctx_final = (ctx_env if ctx_env is not None else (ctx_cfg if ctx_cfg is not None else ctx_default))
    to_final  = (to_env  if to_env  is not None else (to_cfg  if to_cfg  is not None else to_default))

    cpu_final = min(100, max(1, int(cpu_final or cpu_default)))
    ctx_final = max(256, int(ctx_final or ctx_default))
    to_final  = max(2,   int(to_final  or to_default))

    prof_label = which or ("env" if any(v is not None for v in (cpu_env, ctx_env, to_env)) else "defaults")
    _log(f"EnviroGuard -> profile={prof_label} cpu={cpu_final}% ctx={ctx_final} timeout={to_final}s"
         + (f" threads={explicit_threads}" if explicit_threads else ""))

    return ctx_final, cpu_final, to_final, explicit_threads, prof_label

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

# ============================
# HTTP helpers (HF auth across redirects)
# ============================
class _AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None: return None
        auth = req.headers.get("Authorization")
        if auth:   new.add_unredirected_header("Authorization", auth)
        cookie = req.headers.get("Cookie")
        if cookie: new.add_unredirected_header("Cookie", cookie)
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

# ============================
# Model resolution + loading
# ============================
def _resolve_model_from_options(model_url: str, model_path: str, hf_token: Optional[str]) -> Tuple[str, str, Optional[str]]:
    url = (model_url or "").strip()
    path = (model_path or "").strip()
    token = (hf_token or "").strip() or None
    if url and path:
        return url, path, token

    opts = _read_options()
    choice = (opts.get("llm_choice") or "").strip()
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
        if key in seen: continue
        seen.add(key)
        if opts.get(f"llm_{key}_enabled", False):
            cand.append(((opts.get(f"llm_{key}_url") or "").strip(), (opts.get(f"llm_{key}_path") or "").strip()))

    for u, p in cand:
        if u and p:
            _log(f"options resolver -> choice={choice or 'auto'} url={os.path.basename(u)} path={os.path.basename(p)}")
            return u, p, token
    return url, path, token

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
# CPU / Threads
# ============================
def _available_cpus() -> int:
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except Exception:
        pass
    return max(1, os.cpu_count() or 1)

def _threads_from_cpu_limit(limit_pct: int, explicit_threads: Optional[int]) -> int:
    for env_var in ("LLAMA_THREADS", "OMP_NUM_THREADS"):
        v = os.getenv(env_var, "").strip()
        if v.isdigit():
            t = max(1, int(v))
            _log(f"env override {env_var} -> threads={t}")
            return t
    if explicit_threads and explicit_threads > 0:
        _log(f"config explicit threads -> {explicit_threads}")
        return int(explicit_threads)

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

def _load_llama(model_path: str, ctx_tokens: int, cpu_limit: int, explicit_threads: Optional[int]) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH, DEFAULT_CTX
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp:
        return False
    try:
        threads = _threads_from_cpu_limit(cpu_limit, explicit_threads)
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        os.environ.setdefault("LLAMA_THREADS", str(threads))
        LLM = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=ctx_tokens,
            n_threads=threads,
        )
        LOADED_MODEL_PATH = model_path
        LLM_MODE = "llama"
        DEFAULT_CTX = max(1024, int(ctx_tokens or 4096))
        _log(f"loaded GGUF model: {model_path} (ctx={ctx_tokens}, threads={threads})")
        return True
    except Exception as e:
        _log(f"llama load failed: {e}")
        LLM = None
        LOADED_MODEL_PATH = None
        LLM_MODE = "none"
        return False

# ============================
# Generation (no SIGALRM)
# ============================
def _llama_generate(prompt: str) -> str:
    """Non-streaming generation; rely on short max_tokens and thread cap instead of SIGALRM."""
    try:
        out = LLM(
            prompt,
            max_tokens=256,
            temperature=0.35,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=["</s>"]
        )
        txt = (out.get("choices") or [{}])[0].get("text", "")
        return (txt or "").strip()
    except Exception as e:
        _log(f"llama error: {e}")
        return ""

def _do_generate(prompt: str) -> str:
    if LLM_MODE == "llama" and LLM is not None:
        return _llama_generate(prompt)
    return ""

# ============================
# Text cleanup
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
# Lexicon fallback
# ============================
def _lexicon_default(persona: str, subject: str) -> str:
    p = (persona or "").lower().strip()
    if p == "rager":     return "Send it. No flinch."
    if p == "nerd":      return "Parsed, verified, shipped."
    if p == "jarvis":    return "At your service."
    if p == "ops":       return "On it. Eyes up."
    if p == "action":    return "Objective locked."
    if p == "chick":     return "Clean, sharp, done."
    if p == "dude":      return "Chill. It’s handled."
    if p == "comedian":  return "All good—no punchline needed."
    return subject or "Done."

def _riff_fallback(persona: str, subject: str) -> str:
    try:
        import personality  # optional external personality module
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
# Public API
# ============================
def ensure_loaded(
    *,
    model_url: str,
    model_path: str,
    model_sha256: str,
    ctx_tokens: int,
    cpu_limit: int,
    hf_token: Optional[str],
) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH, DEFAULT_CTX
    ctx_final, cpu_final, _, explicit_threads, _ = _enviroguard(ctx_tokens, cpu_limit, 12)
    url, path, token = _resolve_model_from_options(model_url, model_path, hf_token)
    path = _ensure_local_model(url, path, token, model_sha256 or "")
    if not path:
        _log("ensure_local_model failed")
        return False
    with _GenCritical(_lock_timeout()):
        ok = _load_llama(path, ctx_final, cpu_final, explicit_threads)
        return bool(ok)

def rewrite(
    *,
    text: str,
    mood: str = "neutral",
    timeout: int = 12,
    cpu_limit: int = 80,
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
    ctx_final, cpu_final, to_final, explicit_threads, _ = _enviroguard(ctx_tokens, cpu_limit, timeout)
    with _GenCritical(to_final):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_final,
                cpu_limit=cpu_final,
                hf_token=hf_token
            )
            if not ok:
                return text
        prompt = _prompt_for_rewrite(text, mood, allow_profanity)
        out = _do_generate(prompt)
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
    model_url: str = "",
    model_path: str = "",
    allow_profanity: bool = False,
    cpu_limit: Optional[int] = None,
    ctx_tokens: int = 2048,
    hf_token: Optional[str] = None
) -> str:
    ctx_final, cpu_final, to_final, explicit_threads, _ = _enviroguard(ctx_tokens, cpu_limit or _read_options().get("llm_max_cpu_percent", 80), timeout)
    with _GenCritical(to_final):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256="",
                ctx_tokens=ctx_final,
                cpu_limit=cpu_final,
                hf_token=hf_token
            )
            if not ok:
                return _riff_fallback(persona, subject)

        prompt = _prompt_for_riff(persona, subject, allow_profanity)
        out = _do_generate(prompt)
        if not out:
            return _riff_fallback(persona, subject)

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
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

def persona_riff(
    *,
    persona: str,
    context: str,
    max_lines: int = 3,
    timeout: int = 8,
    cpu_limit: int = 80,
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

    ctx_final, cpu_final, to_final, explicit_threads, _ = _enviroguard(ctx_tokens, cpu_limit, timeout)
    with _GenCritical(to_final):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_final,
                cpu_limit=cpu_final,
                hf_token=hf_token
            )
            if not ok:
                return [_riff_fallback(persona, context.strip().splitlines()[0] if context else "Status")]

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
        sys_prompt = " ".join(sys_rules)

        user = (
            f"{(context or '').strip()}\n\n"
            f"Write up to {max(1,int(max_lines or 3))} short lines in the requested voice."
        )
        prompt = f"<s>[INST] <<SYS>>{sys_prompt}<</SYS>>\n{user} [/INST]"

        raw = _do_generate(prompt)
        if not raw:
            return [_riff_fallback(persona, context.strip().splitlines()[0] if context else "Status")]

    INSTRUX_PATTERNS = [
        r'^\s*tone\s*:.*$', r'^\s*voice\s*:.*$', r'^\s*context\s*:.*$',
        r'^\s*style\s*:.*$', r'^\s*subject\s*:.*$', r'^\s*write\s+up\s+to\s+\d+.*$',
        r'^\s*\[image\]\s*$', r'^\s*no\s+lists.*$', r'.*context\s*\(for vibes only\).*',
        r'^\s*you\s+write\s+a\s*single.*$', r'^\s*write\s+1.*lines?.*$', r'^\s*avoid\s+profanity.*$',
        r'^\s*<<\s*sys\s*>>.*$', r'^\s*\[/?\s*inst\s*\]\s*$', r'^\s*<\s*/?\s*s\s*>\s*$',
    ]
    _INSTRUX_RX = [re.compile(p, re.I) for p in INSTRUX_PATTERNS]

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    cleaned: List[str] = []
    seen: set = set()
    for ln in lines:
        t = ln.strip().lstrip("-•* ").strip()
        if not t:
            continue
        if ":" in t[:12] and re.match(r'^\s*(tone|voice|context|style|subject)\s*:', t, flags=re.I):
            continue
        drop = False
        for rx in _INSTRUX_RX:
            if rx.search(t):
                drop = True
                break
        if drop:
            continue
        t = t.replace("[INST]","").replace("[/INST]","").replace("</s>","").replace("<s>","").strip()
        if len(t) > 140:
            t = t[:140].rstrip()
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(t)
        if len(cleaned) >= max(1, int(max_lines or 3)):
            break

    if not cleaned:
        return [_riff_fallback(persona, context.strip().splitlines()[0] if context else "Status")]
    return cleaned

# ============================
# Self-test (optional)
# ============================
if __name__ == "__main__":
    print("llm_client self-check start")
    try:
        ctx, cpu, to, thr, prof = _enviroguard(2048, 80, 8)
        ok = ensure_loaded(
            model_url=os.getenv("TEST_MODEL_URL",""),
            model_path=os.getenv("TEST_MODEL_PATH","/share/jarvis_prime/models/test.gguf"),
            model_sha256=os.getenv("TEST_MODEL_SHA256",""),
            ctx_tokens=ctx,
            cpu_limit=cpu,
            hf_token=os.getenv("TEST_HF_TOKEN","")
        )
        print(f"ensure_loaded -> {ok} mode={LLM_MODE}")
        if ok:
            txt = rewrite(
                text="Status synchronized; elegance maintained.",
                mood="jarvis",
                timeout=to,
                model_url=os.getenv("TEST_MODEL_URL",""),
                model_path=os.getenv("TEST_MODEL_NAME",""),
                ctx_tokens=ctx
            )
            print("rewrite sample ->", (txt or "")[:120])
            r = riff(
                subject="Sonarr ingestion nominal",
                persona="rager",
                timeout=to
            )
            print("riff sample ->", r)
            rl = persona_riff(
                persona="nerd",
                context="Backup complete on NAS-01; rsync delta=2.3GB; checksums verified.",
                timeout=to
            )
            print("persona_riff sample ->", rl[:3])
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")
```0