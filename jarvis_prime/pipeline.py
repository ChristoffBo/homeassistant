#!/usr/bin/env python3
# /app/pipeline.py
from __future__ import annotations
import os, re
from typing import Tuple, Dict

from beautify import beautify
from llm_client import rewrite as llm_rewrite
from llm_client import _polish, _cap  # light presentation cleanup only

NUM_RE = re.compile(r'\b\d[\d,.:]*\b')
URL_RE = re.compile(r'https?://[^\s)>\]]+')
IP_RE  = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

def _facts(sig: str) -> Tuple[tuple, tuple, tuple]:
    nums = tuple(NUM_RE.findall(sig or ''))
    urls = tuple(URL_RE.findall(sig or ''))
    ips  = tuple(IP_RE.findall(sig or ''))
    return nums, urls, ips

def _same_facts(a: str, b: str) -> bool:
    return _facts(a) == _facts(b)

def process(title: str, raw_text: str, mood: str) -> Tuple[str, Dict[str, object]]:
    """
    1) Beautify  2) LLM (low-temp)  3) Polish  4) Fact-guard fallback
    Returns (final_text, extras) where extras includes images/kind, etc.
    """
    # 1) BEAUTIFY
    clean_text, extras = beautify(title, raw_text)
    base = clean_text or ""

    # 2) LLM voice (do not invent facts)
    use_llm = os.getenv("LLM_ENABLED", "true").lower() == "true"
    if use_llm and base.strip():
        try:
            out = llm_rewrite(
                text=base,
                mood=mood or os.getenv("personality_mood", "serious"),
                timeout=int(os.getenv("llm_timeout_seconds", "8")),
                cpu_limit=int(os.getenv("llm_max_cpu_percent", "70")),
            )
            # 3) POLISH
            out = _cap(_polish(out or ""))

            # 4) FACT GUARD — keep only if numbers/URLs/IPs unchanged
            if out and _same_facts(base, out):
                return out, extras
        except Exception:
            pass

    # Fallback: polished beautified text
    return _cap(_polish(base)), extras
