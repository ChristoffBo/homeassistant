#!/usr/bin/env python3
from __future__ import annotations

import os, time, threading, hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List

# Optional backends
try:
    from llama_cpp import Llama  # llama-cpp-python
except Exception:  # pragma: no cover
    Llama = None  # type: ignore

try:
    from ctransformers import AutoModelForCausalLM  # legacy fallback
except Exception:  # pragma: no cover
    AutoModelForCausalLM = None  # type: ignore

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# -----------------------------
# Model registry (Q4_K_M balanced)
# -----------------------------
REGISTRY: Dict[str, str] = {
    "phi2":        "https://huggingface.co/TheBloke/phi-2-GGUF/resolve/main/phi-2.Q4_K_M.gguf?download=true",
    "phi3":        "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct.Q4_K_M.gguf?download=true",
    "tinyllama":   "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf?download=true",
    "llama32_1b":  "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf?download=true",
    "qwen05":      "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf?download=true",
    "qwen15":      "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true",
}

DEFAULT_PRIORITY: List[str] = ["qwen15","phi2","llama32_1b","tinyllama","qwen05","phi3"]

MODELS_DIR = Path(os.getenv("LLM_MODELS_DIR", "/share/jarvis_prime/models"))
MODELS_DIR.mkdir(parents=True, exist_ok=True)

_cache_lock = threading.Lock()
_model_cache: Dict[str, object] = {}

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _requests_download(url: str, dst: Path) -> None:
    # Use certifi store automatically (requests does)
    assert requests is not None
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        tmp = dst.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(dst)

def _safe_download(url: str, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size > 0:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if requests is not None:
        _requests_download(url, dst)
    else:
        # Very small fallback if requests is unavailable
        import urllib.request, shutil
        tmp = str(dst)+".part"
        with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, length=1024*1024)
        os.replace(tmp, dst)

def _pick_candidate(models_priority: Optional[List[str]], env: Dict[str,str]) -> tuple[str, Optional[str], Optional[str]]:
    """
    Return (key, url, path). Honors explicit LLM_MODEL_PATH/URL first, then per-model env overrides,
    finally built-in REGISTRY.
    """
    # Explicit single overrides
    if env.get("LLM_MODEL_PATH"):
        return ("explicit", None, env["LLM_MODEL_PATH"])
    if env.get("LLM_MODEL_URL"):
        return ("explicit", env["LLM_MODEL_URL"], None)

    order = [m for m in (models_priority or env.get("LLM_MODELS_PRIORITY","").split(",")) if m] or DEFAULT_PRIORITY
    for key in order:
        key_up = key.upper()
        path = env.get(f"LLM_{key_up}_PATH")
        url  = env.get(f"LLM_{key_up}_URL") or REGISTRY.get(key)
        if path or url:
            return (key, url, path)
    # nothing -> last resort TinyLlama
    return ("tinyllama", REGISTRY["tinyllama"], None)

def _load_model(path: Path) -> object:
    # Prefer llama-cpp-python
    global _model_cache
    with _cache_lock:
        if str(path) in _model_cache:
            return _model_cache[str(path)]

        if Llama is not None:
            llm = Llama(model_path=str(path), n_ctx=int(os.getenv("LLM_CTX_TOKENS","512")), n_threads=max(1, os.cpu_count() or 2))
            _model_cache[str(path)] = llm
            return llm

        if AutoModelForCausalLM is not None:
            llm = AutoModelForCausalLM.from_pretrained(str(path), model_type="llama")
            _model_cache[str(path)] = llm
            return llm

        raise RuntimeError("No local backend available (install llama-cpp-python or ctransformers).")

def _format_prompt(text: str, system: str) -> str:
    sys_msg = system.strip() or "You summarize infrastructure alerts into one short actionable line."
    return f"<<SYS>>{sys_msg}<</SYS>>\n\n[INST] {text.strip()} [/INST]"

def rewrite(*, text: str, mood: str = "neutral", timeout: int = 12, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, base_url: str = "",  # kept for API parity; not used
            model_url: str = "", model_path: str = "", model_sha256: str = "", allow_profanity: bool = False,
            ) -> str:
    env = {k:os.getenv(k,"") for k in (
        "LLM_MODEL_PATH","LLM_MODEL_URL","LLM_MODELS_PRIORITY","LLM_CTX_TOKENS",
        "LLM_TINYLLAMA_URL","LLM_TINYLLAMA_PATH",
        "LLM_QWEN05_URL","LLM_QWEN05_PATH",
        "LLM_QWEN15_URL","LLM_QWEN15_PATH",
        "LLM_PHI2_URL","LLM_PHI2_PATH",
        "LLM_PHI3_URL","LLM_PHI3_PATH",
        "LLM_LLAMA32_1B_URL","LLM_LLAMA32_1B_PATH",
        "LLM_MODELS_DIR"
    )}
    if env.get("LLM_MODELS_DIR"):
        global MODELS_DIR
        MODELS_DIR = Path(env["LLM_MODELS_DIR"]); MODELS_DIR.mkdir(parents=True, exist_ok=True)

    key, url, path_str = _pick_candidate(models_priority, env)

    # Resolve destination path
    if path_str:
        path = Path(path_str)
    else:
        fname = f"{key}.Q4_K_M.gguf" if url and "Q4_K_M" in url else (Path(url).name if url else f"{key}.gguf")
        path = MODELS_DIR / fname
        if url:
            _safe_download(url, path)

    if model_sha256:
        got = _sha256(path)
        if got.lower() != model_sha256.lower():
            raise RuntimeError(f"Checksum mismatch for {path.name} (got {got[:8]}…)")

    llm = _load_model(path)

    system_prompt = os.getenv("LLM_SYSTEM_PROMPT","You summarize infrastructure alerts into one short actionable line.")
    prompt = _format_prompt(text, system_prompt)

    result_holder: Dict[str,str] = {"out": ""}
    def _run():
        try:
            if Llama is not None and isinstance(llm, Llama):
                out = llm(prompt=prompt, max_tokens=int(os.getenv("LLM_GEN_TOKENS","96")), stop=["</s>"])
                result_holder["out"] = out["choices"][0]["text"].strip()
            elif AutoModelForCausalLM is not None:
                # Minimal ctransformers generate interface
                result_holder["out"] = llm(text=prompt, max_new_tokens=int(os.getenv("LLM_GEN_TOKENS","96"))).strip()
            else:
                result_holder["out"] = ""
        except Exception as e:
            result_holder["out"] = ""

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        # timeout
        return ""
    return result_holder["out"]

def engine_status() -> Dict[str,object]:
    # Ollama intentionally ignored in this build (no external server)
    key, url, path_str = _pick_candidate(None, {k:os.getenv(k,"") for k in os.environ.keys()})
    path = Path(path_str) if path_str else MODELS_DIR / (Path(url).name if url else f"{key}.gguf")
    return {"ready": path.exists(), "model_path": str(path), "backend": "llama.cpp" if Llama else ("ctransformers" if AutoModelForCausalLM else "none")}
