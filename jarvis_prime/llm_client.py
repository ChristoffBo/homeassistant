#!/usr/bin/env python3
"""
Neural Core for Jarvis Prime

- Generates a mood-forward, human-friendly rewrite of inbound messages.
- Uses local GGUF via ctransformers when available.
- Falls back to a compact deterministic renderer.
- Profanity allowed/blocked from /data/options.json.
- NO footer here — callers add a single footer so it never duplicates.
"""

from __future__ import annotations
import os, re, json
from pathlib import Path
from typing import Optional, List

# ---------------- Tunables ----------------
DETAIL_LEVEL = os.getenv("LLM_DETAIL_LEVEL", "rich").lower()
MAX_LINES = 10 if DETAIL_LEVEL == "rich" else 6
MAX_LINE_CHARS = 160

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
LLM_TOP_P      = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "320"))

_MODEL = None
_MODEL_PATH: Optional[Path] = None
_CTRANS_AVAILABLE = False

# ---------------- Config helpers ----------------
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
    try:
        with open("/data/options.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            p = (cfg.get("llm_model_path") or "").strip()
            if p:
                return p
    except Exception:
        pass
    if fallback:
        return fallback
    base = Path("/share/jarvis_prime/models")
    if base.exists():
        ggufs = sorted(base.glob("*.gguf"))
        if ggufs:
            return str(ggufs[0])
    return ""

# ---------------- Model load ----------------
def _load_model(model_path: str) -> bool:
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

# ---------------- Utils ----------------
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

# ---------------- Fallback compact renderer ----------------
def _render_generic(text: str, mood: str, allow_profanity: bool) -> str:
    b = _bullet_for(mood)
    lines: List[str] = []
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    if first:
        lines.append(f"{b} { _cut(first, 150)}")
    lines.append(f"{b} ✅ Done.")
    lines = _dedupe(lines, MAX_LINES)
    return _clean_if_needed("\n".join(lines), allow_profanity)

# ---------------- Prompt building ----------------
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
    # serious
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
    return (
        "You are Jarvis Prime rewriting an inbound notification for a homelab owner.\n"
        f"Tone: {tone}. {profanity}\n"
        "Format rules:\n"
        f"- Output ONLY short bullet lines, each starting with the bullet prefix '{bullet}'.\n"
        "- Do NOT number lines. Do NOT repeat instructions. Do NOT write headings.\n"
        "- Keep 4–8 bullets. Be concrete. Keep existing facts; do not invent.\n"
        "- Finish with a short closing quip as the last bullet.\n\n"
        "Example output for this tone:\n"
        f"{fewshot}\n\n"
        f"Now rewrite the following MESSAGE exactly once in the same format.\n"
        f"Bullet prefix to use: '{bullet}'\n"
        "MESSAGE:\n"
        f"{text}\n"
        "REWRITE:\n"
    )

# ---------------- Public API ----------------
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

    have_model = _load_model(model_path)

    if have_model and _CTRANS_AVAILABLE and _MODEL is not None:
        try:
            prompt = _build_prompt(text, mood, allow_profanity)
            out = _MODEL(
                prompt,
                max_new_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                top_p=LLM_TOP_P,
            )
            gen = str(out or "").strip()

            # ----- Sanitize / enforce bullets -----
            # Drop anything before the first bullet symbol
            first_bullet = re.search(r"(•|✨|⚡|😏|▣)\s", gen)
            if first_bullet:
                gen = gen[first_bullet.start():]
            # Remove numbered echoes or instruction-like lines
            lines = []
            for ln in gen.splitlines():
                s = ln.strip()
                if not s:
                    continue
                if re.match(r"^\d+\.\s", s):
                    continue
                if re.search(r"(Output ONLY short bullet lines|REWRITE:|MESSAGE:|Tone:|Format rules:)", s, re.I):
                    continue
                # Ensure bullet prefix
                if not re.match(r"^(•|✨|⚡|😏|▣)\s", s):
                    s = f"{_bullet_for(mood)} {s}"
                lines.append(s)
                if len(lines) >= MAX_LINES:
                    break

            result = "\n".join(lines)
            if not result:
                result = _render_generic(text, mood, allow_profanity)
            return _clean_if_needed(result, allow_profanity)
        except Exception as e:
            print(f"[Neural Core] Generation error: {e}")

    # Fallback
    return _render_generic(text, mood, allow_profanity)
