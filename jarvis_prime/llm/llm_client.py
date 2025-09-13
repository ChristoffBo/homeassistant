
#!/usr/bin/env python3
# /app/llm_client.py  —  clean-room rewrite (local llama-cpp only)
#
# Principles
#   1) EnviroGuard is sovereign: ENV vars override everything.
#   2) Options file is second: /data/options.json fills gaps.
#   3) No Ollama code at all. Local GGUF via llama-cpp-python only.
#   4) Respect CPU% -> threads and pin OpenMP to prevent oversubscription.
#   5) No reloads if the same model is already in memory.
#   6) Hard generation deadlines with clear logging (no silent stalls).
#   7) Phi-style chat prompting with a finish sentinel and robust stop tokens.
#   8) (Per request) persona_* uses system_prompt.txt as the base system prompt.
#
# Public API:
#   ensure_loaded(...)
#   rewrite(...)
#   riff(...)
#   persona_riff(...)

from __future__ import annotations

import os, json, time, math, hashlib, socket, threading, urllib.request, urllib.error, re
from typing import Optional, Dict, Any, Tuple, List

# =============== logging ===============
def _log(msg: str) -> None:
    print(f"[llm] {msg}", flush=True)

# =============== globals ===============
_MODE: str = "none"          # "none" or "llama"
_ENGINE = None               # llama_cpp.Llama instance when loaded
_MODEL_PATH: Optional[str] = None
_DEFAULT_CTX: int = 4096
_G_LOCK = threading.RLock()

# =============== constants / paths ===============
OPT_PATH = "/data/options.json"
SYS_PROMPT_PATH = "/app/system_prompt.txt"

# =============== config + precedence helpers ===============
def _env_present(name: str) -> bool:
    v = os.getenv(name, None)
    return v is not None and str(v).strip() != ""

def _env_int(name: str, default: Optional[int]) -> Optional[int]:
    if not _env_present(name):
        return default
    try:
        return int(str(os.getenv(name)).strip())
    except Exception:
        return default

def _read_options() -> Dict[str, Any]:
    try:
        with open(OPT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"options read failed ({OPT_PATH}): {e}")
        return {}

def _merge_limits(ctx_def: int, cpu_def: int, to_def: int) -> Tuple[int, int, int, str]:
    """
    Resolve ctx_tokens, cpu_percent, timeout_seconds with strict precedence:
      1) ENVGUARD_* (only if the env var is present)  ← EnviroGuard is GOD
      2) options.json (profile or flat keys)
      3) provided defaults
    Returns: (ctx, cpu%, timeout, source_label)
    """
    source = "defaults"
    ctx, cpu, to = ctx_def, cpu_def, to_def

    # read options second
    opt = _read_options()
    # profile form A: {"enviroguard_profiles": {"manual": {...}}, "enviroguard_profile": "manual"}
    profile_name = (opt.get("enviroguard_profile") or "").strip()
    profiles = opt.get("enviroguard_profiles") or {}
    if profile_name and isinstance(profiles, dict) and profile_name in profiles:
        row = profiles[profile_name] or {}
        try:
            ctx = int(row.get("ctx_tokens", ctx))
            cpu = int(row.get("cpu_percent", cpu))
            to  = int(row.get("timeout_seconds", to))
            source = f"options.profile:{profile_name}"
        except Exception:
            pass
    else:
        # profile form B: top-level blocks: {"manual":{...},"hot":{...},...} + "enviroguard_profile":"manual"
        if profile_name and profile_name in opt and isinstance(opt[profile_name], dict):
            row = opt[profile_name]
            try:
                ctx = int(row.get("ctx_tokens", ctx))
                cpu = int(row.get("cpu_percent", cpu))
                to  = int(row.get("timeout_seconds", to))
                source = f"options.block:{profile_name}"
            except Exception:
                pass
        else:
            # flat overrides
            try:
                if "llm_ctx_tokens" in opt: ctx = int(opt["llm_ctx_tokens"])
                if "llm_max_cpu_percent" in opt: cpu = int(opt["llm_max_cpu_percent"])
                if "llm_timeout_seconds" in opt: to  = int(opt["llm_timeout_seconds"])
                source = "options.flat"
            except Exception:
                pass

    # now ENV (sovereign) last: only override if set
    if _env_present("ENVGUARD_CTX_TOKENS"):
        ctx = _env_int("ENVGUARD_CTX_TOKENS", ctx)
        source = "ENV"
    if _env_present("ENVGUARD_CPU_PERCENT"):
        cpu = _env_int("ENVGUARD_CPU_PERCENT", cpu)
        source = "ENV"
    if _env_present("ENVGUARD_TIMEOUT_SECONDS"):
        to  = _env_int("ENVGUARD_TIMEOUT_SECONDS", to)
        source = "ENV"

    # sanity bounds
    try:
        ctx = max(256, int(ctx))
    except Exception:
        ctx = max(256, int(ctx_def))
    try:
        cpu = min(100, max(1, int(cpu)))
    except Exception:
        cpu = min(100, max(1, int(cpu_def)))
    try:
        to  = max(2, int(to))
    except Exception:
        to = max(2, int(to_def))

    _log(f"limits -> ctx={ctx} cpu%={cpu} timeout={to} (src={source})")
    return ctx, cpu, to, source

def _resolve_max_tokens(kind: str, default_val: int) -> int:
    """
    kind: "riff" | "persona" | "rewrite"
    ENV first: ENVGUARD_MAX_TOKENS_<KIND>
    options: llm_max_tokens_<kind>
    """
    val = default_val
    env_key = f"ENVGUARD_MAX_TOKENS_{kind.upper()}"
    if _env_present(env_key):
        try:
            val = max(1, int(str(os.getenv(env_key)).strip()))
            _log(f"{env_key} -> {val}")
            return val
        except Exception:
            pass
    opt = _read_options()
    k = f"llm_max_tokens_{kind.lower()}"
    if k in opt:
        try:
            val = max(1, int(opt[k]))
            _log(f"options {k} -> {val}")
        except Exception:
            pass
    return val

# =============== file + model helpers ===============
def _coerce_path(model_url: str, model_path: str) -> str:
    if not model_path or model_path.endswith("/"):
        fname = model_url.split("/")[-1] if model_url else "model.gguf"
        base = model_path or "/share/jarvis_prime/models"
        return os.path.join(base, fname)
    return model_path

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()

def _download(url: str, dst: str, token: Optional[str]) -> bool:
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    except Exception:
        pass
    headers = {"User-Agent": "JarvisPrime/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=180) as r, open(dst, "wb") as f:
            f.write(r.read())
        return True
    except Exception as e:
        _log(f"download failed: {e}")
        return False

def _ensure_model(model_url: str, model_path: str, token: Optional[str], sha256: str) -> Optional[str]:
    path = _coerce_path(model_url, model_path)
    if not os.path.exists(path):
        if not model_url:
            _log("no model on disk and no URL to fetch")
            return None
        if not _download(model_url, path, token):
            return None
    if sha256:
        try:
            got = _sha256(path).lower()
            if got != sha256.lower():
                _log(f"sha256 mismatch: got={got} want={sha256}")
                return None
        except Exception as e:
            _log(f"sha256 check error: {e}")
    return path

def _available_cpus() -> int:
    try:
        if hasattr(os, "sched_getaffinity"):
            return max(1, len(os.sched_getaffinity(0)))
    except Exception:
        pass
    try:
        with open("/sys/fs/cgroup/cpu.max", "r", encoding="utf-8") as f:
            q, p = f.read().strip().split()
            if q != "max":
                qq = int(q); pp = int(p)
                if qq > 0 and pp > 0:
                    return max(1, qq // pp)
    except Exception:
        pass
    return max(1, os.cpu_count() or 1)

def _threads_from_percent(pct: int) -> int:
    # explicit env overrides
    for var in ("LLAMA_THREADS", "OMP_NUM_THREADS"):
        v = str(os.getenv(var, "")).strip()
        if v.isdigit():
            t = max(1, int(v))
            _log(f"env override {var} -> {t} threads")
            return t
    cores = _available_cpus()
    pct = min(100, max(1, int(pct)))
    t = max(1, math.ceil(cores * (pct / 100.0)))
    t = min(cores, t)
    _log(f"threads from {pct}% of {cores} cores -> {t}")
    return t

def _pin_threads(t: int) -> None:
    os.environ["OMP_NUM_THREADS"] = str(t)
    os.environ["LLAMA_THREADS"] = str(t)
    os.environ.setdefault("OMP_DYNAMIC", "false")
    os.environ.setdefault("OMP_PROC_BIND", "true")
    # Avoid hidden thread pools
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

def _import_llama():
    try:
        import llama_cpp
        return llama_cpp
    except Exception as e:
        _log(f"llama-cpp import failed: {e}")
        return None

# =============== system prompt ===============
def _sys_prompt() -> str:
    try:
        if os.path.exists(SYS_PROMPT_PATH):
            with open(SYS_PROMPT_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        _log(f"system prompt read error: {e}")
    return "Be concise and precise. Keep outputs short."

# =============== phi chat template & stops ===============
_SENTINEL = "␟"
_STOPS = [
    "<|end|>", "<|endoftext|>", "</s>",
    "<|user|>", "<|system|>", "<|assistant|>",
    _SENTINEL
]

def _phi_round(user_text: str, system_text: str) -> str:
    return (
        "<|system|>\n" + system_text + "\n<|end|>\n"
        "<|user|>\n"   + user_text   + "\n<|end|>\n"
        "<|assistant|>\n"
    )

def _finish_clean(s: str) -> str:
    s = s.replace(_SENTINEL, "")
    s = re.sub(r"\s*(</s>|<\|end\|>|<\|endoftext\|>)\s*$", "", s)
    return s.strip()

# =============== core generation ===============
def _gen_llama(prompt: str, max_tokens: int, timeout_sec: int) -> str:
    if _MODE != "llama" or _ENGINE is None:
        return ""
    # hard deadline using SIGALRM where available
    try:
        import signal
        def _deadline(*_): raise TimeoutError("gen timeout")
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _deadline)
            signal.alarm(max(1, int(timeout_sec)))
    except Exception:
        pass
    try:
        out = _ENGINE(
            prompt,
            max_tokens=max_tokens,
            temperature=0.35,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=_STOPS
        )
        text = (out.get("choices") or [{}])[0].get("text", "") or ""
        return text.strip()
    except TimeoutError as e:
        _log(f"llama timeout: {e}")
        return ""
    except Exception as e:
        _log(f"llama error: {e}")
        return ""
    finally:
        try:
            import signal
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
        except Exception:
            pass

# =============== public: ensure_loaded ===============
def ensure_loaded(*, model_url: str, model_path: str, model_sha256: str,
                  ctx_tokens: int, cpu_limit: int, hf_token: Optional[str],
                  base_url: str = "") -> bool:
    """
    Local-only: prepare llama-cpp with a GGUF file. No Ollama support.
    """
    global _MODE, _ENGINE, _MODEL_PATH, _DEFAULT_CTX
    # resolve control limits
    ctx_res, cpu_res, _to_res, src = _merge_limits(ctx_tokens, cpu_limit, 12)
    _DEFAULT_CTX = max(1024, int(ctx_res))

    with _G_LOCK:
        # prepare model file
        path = _ensure_model(model_url, model_path, hf_token, model_sha256 or "")
        if not path:
            return False
        # fast-path reuse
        if _MODE == "llama" and _ENGINE is not None and os.path.abspath(path) == os.path.abspath(_MODEL_PATH or ""):
            _log("model already loaded; reuse")
            return True

        # load fresh
        lib = _import_llama()
        if not lib:
            return False
        threads = _threads_from_percent(cpu_res)
        _pin_threads(threads)
        try:
            _ENGINE = lib.Llama(model_path=path, n_ctx=_DEFAULT_CTX, n_threads=threads)
            _MODE = "llama"
            _MODEL_PATH = path
            _log(f"loaded GGUF: {os.path.basename(path)} ctx={_DEFAULT_CTX} threads={threads}")
        except Exception as e:
            _log(f"load failure: {e}")
            _MODE, _ENGINE, _MODEL_PATH = "none", None, None
            return False

        # warm up to eliminate "spool" perception
        try:
            _ = _gen_llama(_phi_round("ok", "warm-up; reply OK then " + _SENTINEL), max_tokens=8, timeout_sec=3)
        except Exception:
            pass
        return True

# =============== builders ===============
def _build_rewrite(text: str, mood: str, allow_profanity: bool) -> str:
    sys_txt = _sys_prompt()
    if not allow_profanity:
        sys_txt += " Avoid profanity."
    user = f"Rewrite the following clearly in short sentences. Mood (subtle): {mood or 'neutral'}.\n\n{text}\n\nFinish with {_SENTINEL}"
    return _phi_round(user, sys_txt)

def _build_riff(persona: str, subject: str, allow_profanity: bool) -> str:
    # persona riffs also use system_prompt.txt as base, per request.
    base_sys = _sys_prompt()
    # minimal persona hint appended to system prompt (does not replace it)
    styles = {
        "dude": "laid-back, mellow, confident",
        "chick": "sassy, clever, stylish",
        "nerd": "precise, witty one-liners",
        "rager": "short, intense; profanity allowed",
        "comedian": "brief one-liner humor only",
        "jarvis": "polished butler",
        "ops": "terse incident commander",
        "action": "stoic mission brief",
        "neutral": "light, neutral"
    }
    voice = styles.get((persona or "neutral").lower(), "light, neutral")
    if not allow_profanity and "profanity allowed" in voice:
        voice = "short, intense; no profanity"
    sys_txt = f"{base_sys} Write 1–3 punchy lines (≤20 words). Style: {voice}. No bullets. Output only lines. End with {_SENTINEL}"
    user = f"Subject: {subject or 'Status update'}"
    return _phi_round(user, sys_txt)

def _build_persona(persona: str, context: str, allow_profanity: bool, n: int) -> str:
    # persona uses system_prompt.txt as base (per explicit requirement)
    base_sys = _sys_prompt()
    base = {
        "dude": "laid-back, mellow",
        "chick": "sassy, clever",
        "nerd": "precise, witty",
        "rager": "short, intense; profanity allowed",
        "comedian": "only persona allowed to joke",
        "jarvis": "polished butler",
        "ops": "terse incident commander",
        "action": "stoic mission brief",
        "neutral": "neutral, concise"
    }
    voice = base.get((persona or "neutral").lower(), "neutral, concise")
    if not allow_profanity and "profanity allowed" in voice:
        voice = voice.replace("profanity allowed", "no profanity")
    sys_txt = f"{base_sys} Voice: {voice}. Write up to {max(1,int(n))} distinct one-liners (≤140 chars). No bullets. End with {_SENTINEL}"
    user = context.strip()
    return _phi_round(user, sys_txt)

# =============== cleaners ===============
_META_RX = [re.compile(p, re.I) for p in [
    r'^\s*subject\s*:.*$',
    r'^\s*style\s*:.*$',
    r'^\s*voice\s*:.*$',
    r'^\s*avoid\s+profanity.*$',
    r'^\s*write\s+1.*lines?\.?.*$',
    r'^\s*no\s+bullets.*$',
    r'^\s*<\|/?(system|user|assistant)\|>\s*$',
]]

def _clean_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    seen: set = set()
    for raw in lines:
        s = raw.strip().lstrip("-•* ").strip()
        if not s:
            continue
        skip = False
        for rx in _META_RX:
            if rx.search(s):
                skip = True
                break
        if skip:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 3:
            break
    return out

# =============== unified dispatch ===============
def _generate(prompt: str, timeout_sec: int, max_tokens: int) -> str:
    text = _gen_llama(prompt, max_tokens=max_tokens, timeout_sec=timeout_sec)
    return _finish_clean(text)

# =============== public: rewrite ===============
def rewrite(*, text: str, mood: str = "neutral", timeout: int = 12, cpu_limit: int = 80,
            models_priority: Optional[str] = None, base_url: str = "", model_url: str = "",
            model_path: str = "", model_sha256: str = "", allow_profanity: bool = False,
            ctx_tokens: int = 4096, hf_token: Optional[str] = None,
            max_lines: int = 0, max_chars: int = 0) -> str:
    global _DEFAULT_CTX
    ctx, cpu, to, _ = _merge_limits(ctx_tokens, cpu_limit, timeout)
    with _G_LOCK:
        if _MODE == "none":
            if not ensure_loaded(model_url=model_url, model_path=model_path, model_sha256=model_sha256,
                                 ctx_tokens=ctx, cpu_limit=cpu, hf_token=hf_token, base_url=""):
                return text
    prompt = _build_rewrite(text, mood, allow_profanity)
    max_tok = _resolve_max_tokens("rewrite", 256)
    out = _generate(prompt, timeout_sec=to, max_tokens=max_tok)
    if not out:
        return text
    # optional trimming
    if max_lines:
        lines = out.splitlines()
        out = "\n".join(lines[:max_lines]) if len(lines) > max_lines else out
    if max_chars and len(out) > max_chars:
        out = out[:max_chars-1].rstrip() + "…"
    return out

# =============== public: riff ===============
def riff(*, subject: str, persona: str = "neutral", timeout: int = 8,
         base_url: str = "", model_url: str = "", model_path: str = "",
         allow_profanity: bool = False) -> str:
    # resolve only timeout (cpu/ctx already applied at ensure_loaded)
    _, _, to, _ = _merge_limits(0, 0, timeout)
    with _G_LOCK:
        if _MODE == "none":
            # conservative ctx/cpu if not previously loaded
            if not ensure_loaded(model_url=model_url, model_path=model_path, model_sha256="",
                                 ctx_tokens=2048, cpu_limit=50, hf_token=None, base_url=""):
                return ""
    prompt = _build_riff(persona, subject, allow_profanity)
    max_tok = _resolve_max_tokens("riff", 48)
    raw = _generate(prompt, timeout_sec=to, max_tokens=max_tok)
    lines = _clean_lines([ln for ln in raw.splitlines() if ln.strip()])
    joined = "\n".join(lines[:3])
    if len(joined) > 120:
        joined = joined[:119].rstrip() + "…"
    return joined

# =============== public: persona_riff ===============
def persona_riff(*, persona: str, context: str, max_lines: int = 3, timeout: int = 8,
                 cpu_limit: int = 80, models_priority: Optional[List[str]] = None,
                 base_url: str = "", model_url: str = "", model_path: str = "",
                 model_sha256: str = "", allow_profanity: Optional[bool] = None,
                 ctx_tokens: int = 4096, hf_token: Optional[str] = None) -> List[str]:
    if allow_profanity is None:
        allow_profanity = False
    _, _, to, _ = _merge_limits(ctx_tokens, cpu_limit, timeout)
    with _G_LOCK:
        if _MODE == "none":
            if not ensure_loaded(model_url=model_url, model_path=model_path, model_sha256=model_sha256,
                                 ctx_tokens=ctx_tokens, cpu_limit=cpu_limit, hf_token=hf_token, base_url=""):
                return []
    prompt = _build_persona(persona, context, allow_profanity, n=max_lines)
    max_tok = _resolve_max_tokens("persona", 80)
    raw = _generate(prompt, timeout_sec=to, max_tokens=max_tok)
    lines = _clean_lines([ln for ln in raw.splitlines() if ln.strip()])
    return lines[:max(1, int(max_lines or 3))]

# =============== self-check ===============
if __name__ == "__main__":
    ok = ensure_loaded(
        model_url=os.getenv("TEST_MODEL_URL",""),
        model_path=os.getenv("TEST_MODEL_PATH","/share/jarvis_prime/models/test.gguf"),
        model_sha256=os.getenv("TEST_MODEL_SHA256",""),
        ctx_tokens=int(os.getenv("TEST_CTX","2048")),
        cpu_limit=int(os.getenv("TEST_CPU","50")),
        hf_token=os.getenv("TEST_HF_TOKEN",""),
        base_url=""
    )
    print(f"ensure_loaded: {ok} mode={_MODE}")
    if ok:
        print("riff:", riff(subject="Sonarr ingestion nominal", persona="ops"))
        print("rewrite:", rewrite(text="Status synchronized; elegance maintained.", mood="jarvis")[:120])
        print("persona:", persona_riff(persona="nerd", context="Backup complete on NAS-01; rsync delta=2.3GB; checksums verified.")[:3])
