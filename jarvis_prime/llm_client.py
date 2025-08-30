#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, List, Dict

try:
    from ctransformers import AutoModelForCausalLM
except Exception:
    AutoModelForCausalLM = None  # type: ignore

try:
    import requests
except Exception:
    requests = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# =================== Config knobs ===================
CTX = int(os.getenv("LLM_CTX_TOKENS", "4096"))
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "180"))
CHARS_PER_TOKEN = 4
SAFETY_TOKENS = 32

TEMP = float(os.getenv("LLM_TEMPERATURE", "0.05"))
TOP_P = float(os.getenv("LLM_TOP_P", "0.8"))
REPEAT_P = float(os.getenv("LLM_REPEAT_PENALTY", "1.4"))

SEARCH_ROOTS = [Path("/share/jarvis_prime"), Path("/share/jarvis_prime/models"), Path("/share")]

def _list_local_models() -> list[Path]:
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out += list(root.rglob("*.gguf"))
    seen=set(); uniq=[]
    for p in out:
        s=str(p)
        if s not in seen:
            seen.add(s); uniq.append(p)
    return uniq

def _choose_preferred(paths: list[Path]) -> Optional[Path]:
    if not paths: return None
    pref = (os.getenv("LLM_MODEL_PREFERENCE","phi,qwen,tinyllama").lower()).split(",")
    def score(p: Path):
        name=p.name.lower()
        fam = min([i for i,f in enumerate(pref) if f and f in name] + [999])
        bias = 0 if str(p).startswith("/share/jarvis_prime/") else (1 if str(p).startswith("/share/") else 2)
        size = p.stat().st_size if p.exists() else 1<<60
        return (fam, bias, size)
    return sorted(paths, key=score)[0]

MODEL_PATH  = Path(os.getenv("LLM_MODEL_PATH", ""))
MODEL_URL   = os.getenv("LLM_MODEL_URL","")
MODEL_URLS  = [u.strip() for u in os.getenv("LLM_MODEL_URLS","").split(",") if u.strip()]
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL","")

_loaded_model = None
_model_path: Optional[Path] = None

# === Utils for cleaning ===
IMG_MD_RE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)
PLACEHOLDER_RE = re.compile(r'\[([A-Z][A-Z0-9 _:/\-\.,]{2,})\]')
UPSELL_RE = re.compile(r'(?i)\b(please review|confirm|support team|contact .*@|let us know|thank you|stay in touch|new feature|check out)\b')

def _extract_images(src: str) -> str:
    imgs = IMG_MD_RE.findall(src or '') + IMG_URL_RE.findall(src or '')
    seen=set(); out=[]
    for i in imgs:
        if i not in seen:
            seen.add(i); out.append(i)
    return "\n".join(out)

def _strip_reasoning(text: str) -> str:
    lines=[]
    for ln in (text or "").splitlines():
        t=ln.strip()
        if not t: continue
        tl=t.lower()
        if tl.startswith(("input:","output:","explanation:","reasoning:","analysis:","system:")): continue
        if t in ("[SYSTEM]","[INPUT]","[OUTPUT]") or t.startswith(("[SYSTEM]","[INPUT]","[OUTPUT]")): continue
        if t.startswith("[") and t.endswith("]") and len(t)<40: continue
        if tl.startswith("note:"): continue
        lines.append(t)
    return "\n".join(lines)

def _remove_placeholders(text: str) -> str:
    s = PLACEHOLDER_RE.sub("", text or "")
    s = re.sub(r'\(\s*\)', '', s)
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s

def _drop_boilerplate(text: str) -> str:
    kept=[]
    for ln in (text or "").splitlines():
        if not ln.strip(): continue
        if UPSELL_RE.search(ln): continue
        kept.append(ln.strip())
    return "\n".join(kept)

def _squelch_repeats(text: str) -> str:
    parts = (text or "").split()
    out = []
    prev = None
    count = 0
    for w in parts:
        wl = w.lower()
        if wl == prev:
            count += 1
            if count <= 2:
                out.append(w)
        else:
            prev = wl
            count = 1
            out.append(w)
    s2 = " ".join(out)
    s2 = re.sub(r'(\b\w+\s+\w+)(?:\s+\1){2,}', r'\1 \1', s2, flags=re.I)
    return s2

def _polish(text: str) -> str:
    import re as _re
    s = (text or "").strip()
    s = _re.sub(r'[ \t]+', ' ', s)
    s = _re.sub(r'[ \t]*\n[ \t]*', '\n', s)
    s = _re.sub(r'([,:;.!?])(?=\S)', r'\1 ', s)
    s = _re.sub(r'\s*…+\s*', '. ', s)
    s = _re.sub(r'\s+([,:;.!?])', r'\1', s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    fixed = []
    for ln in lines:
        if not _re.search(r'[.!?]$', ln):
            fixed.append(ln + '.')
        else:
            fixed.append(ln)
    s = "\n".join(fixed)
    seen=set(); out=[]
    for ln in s.splitlines():
        key = ln.lower()
        if key in seen: 
            continue
        seen.add(key); out.append(ln)
    return "\n".join(out)

def _cap(text: str, max_lines: int = int(os.getenv("LLM_MAX_LINES","10")), max_chars: int = 800) -> str:
    lines=[ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines)>max_lines: lines=lines[:max_lines]
    out="\n".join(lines)
    if len(out)>max_chars: out=out[:max_chars].rstrip()
    return out

def _finalize(text: str, imgs: str) -> str:
    out = _strip_reasoning(text)
    out = _remove_placeholders(out)
    out = _drop_boilerplate(out)
    out = _squelch_repeats(out)
    out = _polish(out)
    out = _cap(out)
    return out + ("\n"+imgs if imgs else "")

# =================== Formatter-only LLM ===================

def rewrite(text: str, **kwargs) -> str:
    """Strict formatter: clean, concise, remove nothing, no personality"""
    src = (text or "").strip()
    if not src:
        return src
    imgs = _extract_images(src)
    return _finalize(src, imgs)

# =================== Status ===================

def engine_status() -> Dict[str,object]:
    p=_model_path or _resolve_model_path()
    return {"ready": bool(p and Path(p).exists()), "model_path": str(p or ""), "backend": "ctransformers" if p else "none"}
