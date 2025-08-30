#!/usr/bin/env python3
from __future__ import annotations
import os, re, time
from typing import Optional, List, Dict

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
CTX = int(os.getenv("LLM_CTX_TOKENS", "4096"))
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "180"))
CHARS_PER_TOKEN = 4
SAFETY_TOKENS = 32

def _budget_chars(system: str) -> int:
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * CHARS_PER_TOKEN)
    return max(500, budget_chars - len(system or ""))

def _load_system_prompt() -> str:
    sp = os.getenv("LLM_SYSTEM_PROMPT")
    if sp: return sp
    return "YOU ARE JARVIS PRIME (formatter-only). Do not add, remove, or reorder content."

def _trim_to_ctx(src: str, system: str) -> str:
    if not src: return src
    remaining = _budget_chars(system)
    if len(src) <= remaining: return src
    return src[-remaining:]

ZWSP_RE   = re.compile(r'[\u200B\u200C\u200D\uFEFF]')
TRAIL_WS  = re.compile(r'[ \t]+\n')
MULTIBLNK = re.compile(r'(?:\n[ \t]*){3,}', flags=re.M)
BULLET_RE = re.compile(r'^(?P<pre>[ \t]*)(?P<bullet>[-*•])([ \t]{2,})(?P<rest>\S)', flags=re.M)

def strict_format(text: str) -> str:
    if not text: return text
    s = text.replace('\r\n','\n').replace('\r','\n')
    s = ZWSP_RE.sub('', s)
    s = TRAIL_WS.sub('\n', s)
    s = MULTIBLNK.sub('\n\n', s)
    s = BULLET_RE.sub(lambda m: f"{m.group('pre')}{m.group('bullet')} {m.group('rest')}", s)
    if s and not s.endswith('\n'):
        s = s + '\n'
    return s

def prefetch_model(*args, **kwargs) -> None:
    pass

def engine_status() -> Dict[str, object]:
    return {"ready": True, "model_path": "formatter://strict", "backend": "formatter"}

def rewrite(text: str, mood: str = "serious", timeout: int = 8, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str] = None,
            model_url: Optional[str] = None, model_path: Optional[str] = None,
            model_sha256: Optional[str] = None, allow_profanity: bool = False) -> str:
    src = (text or "")
    if not src: return src
    system = _load_system_prompt()
    src2 = _trim_to_ctx(src, system)
    start = time.time()
    try:
        out = strict_format(src2)
        if (time.time() - start) > max(1, int(timeout)):
            print(f"[{BOT_NAME}] ⚠️ Formatter timeout; returning original.")
            return src
        return out
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Formatter error: {e}")
        return src
