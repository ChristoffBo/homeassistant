#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations

import os
import time
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List

import requests

# Optional dep; the container includes it. If not, we error clearly.
try:
    from ctransformers import AutoModelForCausalLM
except Exception:  # pragma: no cover
    AutoModelForCausalLM = None

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# ---- Config (env or options.json will export these) ----
MODEL_PATH   = os.getenv("LLM_MODEL_PATH", "").strip()
MODEL_URL    = os.getenv("LLM_MODEL_URL", "").strip()
MODEL_SHA256 = (os.getenv("LLM_MODEL_SHA256", "") or "").lower()

MODELS_DIRS = [
    Path("/share/jarvis_prime/models"),
    Path("/share/jarvis_prime"),
]

# Keep it stable: use llama/tinyllama/phi; skip qwen for this build
SUPPORTED_TYPES = ("llama", "phi")

_model = None
_model_type_hint: Optional[str] = None
_loaded_path: Optional[Path] = None


# -----------------------------
# Files & download helpers
# -----------------------------
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
    if "phi" in s:
        return "phi"
    return "llama"

def _find_existing_model() -> Optional[Path]:
    candidates: List[Path] = []
    for d in MODELS_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.gguf")):
            low = p.name.lower()
            if "qwen" in low:  # skip qwen on this build
                continue
            candidates.append(p)
    # Prefer tinyllama-like names first
    candidates.sort(key=lambda p: (0 if "tinyllama" in p.name.lower() else 1, p.stat().st_size))
    return candidates[0] if candidates else None

def _ensure_model(
    model_url: str,
    model_path: str,
    model_sha256: str,
    models_priority: Optional[List[str]] = None,
) -> Tuple[Path, Optional[str]]:
    """
    Resolve a local gguf file (download only when explicitly configured).
    Returns (path, model_type_hint).
    """
    # Explicit path wins
    if model_path:
        dest = Path(model_path)
        if not dest.exists() and model_url:
            _download(model_url, dest, sha256=model_sha256 or "")
        if not dest.exists():
            raise RuntimeError(f"Configured model path not found: {dest}")
        return dest, _guess_model_type_from_path(str(dest))

    # Otherwise, pick an existing local model from /share/jarvis_prime (prefer tinyllama/llama)
    existing = _find_existing_model()
    if existing:
        return existing, _guess_model_type_from_path(str(existing))

    # As a last resort, only download if BOTH url and path were provided (we will write into path)
    if model_url and model_path:
        dest = Path(model_path)
        _download(model_url, dest, sha256=model_sha256 or "")
        return dest, _guess_model_type_from_path(str(dest))

    raise RuntimeError("No usable LLM model found. Set LLM_MODEL_PATH or place a .gguf in /share/jarvis_prime/models.")

def _load_model(model_path: Path, model_type_hint: Optional[str]):
    global _model, _model_type_hint, _loaded_path
    if _model is not None:
        return _model

    if AutoModelForCausalLM is None:
        raise RuntimeError("ctransformers is not installed in this image")

    mtype = model_type_hint or _guess_model_type_from_path(str(model_path))
    if mtype not in SUPPORTED_TYPES:
        raise RuntimeError(f"Model type '{mtype}' not supported by this build; use llama/tinyllama/phi.")

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

# -----------------------------
# Public status / warmup
# -----------------------------
def engine_status():
    try:
        return {
            "ready": _model is not None,
            "model_type": _model_type_hint,
            "model_path": str(_loaded_path or (MODEL_PATH or "")).strip(),
        }
    except Exception:
        return {"ready": False, "model_type": None, "model_path": str(MODEL_PATH or "")}

def prefetch_model() -> Optional[Path]:
    """
    Warm-load in the current process. No surprise downloads.
    """
    try:
        path, hint = _ensure_model(
            model_url=MODEL_URL,
            model_path=MODEL_PATH,
            model_sha256=MODEL_SHA256,
            models_priority=None,
        )
        _ = _load_model(path, hint)
        print(f"[{BOT_NAME}] 🧠 Prefetch complete", flush=True)
        return path
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch failed: {e}", flush=True)
        return None

# -----------------------------
# Rewrite (bullet, mood-amped)
# -----------------------------
def _sanitize_generation(text: str) -> str:
    if not text:
        return text
    bad_prefixes = (
        "[system]", "[SYSTEM]", "SYSTEM:", "Instruction:", "Instructions:",
        "You are", "As an AI", "The assistant", "Rewrite:", "Output:", "[OUTPUT]", "[INPUT]"
    )
    lines = []
    for raw in text.splitlines():
        s = raw.rstrip()
        if not s.strip():
            continue
        if any(s.strip().startswith(p) for p in bad_prefixes):
            continue
        lines.append(s)
    out = "\n".join(lines).strip()
    # collapse extra blank lines
    out = "\n".join([ln for ln in out.splitlines() if ln.strip() != ""])
    return out

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
    Style-preserving rewrite to **bullet points** with mood-driven voice.
    - Keep all facts, numbers, paths, URLs EXACT.
    - NO new facts. NO “Explanation:” blocks. NO code fences.
    - Output strictly as 3–10 bullet lines (•). Clipped, high-signal.
    - If the input already has bullets, tighten and keep them.
    """
    src = (text or "").strip()
    if not src:
        return src

    path, mhint = _ensure_model(model_url, model_path or MODEL_PATH, model_sha256 or MODEL_SHA256, models_priority)
    model = _load_model(path, mhint)

    mood = (mood or "serious").lower()
    voice = {
        "serious": "clinical, confident, precise, no fluff",
        "playful": "cheeky, witty, high personality, light irreverence",
        "angry":   "furious, terse, sharp, no-nonsense, clipped sentences",
        "happy":   "upbeat, punchy, energizing",
        "sad":     "somber, restrained, minimal",
    }.get(mood, "confident, precise")

    profanity = "You may use mild profanity sparingly." if allow_profanity else "Avoid profanity."

    system = (
        "You are the Neural Core stylist. Rewrite the input into BULLET POINTS only.\n"
        f"Voice: {voice}. {profanity}\n"
        "Rules:\n"
        "1) Preserve ALL facts, names, numbers, units, paths, URLs exactly.\n"
        "2) Do NOT invent content. Do NOT add explanations or meta text.\n"
        "3) Output 3–10 bullets, each starting with '• '.\n"
        "4) Keep sentences short and forceful. Remove filler.\n"
        "5) Never include 'Explanation', 'Input', 'Output', system tags, or code fences.\n"
    )

    prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"

    out = model(prompt, max_new_tokens=224, temperature=0.8, top_p=0.9, repetition_penalty=1.1)
    out = _sanitize_generation(out).strip()

    # Safety net: ensure bullet format
    if out and not out.lstrip().startswith(("•", "- ")):
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        out = "\n".join([("• " + ln.lstrip("•- ").strip()) for ln in lines])

    return out or src
