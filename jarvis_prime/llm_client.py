#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations

import os, re, json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Optional, List, Dict

# ---------- Optional backends ----------
try:
    from ctransformers import AutoModelForCausalLM
except Exception:
    AutoModelForCausalLM = None  # type: ignore

try:
    import requests
except Exception:
    requests = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# ---------- Env helpers ----------
def _int_env(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)).strip())
    except Exception: return default

def _float_env(name: str, default: float) -> float:
    try: return float(os.getenv(name, str(default)).strip())
    except Exception: return default

# ---------- Decoding & limits ----------
CTX             = _int_env("LLM_CTX_TOKENS", 4096)
GEN_TOKENS      = _int_env("LLM_GEN_TOKENS", 180)
MAX_LINES       = _int_env("LLM_MAX_LINES", 10)
CHARS_PER_TOKEN = 4
SAFETY_TOKENS   = 48

TEMP     = _float_env("LLM_TEMPERATURE", 0.15)
TOP_P    = _float_env("LLM_TOP_P", 0.85)
REPEAT_P = _float_env("LLM_REPEAT_PENALTY", 1.45)

# ---------- Model discovery ----------
SEARCH_ROOTS = [Path("/share/jarvis_prime/models"), Path("/share/jarvis_prime"), Path("/share")]
OLLAMA_BASE_URL = os.getenv("LLM_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "")).strip()
MODEL_PREF = [s for s in os.getenv("LLM_MODEL_PREFERENCE", "phi,qwen,tinyllama,llama").lower().split(",") if s]

_loaded_model = None
_model_path: Optional[Path] = None

# ---------- FS helpers ----------
def _list_local_models() -> List[Path]:
    out: List[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out.extend(root.rglob("*.gguf"))
    uniq, seen = [], set()
    for p in sorted(out):
        s = str(p)
        if s not in seen: seen.add(s); uniq.append(p)
    return uniq

def _choose_preferred(paths: List[Path]) -> Optional[Path]:
    if not paths: return None
    def score(p: Path):
        name = p.name.lower()
        fam = min([i for i, f in enumerate(MODEL_PREF) if f and f in name] + [999])
        bias = 0 if str(p).startswith("/share/jarvis_prime/") else (1 if str(p).startswith("/share/") else 2)
        size = p.stat().st_size if p.exists() else 1 << 60
        return (fam, bias, size)
    return sorted(paths, key=score)[0]

def _first_gguf_under(p: Path) -> Optional[Path]:
    try:
        if p.is_file() and p.suffix.lower() == ".gguf": return p
        if p.is_dir():
            cands = list(p.rglob("*.gguf"))
            if cands: return _choose_preferred(cands)
    except Exception: pass
    return None

def _download_to(url: str, dest: Path) -> bool:
    if not requests: return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if chunk: f.write(chunk)
        tmp.replace(dest); return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
        return False

def _resolve_model_path() -> Optional[Path]:
    env_model_path = os.getenv("LLM_MODEL_PATH", "").strip()
    if env_model_path:
        p = Path(env_model_path); f = _first_gguf_under(p)
        if f: return f
    best = _choose_preferred(_list_local_models())
    if best: return best
    urls_raw = os.getenv("LLM_MODEL_URLS", "").strip()
    url_one  = os.getenv("LLM_MODEL_URL", "").strip()
    urls = [u for u in (urls_raw.split(",") if urls_raw else []) + ([url_one] if url_one else []) if u]
    for u in urls:
        name = u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"): name += ".gguf"
        dest = Path("/share/jarvis_prime/models") / name
        if dest.exists(): return dest
        if _download_to(u, dest): return dest
    return None

def prefetch_model(model_path: Optional[str] = None, model_url: Optional[str] = None) -> None:
    global _model_path
    if model_path:
        p = Path(model_path); f = _first_gguf_under(p)
        if f: _model_path = f; return
    _model_path = _resolve_model_path()

def _resolve_any_path(model_path: Optional[str], model_url: Optional[str]) -> Optional[Path]:
    if model_path:
        p = Path(model_path); f = _first_gguf_under(p)
        if f: return f
    if _model_path and Path(_model_path).exists():
        return _first_gguf_under(Path(_model_path)) or Path(_model_path)
    return _resolve_model_path()

def _cpu_threads_for_limit(limit_pct: int) -> int:
    cores = max(1, os.cpu_count() or 1)
    limit = max(1, min(100, int(limit_pct or 100)))
    return max(1, int(round(cores * (limit / 100.0))))

def _load_local_model(path: Path):
    global _loaded_model
    if _loaded_model is not None: return _loaded_model
    if AutoModelForCausalLM is None: return None
    if path.is_dir():
        gg = _first_gguf_under(path)
        if gg: path = gg
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",
            context_length=CTX,
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS", "0")),
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

# ---------- Cleaning helpers ----------
IMG_MD_RE       = re.compile(r'![^]*\][^)]+')
IMG_URL_RE      = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)
PLACEHOLDER_RE  = re.compile(r'([A-Z][A-Z0-9 _:/\-\.,]{2,})')

UPSELL_RE = re.compile(r'(?i)\b(please review|confirm|support team|contact .*@|let us know|thank you|stay in touch|new feature|check out)\b')

def _extract_images(src: str) -> str:
    imgs = IMG_MD_RE.findall(src or "") + IMG_URL_RE.findall(src or "")
    out, seen = [], set()
    for i in imgs:
        if i not in seen: seen.add(i); out.append(i)
    return "\n".join(out)

def _strip_reasoning(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        t = ln.strip(); 
        if not t: continue
        tl = t.lower()
        if tl.startswith(("input:", "output:", "explanation:", "reasoning:", "analysis:", "system:")): continue
        if t in ("[SYSTEM]", "[INPUT]", "[OUTPUT]") or t.startswith(("[SYSTEM]", "[INPUT]", "[OUTPUT]")): continue
        if t.startswith("[") and t.endswith("]") and len(t) < 40: continue
        if tl.startswith("note:"): continue
        lines.append(t)
    return "\n".join(lines)

def _strip_meta_lines(text: str) -> str:
    BAD = ("persona","rules","rule:","instruction","instruct","guideline",
           "you are jarvis","jarvis prime","system prompt","style hint",
           "speak as","lines:","produce at most","respond with at most",
           "do not","no labels","no meta")
    out = []
    for ln in (text or "").splitlines():
        t = ln.strip(); 
        if not t: continue
        if any(b in t.lower() for b in BAD): continue
        out.append(t)
    return "\n".join(out)

def _remove_placeholders(text: str) -> str:
    s = PLACEHOLDER_RE.sub("", text or "")
    return re.sub(r"\s{2,}", " ", s).strip()

def _drop_boilerplate(text: str) -> str:
    kept = []
    for ln in (text or "").splitlines():
        if not ln.strip(): continue
        if UPSELL_RE.search(ln): continue
        kept.append(ln.strip())
    return "\n".join(kept)

def _squelch_repeats(text: str) -> str:
    parts = (text or "").split()
    out, prev, count = [], None, 0
    for w in parts:
        wl = w.lower()
        if wl == prev:
            count += 1
            if count <= 2: out.append(w)
        else:
            prev, count = wl, 1; out.append(w)
    s2 = " ".join(out)
    return re.sub(r"(\b\w+\s+\w+)(?:\s+\1){2,}", r"\1 \1", s2, flags=re.I)

def _polish(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"[ \t]+"," ",s)
    s = re.sub(r"[ \t]*\n[ \t]*","\n",s)
    s = re.sub(r"([,:;.!?])(?=\S)",r"\1 ",s)
    s = re.sub(r"\s*…+\s*", ". ", s)
    s = re.sub(r"\s+([,:;.!?])", r"\1", s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    fixed = [(ln if re.search(r"[.!?]$", ln) else ln+".") for ln in lines]
    s = "\n".join(fixed)
    seen, out = set(), []
    for ln in s.splitlines():
        if ln.lower() in seen: continue
        seen.add(ln.lower()); out.append(ln)
    return "\n".join(out)

def _cap(text: str, max_lines: int = MAX_LINES, max_chars: int = 800) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > max_lines: lines = lines[:max_lines]
    out = "\n".join(lines)
    return out if len(out) <= max_chars else out[:max_chars].rstrip()

def _finalize(text: str, imgs: str) -> str:
    out = _strip_reasoning(text)
    out = _strip_meta_lines(out)
    out = _remove_placeholders(out)
    out = _drop_boilerplate(out)
    out = _squelch_repeats(out)
    out = _polish(out)
    out = _cap(out, MAX_LINES)
    return out + ("\n"+imgs if imgs else "")

# ---------- PUBLIC: rewrite ----------
def rewrite(text: str, mood: str="serious", timeout: int=8, cpu_limit: int=70,
            models_priority: Optional[List[str]]=None, base_url: Optional[str]=None,
            model_url: Optional[str]=None, model_path: Optional[str]=None,
            allow_profanity: bool=False) -> str:
    src = (text or "").strip()
    if not src: return src
    imgs   = _extract_images(src)
    system = f"YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."
    src    = _trim_to_ctx(src, system)

    # 1) Ollama
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload = {"model": (models_priority[0] if models_priority else "llama3.1"),
                       "prompt": system+"\n\nINPUT:\n"+src+"\n\nOUTPUT:\n",
                       "stream": False,
                       "options": {"temperature": TEMP,"top_p": TOP_P,"repeat_penalty": REPEAT_P,
                                   "num_ctx": CTX,"num_predict": GEN_TOKENS,
                                   "stop": ["[SYSTEM]","[INPUT]","[OUTPUT]","Persona:","Rules:"]}}
            r = requests.post(base.rstrip("/")+"/api/generate", json=payload, timeout=timeout)
            if r.ok: return _finalize(str(r.json().get("response","")), imgs)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama call failed: {e}", flush=True)

    # 2) Local
    p = _resolve_any_path(model_path, model_url)
    if p and p.exists():
        m = _load_local_model(p)
        if m:
            prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
            threads = _cpu_threads_for_limit(cpu_limit)
            def _gen() -> str:
                return str(m(prompt, max_new_tokens=GEN_TOKENS, temperature=TEMP,
                             top_p=TOP_P, repetition_penalty=REPEAT_P,
                             stop=["[SYSTEM]","[INPUT]","[OUTPUT]","Persona:","Rules:"],
                             threads=threads) or "")
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_gen)
                try: return _finalize(fut.result(timeout=timeout), imgs)
                except TimeoutError: print(f"[{BOT_NAME}] ⚠️ Timeout after {timeout}s", flush=True)
                except Exception as e: print(f"[{BOT_NAME}] ⚠️ Gen failed: {e}", flush=True)

    return _finalize(src, imgs)

# ---------- Persona riff ----------
def _cleanup_quip_block(text: str, max_lines: int) -> List[str]:
    if not text: return []
    s = _strip_reasoning(text); s = _strip_meta_lines(s)
    s = re.sub(r'^\s*[-•\d\)\.]+\s*','',s,flags=re.M)
    parts = []
    for ln in s.splitlines():
        for seg in re.split(r'(?<=[.!?])\s+', ln.strip()):
            if seg: parts.append(seg.strip())
    out, seen = [], set()
    for ln in parts:
        if not ln: continue
        words = ln.split()
        if len(words)>22: ln = " ".join(words[:22])
        if ln.lower() in seen: continue
        seen.add(ln.lower()); out.append(ln)
        if len(out)>=max_lines: break
    return out

def persona_riff(persona: str, context: str, max_lines: int=3, timeout: int=8,
                 cpu_limit: int=70, models_priority: Optional[List[str]]=None,
                 base_url: Optional[str]=None, model_url: Optional[str]=None,
                 model_path: Optional[str]=None) -> List[str]:
    persona = (persona or "ops").strip().lower()
    ctx = (context or "").strip()
    if not ctx: return []

    instruction = (f"You speak as '{persona}'. Produce ONLY {max(1,min(3,int(max_lines or 3)))} short lines. "
                   "Each line < 140 chars. No labels, bullets, numbering, JSON or meta. "
                   "Do NOT summarize facts. Only persona-flavored quips.")

    # 1) Ollama
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload = {"model": (models_priority[0] if models_priority else "llama3.1"),
                       "prompt": instruction+"\n\nContext (vibe only):\n"+ctx+"\n\nQuips:\n",
                       "stream": False,
                       "options": {"temperature": TEMP,"top_p": TOP_P,"repeat_penalty": REPEAT_P,
                                   "num_ctx": CTX,"num_predict": max(64,min(220,GEN_TOKENS//2+64)),
                                   "stop": ["Quips:","Rules:","Persona:","Context:","[SYSTEM]","[INPUT]","[OUTPUT]"]}}
            r = requests.post(base.rstrip("/")+"/api/generate", json=payload, timeout=timeout)
            if r.ok: return _cleanup_quip_block(str(r.json().get("response","")), max_lines)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama riff failed: {e}", flush=True)

    # 2) Local
    p = _resolve_any_path(model_path, model_url)
    if p and p.exists():
        m = _load_local_model(p)
        if m:
            prompt = f"{instruction}\n\nContext (vibe only):\n{ctx}\n\nQuips:\n"
            threads = _cpu_threads_for_limit(cpu_limit)
            def _gen() -> str:
                return str(m(prompt,max_new_tokens=max(64,min(220,GEN_TOKENS//2+64)),
                             temperature=TEMP,top_p=TOP_P,repetition_penalty=REPEAT_P,
                             stop=["Quips:","Rules:","Persona: