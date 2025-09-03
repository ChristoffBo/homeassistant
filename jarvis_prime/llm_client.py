#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations

import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Optional, List, Dict

# ---------- Optional backends ----------
try:
    from ctransformers import AutoModelForCausalLM
except Exception:
    AutoModelForCausalLM = None  # type: ignore

try:
    import requests
except Exception:
    requests = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# ---------- Env helpers ----------
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

# ---------- Decoding & limits ----------
CTX             = _int_env("LLM_CTX_TOKENS", 4096)
GEN_TOKENS      = _int_env("LLM_GEN_TOKENS", 180)
MAX_LINES       = _int_env("LLM_MAX_LINES", 10)
CHARS_PER_TOKEN = 4
SAFETY_TOKENS   = 48

TEMP     = _float_env("LLM_TEMPERATURE", 0.15)
TOP_P    = _float_env("LLM_TOP_P", 0.85)
REPEAT_P = _float_env("LLM_REPEAT_PENALTY", 1.45)

# ---------- Model discovery ----------
SEARCH_ROOTS = [Path("/share/jarvis_prime/models"), Path("/share/jarvis_prime"), Path("/share")]
OLLAMA_BASE_URL = os.getenv("LLM_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "")).strip()
MODEL_PREF = [s for s in os.getenv("LLM_MODEL_PREFERENCE", "phi,qwen,tinyllama,llama").lower().split(",") if s]

_loaded_model = None
_model_path: Optional[Path] = None

# ---------- FS helpers ----------
def _list_local_models() -> List[Path]:
    out: List[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out.extend(root.rglob("*.gguf"))
    uniq, seen = [], set()
    for p in sorted(out):
        s = str(p)
        if s not in seen:
            seen.add(s); uniq.append(p)
    return uniq

def _choose_preferred(paths: List[Path]) -> Optional[Path]:
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
    env_model_path = os.getenv("LLM_MODEL_PATH", "").strip()
    if env_model_path:
        p = Path(env_model_path)
        f = _first_gguf_under(p)
        if f: return f
    best = _choose_preferred(_list_local_models())
    if best:
        return best
    urls_raw = os.getenv("LLM_MODEL_URLS", "").strip()
    url_one  = os.getenv("LLM_MODEL_URL", "").strip()
    urls = [u for u in (urls_raw.split(",") if urls_raw else []) + ([url_one] if url_one else []) if u]
    for u in urls:
        name = u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"): name += ".gguf"
        dest = Path("/share/jarvis_prime/models") / name
        if dest.exists(): return dest
        if _download_to(u, dest): return dest
    return None

def prefetch_model(model_path: Optional[str] = None, model_url: Optional[str] = None) -> None:
    global _model_path
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f: _model_path = f; return
    _model_path = _resolve_model_path()

def _resolve_any_path(model_path: Optional[str], model_url: Optional[str]) -> Optional[Path]:
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f: return f
    if _model_path and Path(_model_path).exists():
        return _first_gguf_under(Path(_model_path)) or Path(_model_path)
    return _resolve_model_path()

def _cpu_threads_for_limit(limit_pct: int) -> int:
    cores = max(1, os.cpu_count() or 1)
    limit = max(1, min(100, int(limit_pct or 100)))
    return max(1, int(round(cores * (limit / 100.0))))

def _load_local_model(path: Path):
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model
    if AutoModelForCausalLM is None:
        return None
    if path.is_dir():
        gg = _first_gguf_under(path)
        if gg: path = gg
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",      # works for llama/phi/qwen/tinyllama gguf
            context_length=CTX,
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS", "0")),
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

# ---------- Cleaning helpers ----------
IMG_MD_RE       = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE      = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)
PLACEHOLDER_RE  = re.compile(r'\[([A-Z][A-Z0-9 _:/\-\.,]{2,})\]')

def _strip_reasoning(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t: continue
        tl = t.lower()
        if tl.startswith(("input:", "output:", "system:", "explanation:", "analysis:", "step")):
            continue
        if any(bad in tl for bad in ("click", "search", "instruction", "guideline")):
            continue
        if t in ("[SYSTEM]", "[INPUT]", "[OUTPUT]"):
            continue
        lines.append(t)
    return "\n".join(lines)

def _cleanup_quip_block(text: str, max_lines: int) -> List[str]:
    if not text: return []
    s = _strip_reasoning(text)
    parts = []
    for ln in s.splitlines():
        for seg in re.split(r'(?<=[.!?])\s+', ln.strip()):
            if seg: parts.append(seg.strip())
    out, seen = [], set()
    for ln in parts:
        if not ln: continue
        if len(ln.split()) > 22:
            ln = " ".join(ln.split()[:22])
        k = ln.lower()
        if k in seen: continue
        seen.add(k)
        if ln in ("[]", "{}", "()"): continue
        out.append(ln)
        if len(out) >= max_lines: break
    return out

# ---------- PUBLIC: persona riff ----------
def persona_riff(persona: str, context: str, max_lines: int = 3, timeout: int = 8,
                 cpu_limit: int = 70, models_priority: Optional[List[str]] = None,
                 base_url: Optional[str] = None, model_url: Optional[str] = None,
                 model_path: Optional[str] = None) -> List[str]:
    persona = (persona or "ops").strip().lower()
    ctx = (context or "").strip()
    if not ctx: return []

    instruction = (
        f"You are '{persona}'. Produce ONLY {max(1, min(3, int(max_lines or 3)))} short, punchy lines. "
        "Each line < 140 chars. No lists, no steps, no instructions, no JSON. "
        "Do NOT summarize facts. Do NOT invent. Just persona-style quips."
    )

    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload = {
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": instruction + "\n\nContext (for vibe only):\n" + ctx + "\n\nQuips:\n",
                "stream": False,
                "options": {
                    "temperature": TEMP,
                    "top_p": TOP_P,
                    "repeat_penalty": REPEAT_P,
                    "num_ctx": CTX,
                    "num_predict": 128,
                    "stop": ["Quips:", "Rules:", "Persona:", "Context:", "Step", "Click", "Search"]
                }
            }
            r = requests.post(base.rstrip("/") + "/api/generate", json=payload, timeout=timeout)
            if r.ok:
                raw = str(r.json().get("response", ""))
                return _cleanup_quip_block(raw, max_lines)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama riff failed: {e}", flush=True)

    p = _resolve_any_path(model_path, model_url)
    if p and p.exists():
        m = _load_local_model(p)
        if m is not None:
            prompt = f"{instruction}\n\nContext (for vibe only):\n{ctx}\n\nQuips:\n"
            threads = _cpu_threads_for_limit(cpu_limit)
            def _gen() -> str:
                return str(m(
                    prompt,
                    max_new_tokens=128,
                    temperature=TEMP,
                    top_p=TOP_P,
                    repetition_penalty=REPEAT_P,
                    stop=["Quips:", "Rules:", "Persona:", "Context:", "Step", "Click", "Search"],
                    threads=threads,
                ) or "")
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_gen)
                try:
                    return _cleanup_quip_block(fut.result(timeout=max(2, int(timeout or 8))), max_lines)
                except TimeoutError:
                    print(f"[{BOT_NAME}] ⚠️ riff timed out", flush=True)
                except Exception as e:
                    print(f"[{BOT_NAME}] ⚠️ riff failed: {e}", flush=True)
    return []

# ---------- PUBLIC: rewrite ----------
def rewrite(text: str, mood: str = "serious", timeout: int = 8, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str] = None,
            model_url: Optional[str] = None, model_path: Optional[str] = None,
            model_sha256: Optional[str] = None, allow_profanity: bool = False) -> str:
    src = (text or "").strip()
    if not src: return src

    # Normal rewrite path (used by beautify)
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload = {
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": f"Rewrite clearly in mood={mood}. Keep facts exact. Input:\n{src}\nOutput:",
                "stream": False,
                "options": {
                    "temperature": TEMP,
                    "top_p": TOP_P,
                    "repeat_penalty": REPEAT_P,
                    "num_ctx": CTX,
                    "num_predict": GEN_TOKENS
                }
            }
            r = requests.post(base.rstrip("/") + "/api/generate", json=payload, timeout=timeout)
            if r.ok:
                return str(r.json().get("response", ""))
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama rewrite failed: {e}", flush=True)

    return src

# ---------- Engine status ----------
def engine_status() -> Dict[str, object]:
    base = (OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            r = requests.get(base.rstrip("/") + "/api/version", timeout=3)
            ok = r.ok
        except Exception:
            ok = False
        return {"ready": bool(ok), "model_path": "", "backend": "ollama"}
    p = _resolve_any_path(os.getenv("LLM_MODEL_PATH", ""), os.getenv("LLM_MODEL_URL", ""))
    return {"ready": bool(p and Path(p).exists()), "model_path": str(p or ""), "backend": "ctransformers" if p else "none"}