# /app/llm_client.py
from __future__ import annotations

import os
import time
import hashlib
import tempfile
from pathlib import Path
from typing import Optional

import requests

# Soft dep: ctransformers
try:
    from ctransformers import AutoModelForCausalLM
except Exception:  # pragma: no cover
    AutoModelForCausalLM = None

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

MODEL_PATH  = os.getenv("LLM_MODEL_PATH", "/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf")
MODEL_URL   = os.getenv("LLM_MODEL_URL", "")
MODEL_SHA256 = (os.getenv("LLM_MODEL_SHA256", "") or "").lower()

_model = None

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def prefetch_model() -> Optional[Path]:
    target = Path(MODEL_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    if not MODEL_URL:
        print(f"[{BOT_NAME}] ⚠️ LLM_MODEL_URL not set; cannot download model.")
        return None
    print(f"[{BOT_NAME}] 🔮 Prefetching LLM model…")
    r = requests.get(MODEL_URL, stream=True, timeout=60)
    r.raise_for_status()
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        for chunk in r.iter_content(1024 * 1024):
            tmp.write(chunk)
        tmp_path = Path(tmp.name)
    if MODEL_SHA256:
        actual = _sha256_file(tmp_path)
        if actual.lower() != MODEL_SHA256.lower():
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Model SHA256 mismatch (expected {MODEL_SHA256}, got {actual})")
    tmp_path.replace(target)
    print(f"[{BOT_NAME}] ✅ Model downloaded -> {target}")
    return target

def _load_model():
    global _model
    if _model is not None:
        return _model
    if AutoModelForCausalLM is None:
        raise RuntimeError("ctransformers is not installed.")
    path = Path(MODEL_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Model not found at {path}")
    print(f"[{BOT_NAME}] 🧠 Loading model: {path.name}")
    _model = AutoModelForCausalLM.from_pretrained(
        str(path),
        model_type="llama",
        gpu_layers=0,
        context_length=2048,
    )
    return _model

def rewrite_text(prompt: str, mood: str = "serious", timeout_s: int = 5) -> str:
    """
    Quick, streaming generation with a hard timeout (best-effort).
    """
    model = _load_model()
    system = (
        "You polish infrastructure alerts for a home server admin. "
        "Keep ALL key facts (titles, IPs, versions, counts, links, times). "
        "Tone matches mood (serious/angry/playful/sarcastic/hacker-noir). "
        "Write short, clear, useful lines."
    )
    tpl = f"[SYSTEM]{system}\n[MOOD]{mood}\n[INPUT]{prompt}\n[OUTPUT]"
    t0 = time.time()
    out = []
    for tok in model(tpl, stream=True):
        out.append(tok)
        if (time.time() - t0) > timeout_s:
            break
    text = "".join(out).strip()
    if "[OUTPUT]" in text:
        text = text.split("[OUTPUT]", 1)[-1].strip()
    return text or prompt

if __name__ == "__main__":
    # Allow run.sh to call this file to prefetch the model.
    try:
        prefetch_model()
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch failed: {e}")
