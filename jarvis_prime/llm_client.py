#!/usr/bin/env python3
# /app/llm_client.py
from __future__ import annotations
import os, re, json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
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

# ---------------- Config ----------------
def _int_env(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)).strip())
    except Exception: return default

def _float_env(name: str, default: float) -> float:
    try: return float(os.getenv(name, str(default)).strip())
    except Exception: return default

CTX         = _int_env("LLM_CTX_TOKENS", 4096)
GEN_TOKENS  = _int_env("LLM_GEN_TOKENS", 180)
MAX_LINES   = _int_env("LLM_MAX_LINES", 10)
TEMP        = _float_env("LLM_TEMPERATURE", 0.4)
TOP_P       = _float_env("LLM_TOP_P", 0.85)
REPEAT_P    = _float_env("LLM_REPEAT_PENALTY", 1.2)

SEARCH_ROOTS = [Path("/share/jarvis_prime"), Path("/share/jarvis_prime/models"), Path("/share")]
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()
MODEL_PREF = [s for s in os.getenv("LLM_MODEL_PREFERENCE", "phi,qwen,tinyllama").lower().split(",") if s]

_loaded_model = None
_model_path: Optional[Path] = None

# ---------------- Model loading utils ----------------
def _list_local_models() -> list[Path]:
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out.extend(root.rglob("*.gguf"))
    seen, uniq = set(), []
    for p in sorted(out):
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq

def _choose_preferred(paths: list[Path]) -> Optional[Path]:
    if not paths: return None
    def score(p: Path):
        name = p.name.lower()
        fam = min([i for i,f in enumerate(MODEL_PREF) if f and f in name] + [999])
        bias = 0 if str(p).startswith("/share/jarvis_prime/") else (1 if str(p).startswith("/share/") else 2)
        size = p.stat().st_size if p.exists() else 1 << 60
        return (fam,bias,size)
    return sorted(paths,key=score)[0]

def _first_gguf_under(p: Path) -> Optional[Path]:
    try:
        if p.is_file() and p.suffix.lower()==".gguf": return p
        if p.is_dir():
            cands = list(p.rglob("*.gguf"))
            if cands: return _choose_preferred(cands)
    except: pass
    return None

def _resolve_model_path() -> Optional[Path]:
    env_model_path = os.getenv("LLM_MODEL_PATH","").strip()
    if env_model_path:
        f = _first_gguf_under(Path(env_model_path))
        if f: return f
    best = _choose_preferred(_list_local_models())
    if best: return best
    urls = []
    raw = os.getenv("LLM_MODEL_URLS","").strip()
    if raw: urls.extend(raw.split(","))
    one = os.getenv("LLM_MODEL_URL","").strip()
    if one: urls.append(one)
    for u in [u for u in urls if u]:
        name = u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"): name += ".gguf"
        dest = Path("/share/jarvis_prime/models")/name
        if dest.exists(): return dest
        if requests:
            try:
                dest.parent.mkdir(parents=True,exist_ok=True)
                tmp = dest.with_suffix(".part")
                with requests.get(u,stream=True,timeout=60) as r:
                    r.raise_for_status()
                    with open(tmp,"wb") as f:
                        for chunk in r.iter_content(1<<20):
                            if chunk: f.write(chunk)
                tmp.replace(dest)
                return dest
            except Exception as e:
                print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
    return None

def _resolve_any_path(model_path: Optional[str], model_url: Optional[str]) -> Optional[Path]:
    if model_path:
        f = _first_gguf_under(Path(model_path))
        if f: return f
    if _model_path and Path(_model_path).exists():
        return _first_gguf_under(Path(_model_path)) or Path(_model_path)
    return _resolve_model_path()

def _cpu_threads_for_limit(limit_pct:int)->int:
    cores = max(1,os.cpu_count() or 1)
    limit = max(1,min(100,limit_pct or 100))
    return max(1,int(round(cores*(limit/100.0))))

def _load_local_model(path: Path):
    global _loaded_model
    if _loaded_model is not None: return _loaded_model
    if AutoModelForCausalLM is None: return None
    if path.is_dir():
        gg = _first_gguf_under(path)
        if gg: path = gg
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path), model_type="llama",
            context_length=CTX, gpu_layers=int(os.getenv("LLM_GPU_LAYERS","0"))
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

# ---------------- Cleaning helpers ----------------
def _strip_reasoning(text: str) -> str:
    bad = ("input:","output:","explanation:","reasoning:","analysis:","system:")
    return "\n".join([ln for ln in (text or "").splitlines()
                      if ln.strip() and not any(ln.strip().lower().startswith(b) for b in bad)])

def _strip_meta_lines(text: str) -> str:
    BAD = ("persona","rules","instruction","guideline","jarvis","system prompt",
           "style hint","lines:","context:","you are")
    return "\n".join([ln for ln in (text or "").splitlines()
                      if ln.strip() and not any(b in ln.lower() for b in BAD)])

def _cleanup_quip_block(text: str, max_lines:int)->List[str]:
    s = _strip_reasoning(text); s = _strip_meta_lines(s)
    lines=[re.sub(r'^\s*[-•\d\)\.]+\s*','',ln.strip()) for ln in s.splitlines() if ln.strip()]
    out,seen=[],set()
    for ln in lines:
        if len(ln.split())>20: ln=" ".join(ln.split()[:20])
        if ln.lower() not in seen:
            seen.add(ln.lower()); out.append(ln)
        if len(out)>=max_lines: break
    return out

# ---------------- Rewrite (normal beautify path) ----------------
def rewrite(text:str,mood:str="serious",timeout:int=8,cpu_limit:int=70,
            models_priority:Optional[List[str]]=None,base_url:Optional[str]=None,
            model_url:Optional[str]=None,model_path:Optional[str]=None,
            model_sha256:Optional[str]=None,allow_profanity:bool=False)->str:
    src=(text or "").strip()
    if not src: return src
    system=f"YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."
    prompt=f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
    stop=["[SYSTEM]","[INPUT]","[OUTPUT]","Persona:","Rules:"]

    # ---- Ollama ----
    base=(base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload={"model":(models_priority[0] if models_priority else "llama3.1"),
                     "prompt":prompt,"stream":False,
                     "options":{"temperature":TEMP,"top_p":TOP_P,"repeat_penalty":REPEAT_P,
                                "num_ctx":CTX,"num_predict":GEN_TOKENS,"stop":stop}}
            r=requests.post(base.rstrip("/")+"/api/generate",json=payload,timeout=timeout)
            if r.ok: return _strip_meta_lines(r.json().get("response",""))
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Ollama rewrite failed: {e}",flush=True)

    # ---- Local ----
    p=_resolve_any_path(model_path,model_url)
    if p and p.exists():
        m=_load_local_model(p)
        if m:
            threads=_cpu_threads_for_limit(cpu_limit)
            def _gen(): return m(prompt,max_new_tokens=GEN_TOKENS,temperature=TEMP,top_p=TOP_P,
                                 repetition_penalty=REPEAT_P,stop=stop,threads=threads)
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut=ex.submit(_gen)
                try: return _strip_meta_lines(str(fut.result(timeout=timeout)))
                except TimeoutError: print(f"[{BOT_NAME}] ⚠️ Rewrite timed out",flush=True)
                except Exception as e: print(f"[{BOT_NAME}] ⚠️ Rewrite failed: {e}",flush=True)
    return src

# ---------------- Persona riffs ----------------
def persona_riff(persona:str,context:str,max_lines:int=3,timeout:int=6,
                 cpu_limit:int=70,models_priority:Optional[List[str]]=None,
                 base_url:Optional[str]=None,model_url:Optional[str]=None,
                 model_path:Optional[str]=None)->List[str]:
    persona=(persona or "jarvis").strip(); ctx=(context or "").strip()
    if not ctx: return []
    instruction=f"As {persona}, write {max_lines} witty one-liners about: \"{ctx}\""
    stop_tokens=["Context:","Lines:","Rules:","Persona:","YOU ARE","[SYSTEM]","[INPUT]","[OUTPUT]"]

    # ---- Ollama ----
    base=(base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload={"model":(models_priority[0] if models_priority else "llama3.1"),
                     "prompt":instruction+"\n\nOne-liners:\n","stream":False,
                     "options":{"temperature":TEMP,"top_p":TOP_P,"repeat_penalty":REPEAT_P,
                                "num_ctx":CTX,"num_predict":max(80,GEN_TOKENS//2),
                                "stop":stop_tokens}}
            r=requests.post(base.rstrip("/")+"/api/generate",json=payload,timeout=timeout)
            if r.ok: return _cleanup_quip_block(r.json().get("response",""),max_lines)
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Ollama riff failed: {e}",flush=True)

    # ---- Local ----
    p=_resolve_any_path(model_path,model_url)
    if p and p.exists():
        m=_load_local_model(p)
        if m:
            prompt=f"{instruction}\n\nOne-liners:\n"; threads=_cpu_threads_for_limit(cpu_limit)
            def _gen(): return m(prompt,max_new_tokens=max(80,GEN_TOKENS//2),
                                 temperature=TEMP,top_p=TOP_P,repetition_penalty=REPEAT_P,
                                 stop=stop_tokens,threads=threads)
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut=ex.submit(_gen)
                try: return _cleanup_quip_block(str(fut.result(timeout=timeout)),max_lines)
                except TimeoutError: print(f"[{BOT_NAME}] ⚠️ Riff timed out",flush=True)
                except Exception as e: print(f"[{BOT_NAME}] ⚠️ Riff failed: {e}",flush=True)
    return []

llm_quips = persona_riff

# ---------------- Engine status ----------------
def engine_status()->Dict[str,object]:
    base=(OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            r=requests.get(base.rstrip("/")+"/api/version",timeout=3)
            return {"ready":bool(r.ok),"model_path":"","backend":"ollama"}
        except: return {"ready":False,"model_path":"","backend":"ollama"}
    p=_resolve_any_path(os.getenv("LLM_MODEL_PATH",""),os.getenv("LLM_MODEL_URL",""))
    return {"ready":bool(p and Path(p).exists()),"model_path":str(p or ""),
            "backend":"ctransformers" if p else "none"}