# /app/llm_client.py
from __future__ import annotations

import os
import json
import time
import hashlib
import tempfile
from pathlib import Path
from typing import Optional, List

import requests

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# Optional dep: ctransformers (installed in add-on image)
try:
    from ctransformers import AutoModelForCausalLM
except Exception as e:  # pragma: no cover
    AutoModelForCausalLM = None
    print(f"[{BOT_NAME}] ⚠️ ctransformers import failed: {e}", flush=True)

# -----------------------------
# Options / environment helpers
# -----------------------------

def _read_options() -> dict:
    """
    Read Home Assistant add-on options (Supervisor writes /data/options.json).
    """
    for p in (Path("/data/options.json"), Path("/app/options.json")):
        try:
            if p.exists():
                return json.loads(p.read_text() or "{}")
        except Exception:
            pass
    return {}

def _envflag(name: str) -> bool:
    v = os.getenv(name, os.getenv(name.lower(), "")).strip().lower()
    return v in ("1", "true", "yes", "on")

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

# -----------------------------
# Model path discovery & fetch
# -----------------------------

def _first_gguf_under(folder: Path) -> Optional[Path]:
    try:
        if not folder.exists():
            return None
        for p in sorted(folder.glob("*.gguf")):
            if p.is_file() and p.stat().st_size > 0:
                return p
    except Exception:
        pass
    return None

def _cfg_model_path(explicit: str = "") -> Path:
    """
    Decide which local *.gguf file to use:
      1) explicit function arg
      2) options.json: llm_model_path
      3) first *.gguf in /share/jarvis_prime/
      4) first *.gguf in /share/jarvis_prime/models/
      5) default path under /share/jarvis_prime/models/
    """
    if explicit:
        return Path(explicit)

    opts = _read_options()
    path = (opts.get("llm_model_path") or "").strip()
    if path:
        return Path(path)

    p = _first_gguf_under(Path("/share/jarvis_prime"))
    if p:
        return p

    p = _first_gguf_under(Path("/share/jarvis_prime/models"))
    if p:
        return p

    # Safe default (TinyLlama filename that you use)
    return Path("/share/jarvis_prime/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")

def _prefetch_model(target: Path, url: str = "", sha256: str = "") -> Optional[Path]:
    """
    Download a model to 'target' if it doesn't exist.
    Uses LLM_MODEL_URL / LLM_MODEL_SHA256 when provided.
    """
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.stat().st_size > 0:
        # Verify hash if given
        if sha256:
            try:
                actual = _sha256_file(target)
                if actual.lower() != sha256.lower():
                    print(f"[{BOT_NAME}] ♻️ SHA mismatch; re-downloading model", flush=True)
                    target.unlink(missing_ok=True)
                else:
                    print(f"[{BOT_NAME}] ✅ Model present and verified: {target}", flush=True)
                    return target
            except Exception:
                pass
        else:
            print(f"[{BOT_NAME}] ✅ Model already present: {target}", flush=True)
            return target

    url = (url or os.getenv("LLM_MODEL_URL") or os.getenv("llm_model_url") or "").strip()
    if not url:
        # Nothing to download; caller may have placed the file manually.
        return target if target.exists() else None

    print(f"[{BOT_NAME}] 🔮 Prefetching LLM model...", flush=True)
    print(f"[{BOT_NAME}] ⬇️  Downloading: {url}", flush=True)

    with requests.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    tmp.write(chunk)
            tmp_path = Path(tmp.name)

    if sha256:
        actual = _sha256_file(tmp_path)
        if actual.lower() != sha256.lower():
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Model SHA256 mismatch (expected {sha256}, got {actual})")

    tmp_path.replace(target)
    print(f"[{BOT_NAME}] ✅ Model downloaded to {target}", flush=True)
    return target

# -----------------------------
# Loading & generation
# -----------------------------

_model = None

def _load_model(model_path: Path):
    global _model
    if _model is not None:
        return _model
    if AutoModelForCausalLM is None:
        raise RuntimeError("ctransformers is not available in this image")

    # Infer sensible model_type hint
    s = model_path.name.lower()
    if "qwen" in s:
        mtype = "qwen"
    elif "phi" in s:
        mtype = "phi"
    else:
        mtype = "llama"

    print(f"[{BOT_NAME}] 🧠 Loading model into memory: {model_path} (type={mtype})", flush=True)
    t0 = time.time()
    _model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        model_type=mtype,
        gpu_layers=0,
        context_length=4096,
    )
    dt = time.time() - t0
    print(f"[{BOT_NAME}] 🌟 Model ready in {dt:.1f}s", flush=True)
    return _model

def _build_prompt(text: str, mood: str) -> str:
    mood = (mood or "serious").strip().lower()
    persona = {
        "serious": "direct, concise, professional",
        "sarcastic": "dry wit, playful jabs, still helpful",
        "playful": "light, fun, friendly",
        "hacker-noir": "noir monologue, terse, technical",
        "angry": "brutally honest but helpful, short sentences",
    }.get(mood, "direct, concise, professional")

    system = (
        "You are Jarvis Prime. Polish infrastructure alerts for a home-lab admin.\n"
        "Keep ALL key facts intact (titles, IPs, versions, counts, links, times, poster URLs).\n"
        "Preserve markdown and lists. Do NOT invent facts. Be short, clear, and human."
    )
    return f"[SYSTEM]{system}\n[MOOD]{persona}\n[INPUT]{text}\n[OUTPUT]"

# -----------------------------
# Public API expected by bot/proxy/SMTP
# -----------------------------

def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 5,
    cpu_limit: int = 70,            # reserved for future throttle; harmless here
    models_priority: Optional[List[str]] = None,  # unused; kept for signature compatibility
    base_url: str = "",             # unused; kept for compatibility
    model_url: str = "",            # optional override for download
    model_path: str = "",           # optional override for path
    model_sha256: str = "",         # optional integrity check
) -> str:
    """
    LLM pass: rewrite text with mood/personality and return the rewritten text.
    MUST be fast and bounded; the caller enforces a hard timeout around this.
    """
    # Resolve local model file (and download if needed)
    local = _cfg_model_path(model_path)
    local = _prefetch_model(local, url=model_url, sha256=model_sha256) or local
    if not local.exists():
        # No model found; gracefully return original text
        print(f"[{BOT_NAME}] ⚠️ Model path not found: {local}", flush=True)
        return text

    model = _load_model(local)
    prompt = _build_prompt(text, mood)

    # Streamed generation with a wall-clock cutoff
    start = time.time()
    out = []
    try:
        for tok in model(
            prompt,
            stream=True,
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.05,
            max_new_tokens=180,
        ):
            out.append(tok)
            if time.time() - start > max(1, int(timeout)):
                print(f"[{BOT_NAME}] ⏱️ LLM generation timed out at ~{timeout}s (returning partial).", flush=True)
                break
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ LLM generation failed: {e}", flush=True)
        return text

    text_out = "".join(out).strip()
    if "[OUTPUT]" in text_out:
        text_out = text_out.split("[OUTPUT]", 1)[-1].strip()

    return text_out or text

# -----------------------------
# Prefetch when invoked directly (run.sh does this)
# -----------------------------
if __name__ == "__main__":
    try:
        if _envflag("LLM_ENABLED"):
            url = os.getenv("LLM_MODEL_URL", os.getenv("llm_model_url", ""))
            sha = os.getenv("LLM_MODEL_SHA256", os.getenv("llm_model_sha256", ""))
            path = os.getenv("LLM_MODEL_PATH", os.getenv("llm_model_path", "")) or str(_cfg_model_path(""))
            _prefetch_model(Path(path), url=url, sha256=sha)
            # Try a quick load/unload to surface errors early
            if Path(path).exists():
                _load_model(Path(path))
            print(f"[{BOT_NAME}] 💾 Prefetch complete", flush=True)
        else:
            print(f"[{BOT_NAME}] ℹ️ LLM disabled; skipping prefetch", flush=True)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch failed: {e}", flush=True)
