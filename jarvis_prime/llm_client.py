#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations

import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Optional, List, Dict

# =========================
# Environment & constants
# =========================
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

def _int_env(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)).strip())
    except Exception: return default

def _float_env(name: str, default: float) -> float:
    try: return float(os.getenv(name, str(default)).strip())
    except Exception: return default

CTX             = _int_env("LLM_CTX_TOKENS", 4096)
GEN_TOKENS      = _int_env("LLM_GEN_TOKENS", 180)
MAX_LINES       = _int_env("LLM_MAX_LINES", 10)
SAFETY_TOKENS   = 64
CHARS_PER_TOKEN = 4

TEMP     = _float_env("LLM_TEMPERATURE", 0.2)
TOP_P    = _float_env("LLM_TOP_P", 0.9)
REPEAT_P = _float_env("LLM_REPEAT_PENALTY", 1.3)

TIMEOUT_DEFAULT = _int_env("LLM_TIMEOUT_SECONDS", 12)
CPU_LIMIT_PCT   = _int_env("LLM_MAX_CPU_PERCENT", 70)

OLLAMA_BASE_URL = (os.getenv("LLM_OLLAMA_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or "").strip()

# Model search roots (local gguf)
SEARCH_ROOTS = [
    Path(os.getenv("LLM_MODELS_DIR", "/share/jarvis_prime/models")),
    Path("/share/jarvis_prime"),
    Path("/share"),
]

# Preference list (names or families; order = priority)
# Accepts comma list or JSON array
def _parse_priority(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw: return []
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            return [str(x).lower().strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [s.lower().strip() for s in raw.split(",") if s.strip()]

MODELS_PRIORITY = _parse_priority(
    os.getenv("LLM_MODELS_PRIORITY", os.getenv("llm_models_priority", "phi3,qwen15,phi2,llama32_1b,tinyllama,qwen05"))
)

# Optional explicit model path/url from config.json
EXPLICIT_MODEL_PATH = os.getenv("LLM_MODEL_PATH", os.getenv("llm_model_path", "")).strip()
EXPLICIT_MODEL_URL  = os.getenv("LLM_MODEL_URL",  os.getenv("llm_model_url",  "")).strip()

# =========================
# Optional deps
# =========================
try:
    import requests
except Exception:
    requests = None  # type: ignore

try:
    from ctransformers import AutoModelForCausalLM  # llama.cpp gguf runner
except Exception:
    AutoModelForCausalLM = None  # type: ignore

# =========================
# Local model discovery
# =========================
# Map short “family” keys to substrings we’ll match inside filenames
FAMILY_HINTS = {
    "phi3":        ("phi-3", "phi_3", "phi3"),
    "phi2":        ("phi-2", "phi_2", "phi2"),
    "qwen15":      ("qwen2.5-1.5b", "qwen1.5", "qwen15"),
    "qwen05":      ("qwen2.5-0.5b", "qwen0.5", "qwen05"),
    "llama32_1b":  ("llama-3.2-1b", "llama3.2-1b", "llama32-1b"),
    "llama":       ("llama",),
    "tinyllama":   ("tinyllama",),
    "qwen":        ("qwen",),
    "mistral":     ("mistral",),
}

_loaded_model = None
_loaded_path: Optional[Path] = None

def _list_gguf() -> List[Path]:
    out: List[Path] = []
    for root in SEARCH_ROOTS:
        try:
            if root.exists():
                out.extend(root.rglob("*.gguf"))
        except Exception:
            pass
    # stable order, unique
    seen = set(); uniq: List[Path] = []
    for p in sorted(out):
        s = str(p)
        if s not in seen:
            seen.add(s); uniq.append(p)
    return uniq

def _choose_by_priority(paths: List[Path], priority: List[str]) -> Optional[Path]:
    if not paths: return None

    def fam_rank(name: str) -> int:
        n = name.lower()
        for i, fam in enumerate(priority):
            hints = FAMILY_HINTS.get(fam, (fam,))
            if any(h in n for h in hints):
                return i
        return len(priority) + 999

    def score(p: Path):
        name = p.name
        fam = fam_rank(name)
        # prefer files under /share/jarvis_prime/models > /share/jarvis_prime > /share
        path_s = str(p)
        if path_s.startswith("/share/jarvis_prime/models/"): bias = 0
        elif path_s.startswith("/share/jarvis_prime/"):      bias = 1
        elif path_s.startswith("/share/"):                   bias = 2
        else:                                                bias = 3
        size = p.stat().st_size if p.exists() else 0
        return (fam, bias, -size)  # larger first

    return sorted(paths, key=score)[0]

def _resolve_local_model(explicit_path: Optional[str] = None) -> Optional[Path]:
    # 1) explicit path (file or dir)
    ep = (explicit_path or EXPLICIT_MODEL_PATH or "").strip()
    if ep:
        p = Path(ep)
        if p.is_file() and p.suffix.lower() == ".gguf":
            return p
        if p.is_dir():
            cands = list(p.rglob("*.gguf"))
            best = _choose_by_priority(cands, MODELS_PRIORITY) if cands else None
            if best: return best

    # 2) scan
    all_gguf = _list_gguf()
    best = _choose_by_priority(all_gguf, MODELS_PRIORITY) if all_gguf else None
    return best

def _download(url: str, dest: Path) -> bool:
    if not requests: return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with requests.get(url, stream=True, timeout=max(8, TIMEOUT_DEFAULT)) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if chunk: f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
        return False

def _resolve_or_download(url: Optional[str]) -> Optional[Path]:
    if not url: return None
    try:
        name = url.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"): name += ".gguf"
        dest = Path("/share/jarvis_prime/models") / name
        if dest.exists(): return dest
        ok = _download(url, dest)
        return dest if ok else None
    except Exception:
        return None

# =========================
# Ollama backend
# =========================
def _ollama_generate(prompt: str, model_hint_priority: Optional[List[str]] = None,
                     stop: Optional[List[str]] = None, timeout: Optional[int] = None,
                     num_ctx: Optional[int] = None, num_predict: Optional[int] = None) -> Optional[str]:
    base = OLLAMA_BASE_URL
    if not base or not requests:
        return None
    try:
        model = None
        # If user supplies a priority list, pick first name-like that could exist in Ollama
        if model_hint_priority:
            # map shorthand to likely ollama model tags
            for fam in model_hint_priority:
                fam = fam.lower().strip()
                if fam in ("phi3", "phi-3", "phi_3"): model = "phi3"
                elif fam in ("qwen15", "qwen-1.5", "qwen 1.5"): model = "qwen2.5:1.5b-instruct-q4_K_M"  # common tag variants
                elif fam in ("qwen05", "qwen-0.5", "qwen 0.5"): model = "qwen2.5:0.5b-instruct-q4_K_M"
                elif fam in ("llama32_1b", "llama-3.2-1b"):     model = "llama3.2:1b-instruct-q4_K_M"
                elif fam in ("tinyllama",):                     model = "tinyllama:1.1b-chat-q4_K_M"
                elif fam in ("llama", "llama3", "llama-3"):     model = "llama3"
                if model: break
        payload = {
            "model": model or "llama3",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": TEMP,
                "top_p": TOP_P,
                "repeat_penalty": REPEAT_P,
                "num_ctx": num_ctx or CTX,
                "num_predict": num_predict or GEN_TOKENS,
            }
        }
        if stop:
            payload["options"]["stop"] = stop
        r = requests.post(base.rstrip("/") + "/api/generate", json=payload, timeout=timeout or TIMEOUT_DEFAULT)
        if not r.ok: return None
        return str(r.json().get("response", "") or "")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Ollama call failed: {e}", flush=True)
        return None

# =========================
# Local gguf backend
# =========================
def _cpu_threads_for_limit(limit_pct: int) -> int:
    cores = max(1, os.cpu_count() or 1)
    limit = max(1, min(100, int(limit_pct or 100)))
    return max(1, int(round(cores * (limit / 100.0))))

def _ensure_local_model() -> Optional["AutoModelForCausalLM"]:
    global _loaded_model, _loaded_path
    if _loaded_model is not None:
        return _loaded_model

    path: Optional[Path] = None
    # Use explicit path first, else resolve
    if EXPLICIT_MODEL_PATH:
        path = _resolve_local_model(EXPLICIT_MODEL_PATH)
    else:
        path = _resolve_local_model(None)

    if (not path) and EXPLICIT_MODEL_URL:
        path = _resolve_or_download(EXPLICIT_MODEL_URL)

    if not path:
        return None

    try:
        if AutoModelForCausalLM is None:
            return None
        _loaded_path = path
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",  # llama.cpp compatible families (llama, qwen, phi, tinyllama)
            context_length=CTX,
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS", "0")),
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        _loaded_model = None
        return None

def _local_generate(prompt: str, stop: Optional[List[str]] = None,
                    timeout: Optional[int] = None, num_predict: Optional[int] = None) -> Optional[str]:
    m = _ensure_local_model()
    if m is None:
        return None

    threads = _cpu_threads_for_limit(CPU_LIMIT_PCT)
    max_new = num_predict or GEN_TOKENS

    def _gen() -> str:
        return str(m(
            prompt,
            max_new_tokens=max_new,
            temperature=TEMP,
            top_p=TOP_P,
            repetition_penalty=REPEAT_P,
            stop=stop or [],
            threads=threads,
        ) or "")

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_gen)
            return fut.result(timeout=max(2, timeout or TIMEOUT_DEFAULT))
    except TimeoutError:
        print(f"[{BOT_NAME}] ⚠️ Generation timed out after {timeout or TIMEOUT_DEFAULT}s", flush=True)
        return None
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Generation failed: {e}", flush=True)
        return None

# =========================
# Cleaning helpers
# =========================
IMG_MD_RE       = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE      = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)
PLACEHOLDER_RE  = re.compile(r'\[([A-Z][A-Z0-9 _:/\-\.,]{2,})\]')

def _extract_images(src: str) -> str:
    imgs = IMG_MD_RE.findall(src or "") + IMG_URL_RE.findall(src or "")
    out, seen = [], set()
    for i in imgs:
        if i not in seen:
            seen.add(i); out.append(i)
    return "\n".join(out)

def _strip_reasoning(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t: continue
        tl = t.lower()
        if tl.startswith(("input:", "output:", "explanation:", "reasoning:", "analysis:", "system:")):
            continue
        if t in ("[SYSTEM]", "[INPUT]", "[OUTPUT]") or t.startswith(("[SYSTEM]", "[INPUT]", "[OUTPUT]")):
            continue
        if t.startswith("[") and t.endswith("]") and len(t) < 40:
            continue
        if tl.startswith("note:"):
            continue
        lines.append(t)
    return "\n".join(lines)

def _strip_meta_lines(text: str) -> str:
    BAD = (
        "persona", "rules", "rule:", "instruction", "guideline",
        "system prompt", "style hint", "produce only", "no bullets", "do not summarize"
    )
    out = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t: continue
        low = t.lower()
        if any(b in low for b in BAD): continue
        out.append(t)
    return "\n".join(out)

def _remove_placeholders(text: str) -> str:
    s = PLACEHOLDER_RE.sub("", text or "")
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

def _drop_boilerplate(text: str) -> str:
    return "\n".join([ln.strip() for ln in (text or "").splitlines() if ln.strip()])

def _polish(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    s = re.sub(r"([,:;.!?])(?=\S)", r"\1 ", s)
    s = re.sub(r"\s+([,:;.!?])", r"\1", s)
    # hard-end sentences
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    fixed = [(ln if re.search(r"[.!?]$", ln) else ln + ".") for ln in lines]
    # dedupe lines
    seen = set(); out = []
    for ln in fixed:
        k = ln.lower()
        if k in seen: continue
        seen.add(k); out.append(ln)
    return "\n".join(out)

def _cap_lines(text: str, max_lines: int = MAX_LINES, max_chars: int = 800) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out

def _finalize(text: str, imgs: str) -> str:
    out = _strip_reasoning(text)
    out = _strip_meta_lines(out)
    out = _remove_placeholders(out)
    out = _drop_boilerplate(out)
    out = _polish(out)
    out = _cap_lines(out, MAX_LINES)
    return out + (("\n" + imgs) if imgs else "")

def _trim_to_ctx(src: str, system: str, headroom: int = SAFETY_TOKENS) -> str:
    if not src: return src
    budget_tokens = max(256, CTX - GEN_TOKENS - headroom)
    budget_chars  = max(1000, budget_tokens * CHARS_PER_TOKEN)
    remaining     = max(500, budget_chars - len(system))
    return src if len(src) <= remaining else src[-remaining:]

def _system_prompt() -> str:
    sp = os.getenv("LLM_SYSTEM_PROMPT", "")
    if sp: return sp
    # look for mounted prompt
    for p in (Path("/share/jarvis_prime/memory/system_prompt.txt"),
              Path("/app/memory/system_prompt.txt")):
        try:
            if p.exists():
                return p.read_text(encoding="utf-8")
        except Exception:
            pass
    return "YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."

# =========================
# PUBLIC: rewrite
# =========================
def rewrite(text: str, mood: str = "serious", timeout: int = TIMEOUT_DEFAULT,
            cpu_limit: int = CPU_LIMIT_PCT, models_priority: Optional[List[str]] = None,
            base_url: Optional[str] = None, model_url: Optional[str] = None,
            model_path: Optional[str] = None, model_sha256: Optional[str] = None,
            allow_profanity: bool = False) -> str:
    """
    Safe rewriter. Tries Ollama first (if configured), else local gguf via ctransformers.
    Returns a cleaned version of input if all generation fails.
    """
    src = (text or "").strip()
    if not src:
        return src

    imgs   = _extract_images(src)
    system = _system_prompt().format(mood=mood)
    src2   = _trim_to_ctx(src, system)

    prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src2}\n[OUTPUT]\n"
    stop = ["[SYSTEM]", "[INPUT]", "[OUTPUT]"]

    # 1) Ollama
    out = None
    if (base_url or OLLAMA_BASE_URL) and requests:
        out = _ollama_generate(
            prompt=prompt,
            model_hint_priority=(models_priority or MODELS_PRIORITY),
            stop=stop,
            timeout=timeout,
            num_ctx=CTX,
            num_predict=GEN_TOKENS
        )
        if out: return _finalize(out, imgs)

    # 2) Local GGUF
    # accept explicit path/url from caller if provided
    global EXPLICIT_MODEL_PATH, EXPLICIT_MODEL_URL
    if model_path: EXPLICIT_MODEL_PATH = model_path
    if model_url:  EXPLICIT_MODEL_URL  = model_url

    out = _local_generate(prompt, stop=stop, timeout=timeout, num_predict=GEN_TOKENS)
    if out: return _finalize(out, imgs)

    # 3) Fallback: cleaned input
    return _finalize(src, imgs)

# =========================
# PUBLIC: persona riff
# =========================
def _cleanup_quips(text: str, max_lines: int) -> List[str]:
    if not text: return []
    s = _strip_reasoning(text)
    s = _strip_meta_lines(s)
    s = re.sub(r'^\s*[-•\d\)\.]+\s*', '', s, flags=re.M)
    parts: List[str] = []
    for ln in s.splitlines():
        for seg in re.split(r'(?<=[.!?])\s+', ln.strip()):
            if seg: parts.append(seg.strip())
    out: List[str] = []
    seen = set()
    for ln in parts:
        if not ln: continue
        words = ln.split()
        if len(words) > 22:
            ln = " ".join(words[:22])
        k = ln.lower()
        if k in seen: continue
        seen.add(k)
        if ln in ("[]", "{}", "()"): continue
        out.append(ln)
        if len(out) >= max_lines:
            break
    return out

def persona_riff(persona: str, context: str, max_lines: int = 3, timeout: int = TIMEOUT_DEFAULT,
                 cpu_limit: int = CPU_LIMIT_PCT, models_priority: Optional[List[str]] = None,
                 base_url: Optional[str] = None, model_url: Optional[str] = None,
                 model_path: Optional[str] = None) -> List[str]:
    """
    Generate 1–N SHORT persona-flavored lines about `context`.
    STRICT: no labels, no bullets, no numbering, no JSON, no summaries.
    """
    persona = (persona or "ops").strip().lower()
    ctx = (context or "").strip()
    if not ctx:
        return []

    n = max(1, min(3, int(max_lines or 3)))
    instruction = (
        f"You speak as '{persona}'. Produce ONLY {n} short lines. "
        "Each line under 140 characters. No bullets, no numbering, no labels, no JSON, no quotes. "
        "Do NOT summarize or restate facts. Do NOT invent details. Keep it punchy."
    )
    prompt = instruction + "\n\nContext (vibe only):\n" + ctx + "\n\nQuips:\n"
    stop = ["Quips:", "Rules:", "Persona:", "Context:", "[SYSTEM]", "[INPUT]", "[OUTPUT]"]

    # 1) Ollama
    out = None
    if (base_url or OLLAMA_BASE_URL) and requests:
        out = _ollama_generate(
            prompt=prompt,
            model_hint_priority=(models_priority or MODELS_PRIORITY),
            stop=stop,
            timeout=timeout,
            num_ctx=CTX,
            num_predict=max(64, min(220, GEN_TOKENS // 2 + 64))
        )
        if out:
            return _cleanup_quips(out, n)

    # 2) Local GGUF
    global EXPLICIT_MODEL_PATH, EXPLICIT_MODEL_URL
    if model_path: EXPLICIT_MODEL_PATH = model_path
    if model_url:  EXPLICIT_MODEL_URL  = model_url

    out = _local_generate(
        prompt,
        stop=stop,
        timeout=timeout,
        num_predict=max(64, min(220, GEN_TOKENS // 2 + 64))
    )
    if out:
        return _cleanup_quips(out, n)

    return []

# Back-compat alias some modules expect
llm_quips = persona_riff

# =========================
# PUBLIC: engine status
# =========================
def engine_status() -> Dict[str, object]:
    # Prefer Ollama if configured and reachable
    if OLLAMA_BASE_URL and requests:
        try:
            r = requests.get(OLLAMA_BASE_URL.rstrip("/") + "/api/version", timeout=3)
            ok = bool(r.ok)
        except Exception:
            ok = False
        return {"ready": ok, "model_path": "", "backend": "ollama"}

    p = _resolve_local_model(EXPLICIT_MODEL_PATH) or _resolve_or_download(EXPLICIT_MODEL_URL)
    return {
        "ready": bool(p and Path(p).exists()),
        "model_path": str(p or ""),
        "backend": "ctransformers" if p else "none",
    }