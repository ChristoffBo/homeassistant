#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Jarvis Prime — Neural Core (ctransformers GGUF loader + rewrite API)
#
# Key points:
# - Provides BOTH rewrite_text(...) and rewrite_with_info(...).
# - Robust GGUF loading for ctransformers==0.2.27:
#     * If MODEL_PATH is a file: try LLM(model_path=...), then fallback to
#       AutoModelForCausalLM.from_pretrained(dir, model_file=...).
#     * If MODEL_PATH is a directory: pick a .gguf inside (respects LLM_MODELS_PRIORITY).
# - Smart prefetch: if MODEL_PATH is a directory, download to that directory using
#   the URL basename; if it's a file, download exactly to that file.
# - Loud logs so you can see it firing.
from __future__ import annotations

import os
import re
import time
import hashlib
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List
from urllib.parse import urlparse
import json

import requests

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# ---- Configuration via env (run.sh exports these from options.json) ----------
MODEL_PATH = os.getenv(
    "LLM_MODEL_PATH",
    "/share/jarvis_prime/models"  # default to directory for resilience
)
MODEL_URL = os.getenv("LLM_MODEL_URL", "")
MODEL_SHA256 = (os.getenv("LLM_MODEL_SHA256", "") or "").lower()
DETAIL_LEVEL = os.getenv("LLM_DETAIL_LEVEL", "rich").lower()
MAX_LINES = 10 if DETAIL_LEVEL == "rich" else 6
MAX_LINE_CHARS = 160
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
LLM_TOP_P      = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "320"))

VERBOSE = True

# ---- Soft dep: ctransformers -------------------------------------------------
_CTRANS_OK = False
_MODEL = None
_MODEL_ANCHOR: Optional[Path] = None  # exactly what caller configured (file OR dir)

def _import_ctransformers() -> bool:
    global _CTRANS_OK
    if _CTRANS_OK:
        return True
    try:
        from ctransformers import AutoModelForCausalLM  # noqa: F401
        from ctransformers import LLM  # noqa: F401
        _CTRANS_OK = True
        if VERBOSE:
            print("[Neural Core] ctransformers import: OK", flush=True)
        return True
    except Exception as e:
        print(f"[Neural Core] ctransformers import FAILED: {e}", flush=True)
        _CTRANS_OK = False
        return False

# ---- Personality / profanity gates ------------------------------------------
def _cfg_allow_profanity() -> bool:
    env = os.getenv("PERSONALITY_ALLOW_PROFANITY")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("personality_allow_profanity", False))
    except Exception:
        return False

def _normalize_mood(mood: str) -> str:
    m = (mood or "").strip().lower()
    return m or "serious"

def _bullet_for(mood: str) -> str:
    return {
        "serious": "•",
        "cheeky": "😏",
        "relaxed": "✨",
        "urgent": "⚡",
        "angry": "🔥",
        "sarcastic": "🙃",
        "hacker-noir": "▣",
    }.get(_normalize_mood(mood), "•")

def _clean_if_needed(text: str, allow_profanity: bool) -> str:
    if allow_profanity:
        return text
    return re.sub(r"\b(fuck|shit|bitch|bastard)\b", "****", text, flags=re.I)

# ---- Utilities ---------------------------------------------------------------
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _url_basename(u: str) -> str:
    p = urlparse(u)
    name = os.path.basename(p.path.rstrip("/"))
    return name or "model.gguf"

def _pick_gguf_in_dir(d: Path) -> Optional[Path]:
    files = sorted([p for p in d.iterdir() if p.suffix.lower() == ".gguf"])
    if not files:
        return None
    pref = os.getenv("LLM_MODELS_PRIORITY", "")
    if pref:
        keys = [s.strip().lower() for s in pref.split(",") if s.strip()]
        for k in keys:
            for f in files:
                if k in f.name.lower():
                    return f
    return files[0]

# ---- Prefetch / download -----------------------------------------------------
def prefetch_model() -> Optional[Path]:
    """
    Download model if missing.
    - If MODEL_PATH is a file: download to that file.
    - If MODEL_PATH is a dir: download to dir/<basename(url)>
    """
    target_anchor = Path(MODEL_PATH).expanduser()
    target: Path

    if target_anchor.suffix.lower() == ".gguf":
        target = target_anchor
    else:
        if not MODEL_URL:
            print(f"[{BOT_NAME}] ⚠️ LLM_MODEL_URL not set and MODEL_PATH is a directory; cannot infer filename.", flush=True)
            return None
        target = target_anchor / _url_basename(MODEL_URL)

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if VERBOSE:
            print(f"[{BOT_NAME}] ✅ Model already present at {target}", flush=True)
        return target

    if not MODEL_URL:
        print(f"[{BOT_NAME}] ⚠️ LLM_MODEL_URL not set; cannot download model.", flush=True)
        return None

    print(f"[{BOT_NAME}] 🔮 Prefetching LLM model -> {target}", flush=True)
    headers = {"User-Agent": "jarvis-prime/1.0", "Accept": "*/*"}
    with requests.get(MODEL_URL, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    tmp.write(chunk)
            tmp_path = Path(tmp.name)

    if MODEL_SHA256:
        actual = _sha256_file(tmp_path)
        if actual.lower() != MODEL_SHA256:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Model SHA256 mismatch (expected {MODEL_SHA256}, got {actual})")

    tmp_path.replace(target)
    print(f"[{BOT_NAME}] ✅ Model downloaded -> {target}", flush=True)
    return target

# ---- Model loading (robust) --------------------------------------------------
def _resolve_model_file(anchor: Path) -> Optional[Path]:
    """
    Resolve the actual .gguf to load based on MODEL_PATH 'anchor'.
    - If anchor is a file -> return it.
    - If anchor is a dir  -> pick a .gguf inside.
    """
    anchor = anchor.expanduser()
    if anchor.is_file() and anchor.suffix.lower() == ".gguf":
        return anchor
    if anchor.is_dir():
        pick = _pick_gguf_in_dir(anchor)
        if pick:
            return pick
    return None

def _load_model() -> Optional[object]:
    global _MODEL, _MODEL_ANCHOR
    if _MODEL is not None:
        return _MODEL

    if not _import_ctransformers():
        return None

    anchor = Path(MODEL_PATH).expanduser()
    gguf = _resolve_model_file(anchor)
    if gguf is None:
        print(f"[Neural Core] ❌ Model file not found. MODEL_PATH='{anchor}'", flush=True)
        return None

    try:
        # Fast path: LLM(model_path=<file>)
        from ctransformers import LLM
        t0 = time.time()
        print(f"[Neural Core] 🧠 Loading GGUF via LLM(): '{gguf}' ...", flush=True)
        model = LLM(model_path=str(gguf), model_type="llama")
        _MODEL = model
        _MODEL_ANCHOR = anchor
        print(f"[Neural Core] ✅ Model ready in {time.time() - t0:.2f}s (LLM())", flush=True)
        return _MODEL
    except Exception as e1:
        print(f"[Neural Core] ⚠️ LLM() load failed: {e1}", flush=True)

    try:
        # Fallback: directory + model_file
        from ctransformers import AutoModelForCausalLM
        t0 = time.time()
        print(f"[Neural Core] 🧠 Loading GGUF via from_pretrained(dir, model_file): dir='{gguf.parent}', file='{gguf.name}' ...", flush=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_path_or_repo_id=str(gguf.parent),
            model_file=gguf.name,
            model_type="llama",
            local_files_only=True,
            gpu_layers=0,
            context_length=2048,
        )
        _MODEL = model
        _MODEL_ANCHOR = anchor
        print(f"[Neural Core] ✅ Model ready in {time.time() - t0:.2f}s (from_pretrained)", flush=True)
        return _MODEL
    except Exception as e2:
        print(f"[Neural Core] ❌ from_pretrained load failed: {e2}", flush=True)
        _MODEL = None
        _MODEL_ANCHOR = None
        return None

# ---- Prompting ---------------------------------------------------------------
def _build_prompt(text: str, mood: str, allow_profanity: bool) -> str:
    tone = {
        "serious": "succinct, confident, professional, no filler",
        "cheeky": "playful, witty, lightly sarcastic, but helpful",
        "relaxed": "friendly, calm, conversational",
        "urgent": "terse, high-priority, crisp",
        "angry": "short, no-nonsense, sharp edges",
        "sarcastic": "dry, sardonic, minimal fluff",
        "hacker-noir": "laconic, neon-noir sysop vibe",
    }[_normalize_mood(mood)]
    filters = "" if allow_profanity else "Keep it family-friendly; avoid profanity."
    return (
        "You polish infrastructure alerts for a home server admin.\n"
        "Keep ALL key facts (titles, IPs, versions, counts, links, times).\n"
        "Output ONLY bullet lines (no headings, no labels).\n"
        f"Tone: {tone}. {filters}\n"
        "Bullets should feel like my homelab is speaking.\n\n"
        f"MESSAGE:\n{text}\n"
        "REWRITE:\n"
    )

def _cut(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[: max(0, n - 1)].rstrip() + "…")

# ---- Public API --------------------------------------------------------------
def rewrite_text(prompt: str, mood: str = "serious", timeout_s: int = 5) -> str:
    """
    Streaming generation with a hard timeout (best-effort).
    Kept for backward compatibility with existing callers.
    """
    model = _load_model()
    if model is None:
        # fallback: simply bulletize original text
        return rewrite_fallback(prompt, mood)

    allow_profanity = _cfg_allow_profanity()
    tpl = _build_prompt(prompt or "", mood, allow_profanity)
    t0 = time.time()
    out_parts: List[str] = []
    try:
        for tok in model(tpl, stream=True, max_new_tokens=LLM_MAX_TOKENS,
                         temperature=LLM_TEMPERATURE, top_p=LLM_TOP_P):
            out_parts.append(tok)
            if (time.time() - t0) > timeout_s:
                break
    except Exception as e:
        print(f"[Neural Core] ⚠️ Generation error (stream): {e}", flush=True)
        return rewrite_fallback(prompt, mood)

    gen = "".join(out_parts).strip()
    bullets = _postprocess(gen, mood, allow_profanity)
    return bullets or rewrite_fallback(prompt, mood)

def rewrite_with_info(
    text: str,
    mood: str = "serious",
    timeout: int = 5,
    cpu_limit: int = 70,          # signature-compat only
    models_priority=None,         # signature-compat only
    base_url: str = "",           # signature-compat only
    allow_profanity: Optional[bool] = None,
    model_path: str = ""
) -> Tuple[str, bool]:
    """
    Preferred API for SMTP/Proxy path.
    Returns (output_text, used_llm).
    used_llm == True only when a GGUF model was successfully loaded & used.
    """
    if model_path:
        # Allow per-call override
        global MODEL_PATH
        MODEL_PATH = model_path

    model = _load_model()
    if model is None:
        return rewrite_fallback(text, mood), False

    if allow_profanity is None:
        allow_profanity = _cfg_allow_profanity()

    prompt = _build_prompt(text or "", mood, allow_profanity)
    t0 = time.time()
    out = ""
    try:
        # Non-stream call for simplicity/compat
        out = str(model(prompt,
                        max_new_tokens=LLM_MAX_TOKENS,
                        temperature=LLM_TEMPERATURE,
                        top_p=LLM_TOP_P) or "").strip()
    except Exception as e:
        print(f"[Neural Core] ⚠️ Generation error: {e}", flush=True)
        return rewrite_fallback(text, mood), False

    bullets = _postprocess(out, mood, allow_profanity)
    if not bullets:
        return rewrite_fallback(text, mood), False
    return bullets, True

# ---- Fallback & postprocess --------------------------------------------------
def rewrite_fallback(text: str, mood: str) -> str:
    bullet = _bullet_for(mood)
    base = (text or "").strip().replace("\r", "")
    lines = []
    for raw in base.splitlines():
        s = raw.strip()
        if not s:
            continue
        if not s.startswith(bullet + " "):
            s = f"{bullet} {s}"
        lines.append(_cut(s, MAX_LINE_CHARS))
        if len(lines) >= MAX_LINES:
            break
    if not lines:
        lines = [f"{bullet} (no content)"]
    return _clean_if_needed("\n".join(lines), _cfg_allow_profanity())

def _postprocess(gen: str, mood: str, allow_profanity: bool) -> str:
    if not gen:
        return ""
    # If model echoed instructions, try to trim to first bullet
    m = re.search(r"(•|✨|⚡|😏|▣)\s", gen)
    if m:
        gen = gen[m.start():]
    lines: List[str] = []
    for raw in gen.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.search(r"(REWRITE:|MESSAGE:|Example|Tone:|Rules:|Output ONLY)", s, re.I):
            continue
        if not re.match(r"^(•|✨|⚡|😏|▣)\s", s):
            s = f"{_bullet_for(mood)} {s}"
        lines.append(_cut(s, MAX_LINE_CHARS))
        if len(lines) >= MAX_LINES:
            break
    return _clean_if_needed("\n".join(lines), allow_profanity) if lines else ""

# ---- Main: allow run.sh to prefetch (and optional self-test) -----------------
if __name__ == "__main__":
    try:
        dest = prefetch_model()
        if dest:
            print(f"[{BOT_NAME}] 🔧 Prefetch complete: {dest}", flush=True)
        else:
            print(f"[{BOT_NAME}] ⚠️ Prefetch skipped.", flush=True)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch failed: {e}", flush=True)

    # Optional quick self-test if model is present
    model = _load_model()
    if model is not None:
        try:
            out, used = rewrite_with_info("Boot self-test: say hello in bullet points.", mood=os.getenv("CHAT_MOOD", "serious"))
            print(f"[Neural Core] SELF-TEST used_llm={used} chars={len(out)}", flush=True)
        except Exception as e:
            print(f"[Neural Core] SELF-TEST generation failed: {e}", flush=True)
