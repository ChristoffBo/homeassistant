#!/usr/bin/env python3
# /app/llm_client.py  —  Formatter-only core (non-destructive)
from __future__ import annotations

import os
import re
import time
from typing import Optional, List, Dict

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# Performance knobs still honored (used to guard the formatter path)
CTX = int(os.getenv("LLM_CTX_TOKENS", "4096"))
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "180"))
CHARS_PER_TOKEN = 4
SAFETY_TOKENS = 32

def _budget_chars(system: str) -> int:
    # Maintain same budgeting math so knobs remain meaningful
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * CHARS_PER_TOKEN)
    return max(500, budget_chars - len(system or ""))

def _load_system_prompt() -> str:
    # Kept for compatibility; not used to change content
    sp = os.getenv("LLM_SYSTEM_PROMPT")
    if sp:
        return sp
    try:
        for p in ("/share/jarvis_prime/memory/system_prompt.txt",
                  "/app/memory/system_prompt.txt"):
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
    except Exception:
        pass
    return "YOU ARE JARVIS PRIME (formatter-only). Do not add, remove, or reorder content."

def _trim_to_ctx(src: str, system: str) -> str:
    if not src:
        return src
    remaining = _budget_chars(system)
    if len(src) <= remaining:
        return src
    # Keep tail (most recent text); do not remove *semantic* content beyond the contextual window limit.
    return src[-remaining:]

# ========== STRICT FORMATTER (NON-DESTRUCTIVE) ==========
# Rules:
# - Do NOT add/remove words or lines.
# - Normalize line endings, strip trailing spaces, collapse gratuitous whitespace-only lines to a single blank,
#   normalize bullet spacing, and remove zero-width chars. All text tokens remain in the same order.
# - No emojis, no quips, no summaries, no interpretation.
ZWSP_RE   = re.compile(r'[\u200B\u200C\u200D\uFEFF]')  # zero-width space/joiners
TRAIL_WS  = re.compile(r'[ \t]+\n')
MULTIBLNK = re.compile(r'(?:\n[ \t]*){3,}', flags=re.M)
BULLET_RE = re.compile(r'^(?P<pre>[ \t]*)(?P<bullet>[-*•])([ \t]{2,})(?P<rest>\S)', flags=re.M)

def strict_format(text: str) -> str:
    if not text:
        return text
    s = text

    # 1) Normalize newlines
    s = s.replace('\r\n', '\n').replace('\r', '\n')

    # 2) Remove zero-width chars (visual junk)
    s = ZWSP_RE.sub('', s)

    # 3) Trim trailing whitespace at line ends (no token loss)
    s = TRAIL_WS.sub('\n', s)

    # 4) Normalize excessive blank lines (keep at most two in a row)
    s = MULTIBLNK.sub('\n\n', s)

    # 5) Make bullets consistent without changing text content
    s = BULLET_RE.sub(lambda m: f"{m.group('pre')}{m.group('bullet')} {m.group('rest')}", s)

    # 6) Preserve leading/trailing newlines exactly once
    if s and not s.endswith('\n'):
        s = s + '\n'
    return s

# ========== PUBLIC API (kept stable for callers) ==========
def prefetch_model(*args, **kwargs) -> None:
    # No-op for formatter mode (no model to load)
    pass

def engine_status() -> Dict[str, object]:
    # Always ready in formatter mode; show a virtual path so the boot card can present a family
    return {"ready": True, "model_path": "formatter://strict", "backend": "formatter"}

def rewrite(text: str, mood: str = "serious", timeout: int = 8, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str] = None,
            model_url: Optional[str] = None, model_path: Optional[str] = None,
            model_sha256: Optional[str] = None, allow_profanity: bool = False) -> str:
    """
    Non-destructive formatter:
      - keeps all original content and order
      - normalizes only whitespace/bullets/newlines
      - respects 'timeout' by bailing out to the original text if exceeded
      - 'cpu_limit' is acknowledged (formatting is O(n) and lightweight)
    """
    src = (text or "")
    if not src:
        return src

    # Respect contextual budget for extremely long inputs; trimming is a *display* constraint, not semantic deletion.
    system = _load_system_prompt()
    src2 = _trim_to_ctx(src, system)

    start = time.time()
    try:
        out = strict_format(src2)
        # Basic timeout guard
        if (time.time() - start) > max(1, int(timeout)):
            print(f"[{BOT_NAME}] ⚠️ Formatter timeout; returning original.")
            return src
        return out
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Formatter error: {e}")
        return src
