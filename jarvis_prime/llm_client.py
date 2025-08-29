#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, List, Dict

try:
    from ctransformers import AutoModelForCausalLM
except Exception:
    AutoModelForCausalLM = None  # type: ignore

try:
    import requests
except Exception:
    requests = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# =================== Config knobs ===================
CTX = int(os.getenv("LLM_CTX_TOKENS", "4096"))
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "180"))
CHARS_PER_TOKEN = 4
SAFETY_TOKENS = 32

# Decoding knobs (safer & more precise defaults; can override via env if needed)
TEMP = float(os.getenv("LLM_TEMPERATURE", "0.05"))
TOP_P = float(os.getenv("LLM_TOP_P", "0.8"))
REPEAT_P = float(os.getenv("LLM_REPEAT_PENALTY", "1.4"))

SEARCH_ROOTS = [Path("/share/jarvis_prime"), Path("/share/jarvis_prime/models"), Path("/share")]

def _list_local_models() -> list[Path]:
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out += list(root.rglob("*.gguf"))
    seen=set(); uniq=[]
    for p in out:
        s=str(p)
        if s not in seen:
            seen.add(s); uniq.append(p)
    return uniq

def _choose_preferred(paths: list[Path]) -> Optional[Path]:
    if not paths: return None
    pref = (os.getenv("LLM_MODEL_PREFERENCE","phi3,tinyllama,qwen").lower()).split(",")
    def score(p: Path):
        name=p.name.lower()
        fam = min([i for i,f in enumerate(pref) if f and f in name] + [999])
        bias = 0 if str(p).startswith("/share/jarvis_prime/") else (1 if str(p).startswith("/share/") else 2)
        size = p.stat().st_size if p.exists() else 1<<60
        return (fam, bias, size)
    return sorted(paths, key=score)[0]

MODEL_PATH  = Path(os.getenv("LLM_MODEL_PATH", ""))
MODEL_URL   = os.getenv("LLM_MODEL_URL","")
MODEL_URLS  = [u.strip() for u in os.getenv("LLM_MODEL_URLS","").split(",") if u.strip()]
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL","")

_loaded_model = None

# --- helpers: image extraction ---
def _extract_images(s: str):
    """Return list of image URLs/paths found in markdown or HTML; safe fallback to empty list."""
    if not s:
        return []
    urls = []
    try:
        import re as _re
        urls += _re.findall(r'!\[[^\]]*\]\(([^)\s]+)\)', s)
        urls += _re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', s, flags=_re.IGNORECASE)
    except Exception:
        return []
    seen = set(); out = []
    for u in urls:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

# --- helpers: system prompt ---
def _load_system_prompt() -> str:
    """Load system prompt from memory dir; safe default if missing."""
    try:
        import os
        base = os.getenv("LLM_MEMORY_DIR", "/share/jarvis_prime/memory")
        path = Path(base) / "system_prompt.txt"
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore").strip() or "You are Jarvis Prime."
    except Exception:
        pass
    return "You are Jarvis Prime."

# --- helpers: context trimming & finalize ---
def _trim_to_ctx(s: str, system_prompt: str, limit_tokens: int = CTX//2) -> str:
    """Conservative trim based on characters (~4 chars/token). Keeps tail and includes system prompt length."""
    if not s:
        return s
    # very rough char budget
    sys_len = len(system_prompt or "")
    max_chars = max(1024, int(limit_tokens * 4) - sys_len)
    if max_chars < 1024:
        max_chars = 1024
    return s[-max_chars:] if len(s) > max_chars else s

def _finalize(s: str, images=None) -> str:
    return (s or "").strip()

_loaded_backend = ''
_model_path: Optional[Path] = None

def _find_family(path: Path) -> str:
    name = path.name.lower()
    if 'phi-3' in name or 'phi3' in name:
        return 'phi3'
    if 'qwen' in name:
        return 'qwen'
    # tinyllama / llama
    return 'llama'

def _candidate_types(path: Path):
    fam = _find_family(path)
    if fam == 'phi3':
        return ['phi3','llama']
    if fam == 'qwen':
        return ['qwen','llama']
    return ['llama']
def _download_to(url: str, dest: Path) -> bool:
    if not requests: return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1<<20):
                    if chunk: f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
        return False

def _resolve_model_path() -> Optional[Path]:
    if str(MODEL_PATH):
        p=Path(MODEL_PATH)
        if p.is_file() and p.suffix.lower()==".gguf": return p
        if p.is_dir():
            best=_choose_preferred(list(p.rglob("*.gguf")))
            if best: return best
    best=_choose_preferred(_list_local_models())
    if best: return best
    urls = MODEL_URLS or ([MODEL_URL] if MODEL_URL else [])
    for u in urls:
        name=u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"): name += ".gguf"
        dest=Path("/share/jarvis_prime/models")/name
        if dest.exists(): return dest
        if _download_to(u, dest): return dest
    return None

def prefetch_model(model_path: Optional[str]=None, model_url: Optional[str]=None) -> None:
    global _model_path
    # Priority: explicit arg -> env LLM_MODEL_PATH -> resolve
    cand = (model_path or os.getenv('LLM_MODEL_PATH','')).strip()
    if cand:
        p = Path(cand)
        if p.is_file():
            _model_path = p
            return
    _model_path = _resolve_model_path()
    print(f"[{BOT_NAME}] resolve→ { _model_path }", flush=True)
def engine_status() -> Dict[str,object]:
    """Report backend readiness and chosen model path.
    - If OLLAMA_BASE_URL is set, we ping it and report that backend.
    - Else we check local ctransformers + model file.
    """
    base = OLLAMA_BASE_URL.strip()
    if base and requests:
        ok = False
        try:
            r = requests.get(base.rstrip('/') + '/api/version', timeout=3)
            ok = bool(r.ok)
        except Exception:
            ok = False
        return {'ready': ok, 'model_path': '', 'backend': 'ollama'}
    p = _model_path or _resolve_model_path()
    ok = bool(p and Path(p).exists() and AutoModelForCausalLM is not None)
    return {'ready': ok, 'model_path': str(p) if p else '', 'backend': 'ctransformers'}

def _load_local_model(path: Path):
    global _loaded_model, _loaded_backend
    try:
        from ctransformers import AutoModelForCausalLM  # type: ignore
    except Exception:
        AutoModelForCausalLM = None
    # Try ctransformers with candidate types
    if AutoModelForCausalLM is not None:
        for mt in _candidate_types(path):
            try:
                _loaded_model = AutoModelForCausalLM.from_pretrained(
                    str(path), model_type=mt,
                    gpu_layers=int(os.getenv('LLM_GPU_LAYERS','0')),
                    context_length=CTX,
                )
                _loaded_backend = 'ctransformers'
                print(f"[{BOT_NAME}] ✅ ctransformers loaded as {mt}", flush=True)
                return _loaded_model
            except Exception as e:
                print(f"[{BOT_NAME}] ⚠️ ctransformers {mt} load failed: {e}", flush=True)
    # Fallback to llama_cpp if available
    try:
        from llama_cpp import Llama  # type: ignore
        _loaded_model = Llama(
            model_path=str(path),
            n_ctx=CTX,
            n_gpu_layers=int(os.getenv('LLM_GPU_LAYERS','0')),
            logits_all=False,
        )
        _loaded_backend = 'llama_cpp'
        print(f"[{BOT_NAME}] ✅ llama_cpp loaded", flush=True)
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to load local model via any backend: {e}", flush=True)
        _loaded_model = None
        _loaded_backend = ''
    return _loaded_model


def rewrite(text: str, mood: str="serious", timeout: int=8, cpu_limit: int=70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str]=None,
            model_url: Optional[str]=None, model_path: Optional[str]=None,
            model_sha256: Optional[str]=None, allow_profanity: bool=False) -> str:
    src=(text or "").strip()
    if not src: return src

    imgs=_extract_images(src)
    system=_load_system_prompt().format(mood=mood)
    src=_trim_to_ctx(src, system)

    # Special-case trivial tests
    if re.search(r'(?i)\btest\b', src) and len(src) < 600:
        return _finalize(src, imgs)

    # 1) Ollama path
    base=(base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload={
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": system + "\n\nINPUT:\n" + src + "\n\nOUTPUT:\n",
                "stream": False,
                "options": {
                    "temperature": TEMP, "top_p": TOP_P, "repeat_penalty": REPEAT_P,
                    "num_ctx": CTX, "num_predict": GEN_TOKENS,
                    "stop": ["[SYSTEM]", "[INPUT]", "[OUTPUT]"]
                }
            }
            r=requests.post(base.rstrip("/")+"/api/generate", json=payload, timeout=timeout)
            if r.ok:
                out=str(r.json().get("response",""))
                return _finalize(out, imgs)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama call failed: {e}", flush=True)

    # 2) Local ctransformers
    p = Path(model_path) if model_path else (_model_path or _resolve_model_path())
    if p and p.exists():
        if p.is_dir():
            cand = _choose_preferred(list(p.rglob('*.gguf')))
            if cand:
                print(f"[{BOT_NAME}] 🔎 picked {cand} inside {p}", flush=True)
                p = cand
            else:
                print(f"[{BOT_NAME}] ⚠️ No .gguf in {p}", flush=True)
                p = None
    if p and p.exists() and p.is_file():
        if p.is_dir():
            cand = _choose_preferred(list(p.rglob("*.gguf")))
            if cand:
                p = cand
            else:
                print(f"[{BOT_NAME}] ⚠️ No .gguf in {p}", flush=True)
                p = None
    if p and p.exists() and p.is_file():
        m=_load_local_model(p)
        if m is not None:
            prompt=f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
            try:
                out=m(prompt, max_new_tokens=GEN_TOKENS, temperature=TEMP,
                       top_p=TOP_P, repetition_penalty=REPEAT_P, stop=["[SYSTEM]","[INPUT]","[OUTPUT]"])
                return _finalize(str(out or ""), imgs)
            except Exception as e:
                print(f"[{BOT_NAME}] ⚠️ Generation failed: {e}", flush=True)

    # 3) Fallback
    return _finalize(src, imgs)