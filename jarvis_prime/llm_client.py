#!/usr/bin/env python3
"""
Neural Core for Jarvis Prime

What it does
------------
- If a local GGUF model is available (ctransformers), it GENERATES a full,
  mood-drenched, human-friendly rewrite of the incoming message.
- If not available / times out / errors: falls back to deterministic
  rules-based renderers so you still get a clean, readable output.
- Profanity is allowed/blocked based on options.json.
- NO footer added here (callers add a single footer so it never duplicates).

Environment / Options
---------------------
- /data/options.json keys used:
    personality_allow_profanity: bool
    llm_model_path: str (preferred), we will also try /share/jarvis_prime/models/*.gguf
- Optional env overrides:
    PERSONALITY_ALLOW_PROFANITY=1|0
    LLM_DETAIL_LEVEL=rich|normal
    LLM_TEMPERATURE (default 0.45)
    LLM_TOP_P (default 0.9)
    LLM_MAX_TOKENS (default 320)
"""

from __future__ import annotations
import os, re, json
from pathlib import Path
from typing import Optional, Dict, List

# ---------- Tunables ----------
DETAIL_LEVEL = os.getenv("LLM_DETAIL_LEVEL", "rich").lower()
MAX_LINES = 10 if DETAIL_LEVEL == "rich" else 6
MAX_LINE_CHARS = 160

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.45"))
LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "320"))

_MODEL = None
_MODEL_PATH: Optional[Path] = None
_CTRANS_AVAILABLE = False

# ---------- Config ----------
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
    # Prefer explicit path from /data/options.json
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            p = (cfg.get("llm_model_path") or "").strip()
            if p:
                return p
    except Exception:
        pass
    # Then use provided fallback
    if fallback:
        return fallback
    # Then check default share folder
    base = Path("/share/jarvis_prime/models")
    if base.exists():
        ggufs = sorted(base.glob("*.gguf"))
        if ggufs:
            return str(ggufs[0])
    return ""

# ---------- Optional model load ----------
def _load_model(model_path: str):
    global _MODEL, _MODEL_PATH, _CTRANS_AVAILABLE
    if not model_path:
        return False
    try:
        from ctransformers import AutoModelForCausalLM
        _CTRANS_AVAILABLE = True
    except Exception as e:
        print(f"[Neural Core] ctransformers not available: {e}")
        _CTRANS_AVAILABLE = False
        return False

    p = Path(os.path.expandvars(model_path))
    if not p.exists():
        print(f"[Neural Core] Model path not found: {p}")
        return False

    if _MODEL is not None and _MODEL_PATH == p:
        return True

    print(f"[Neural Core] Loading model: {p}")
    try:
        _MODEL = AutoModelForCausalLM.from_pretrained(
            str(p.parent),
            model_file=p.name,
            model_type="llama",
            gpu_layers=0,
        )
        _MODEL_PATH = p
        print("[Neural Core] Model ready")
        return True
    except Exception as e:
        print(f"[Neural Core] Failed to load GGUF: {e}")
        _MODEL = None
        _MODEL_PATH = None
        return False

# ---------- Utils ----------
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

def _variety(seed: str, options: List[str]) -> str:
    if not options:
        return ""
    import hashlib as _h
    h = int(_h.md5(seed.encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]

# ---------- Mood ----------
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

def _closer(mood: str, seed: str, allow_profanity: bool) -> str:
    choices = {
        "angry": ["Done. No BS.", "Handled.", "We’re good.", "Sorted."],
        "sarcastic": ["Obviously.", "Ground-breaking.", "Noted.", "Thrilling."],
        "playful": ["Nice!", "Neat!", "All set!", "Wrapped!"],
        "hacker-noir": ["Logged.", "Filed.", "In the ledger.", "Trace saved."],
        "serious": ["All set.", "Complete.", "OK.", "Done."],
    }.get(mood, ["Done."])
    return _variety(seed, choices)

# ---------- Deterministic renderers (fallback) ----------
def _render_generic(text: str, mood: str, allow_profanity: bool) -> List[str]:
    b = _bullet_for(mood)
    out: List[str] = []
    for ln in (text or "").splitlines():
        if ln.strip():
            out.append(f"{b} {_cut(ln, 150)}")
            break
    out.append(f"{b} ✅ {_closer(mood, text, allow_profanity)}")
    return out

# ---------- LLM prompt ----------
def _build_prompt(text: str, mood: str, allow_profanity: bool) -> str:
    tone = {
        "serious": "clear, terse, professional",
        "sarcastic": "dry, witty, slightly mocking (but not cruel)",
        "playful": "friendly, lively, fun",
        "hacker-noir": "terse, noir, sysadmin detective vibe",
        "angry": "blunt, spicy, no-nonsense",
    }.get(mood, "clear and concise")

    profanity = "Profanity allowed if natural." if allow_profanity else "No profanity."
    style = (
        "Use short punchy lines with emoji bullets. "
        "Keep 4–8 bullets maximum. Prefer facts over fluff. "
        "No hallucinations. If links are present, keep one. "
        "If there are errors, call them out clearly."
    )
    bullet = _bullet_for(mood)

    return (
        f"You are Jarvis Prime rewriting an inbound notification for a homelab owner.\n"
        f"Tone: {tone}. {profanity}\n"
        f"{style}\n"
        f"Bullet prefix: '{bullet}'\n"
        f"Rewrite the MESSAGE below as a neat list of bullets in the given tone.\n"
        f"End with a final bullet that feels like a short closing quip.\n"
        f"\nMESSAGE:\n{text}\n\nREWRITE:\n"
    )

# ---------- Public API ----------
def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 5,
    cpu_limit: int = 70,
    models_priority=None,
    base_url: str = "",
    model_path: str = "",
) -> str:
    """
    Returns ONLY the rewritten body (no footer). Callers add footers.
    """
    text = text or ""
    allow_profanity = _cfg_allow_profanity()
    mood = _normalize_mood(mood)
    model_path = model_path or _cfg_model_path()

    # Try to load once; generation below can still fail and we will fallback.
    have_model = _load_model(model_path)

    # If a model is ready, try generation
    if have_model and _CTRANS_AVAILABLE and _MODEL is not None:
        try:
            prompt = _build_prompt(text, mood, allow_profanity)
            # NOTE: ctransformers call is synchronous; caller wraps this in a thread with timeout.
            out = _MODEL(
                prompt,
                max_new_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                top_p=LLM_TOP_P,
            )
            gen = str(out or "").strip()
            gen = re.sub(r"^\s*(rewrite|message)\s*:\s*", "", gen, flags=re.I)
            gen = re.sub(r"(\n){3,}", "\n\n", gen)
            # Basic sanity: must contain at least one bullet line; if not, wrap it
            if not re.search(r"^\s*(•|✨|⚡|😏|▣)\s", gen, re.M):
                lines = [ln.strip() for ln in gen.splitlines() if ln.strip()]
                gen = "\n".join(f"{_bullet_for(mood)} {ln}" for ln in lines[:MAX_LINES])
            return _clean_if_needed(gen, allow_profanity)
        except Exception as e:
            print(f"[Neural Core] Generation error: {e}")

    # Fallback: deterministic compact render
    try:
        lines = _render_generic(text, mood, allow_profanity)
        lines = _dedupe(lines, MAX_LINES)
        out = "\n".join(lines) if lines else text
        return _clean_if_needed(out, allow_profanity)
    except Exception as e:
        print(f"[Neural Core] Fallback compose error: {e}")
        return _clean_if_needed(text, allow_profanity)
