
#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (Phi GGUF only, no Ollama)
# - GGUF local loading via llama-cpp
# - Hugging Face downloads with Authorization header preserved across redirects
# - SHA256 optional integrity check
# - Hard timeouts; best-effort, never crash callers
# - Phi chat template (<|system|>, <|user|>, <|assistant|>, <|end|>) w/ correct EOS
# - EnviroGuard respected FIRST, then options.json, then defaults
# - ctx_tokens is never clamped — what you set is what you get
#
# Public entry points:
#   ensure_loaded(...)
#   rewrite(...)
#   riff(...)
#   persona_riff(...)
# Helper:
#   get_chat_tokens() -> (BOS_TOKEN, EOS_TOKEN)

from __future__ import annotations
import os
import sys
import json
import time
import math
import hashlib
import re
import threading
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, Tuple, List

# ============================
# Chat tokens (Phi-compatible)
# ============================
BOS_TOKEN = "<s>"
EOS_TOKEN = "<|end|>"   # Phi chat EOS (GGUF tokenizer may also emit <|endoftext|>)

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama"
LLM = None               # llama_cpp.Llama instance
LOADED_MODEL_PATH = None
DEFAULT_CTX = 4096
OPTIONS_PATH = "/data/options.json"
SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"

_GEN_LOCK = threading.RLock()

def get_chat_tokens() -> Tuple[str, str]:
    """Return BOS/EOS tokens for external template runners if needed."""
    return BOS_TOKEN, EOS_TOKEN

def _lock_timeout() -> int:
    """Optional env-configurable lock wait. Defaults to 300s."""
    try:
        v = int(os.getenv("LLM_LOCK_TIMEOUT_SECONDS", "300").strip())
        return max(1, min(300, v))
    except Exception:
        return 300

class _GenCritical:
    """Serialize LLM load/generation to avoid collisions; best-effort timed acquire."""
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
            try: _GEN_LOCK.release()
            except Exception: pass

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
# Options
# ============================
def _read_options() -> Dict[str, Any]:
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"options read failed ({OPTIONS_PATH}): {e}")
        return {}

# ============================
# EnviroGuard + Options merge
# ============================
def _int_env(name: str, default: Optional[int]) -> Optional[int]:
    try:
        v = os.getenv(name, "").strip()
        if not v:
            return default
        return int(v)
    except Exception:
        return default

def _effective_limits(default_ctx: int,
                      default_cpu: int,
                      default_timeout: int,
                      default_threads: Optional[int] = None,
                      default_gen_tokens: Optional[int] = None
                      ) -> Tuple[int, int, int, int, int]:
    """
    Priority:
      1) EnviroGuard env vars (ENVGUARD_*), if set
      2) /data/options.json values
      3) Provided defaults
    Returns: (ctx_tokens, cpu_percent, timeout_seconds, threads, gen_tokens)
    """
    opts = _read_options()
    # options.json
    ctx = int(opts.get("llm_ctx_tokens", default_ctx))
    cpu = int(opts.get("llm_max_cpu_percent", default_cpu))
    timeout = int(opts.get("llm_timeout_seconds", default_timeout))
    threads_opt = int(opts.get("llm_threads", default_threads or 0) or 0)
    gen_tokens = int(opts.get("llm_gen_tokens", default_gen_tokens or 256))

    # EnviroGuard overrides — WIN if set
    env_ctx = _int_env("ENVGUARD_CTX_TOKENS", None)
    if env_ctx is not None: ctx = env_ctx
    env_cpu = _int_env("ENVGUARD_CPU_PERCENT", None)
    if env_cpu is not None: cpu = env_cpu
    env_timeout = _int_env("ENVGUARD_TIMEOUT_SECONDS", None)
    if env_timeout is not None: timeout = env_timeout
    env_gen = _int_env("ENVGUARD_GEN_TOKENS", None)
    if env_gen is not None: gen_tokens = env_gen

    # Final sanitization (NO clamping on ctx)
    cpu = min(100, max(1, int(cpu)))
    timeout = max(2, int(timeout))
    gen_tokens = max(16, min(4096, int(gen_tokens)))

    _log(f"effective limits -> ctx={ctx} cpu={cpu}% timeout={timeout}s threads={threads_opt} gen={gen_tokens}")
    return int(ctx), cpu, timeout, int(threads_opt), gen_tokens

# ============================
# SHA256 utils
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
# HTTP helpers (Hugging Face)
# ============================
class _AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None: return None
        auth = req.headers.get("Authorization")
        if auth: new.add_unredirected_header("Authorization", auth)
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

def _download(url: str, dst_path: str, token: Optional[str]) -> bool:
    try: os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    except Exception: pass

    headers = {}
    if token: headers["Authorization"] = f"Bearer {token.strip()}"
    headers["User-Agent"] = "JarvisPrime/1.1 (urllib)"

    try:
        _log(f"downloading: {os.path.basename(url)} -> {dst_path}")
        buf = _http_get(url, headers=headers, timeout=180)
        with open(dst_path, "wb") as f: f.write(buf)
        _log("downloaded ok")
        return True
    except urllib.error.HTTPError as e:
        _log(f"download failed: HTTP {e.code} {getattr(e, 'reason', '')}")
        return False
    except Exception as e:
        _log(f"download failed: {e}")
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
# CPU / Threads
# ============================
def _available_cpus() -> int:
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except Exception:
        pass
    return max(1, os.cpu_count() or 1)

def _threads_from_limits(limit_pct: int, threads_opt: int) -> int:
    if threads_opt and threads_opt > 0:
        _log(f"options override -> threads={threads_opt}")
        return max(1, int(threads_opt))
    cores = _available_cpus()
    try: pct = max(1, min(100, int(limit_pct or 100)))
    except Exception: pct = 100
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

def _load_llama(model_path: str, ctx_tokens: int, cpu_limit: int, threads_opt: int) -> bool:
    global LLM_MODE, LLM, LOADED_MODEL_PATH
    llama_cpp = _try_import_llama_cpp()
    if not llama_cpp: return False
    try:
        threads = _threads_from_limits(cpu_limit, threads_opt)
        os.environ["OMP_NUM_THREADS"] = str(threads)
        os.environ["LLAMA_THREADS"] = str(threads)
        LLM = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=ctx_tokens,
            n_threads=threads,
        )
        LOADED_MODEL_PATH = model_path
        LLM_MODE = "llama"
        _log(f"loaded GGUF model: {model_path} (ctx={ctx_tokens}, threads={threads})")
        _log("stopping on tokens: <|end|>, <|assistant|>, <|endoftext|>")
        return True
    except Exception as e:
        _log(f"llama load failed: {e}")
        LLM = None
        LOADED_MODEL_PATH = None
        LLM_MODE = "none"
        return False

# ============================
# Output cleaning / guards
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
# Prompt builders (Phi chat)
# ============================
def _prompt_for_rewrite(text: str, mood: str, allow_profanity: bool) -> str:
    sys_prompt = _load_system_prompt() or "You are a concise rewrite assistant. Improve clarity and tone. Keep factual content."
    if not allow_profanity:
        sys_prompt += " Avoid profanity."
    user = (
        "Rewrite the text clearly. Keep short, readable sentences.\n"
        f"Mood (subtle): {mood or 'neutral'}\n\n"
        f"{text}"
    )
    # Do NOT inject BOS; tokenizer metadata says add_bos_token=false
    return (
        "<|system|>\n" + sys_prompt + EOS_TOKEN + "\n"
        "<|user|>\n"   + user       + EOS_TOKEN + "\n"
        "<|assistant|>\n"
    )

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
    return (
        "<|system|>\n" + sys_prompt + EOS_TOKEN + "\n"
        "<|user|>\n"   + user       + EOS_TOKEN + "\n"
        "<|assistant|>\n"
    )

# ============================
# Generation (llama-cpp only)
# ============================
def _llama_generate(prompt: str, timeout: int = 12, max_tokens: Optional[int] = None) -> str:
    """Generate text via local llama-cpp (non-streaming)."""
    try:
        import signal
        def _alarm_handler(signum, frame):
            raise TimeoutError("gen timeout")
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(max(1, int(timeout)))

        # Pull llm_gen_tokens each call (respects EnviroGuard & options)
        _ctx, _cpu, _to, _threads, gen_toks = _effective_limits(4096, 80, 20, None, 256)
        mtoks = int(max_tokens or gen_toks)

        out = LLM(
            prompt,
            max_tokens=mtoks,
            temperature=0.35,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=[EOS_TOKEN, "<|endoftext|>"]
        )

        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

        txt = (out.get("choices") or [{}])[0].get("text", "")
        txt = (txt or "").strip()
        if not txt:
            # one quick retry with slightly higher temperature to avoid immediate stop
            out = LLM(
                prompt,
                max_tokens=mtoks,
                temperature=0.5,
                top_p=0.9,
                repeat_penalty=1.1,
                stop=[EOS_TOKEN, "<|endoftext|>"]
            )
            txt = (out.get("choices") or [{}])[0].get("text", "")
            txt = (txt or "").strip()
        return txt
    except TimeoutError as e:
        _log(f"llama timeout: {e}")
        return ""
    except Exception as e:
        _log(f"llama error: {e}")
        return ""

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
    base_url: str = ""  # ignored; kept for API compatibility
) -> bool:
    """
    Load local GGUF via llama-cpp. EnviroGuard & options.json define limits.
    No clamping on ctx — your value is used as-is.
    """
    global LLM_MODE, LLM, LOADED_MODEL_PATH, DEFAULT_CTX

    # Merge limits (EnviroGuard > options > defaults)
    ctx_eff, cpu_eff, _to, threads_eff, _gen = _effective_limits(
        default_ctx=ctx_tokens or 4096,
        default_cpu=cpu_limit or 80,
        default_timeout=20,
        default_threads=None,
        default_gen_tokens=256
    )
    DEFAULT_CTX = int(ctx_eff)  # exact

    with _GenCritical():
        # Resolve URL/path/Token from options if not provided
        model_url, model_path, hf_token = _resolve_model_from_options(model_url, model_path, hf_token)

        # Optional cleanup on switch
        try:
            opts = _read_options()
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

        ok = _load_llama(path, DEFAULT_CTX, cpu_eff, threads_eff or 0)
        return bool(ok)

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
    base_url: str = "",  # ignored
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
    global LLM_MODE, LLM, LOADED_MODEL_PATH, DEFAULT_CTX

    # Merge runtime limits (EnviroGuard-first)
    g_ctx, g_cpu, g_to, _threads, gen_toks = _effective_limits(ctx_tokens or 4096, cpu_limit or 80, timeout or 12, None, None)

    with _GenCritical(g_to):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=g_ctx,
                cpu_limit=g_cpu,
                hf_token=hf_token,
                base_url=""  # ignored
            )
            if not ok:
                return text

        prompt = _prompt_for_rewrite(text, mood, allow_profanity)
        out = _llama_generate(prompt, timeout=g_to, max_tokens=gen_toks)
        final = out if out else text

    final = _strip_meta_markers(final)
    if max_lines:
        final = _trim_lines(final, max_lines)
    if max_chars:
        final = _soft_trim_chars(final, max_chars)
    return final

# ============================
# Public: riff
# ============================
def riff(
    *, subject: str, persona: str = "neutral",
    timeout: int = 8, base_url: str = "", model_url: str = "", model_path: str = "",
    allow_profanity: bool = False
) -> str:
    """
    Generate 1–3 very short riff lines for the bottom of a card.
    Returns empty string if engine unavailable.
    """
    g_ctx, g_cpu, g_to, _threads, gen_toks = _effective_limits(2048, 80, timeout or 8, None, None)

    with _GenCritical(g_to):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256="",
                ctx_tokens=g_ctx,
                cpu_limit=g_cpu,
                hf_token=None,
                base_url=""  # ignored
            )
            if not ok:
                return ""

        prompt = _prompt_for_riff(persona, subject, allow_profanity)
        out = _llama_generate(prompt, timeout=g_to, max_tokens=min(gen_toks, 128))
        if not out:
            return ""

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    cleaned = []
    _instrux = [
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
    _instrux_rx = [re.compile(p, re.I) for p in _instrux]
    for ln in lines:
        t = ln.strip()
        if not t: continue
        skip = any(rx.search(t) for rx in _instrux_rx)
        if skip: continue
        t = re.sub(r'\bcontext\s*:.*$', '', t, flags=re.I).strip()
        t = t.replace("</s>", "").replace("<s>", "").strip()
        if t:
            cleaned.append(t)
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
    base_url: str = "",  # ignored
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
        allow_profanity = False

    g_ctx, g_cpu, g_to, _threads, gen_toks = _effective_limits(ctx_tokens or 4096, cpu_limit or 80, timeout or 8, None, None)

    with _GenCritical(g_to):
        if LLM_MODE == "none":
            ok = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=g_ctx,
                cpu_limit=g_cpu,
                hf_token=hf_token,
                base_url=""  # ignored
            )
            if not ok:
                return []

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
            f"Write up to {max_lines} distinct one-liners. Each ≤ 140 chars.",
            "No bullets or numbering. No labels. No lists. No JSON.",
            "No quotes or catchphrases. No character or actor names.",
            "No explanations or meta-commentary. Output ONLY the lines.",
            "Do NOT tell jokes unless persona = comedian. Do NOT drift into another persona’s style.",
        ]
        if not allow_profanity:
            sys_rules.append("Avoid profanity.")
        sys_prompt = " ".join(sys_rules)

        user = context.strip()
        prompt = (
            "<|system|>\n" + sys_prompt + EOS_TOKEN + "\n"
            "<|user|>\n"   + user       + EOS_TOKEN + "\n"
            "<|assistant|>\n"
        )

        raw = _llama_generate(prompt, timeout=g_to, max_tokens=min(gen_toks, 220))
        if not raw:
            return []

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
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
            base_url=""  # ignored
        )
        print(f"ensure_loaded -> {ok} mode={LLM_MODE}")
        if ok:
            print("chat tokens:", get_chat_tokens())
            txt = rewrite(
                text="Status synchronized; elegance maintained.",
                mood="jarvis",
                timeout=6,
                base_url="",  # ignored
                model_url=os.getenv("TEST_MODEL_URL",""),
                model_path=os.getenv("TEST_MODEL_NAME",""),
                ctx_tokens=2048
            )
            print("rewrite sample ->", txt[:200])
            r = riff(subject="Sonarr ingestion nominal", persona="nerd", base_url="")
            print("riff sample ->", r)
            rl = persona_riff(
                persona="nerd",
                context="Backup complete on NAS-01; rsync delta=2.3GB; checksums verified.",
                base_url=""
            )
            print("persona_riff sample ->", rl[:3])
    except Exception as e:
        print("self-check error:", e)
    print("llm_client self-check end")
