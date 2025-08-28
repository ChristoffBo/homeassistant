# /app/llm_client.py
import os, time, json, hashlib, threading, requests
from typing import Optional

_llm_lock = threading.RLock()
_model = None
_model_path: Optional[str] = None

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _ensure_model(model_url: str, model_path: str, expect_sha: str = ""):
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    if not os.path.exists(model_path):
        print(f"[Jarvis Prime] 📥 Downloading LLM model: {model_url}")
        with requests.get(model_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            tmp = model_path + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        os.replace(tmp, model_path)
        print(f"[Jarvis Prime] ✅ Model downloaded to {model_path}")
    else:
        print(f"[Jarvis Prime] 🎯 Using existing LLM model {model_path}")

    if expect_sha:
        got = _sha256(model_path)
        if got.lower() != expect_sha.lower():
            raise RuntimeError(f"SHA256 mismatch for {model_path}: {got} != {expect_sha}")

def _load_model_if_needed(model_path: str):
    global _model, _model_path
    if _model is not None and _model_path == model_path:
        return
    print(f"[Jarvis Prime] 🔧 Loading model into memory: {model_path}")
    from ctransformers import AutoModelForCausalLM
    with _llm_lock:
        if _model is None or _model_path != model_path:
            _model = AutoModelForCausalLM.from_pretrained(
                model_path,
                model_type="llama",
                gpu_layers=0
            )
            _model_path = model_path
    print("[Jarvis Prime] 🧩 Model ready")

def rewrite(text: str, mood: str,
            timeout: int,
            cpu_limit: int,
            models_priority,    # kept for compatibility; unused
            base_url: str,      # kept for compatibility; unused
            model_url: str = "",
            model_path: str = "",
            model_sha256: str = "") -> str:
    if not text:
        return ""

    if not model_url or not model_path:
        print("[Jarvis Prime] ⚠️ LLM rewrite called without model_url/model_path")
        return text

    _ensure_model(model_url, model_path, model_sha256)
    _load_model_if_needed(model_path)

    prompt = (
        f"Rewrite the following message concisely in a {mood} tone. "
        "Keep all critical data (titles, URLs, numbers, image links). "
        "Do not remove posters or links. Do not fabricate details.\n"
        f"Message:\n{text}\n"
        "Rewrite:\n"
    )

    with _llm_lock:
        from ctransformers import AutoModelForCausalLM  # ensure import present
        result = _model(prompt, max_new_tokens=120, temperature=0.7, top_p=0.9)
    return str(result).strip()
