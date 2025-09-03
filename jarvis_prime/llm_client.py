#!/usr/bin/env python3
# /app/llm_client.py
# Local LLM client for Jarvis Prime
# - Multi-engine, no hard-coded "llama" model name
# - Works with llama-cpp-python or ctransformers if present
# - Optional Hugging Face download with llm_hf_token
# - Obeys timeouts, CPU caps (best-effort), context/gen tokens, max lines
# - Safe fallback: if load/generate fails, returns original text

from __future__ import annotations
import os
import json
import time
import hashlib
import signal
import threading
import requests
from typing import Optional, Dict, Any, List

# ========== Utilities ==========

def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _mask(s: str) -> str:
    if not s:
        return ""
    if len(s) <= 6:
        return "***"
    return s[:3] + "***" + s[-3:]

def _sha256_file(path: str) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()

def _ensure_dir(p: str):
    d = os.path.dirname(p) if os.path.splitext(p)[1] else p
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def _split_csv(s: str) -> List[str]:
    if not s:
        return []
    return [x.strip() for x in str(s).split(",") if x.strip()]

# ========== Load config ==========

OPTIONS = {}
try:
    # Primary user options
    OPTIONS = _read_json("/data/options.json")
    # Fallback defaults if present
    DEFAULTS = _read_json("/data/config.json")
    # Merge (options win)
    OPTIONS = {**DEFAULTS, **OPTIONS}
except Exception:
    pass

# Keys we honor
LLM_ENABLED            = bool(OPTIONS.get("llm_enabled", False))
LLM_MODELS_DIR         = str(OPTIONS.get("llm_models_dir", "/share/jarvis_prime/models")).rstrip("/")
LLM_TIMEOUT            = int(OPTIONS.get("llm_timeout_seconds", 20))
LLM_CPU_MAX            = int(OPTIONS.get("llm_max_cpu_percent", 80))
LLM_CTX_TOKENS         = int(OPTIONS.get("llm_ctx_tokens", 4096))
LLM_GEN_TOKENS         = int(OPTIONS.get("llm_gen_tokens", 300))
LLM_MAX_LINES          = int(OPTIONS.get("llm_max_lines", 30))
LLM_AUTODOWNLOAD       = bool(OPTIONS.get("llm_autodownload", True))
LLM_HF_TOKEN           = str(OPTIONS.get("llm_hf_token", "") or "")

# Model selection knobs
LLM_CHOICE             = str(OPTIONS.get("llm_choice", "off")).strip().lower()  # "off", "auto", "phi", "tinyllama", "qwen05", "llama32_1b", etc.
LLM_MODELS_PRIORITY    = OPTIONS.get("llm_models_priority", "qwen15,phi2,llama32_1b,tinyllama,qwen05,phi3")

# Per-model URLs/paths (these are hints; we’ll decide in _select_model)
PHI3_URL               = str(OPTIONS.get("llm_phi3_url", ""))
PHI3_PATH              = str(OPTIONS.get("llm_phi3_path", ""))
TINYLLAMA_URL          = str(OPTIONS.get("llm_tinyllama_url", ""))
TINYLLAMA_PATH         = str(OPTIONS.get("llm_tinyllama_path", ""))
QWEN05_URL             = str(OPTIONS.get("llm_qwen05_url", ""))
QWEN05_PATH            = str(OPTIONS.get("llm_qwen05_path", ""))

# Global “single URL/path” (legacy); we still honor if provided
LEGACY_MODEL_URL       = str(OPTIONS.get("llm_model_url", ""))
LEGACY_MODEL_PATH      = str(OPTIONS.get("llm_model_path", LLM_MODELS_DIR))
LEGACY_MODEL_SHA256    = str(OPTIONS.get("llm_model_sha256", ""))

# ========== Backend detection ==========

_backend_name = None
_llama = None          # llama_cpp.Llama
_ct = None             # ctransformers

try:
    import llama_cpp as _lc
    _backend_name = "llama_cpp"
except Exception:
    _lc = None

if _backend_name is None:
    try:
        import ctransformers as _ctmod
        _backend_name = "ctransformers"
        _ct = _ctmod
    except Exception:
        _ct = None

# ========== Downloader ==========

def _download(url: str, dest_path: str, hf_token: str = "") -> bool:
    try:
        _ensure_dir(dest_path)
        headers = {}
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"
            print(f"[LLM] using HuggingFace token {_mask(hf_token)}")

        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            tmp = dest_path + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp, dest_path)
        print(f"[LLM] downloaded -> {dest_path}")
        return True
    except Exception as e:
        print(f"[LLM] download failed: {e}")
        return False

# ========== Model selection ==========

def _select_model(preferred: List[str]) -> Dict[str, str]:
    """
    Return dict {engine, name, url, path, sha256?} for the first model that has
    either a usable path or a URL we can download.
    """
    # Build a candidate table from known keys + legacy
    candidates = []

    # map canonical keys -> (url, path)
    canon = {
        "phi3": (PHI3_URL, PHI3_PATH),
        "tinyllama": (TINYLLAMA_URL, TINYLLAMA_PATH),
        "qwen05": (QWEN05_URL, QWEN05_PATH),
        # Accept legacy llama tokens (llama32_1b, etc.) via LEGACY_MODEL_URL/PATH
        "llama32_1b": (LEGACY_MODEL_URL, LEGACY_MODEL_PATH),
        "phi2": (LEGACY_MODEL_URL, LEGACY_MODEL_PATH),   # allow mapping if user gives phi2 in priority but only legacy URL provided
        "qwen15": (LEGACY_MODEL_URL, LEGACY_MODEL_PATH),
        # Explicit catch-all
        "custom": (LEGACY_MODEL_URL, LEGACY_MODEL_PATH),
    }

    for key in preferred:
        k = key.strip().lower()
        if k in canon:
            url, path = canon[k]
        else:
            # Unknown key → fall back to legacy
            url, path = LEGACY_MODEL_URL, LEGACY_MODEL_PATH

        # If a directory provided for path, try to append filename from URL if present
        if path and os.path.isdir(path) and url:
            fname = url.split("/")[-1]
            path = os.path.join(path, fname)

        candidates.append({
            "engine": k,
            "name": k,
            "url": url or "",
            "path": path or "",
            "sha256": LEGACY_MODEL_SHA256 if k in ("custom", "llama32_1b", "phi2", "qwen15") else ""
        })

    # If user explicitly set llm_choice (not off/auto), put it first
    if LLM_CHOICE not in ("", "off", "auto", "none"):
        forced = LLM_CHOICE
        candidates.insert(0, {
            "engine": forced,
            "name": forced,
            "url": canon.get(forced, (LEGACY_MODEL_URL, LEGACY_MODEL_PATH))[0],
            "path": canon.get(forced, (LEGACY_MODEL_URL, LEGACY_MODEL_PATH))[1],
            "sha256": ""
        })

    # Deduplicate by path/url preference order
    seen = set()
    uniq = []
    for c in candidates:
        key = (c["engine"], c["url"], c["path"])
        if key not in seen:
            uniq.append(c)
            seen.add(key)

    return _pick_first_viable(uniq)

def _pick_first_viable(cands: List[Dict[str, str]]) -> Dict[str, str]:
    # Prefer any existing local file
    for c in cands:
        p = c.get("path", "")
        if p and os.path.isfile(p):
            return c
    # Else, return first one with a URL (we’ll download if allowed)
    for c in cands:
        if c.get("url"):
            return c
    # Else, last resort: first candidate (may fail cleanly)
    return cands[0] if cands else {"engine": "none", "name": "none", "url": "", "path": ""}

# ========== Loader ==========

class _Timeout:
    def __init__(self, seconds: int):
        self.seconds = max(1, int(seconds))
        self._hit = False
    def __enter__(self):
        self._hit = False
        signal.signal(signal.SIGALRM, self._handle)
        signal.alarm(self.seconds)
    def _handle(self, signum, frame):
        self._hit = True
        raise TimeoutError("generation timeout")
    def __exit__(self, exc_type, exc, tb):
        signal.alarm(0)

class LocalLLM:
    def __init__(self):
        self.backend = None      # "llama_cpp" | "ctransformers" | None
        self.model = None
        self.info  = {"engine": "none", "path": "", "name": "", "url": ""}

    def _log(self, msg: str):
        print(f"[LLM] {msg}")

    def ensure_model(self):
        if not LLM_ENABLED:
            self._log("disabled via options")
            return False

        priority = _split_csv(LLM_MODELS_PRIORITY) or []
        picked = _select_model(priority)
        self.info = picked
        url, path = picked.get("url", ""), picked.get("path", "")

        if not path:
            # If no path defined but we do have a URL and a models_dir, derive a filename
            if url:
                fname = url.split("/")[-1] or "model.gguf"
                path = os.path.join(LLM_MODELS_DIR, fname)
                self.info["path"] = path

        # Download if needed
        if not os.path.isfile(path):
            if not url:
                self._log("no local model file and no URL to download; continuing without a model")
                return False
            if not LLM_AUTODOWNLOAD:
                self._log("autodownload disabled and model not present; continuing without a model")
                return False
            self._log(f"downloading model from {url}")
            ok = _download(url, path, LLM_HF_TOKEN)
            if not ok:
                self._log("download failed; continuing without a model")
                return False

        # Verify sha256 if provided
        sha_cfg = picked.get("sha256", "").strip().lower()
        if sha_cfg:
            try:
                sha_actual = _sha256_file(path).lower()
                if sha_actual != sha_cfg:
                    self._log(f"sha256 mismatch: got={sha_actual} expected={sha_cfg}")
                    # do not abort; warn and continue
            except Exception as e:
                self._log(f"sha256 check failed: {e}")

        # Load
        try:
            if _backend_name == "llama_cpp" and _lc is not None:
                # Threads best-effort: bound by CPU percent is tricky; we just scale threads
                n_threads = max(1, min(os.cpu_count() or 2, int((LLM_CPU_MAX/100.0) * (os.cpu_count() or 2)) or 1))
                self.model = _lc.Llama(
                    model_path=path,
                    n_ctx=LLM_CTX_TOKENS,
                    n_threads=n_threads,
                    # Keep defaults for kv by llama-cpp
                )
                self.backend = "llama_cpp"
                self._log(f"loaded (llama_cpp) path={path} ctx={LLM_CTX_TOKENS} threads={n_threads}")
                return True

            if _backend_name == "ctransformers" and _ct is not None:
                # ctransformers auto-detects gguf; set threads
                config = {"context_length": LLM_CTX_TOKENS}
                n_threads = max(1, min(os.cpu_count() or 2, int((LLM_CPU_MAX/100.0) * (os.cpu_count() or 2)) or 1))
                self.model = _ct.AutoModelForCausalLM.from_pretrained(
                    path,
                    model_type="llama",   # works for GGUF llama-family (qwen/phi in GGUF still use llama kernels)
                    gpu_layers=0,
                    threads=n_threads,
                    **config
                )
                self.backend = "ctransformers"
                self._log(f"loaded (ctransformers) path={path} ctx={LLM_CTX_TOKENS} threads={n_threads}")
                return True

            self._log("no supported backend found (install llama-cpp-python or ctransformers)")
            return False

        except Exception as e:
            self._log(f"load failed: {e}")
            self.model = None
            self.backend = None
            return False

    # ========== Generation / Rewrite ==========

    def _build_prompt(self, text: str, mood: str, allow_profanity: bool) -> str:
        mood = (mood or "neutral").strip()
        rules = [
            "Rewrite the message to be clear and concise.",
            f"Keep the tone aligned with '{mood}'.",
            f"Maximum {LLM_MAX_LINES} lines.",
            "Do not invent facts; preserve user content.",
        ]
        if not allow_profanity:
            rules.append("Avoid profanity and slurs; keep it family-friendly.")
        sys = "You are a notification beautifier. Format lightly; use short lines and bulleting only if it improves scannability."
        instructions = "\n".join(f"- {r}" for r in rules)
        return f"""[SYSTEM]
{sys}

[INSTRUCTIONS]
{instructions}

[INPUT]
{text.strip()}

[OUTPUT]
"""

    def rewrite(self, *, text: str, mood: str = "neutral", timeout: int = None,
                cpu_limit: int = None, models_priority: Any = None,
                base_url: str = "", model_url: str = "", model_path: str = "",
                model_sha256: str = "", allow_profanity: bool = False) -> Optional[str]:

        if not LLM_ENABLED:
            return text  # LLM disabled → pass-through

        # If we don’t have a model instance yet, try to load once
        if self.model is None or self.backend is None:
            if not self.ensure_model():
                return text  # graceful pass-through

        prompt = self._build_prompt(text, mood, allow_profanity)

        # Enforce timeout
        tmo = int(timeout or LLM_TIMEOUT)
        try:
            with _Timeout(tmo):
                if self.backend == "llama_cpp":
                    out = self.model(
                        prompt,
                        max_tokens=LLM_GEN_TOKENS,
                        stop=["[END]", "[INPUT]", "[SYSTEM]"],
                        echo=False,
                    )
                    raw = out["choices"][0]["text"]
                elif self.backend == "ctransformers":
                    raw = ""
                    for token in self.model(prompt, max_new_tokens=LLM_GEN_TOKENS, stream=True):
                        raw += token
                else:
                    return text
        except TimeoutError:
            self._log("generation timeout")
            return text
        except Exception as e:
            self._log(f"generation failed: {e}")
            return text

        # Post-process: trim to max lines
        lines = [ln.rstrip() for ln in raw.splitlines()]
        if LLM_MAX_LINES > 0 and len(lines) > LLM_MAX_LINES:
            lines = lines[:LLM_MAX_LINES]
        cleaned = _tidy("\n".join(lines)).strip()
        return cleaned or text

def _tidy(s: str) -> str:
    # collapse excess blank lines; trim trailing spaces
    out = []
    blank = 0
    for ln in s.splitlines():
        t = ln.rstrip()
        if t == "":
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(t)
    return "\n".join(out)

# ========== Public API used by bot/proxy/smtp ==========

_client = LocalLLM()

def rewrite(**kwargs) -> Optional[str]:
    """
    Compatible entry point:
      rewrite(text=..., mood=..., timeout=..., cpu_limit=..., models_priority=...,
              base_url=..., model_url=..., model_path=..., model_sha256=...,
              allow_profanity=False)
    """
    try:
        return _client.rewrite(**kwargs)
    except Exception as e:
        print(f"[LLM] rewrite() error: {e}")
        return kwargs.get("text", "")