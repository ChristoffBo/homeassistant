#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations

import os
import time
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List

import requests

# Soft dep: ctransformers
try:
    from ctransformers import AutoModelForCausalLM
except Exception:  # pragma: no cover
    AutoModelForCausalLM = None

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# Defaults can be overridden by env or callers
MODEL_PATH   = os.getenv("LLM_MODEL_PATH", "/share/jarvis_prime/models/tinyllama-1.1b-chat.v1.Q4_K_M.gguf")
MODEL_URL    = os.getenv("LLM_MODEL_URL", "")
MODEL_SHA256 = (os.getenv("LLM_MODEL_SHA256", "") or "").lower()

# Priority catalog for tiny CPU models (smallest first)
CATALOG: List[Tuple[str, str, str, str]] = [
    # (key, repo, filename, model_type)
    ("qwen2.5-0.5b-instruct", "Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf", "qwen"),
    ("phi-2",                 "TheBloke/phi-2-GGUF",            "phi-2.Q4_K_M.gguf",                  "phi"),
    ("tinyllama-1.1b-chat",  "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF", "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf", "llama"),
]

_model = None
_model_type_hint: Optional[str] = None
_loaded_path: Optional[Path] = None


def _hf_resolve(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, sha256: str = "", timeout: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and dest.stat().st_size > 0:
        if sha256:
            if _sha256_file(dest).lower() == sha256.lower():
                print(f"[{BOT_NAME}] ✅ Model already present: {dest}", flush=True)
                return
            dest.unlink(missing_ok=True)
        else:
            print(f"[{BOT_NAME}] ✅ Model already present: {dest}", flush=True)
            return

    print(f"[{BOT_NAME}] 📥 Downloading LLM model: {url}", flush=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)

    if sha256:
        got = _sha256_file(dest)
        if got.lower() != sha256.lower():
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"Model SHA256 mismatch (expected {sha256}, got {got})")

    print(f"[{BOT_NAME}] ✅ Model downloaded to {dest}", flush=True)


def _guess_model_type_from_path(path: str) -> str:
    s = path.lower()
    if "qwen" in s: return "qwen"
    if "phi"  in s: return "phi"
    return "llama"


def _ensure_model(
    model_url: str,
    model_path: str,
    model_sha256: str,
    models_priority: Optional[List[str]],
) -> Tuple[Path, Optional[str]]:
    """
    Resolve a local gguf file (download if needed). Returns (path, model_type_hint).
    """
    # If caller provided explicit url+path → honor it first
    if model_url and model_path:
        dest = Path(model_path)
        try:
            _download(model_url, dest, sha256=model_sha256 or "")
            return dest, _guess_model_type_from_path(str(dest))
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Explicit model download failed: {e}", flush=True)

    # Else pick from our catalog by priority
    wanted = models_priority or ["qwen2.5-0.5b-instruct", "phi-2", "tinyllama-1.1b-chat"]
    wanted = [w.strip().lower() for w in wanted]

    for key, repo, filename, mtype in CATALOG:
        if key.lower() not in wanted:
            continue
        url  = _hf_resolve(repo, filename)
        dest = Path("/share/jarvis_prime/models") / filename
        try:
            _download(url, dest)
            return dest, mtype
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Fallback '{key}' failed: {e}", flush=True)

    raise RuntimeError("No LLM model could be downloaded. Check URLs/network.")


def prefetch_model() -> Optional[Path]:
    """
    CLI entry: prefetch on boot (run.sh). Uses env overrides when present.
    """
    try:
        path, _ = _ensure_model(
            model_url=MODEL_URL,
            model_path=MODEL_PATH,
            model_sha256=MODEL_SHA256,
            models_priority=None,
        )
        # Warm-load quickly (helps first inference)
        _ = _load_model(path, None)
        print(f"[{BOT_NAME}] 🧠 Prefetch complete", flush=True)
        return path
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch failed: {e}", flush=True)
        return None


def _load_model(model_path: Path, model_type_hint: Optional[str]):
    global _model, _model_type_hint, _loaded_path
    if _model is not None:
        return _model

    if AutoModelForCausalLM is None:
        raise RuntimeError("ctransformers is not installed in this image")

    mtype = model_type_hint or _guess_model_type_from_path(str(model_path))
    print(f"[{BOT_NAME}] 🧠 Loading model into memory: {model_path} (type={mtype})", flush=True)
    t0 = time.time()
    _model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        model_type=mtype,
        gpu_layers=0,
        context_length=4096,
    )
    _model_type_hint = mtype
    _loaded_path = model_path
    dt = time.time() - t0
    print(f"[{BOT_NAME}] 🌟 Model ready in {dt:.1f}s", flush=True)
    return _model


def _sanitize_generation(text: str) -> str:
    """
    Remove system/instruction echoes and keep the useful rewrite.
    """
    if not text:
        return text

    bad_prefixes = (
        "[system]", "[SYSTEM]", "SYSTEM:", "Instruction:", "Instructions:",
        "You are", "As an AI", "The assistant", "Rewrite:", "Output:", "[OUTPUT]"
    )
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if any(s.startswith(p) for p in bad_prefixes):
            continue
        lines.append(s)
    out = "\n".join(lines).strip()
    # squeeze extra blank lines
    out = "\n".join([ln for ln in out.splitlines() if ln.strip() != ""])
    return out


def engine_status():
    try:
        return {
            "ready": _model is not None,
            "model_type": _model_type_hint,
            "model_path": str(_loaded_path or MODEL_PATH or "").strip(),
        }
    except Exception:
        return {"ready": False, "model_type": None, "model_path": str(MODEL_PATH or "")}


def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 8,
    cpu_limit: int = 70,
    models_priority: Optional[List[str]] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: bool = False,
) -> str:
    """
    Style-preserving rewrite: aggressive personality by mood, no new facts,
    keep all numbers/URLs/paths, compress fluff, 2–6 lines.
    """
    src = (text or "").strip()
    if not src:
        return src

    # Ensure model on disk and loaded
    path, mhint = _ensure_model(model_url, model_path or MODEL_PATH, model_sha256 or MODEL_SHA256, models_priority)
    model = _load_model(path, mhint)

    # VERY strong mood dial
    mood_map = {
        "serious": "clinical, confident, precise, authoritative, no jokes",
        "playful": "cheeky, energetic, witty, high personality, light irreverence",
        "angry":   "furious, terse, sharp, no-nonsense, clipped sentences",
        "happy":   "radiant, upbeat, encouraging, joyful, sparkly",
        "sad":     "somber, reflective, restrained",
    }
    vibe = mood_map.get((mood or "").lower(), "confident, precise")
    profanity = "neutral on profanity" if allow_profanity else "avoid profanity"

    system = (
        f"You are Jarvis Prime’s Neural Core. Rewrite the input with {vibe}. "
        f"Preserve all facts, numbers, filenames, URLs, and technical terms exactly. "
        f"Do not invent or add new information. Keep it punchy. {profanity}. "
        f"Target 2–6 lines. End without extra labels."
    )
    prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"

    out = model(prompt, max_new_tokens=192, temperature=0.85, top_p=0.92, repetition_penalty=1.1)
    out = _sanitize_generation(out).strip()
    return out or src
