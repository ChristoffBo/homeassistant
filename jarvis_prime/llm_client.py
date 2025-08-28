#!/usr/bin/env python3
"""
Neural Core for Jarvis Prime

- Rewrites inbound messages into mood-forward, human-friendly bullets.
- Local GGUF via ctransformers (CPU). No networking required.
- If model import/load fails, returns a compact deterministic fallback.
- Profanity allowed/blocked from /data/options.json (personality_allow_profanity).
"""

from __future__ import annotations
import os
import re
import json
import time
from pathlib import Path
from typing import Optional, List

# ============================ Tunables ============================
DETAIL_LEVEL = os.getenv("LLM_DETAIL_LEVEL", "rich").lower()
MAX_LINES = 10 if DETAIL_LEVEL == "rich" else 6
MAX_LINE_CHARS = 160

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
LLM_TOP_P      = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "320"))

# Verbose logging so we can prove it's firing
VERBOSE = True

# ============================ Globals =============================
_MODEL = None
_MODEL_PATH: Optional[Path] = None
_CTRANS_AVAILABLE = False

# ====================== Config / helpers ==========================
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

def _cfg_model_path(fallback: str = "") -> str:
    # Prefer options.json (user editable)
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            p = (cfg.get("llm_model_path") or "").strip()
            if p:
                return p
    except Exception:
        pass
    # Fallback the explicit arg if provided
    if fallback:
        return fallback
    # Finally, pick first .gguf under /share/jarvis_prime/models
    base = Path("/share/jarvis_prime/models")
    if base.exists():
        ggufs = sorted(base.glob("*.gguf"))
        if ggufs:
            return str(ggufs[0])
    return ""

# ============================ Model ===============================
def _import_ctransformers() -> bool:
    global _CTRANS_AVAILABLE
    if _CTRANS_AVAILABLE:
        return True
    try:
        from ctransformers import AutoModelForCausalLM  # noqa: F401
        _CTRANS_AVAILABLE = True
        if VERBOSE:
            print("[Neural Core] ctransformers import: OK")
        return True
    except Exception as e:
        print(f"[Neural Core] ctransformers import FAILED: {e}")
        _CTRANS_AVAILABLE = False
        return False

def _load_model(model_path: str) -> bool:
    """
    Load GGUF once. Returns True if the model is ready.
    """
    global _MODEL, _MODEL_PATH
    if not model_path:
        print("[Neural Core] No model path configured.")
        return False

    # Already loaded?
    p = Path(os.path.expandvars(model_path))
    if _MODEL is not None and _MODEL_PATH == p:
        return True

    if not _import_ctransformers():
        return False

    if not p.exists():
        print(f"[Neural Core] Model path not found: {p}")
        return False

    try:
        from ctransformers import AutoModelForCausalLM
        if VERBOSE:
            size = p.stat().st_size
            print(f"[Neural Core] Loading GGUF: {p} (size={size} bytes)")
        t0 = time.time()
        _MODEL = AutoModelForCausalLM.from_pretrained(
            str(p.parent),
            model_file=p.name,
            model_type="llama",   # TinyLlama is llama-compatible
            gpu_layers=0,         # CPU only in HA add-on
        )
        _MODEL_PATH = p
        if VERBOSE:
            print(f"[Neural Core] Model ready in {time.time()-t0:.2f}s")
        return True
    except Exception as e:
        print(f"[Neural Core] Failed to load GGUF: {e}")
        _MODEL = None
        _MODEL_PATH = None
        return False

# ============================ Text utils ==========================
def _cut(s: str, n: int) -> str:
    s = (s or "").strip()
    return (s[: n - 1] + "…") if len(s) > n else s

_PROF_RE = re.compile(
    r"\b(fuck|f\*+k|f\W?u\W?c\W?k|shit|bitch|cunt|asshole|motherf\w+|dick|prick|whore)\b",
    re.I,
)

def _clean_if_needed(text: str, allow_profanity: bool) -> str:
    return text if allow_profanity else _PROF_RE.sub("—", text or "")

def _dedupe(lines: List[str], limit: int) -> List[str]:
    out, seen = [], set()
    for ln in lines:
        ln = (ln or "").strip()
        if not ln:
            continue
        k = ln.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(_cut(ln, MAX_LINE_CHARS))
        if len(out) >= limit:
            break
    return out

def _normalize_mood(mood: str) -> str:
    m = (mood or "serious").strip().lower()
    table = {
        "ai": "serious","calm": "serious","tired": "serious","depressed": "serious",
        "excited": "playful","happy": "playful","playful": "playful",
        "sarcastic": "sarcastic","snarky": "sarcastic",
        "angry": "angry","hacker-noir": "hacker-noir","noir": "hacker-noir",
        "serious": "serious",
    }
    return table.get(m, "serious")

def _bullet_for(mood: str) -> str:
    return {"serious":"•","sarcastic":"😏","playful":"✨","hacker-noir":"▣","angry":"⚡"}.get(mood,"•")

# =============== Deterministic fallback renderer ==================
def _render_generic(text: str, mood: str, allow_profanity: bool) -> str:
    b = _bullet_for(mood)
    lines: List[str] = []
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    if first:
        lines.append(f"{b} { _cut(first, 150)}")
    lines.append(f"{b} ✅ Done.")
    lines = _dedupe(lines, MAX_LINES)
    out = "\n".join(lines)
    if VERBOSE:
        print("[Neural Core] Fallback renderer used.")
    return _clean_if_needed(out, allow_profanity)

# =========================== Prompting ============================
def _examples(mood: str) -> str:
    b = _bullet_for(mood)
    if mood == "angry":
        return (
            f"{b} APT finished on 10.0.0.249 — nothing to upgrade.\n"
            f"{b} Reboot? Nope.\n"
            f"{b} System ready. Move on.\n"
            f"{b} ✅ Done. No BS."
        )
    if mood == "sarcastic":
        return (
            f"{b} APT ran on 10.0.0.249. Riveting.\n"
            f"{b} Packages upgraded: none. Shocking.\n"
            f"{b} Reboot required: no — try to contain your excitement.\n"
            f"{b} ✅ System ready. Obviously."
        )
    if mood == "playful":
        return (
            f"{b} APT spruced up 10.0.0.249.\n"
            f"{b} Upgrades: none — already shiny!\n"
            f"{b} Reboot? Nah, we’re chill.\n"
            f"{b} ✅ All set. High-five!"
        )
    if mood == "hacker-noir":
        return (
            f"{b} Host 10.0.0.249 checked the depot. Quiet night.\n"
            f"{b} No packages moved. No reboot.\n"
            f"{b} The machine hums, waiting.\n"
            f"{b} ✅ Logged."
        )
    return (
        f"{b} APT completed on 10.0.0.249.\n"
        f"{b} Packages upgraded: none.\n"
        f"{b} Reboot required: no.\n"
        f"{b} ✅ System ready."
    )

def _build_prompt(text: str, mood: str, allow_profanity: bool) -> str:
    tone = {
        "serious": "clear, terse, professional",
        "sarcastic": "dry, witty, slightly mocking (not cruel)",
        "playful": "friendly, lively, fun",
        "hacker-noir": "terse, noir sysadmin detective vibe",
        "angry": "blunt, spicy, no-nonsense",
    }.get(mood, "clear and concise")
    profanity = "Profanity allowed if it fits the tone." if allow_profanity else "Do NOT use profanity."
    bullet = _bullet_for(mood)
    fewshot = _examples(mood)
    # Keep the prompt *very* tight so TinyLlama doesn’t parrot instructions.
    return (
        "You are Jarvis Prime. Rewrite the MESSAGE for a homelab owner.\n"
        f"Tone: {tone}. {profanity}\n"
        f"Output ONLY short bullets using this prefix: '{bullet}'. No headings, no numbering, no explanations.\n"
        "Keep 4–8 bullets. Be concrete. Keep facts; do not invent. End with a quick closing quip.\n\n"
        "Example:\n"
        f"{fewshot}\n\n"
        f"MESSAGE:\n{text}\n"
        "REWRITE:\n"
    )

# ============================ Public API ==========================
def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 5,          # (caller enforces timeouts with thread pools)
    cpu_limit: int = 70,       # kept for signature compatibility
    models_priority=None,      # kept for signature compatibility
    base_url: str = "",        # kept for signature compatibility
    model_path: str = "",
) -> str:
    """
    Returns ONLY the rewritten body (no footer). Callers add the footer.
    """
    allow_profanity = _cfg_allow_profanity()
    mood = _normalize_mood(mood)
    model_path = model_path or _cfg_model_path()

    if VERBOSE:
        print(f"[Neural Core] rewrite() start: mood={mood} model='{model_path}'")

    ready = _load_model(model_path)
    if not ready or _MODEL is None:
        return _render_generic(text or "", mood, allow_profanity)

    # Build prompt and generate
    try:
        prompt = _build_prompt(text or "", mood, allow_profanity)
        if VERBOSE:
            print("[Neural Core] Generating...")
        t0 = time.time()
        out = _MODEL(
            prompt,
            max_new_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            top_p=LLM_TOP_P,
        )
        gen = str(out or "").strip()
        if VERBOSE:
            print(f"[Neural Core] Generation done in {time.time()-t0:.2f}s")
    except Exception as e:
        print(f"[Neural Core] Generation error: {e}")
        return _render_generic(text or "", mood, allow_profanity)

    # -------- Sanitize / enforce bullet lines ----------
    # Keep only content from the first bullet onwards.
    m = re.search(r"(•|✨|⚡|😏|▣)\s", gen)
    if m:
        gen = gen[m.start():]

    lines: List[str] = []
    for raw in gen.splitlines():
        s = raw.strip()
        if not s:
            continue
        # Drop anything that looks like instructions or echoes
        if re.match(r"^\d+\.\s", s):                 # numbered lists
            continue
        if re.search(r"(REWRITE:|MESSAGE:|Example|Tone:|Output ONLY)", s, re.I):
            continue
        # Ensure each line starts with the mood bullet
        if not re.match(r"^(•|✨|⚡|😏|▣)\s", s):
            s = f"{_bullet_for(mood)} {s}"
        lines.append(_cut(s, MAX_LINE_CHARS))
        if len(lines) >= MAX_LINES:
            break

    if not lines:
        return _render_generic(text or "", mood, allow_profanity)

    result = "\n".join(lines)
    return _clean_if_needed(result, allow_profanity)
