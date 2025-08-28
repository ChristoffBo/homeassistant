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
# Context tokens (prompt + system + history + generation headroom)
# Override via env/option: LLM_CTX_TOKENS=2048|4096
CTX = int(os.getenv("LLM_CTX_TOKENS", "4096"))
# How many tokens we intend to generate; used to keep space in the window
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "180"))
# Character budget approximation when we trim prompts to fit context.
# (roughly 4 chars/token; conservative to avoid edge cases)
CHARS_PER_TOKEN = 4
SAFETY_TOKENS = 32  # extra headroom in window

# =================== Model discovery ===================
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

def _download_to(url: str, dest: Path) -> bool:
    if not requests: return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1<<20):
                    if chunk: f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
        return False

def _resolve_model_path() -> Optional[Path]:
    # explicit path
    if str(MODEL_PATH):
        p=Path(MODEL_PATH)
        if p.is_file() and p.suffix.lower()==".gguf": return p
        if p.is_dir():
            best=_choose_preferred(list(p.rglob("*.gguf")))
            if best: return best
    # local discovery
    best=_choose_preferred(_list_local_models())
    if best: return best
    # download
    urls = MODEL_URLS or ([MODEL_URL] if MODEL_URL else [])
    for u in urls:
        name=u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"): name += ".gguf"
        dest=Path("/share/jarvis_prime/models")/name
        if dest.exists(): return dest
        if _download_to(u, dest): return dest
    return None

def prefetch_model(model_path: Optional[str]=None, model_url: Optional[str]=None)->None:
    global _model_path
    if model_path:
        p=Path(model_path)
        if p.is_file():
            _model_path=p; return
    _model_path=_resolve_model_path()

def engine_status() -> Dict[str,object]:
    base=OLLAMA_BASE_URL.strip()
    if base and requests:
        try:
            r=requests.get(base.rstrip("/")+"/api/version",timeout=3)
            ok=r.ok
        except Exception:
            ok=False
        return {"ready": bool(ok), "model_path":"", "backend":"ollama"}
    p=_model_path or _resolve_model_path()
    return {"ready": bool(p and p.exists()), "model_path": str(p or ""), "backend": "ctransformers" if p else "none"}

def _load_local_model(path: Path):
    global _loaded_model
    if _loaded_model is not None: return _loaded_model
    if AutoModelForCausalLM is None: return None
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS","0")),
            context_length=CTX,            # 🔥 raise context window
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

# =================== Sanitizers & helpers ===================
IMG_MD_RE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)

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

def _squelch_repeats(text: str) -> str:
    """Collapse obvious word/bigram repetition (e.g., '60 up 60 up 60 up …')."""
    parts = text.split()
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

def _cap(text: str, max_lines: int = int(os.getenv("LLM_MAX_LINES","10")), max_chars: int = 800) -> str:
    lines=[ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines)>max_lines: lines=lines[:max_lines]
    out="\n".join(lines)
    if len(out)>max_chars: out=out[:max_chars].rstrip()
    return out

def _load_system_prompt() -> str:
    # 1) env var
    sp = os.getenv("LLM_SYSTEM_PROMPT")
    if sp: return sp
    # 2) host-shared file
    p = Path("/share/jarvis_prime/memory/system_prompt.txt")
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            pass
    # 3) built-in file in image (copied by Dockerfile)
    p2 = Path("/app/memory/system_prompt.txt")
    if p2.exists():
        try:
            return p2.read_text(encoding="utf-8")
        except Exception:
            pass
    # 4) fallback default
    return (
        "YOU ARE JARVIS PRIME — HOMELAB OPERATOR’S AIDE.\n"
        "PRIME DIRECTIVES — OBEY EXACTLY:\n"
        "1) READ the incoming text carefully.\n"
        "2) SAY what it means in plain, concise English. Explain, don’t embellish.\n"
        "3) KEEP every fact/number/URL/IP/hostname/service name EXACTLY as given. No new facts.\n"
        "4) OUTPUT up to 10 short lines, paragraph style. No lists unless input already has bullets.\n"
        "5) NO meta (Input/Output/Explanation), NO 'Note:', NO placeholders like [YOURNAME]/[FEATURE].\n"
        "6) If something is missing, say 'unknown' or 'not specified'; do not guess.\n"
        "7) PERSONALITY = {mood}. Angry → blunt, sardonic (no slurs). Playful → cheeky. Serious → crisp.\n"
        "8) Keep any images/markdown image links exactly as-is.\n"
    )

def _trim_to_ctx(src: str, system: str) -> str:
    """
    Roughly trim INPUT text so (system + INPUT + headroom) fits into CTX tokens.
    We approximate with chars-per-token and leave GEN_TOKENS + SAFETY_TOKENS free.
    """
    if not src: return src
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * CHARS_PER_TOKEN)
    system_chars = len(system)
    # keep part of the budget for system text too
    remaining = max(500, budget_chars - system_chars)
    if len(src) <= remaining:
        return src
    # Keep the tail (most recent content) which is usually most relevant
    return src[-remaining:]

# =================== Rewrite ===================
def rewrite(text: str, mood: str="serious", timeout: int=8, cpu_limit: int=70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str]=None,
            model_url: Optional[str]=None, model_path: Optional[str]=None,
            model_sha256: Optional[str]=None, allow_profanity: bool=False) -> str:
    src=(text or "").strip()
    if not src: return src

    imgs=_extract_images(src)
    system=_load_system_prompt().format(mood=mood)
    src=_trim_to_ctx(src, system)

    # 1) Ollama
    base=(base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload={
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": system + "\n\nINPUT:\n" + src + "\n\nOUTPUT:\n",
                "stream": False,
                "options": {"temperature": 0.15, "top_p": 0.9, "repeat_penalty": 1.3,
                            "num_ctx": CTX, "num_predict": GEN_TOKENS}
            }
            r=requests.post(base.rstrip("/")+"/api/generate", json=payload, timeout=timeout)
            if r.ok:
                out=_strip_reasoning(str(r.json().get("response","")))
                out=_squelch_repeats(out)
                out=_cap(out)
                return out + ("\n"+imgs if imgs else "")
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama call failed: {e}", flush=True)

    # 2) Local (ctransformers)
    p = Path(model_path) if model_path else (_model_path or _resolve_model_path())
    if p and p.exists():
        m=_load_local_model(p)
        if m is not None:
            prompt=f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
            try:
                out=m(prompt, max_new_tokens=GEN_TOKENS, temperature=0.15,
                       top_p=0.9, repetition_penalty=1.3)
                out=_strip_reasoning(str(out or ""))
                out=_squelch_repeats(out)
                out=_cap(out)
                return out + ("\n"+imgs if imgs else "")
            except Exception as e:
                print(f"[{BOT_NAME}] ⚠️ Generation failed: {e}", flush=True)

    # 3) Fallback
    out=_cap(_squelch_repeats(_strip_reasoning(src)))
    return out + ("\n"+imgs if imgs else "")
