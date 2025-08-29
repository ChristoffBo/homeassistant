#!/usr/bin/env python3
# /app/pipeline.py
from __future__ import annotations
import os, re, importlib
from typing import Tuple, Dict

# ---------- Safe imports ----------
try:
    _beaut_mod = importlib.import_module("beautify")
    _beautify = getattr(_beaut_mod, "beautify", None)
except Exception:
    _beaut_mod = None
    _beautify = None

try:
    from llm_client import rewrite as llm_rewrite  # type: ignore
except Exception:
    def llm_rewrite(text: str, mood: str = "serious", **_: object) -> str:
        return text

try:
    from llm_client import _polish, _cap  # type: ignore
except Exception:
    def _polish(text: str) -> str:
        s = (text or "").strip()
        s = re.sub(r'[ \t]+', ' ', s)
        s = re.sub(r'[ \t]*\n[ \t]*', '\n', s)
        return s
    def _cap(text: str, max_lines: int = int(os.getenv("LLM_MAX_LINES", "10")), max_chars: int = 800) -> str:
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        out = "\n".join(lines)
        if len(out) > max_chars:
            out = out[:max_chars].rstrip()
        return out

IMG_MD_RE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)

def _extract_images(src: str) -> list[str]:
    imgs = IMG_MD_RE.findall(src or '') + IMG_URL_RE.findall(src or '')
    seen: set[str] = set(); out: list[str] = []
    for i in imgs:
        if i not in seen:
            seen.add(i); out.append(i)
    return out

NUM_RE = re.compile(r'\b\d[\d,.:]*\b')
URL_RE = re.compile(r'https?://[^\s)>\]]+')
IP_RE  = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

def _facts(sig: str):
    nums = tuple(NUM_RE.findall(sig or ''))
    urls = tuple(URL_RE.findall(sig or ''))
    ips  = tuple(IP_RE.findall(sig or ''))
    return nums, urls, ips

def _same_facts(a: str, b: str) -> bool:
    return _facts(a) == _facts(b)

def _safe_beautify(title: str, raw_text: str) -> Tuple[str, Dict[str, object]]:
    if callable(_beautify):
        try:
            out_text, extras = _beautify(title, raw_text)
            if isinstance(out_text, str) and isinstance(extras, dict):
                return out_text, extras
        except Exception:
            pass

    images = _extract_images(raw_text)
    chunks = [ln.strip() for ln in (raw_text or "").splitlines()]
    out_lines: list[str] = []
    blank = False
    for ln in chunks:
        if ln:
            out_lines.append(ln); blank = False
        else:
            if not blank:
                out_lines.append(""); blank = True
    out = "\n".join(out_lines).strip()
    return out, {"images": images, "kind": "generic", "beautify_fallback": True}

def process(title: str, raw_text: str, mood: str):
    clean_text, extras = _safe_beautify(title or "", raw_text or "")
    base = clean_text or ""

    use_llm = os.getenv("LLM_ENABLED", "true").lower() == "true"
    if use_llm and base.strip():
        try:
            out = llm_rewrite(
                text=base,
                mood=mood or os.getenv("personality_mood", "serious"),
                timeout=int(os.getenv("llm_timeout_seconds", "8")),
                cpu_limit=int(os.getenv("llm_max_cpu_percent", "70")),
            )
            out = _cap(_polish(out or ""))
            if out and _same_facts(base, out):
                return out, extras
        except Exception:
            pass

    return _cap(_polish(base)), extras
