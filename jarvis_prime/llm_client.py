#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations

import os
import re
import time
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Optional, List, Dict

try:
    from ctransformers import AutoModelForCausalLM
except Exception:
    AutoModelForCausalLM = None  # type: ignore

# Optional HTTP (unused if you don't configure Ollama)
try:
    import requests
except Exception:
    requests = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# =================== Config knobs (env) ===================
def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default

# Context & decoding
CTX            = _int_env("LLM_CTX_TOKENS", 4096)
GEN_TOKENS     = _int_env("LLM_GEN_TOKENS", 180)
MAX_LINES      = _int_env("LLM_MAX_LINES", 10)
CHARS_PER_TOKEN = 4
SAFETY_TOKENS   = 32

TEMP     = _float_env("LLM_TEMPERATURE", 0.05)
TOP_P    = _float_env("LLM_TOP_P", 0.80)
REPEAT_P = _float_env("LLM_REPEAT_PENALTY", 1.40)

# Model discovery
SEARCH_ROOTS = [
    Path("/share/jarvis_prime"),
    Path("/share/jarvis_prime/models"),
    Path("/share"),
]

# Optional Ollama base URL (will be ignored if empty)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()

# Preferred model family selector
MODEL_PREF = [s for s in os.getenv("LLM_MODEL_PREFERENCE", "phi,qwen,tinyllama").lower().split(",") if s]

# Global model handle
_loaded_model = None
_model_path: Optional[Path] = None


# =================== Utilities ===================
def _list_local_models() -> list[Path]:
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out.extend(root.rglob("*.gguf"))
    # stable, unique order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in sorted(out):
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq

def _choose_preferred(paths: list[Path]) -> Optional[Path]:
    if not paths:
        return None

    def score(p: Path):
        name = p.name.lower()
        fam = min([i for i, f in enumerate(MODEL_PREF) if f and f in name] + [999])
        bias = 0 if str(p).startswith("/share/jarvis_prime/") else (1 if str(p).startswith("/share/") else 2)
        size = p.stat().st_size if p.exists() else 1 << 60
        return (fam, bias, size)

    return sorted(paths, key=score)[0]

def _first_gguf_under(p: Path) -> Optional[Path]:
    try:
        if p.is_file() and p.suffix.lower() == ".gguf":
            return p
        if p.is_dir():
            cands = list(p.rglob("*.gguf"))
            if cands:
                return _choose_preferred(cands)
    except Exception:
        pass
    return None

def _download_to(url: str, dest: Path) -> bool:
    if not requests:
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if chunk:
                        f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
        return False

def _resolve_model_path() -> Optional[Path]:
    # 1) explicit env path (file or dir)
    env_model_path = os.getenv("LLM_MODEL_PATH", "").strip()
    if env_model_path:
        p = Path(env_model_path)
        f = _first_gguf_under(p)
        if f:
            return f

    # 2) known local dirs
    best = _choose_preferred(_list_local_models())
    if best:
        return best

    # 3) download if URL(s) provided
    urls_raw = os.getenv("LLM_MODEL_URLS", "").strip()
    url_one  = os.getenv("LLM_MODEL_URL", "").strip()
    urls = [u for u in (urls_raw.split(",") if urls_raw else []) + ([url_one] if url_one else []) if u]
    for u in urls:
        name = u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"):
            name += ".gguf"
        dest = Path("/share/jarvis_prime/models") / name
        if dest.exists():
            return dest
        if _download_to(u, dest):
            return dest
    return None

def prefetch_model(model_path: Optional[str] = None, model_url: Optional[str] = None) -> None:
    """Optional prefetch hook used by the bot on startup."""
    global _model_path
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f:
            _model_path = f
            return
    _model_path = _resolve_model_path()

def _resolve_any_path(model_path: Optional[str], model_url: Optional[str]) -> Optional[Path]:
    # 1) explicit
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f:
            return f
    # 2) cached
    if _model_path and Path(_model_path).exists():
        return _first_gguf_under(Path(_model_path)) or Path(_model_path)
    # 3) default resolver (may download if URLs env present)
    return _resolve_model_path()

def _cpu_threads_for_limit(limit_pct: int) -> int:
    """Approximate CPU cap by reducing llama.cpp threads."""
    cores = max(1, os.cpu_count() or 1)
    limit = max(1, min(100, int(limit_pct or 100)))
    threads = max(1, int(round(cores * (limit / 100.0))))
    return threads

def _load_local_model(path: Path):
    """Load ctransformers model lazily. Honors context length and thread cap."""
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model
    if AutoModelForCausalLM is None:
        return None

    # If a directory was passed, pick a .gguf inside it
    if path.is_dir():
        gg = _first_gguf_under(path)
        if gg:
            path = gg

    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",               # works for llama/phi/tinyllama gguf via llama.cpp backend
            context_length=CTX,
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS", "0")),
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None


# =================== Rewriter helpers ===================
IMG_MD_RE       = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE      = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)
PLACEHOLDER_RE  = re.compile(r'\[([A-Z][A-Z0-9 _:/\-\.,]{2,})\]')
UPSELL_RE       = re.compile(r'(?i)\b(please review|confirm|support team|contact .*@|let us know|thank you|stay in touch|new feature|check out)\b')

def _extract_images(src: str) -> str:
    imgs = IMG_MD_RE.findall(src or "") + IMG_URL_RE.findall(src or "")
    seen: set[str] = set()
    out: list[str] = []
    for i in imgs:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return "\n".join(out)

def _strip_reasoning(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t:
            continue
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

def _remove_placeholders(text: str) -> str:
    s = PLACEHOLDER_RE.sub("", text or "")
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

def _drop_boilerplate(text: str) -> str:
    kept = []
    for ln in (text or "").splitlines():
        if not ln.strip():
            continue
        if UPSELL_RE.search(ln):
            continue
        kept.append(ln.strip())
    return "\n".join(kept)

def _squelch_repeats(text: str) -> str:
    parts = (text or "").split()
    out: list[str] = []
    prev = None
    count = 0
    for w in parts:
        wl = w.lower()
        if wl == prev:
            count += 1
            if count <= 2:
                out.append(w)
        else:
            prev = wl
            count = 1
            out.append(w)
    s2 = " ".join(out)
    s2 = re.sub(r"(\b\w+\s+\w+)(?:\s+\1){2,}", r"\1 \1", s2, flags=re.I)
    return s2

def _polish(text: str) -> str:
    import re as _re
    s = (text or "").strip()
    s = _re.sub(r"[ \t]+", " ", s)
    s = _re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    s = _re.sub(r"([,:;.!?])(?=\S)", r"\1 ", s)
    s = _re.sub(r"\s*…+\s*", ". ", s)
    s = _re.sub(r"\s+([,:;.!?])", r"\1", s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    fixed = []
    for ln in lines:
        if not _re.search(r"[.!?]$", ln):
            fixed.append(ln + ".")
        else:
            fixed.append(ln)
    s = "\n".join(fixed)
    seen: set[str] = set()
    out: list[str] = []
    for ln in s.splitlines():
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ln)
    return "\n".join(out)

def _cap(text: str, max_lines: int = MAX_LINES, max_chars: int = 800) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out

def _sanitize_system_prompt(s: str) -> str:
    """If a JSON-schema/formatter prompt slipped in, strip it out entirely."""
    if '"$schema"' in s or "SCHEMA:" in s or "USER TEMPLATE:" in s:
        # Keep only a simple, safe instruction
        return "YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."
    return s

def _load_system_prompt() -> str:
    sp = os.getenv("LLM_SYSTEM_PROMPT")
    if sp:
        return _sanitize_system_prompt(sp)

    for p in (Path("/share/jarvis_prime/memory/system_prompt.txt"),
              Path("/app/memory/system_prompt.txt")):
        if p.exists():
            try:
                return _sanitize_system_prompt(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    # fallback
    return "YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."

def _trim_to_ctx(src: str, system: str) -> str:
    if not src:
        return src
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * CHARS_PER_TOKEN)
    remaining = max(500, budget_chars - len(system))
    if len(src) <= remaining:
        return src
    return src[-remaining:]

def _finalize(text: str, imgs: str) -> str:
    out = _strip_reasoning(text)
    out = _remove_placeholders(out)
    out = _drop_boilerplate(out)
    out = _squelch_repeats(out)
    out = _polish(out)
    out = _cap(out, MAX_LINES)
    return out + ("\n" + imgs if imgs else "")


# =================== Public API ===================
def rewrite(text: str, mood: str = "serious", timeout: int = 8, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str] = None,
            model_url: Optional[str] = None, model_path: Optional[str] = None,
            model_sha256: Optional[str] = None, allow_profanity: bool = False) -> str:
    """
    Rewrites `text` with a tiny local GGUF model (ctransformers / llama.cpp).
    - Respects `timeout` (seconds) via a worker thread.
    - Caps CPU by reducing llama.cpp threads according to `cpu_limit` (%).
    - Falls back to returning a lightly cleaned version of the input if anything fails.
    """
    src = (text or "").strip()
    if not src:
        return src

    imgs = _extract_images(src)
    system = _load_system_prompt().format(mood=mood)
    src = _trim_to_ctx(src, system)

    # If a prior "formatter JSON schema" file sneaked in, do not short-circuit — we fixed it in _sanitize_system_prompt

    # 1) Optional Ollama path (ignored if base_url empty / not configured)
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload = {
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": system + "\n\nINPUT:\n" + src + "\n\nOUTPUT:\n",
                "stream": False,
                "options": {
                    "temperature": TEMP,
                    "top_p": TOP_P,
                    "repeat_penalty": REPEAT_P,
                    "num_ctx": CTX,
                    "num_predict": GEN_TOKENS,
                    "stop": ["[SYSTEM]", "[INPUT]", "[OUTPUT]"]
                }
            }
            r = requests.post(base.rstrip("/") + "/api/generate", json=payload, timeout=timeout)
            if r.ok:
                out = str(r.json().get("response", ""))
                return _finalize(out, imgs)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama call failed: {e}", flush=True)
            # fall through to local

    # 2) Local ctransformers (.gguf) with CPU thread cap + timeout
    p = _resolve_any_path(model_path, model_url)
    if p and p.exists():
        m = _load_local_model(p)
        if m is not None:
            prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
            threads = _cpu_threads_for_limit(cpu_limit)

            def _gen() -> str:
                # ctransformers accepts generation kwargs including `threads`
                out = m(
                    prompt,
                    max_new_tokens=GEN_TOKENS,
                    temperature=TEMP,
                    top_p=TOP_P,
                    repetition_penalty=REPEAT_P,
                    stop=["[SYSTEM]", "[INPUT]", "[OUTPUT]"],
                    threads=threads,
                )
                return str(out or "")

            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_gen)
                try:
                    result = fut.result(timeout=max(2, int(timeout or 8)))
                    return _finalize(result, imgs)
                except TimeoutError:
                    # Let the future keep running in thread until it finishes; we just return fallback
                    print(f"[{BOT_NAME}] ⚠️ LLM generation timed out after {timeout}s", flush=True)
                except Exception as e:
                    print(f"[{BOT_NAME}] ⚠️ Generation failed: {e}", flush=True)

    # 3) Fallback (no LLM or failure)
    return _finalize(src, imgs)


def engine_status() -> Dict[str, object]:
    """Quick status for boot card."""
    base = (OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            r = requests.get(base.rstrip("/") + "/api/version", timeout=3)
            ok = r.ok
        except Exception:
            ok = False
        return {"ready": bool(ok), "model_path": "", "backend": "ollama"}

    p = _resolve_any_path(os.getenv("LLM_MODEL_PATH", ""), os.getenv("LLM_MODEL_URL", ""))
    return {
        "ready": bool(p and Path(p).exists()),
        "model_path": str(p or ""),
        "backend": "ctransformers" if p else "none",
    }