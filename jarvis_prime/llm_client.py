
#!/usr/bin/env python3
from __future__ import annotations

import os, json, time
from pathlib import Path
from typing import Optional, List, Dict, Iterable

# Optional dependencies
try:
    from ctransformers import AutoModelForCausalLM  # local GGUF
except Exception:
    AutoModelForCausalLM = None  # type: ignore

try:
    import requests  # for model download and/or Ollama
except Exception:
    requests = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# Defaults (can be overridden via args)
MODEL_PATH  = Path(os.getenv("LLM_MODEL_PATH", "/share/jarvis_prime/models/model.gguf"))
MODEL_URL   = os.getenv("LLM_MODEL_URL", "")
MODEL_SHA256 = os.getenv("LLM_MODEL_SHA256", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "")  # e.g., http://ollama:11434

# Internal state

def list_local_models() -> list[str]:
    models = []
    for root in [Path("/share/jarvis_prime/models"), Path("/share/jarvis_prime"), Path("/share")]:
        if root.exists():
            for gg in root.rglob("*.gguf"):
                models.append(str(gg))
    return sorted(set(models))

def _iter_candidate_paths() -> Iterable[Path]:
    # Search common locations for .gguf models
    roots = [Path("/share/jarvis_prime/models"), Path("/share/jarvis_prime"), Path("/share")]
    for root in roots:
        if root.exists():
            for gg in sorted(root.glob("*.gguf")):
                yield gg

def _find_any_model() -> Optional[Path]:
    for gg in _iter_candidate_paths():
        return gg
    return None

_loaded_model = None
_model_path: Optional[Path] = None
_backend: str = "none"  # none|ctransformers|ollama

def _ensure_model(path: Path = MODEL_PATH) -> Optional[Path]:
    global _model_path
    if path and path.exists():
        _model_path = path
        return path
    # Try discovery
    guess = _find_any_model()
    if guess:
        _model_path = guess
        return guess
    if MODEL_URL and requests:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            with requests.get(MODEL_URL, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1<<20):
                        if chunk:
                            f.write(chunk)
            os.replace(tmp, path)
            _model_path = path
            return path
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Model download failed: {e}", flush=True)
            return None
    return None

def _load_model(path: Path) -> Optional[object]:
    global _loaded_model, _backend
    if _loaded_model is not None:
        return _loaded_model
    if AutoModelForCausalLM is None:
        return None
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path), model_type="llama", gpu_layers=0
        )
        _backend = "ctransformers"
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

def _ollama_generate(base_url: str, prompt: str, model: str = "llama3.1") -> Optional[str]:
    if not requests:
        return None
    try:
        url = base_url.rstrip("/") + "/api/generate"
        payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.7}}
        r = requests.post(url, json=payload, timeout=30)
        if r.ok:
            j = r.json()
            return str(j.get("response", "")).strip()
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Ollama request failed: {e}", flush=True)
    return None

def prefetch_model(model_path: Optional[str] = None, model_url: Optional[str] = None) -> None:  # noqa: E402
    # If any local .gguf present, we are done
    if list_local_models():
        return
    # Otherwise, try comma-separated env LLM_MODEL_URLS first, then single MODEL_URL
    urls = []
    env_urls = os.getenv('LLM_MODEL_URLS', '')
    if env_urls:
        urls.extend([u.strip() for u in env_urls.split(',') if u.strip()])
    if model_url or MODEL_URL:
        urls.append(model_url or MODEL_URL)
    for u in urls:
        try:
            if not requests:
                break
            dest_root = Path('/share/jarvis_prime/models')
            dest_root.mkdir(parents=True, exist_ok=True)
            name = u.split('/')[-1] or 'model.gguf'
            if not name.endswith('.gguf'):
                name += '.gguf'
            dest = dest_root / name
            if dest.exists():
                continue
            with requests.get(u, stream=True, timeout=60) as r:
                r.raise_for_status()
                tmp = dest.with_suffix('.part')
                with open(tmp, 'wb') as f:
                    for chunk in r.iter_content(1<<20):
                        if chunk:
                            f.write(chunk)
                tmp.replace(dest)
            # stop after first successful download
            break
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Failed to fetch {u}: {e}", flush=True)
    """
    Load or download the local GGUF so startup can show ONLINE quickly.
    No-op if using Ollama only.
    """
    path = Path(model_path) if model_path else MODEL_PATH
    url  = model_url or MODEL_URL
    if OLLAMA_BASE_URL and not (model_path or MODEL_PATH).exists():
        # Using Ollama only; nothing to prefetch locally
        return
    p = _ensure_model(path)
    if p is not None:
        _load_model(p)

def engine_status() -> Dict[str, object]:
    """
    Return a dict used by bot.py to render the boot card.
    Keys:
      - ready: bool
      - model_path: str (if local)
      - backend: 'ctransformers' | 'ollama' | 'none'
    """
    # Prefer Ollama if configured
    base = OLLAMA_BASE_URL.strip()
    if base:
        ready = False
        if requests:
            try:
                r = requests.get(base.rstrip("/") + "/api/version", timeout=3)
                ready = r.ok
            except Exception:
                ready = False
        return {
            "ready": bool(ready),
            "model_path": "",
            "backend": "ollama",
        }

    # Otherwise, local
    p = _model_path or (MODEL_PATH if MODEL_PATH.exists() else None) or _find_any_model()
    ready = bool(list_local_models()) or _loaded_model is not None or (p is not None and p.exists())
    return {
        "ready": bool(ready),
        "model_path": str(p) if p else "",
        "backend": "ctransformers" if ready else "none",
    }

def _strip_numbered_reasoning(text: str) -> str:
    out_lines = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        tl = t.lower()
        if tl.startswith(("input:", "output:", "explanation:", "reasoning:", "analysis:")):
            continue
        # Remove bracketed tags
        if t in ("[SYSTEM]", "[INPUT]", "[OUTPUT]") or t.startswith("[SYSTEM]") or t.startswith("[INPUT]") or t.startswith("[OUTPUT]"):
            continue
        if tl[:2].isdigit() or tl[:1].isdigit():
            # lines like "1. ..." or "2) ..."
            if len(t) > 1 and t[1] in {'.', ')'}:
                continue
        out_lines.append(t)
    return "\n".join(out_lines)

def _cap(text: str, max_lines: int = 6, max_chars: int = 400) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out

def rewrite(text: str, mood: str = "serious", timeout: int = 8, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str] = None,
            model_url: Optional[str] = None, model_path: Optional[str] = None,
            model_sha256: Optional[str] = None, allow_profanity: bool = False) -> str:
    """
    Clamped rewrite. Uses Ollama (if base_url/OLLAMA_BASE_URL is set), otherwise local GGUF via ctransformers.
    If no engine is available, returns the original text.
    """
    src = (text or "").strip()
    if not src:
        return src

    # Select backend
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base:
        # Remote generation
        system = (
            f"You are Jarvis Prime. Tone={mood}. Keep facts, numbers, links unchanged. "
            f"Short, human, no lists, no 'Input/Output/Explanation'. Max 6 short lines."
        )
        prompt = f"{system}\n\nRewrite:\n{src}\n\nNew:"
        out = _ollama_generate(base, prompt, model=(models_priority[0] if models_priority else "llama3.1")) or src
        out = _strip_numbered_reasoning(out)
        return _cap(out, 6, 400)

    # Local model
    p = _ensure_model(Path(model_path) if model_path else MODEL_PATH)
    model = _load_model(p) if p else None

    if model:
        system = (
            f"You are Jarvis Prime. Tone={mood}. Keep facts/URLs/numbers exactly. "
            f"No lists. No 'Input/Output/Explanation'. 2–6 short lines."
        )
        prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
        try:
            out = model(prompt, max_new_tokens=160, temperature=0.8, top_p=0.92, repetition_penalty=1.1)
            out = str(out or "").strip()
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ LLM generation failed: {e}", flush=True)
            out = src
    else:
        out = src

    out = _strip_numbered_reasoning(out)
    out = _cap(out, 6, 400)
    if not out or len(out) < 2:
        out = src[:200]
    return out
