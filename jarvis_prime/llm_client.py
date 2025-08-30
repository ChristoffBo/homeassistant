#!/usr/bin/env python3
# Formatter-only LLM client for Jarvis Prime (ALWAYS-FIRES + ZERO-LOSS)
# Purpose: First pass of beautification. Read incoming text and NEATEN ONLY.
# No persona, no summaries, no added words. KEEP ALL INFORMATION EXACT.
# Preserves numbers/units/keywords; if the LLM loses anything → fallback to normalized original.
# Works with Ollama or local ctransformers (.gguf). If neither is available → normalized original.
# Optional debug: export LLM_DEBUG=1 to see decisions in logs.
from __future__ import annotations

import os, re
from pathlib import Path
from typing import Optional, List, Dict

def _dbg(msg: str) -> None:
    if os.getenv("LLM_DEBUG", "0") == "1":
        print(f"[LLM/formatter] {msg}", flush=True)

# Optional deps
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

# Decoding knobs (deterministic, conservative)
TEMP = float(os.getenv("LLM_TEMPERATURE", "0.05"))
TOP_P = float(os.getenv("LLM_TOP_P", "0.8"))
REPEAT_P = float(os.getenv("LLM_REPEAT_PENALTY", "1.4"))

# Search roots for local models
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
    # search local
    best=_choose_preferred(_list_local_models())
    if best: return best
    # download if URL(s) provided
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
            _model_path=p; _dbg(f"prefetch_model(explicit) -> {p}"); return
    _model_path=_resolve_model_path()
    _dbg(f"prefetch_model(auto) -> {_model_path}")

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

# -------- Conservative helpers (preserve all info) --------

def _normalize_conservative(text: str) -> str:
    # Conservative cleanup that keeps all tokens (no info loss).
    if not text:
        return text
    CODE_RE = re.compile(r"```.*?```", re.S)
    blocks = []
    def _hold(m):
        blocks.append(m.group(0))
        return f"@@CODEBLOCK{len(blocks)-1}@@"
    s = CODE_RE.sub(_hold, text)

    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join([ln.rstrip() for ln in s.split("\n")])
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"([,:;.!?])(?=\S)", r"\1 ", s)

    for i,blk in enumerate(blocks):
        s = s.replace(f"@@CODEBLOCK{i}@@", blk, 1)
    return s

# --- Loss guard helpers ---
NUM_RE = re.compile(r'[-+]?\d+(?:\.\d+)?')

def _numbers_in(text: str) -> List[str]:
    return NUM_RE.findall(text or "" )

def _looks_structured_metrics(text: str) -> bool:
    # Detect classic Key: value lines; used only for strictness checks, not to skip LLM.
    return bool(re.search(r"(?mi)^[A-Za-z][A-Za-z0-9 _-]+:\s+.+$", text or ""))

def _loss_detected(original: str, candidate: str) -> bool:
    # True if any number from original is missing OR if headers disappeared for structured metrics.
    orig_nums = _numbers_in(original)
    cand = candidate or ""
    for n in orig_nums:
        if n and n not in cand:
            return True
    if _looks_structured_metrics(original):
        orig_keys = set([m.group(1).strip().lower() for m in re.finditer(r"(?mi)^([A-Za-z][A-Za-z0-9 _-]+):", original or "")])
        cand_low = (candidate or "").lower()
        for k in orig_keys:
            if k and (k + ":") not in cand_low:
                return True
    return False

# -------- LLM loading --------

def _first_gguf_under(p: Path) -> Optional[Path]:
    try:
        if p.is_file() and p.suffix.lower() == ".gguf":
            return p
        if p.is_dir():
            cands = sorted(list(p.rglob("*.gguf")),
                           key=lambda x: (0 if str(x).startswith("/share/jarvis_prime/models")
                                          else (1 if str(x).startswith("/share/jarvis_prime") else 2),
                                          x.stat().st_size if x.exists() else 1<<60))
            return cands[0] if cands else None
    except Exception:
        pass
    return None

def _resolve_any_path(model_path: Optional[str], model_url: Optional[str]) -> Optional[Path]:
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f:
            return f
    if _model_path and Path(_model_path).exists():
        mp = Path(_model_path)
        return _first_gguf_under(mp) or mp
    return _resolve_model_path()

def _load_local_model(path: Path):
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model
    if AutoModelForCausalLM is None:
        return None
    if path.is_dir():
        gg = _first_gguf_under(path)
        if gg:
            path = gg
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS", "0")),
            context_length=CTX,
        )
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

# -------- Formatter-only prompt (neutral & strict) --------

FORMATTER_SYSTEM_PROMPT = (
    "You are a formatter. Rewrite the text to be clean and readable.\n"
    "CRITICAL RULES:\n"
    " - Do NOT add or remove ANY information.\n"
    " - Do NOT paraphrase or summarize.\n"
    " - Preserve ALL numbers and units exactly.\n"
    " - Preserve line breaks, URLs, code, emojis, and markdown.\n"
    " - Return ONLY the rewritten text, with minimal punctuation fixes."
)

# -------- Public API --------

def rewrite(text: str, mood: str="serious", timeout: int=8, cpu_limit: int=70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str]=None,
            model_url: Optional[str]=None, model_path: Optional[str]=None,
            model_sha256: Optional[str]=None, allow_profanity: bool=False) -> str:
    # Read inbound text and NEATEN ONLY while keeping ALL information.
    # LLM ALWAYS fires when available; if its output loses content, we fall back to normalized original.
    src = (text or "").strip()
    if not src:
        _dbg("skip: empty input")
        return src

    # 0) Precompute normalized original (used for fallback)
    normalized_src = _normalize_conservative(src)

    # 1) Decide if we have an engine
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    have_ollama = bool(base and requests)
    local_path = _resolve_any_path(model_path, model_url)
    have_ctrans = bool(local_path and AutoModelForCausalLM is not None)

    if not have_ollama and not have_ctrans:
        _dbg("no engine available → return normalized original")
        return normalized_src

    # 2) Keep within context; if too long, we still DO NOT drop info — fall back
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * CHARS_PER_TOKEN)
    if len(src) > max(500, budget_chars - len(FORMATTER_SYSTEM_PROMPT)):
        _dbg("input exceeds safe context → return normalized original")
        return normalized_src

    # 3) Try Ollama first
    if have_ollama:
        try:
            payload = {
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": FORMATTER_SYSTEM_PROMPT + "\n\n" + src,
                "stream": False,
                "options": {
                    "temperature": TEMP, "top_p": TOP_P, "repeat_penalty": REPEAT_P,
                    "num_ctx": CTX, "num_predict": GEN_TOKENS
                }
            }
            r = requests.post(base.rstrip("/") + "/api/generate", json=payload, timeout=timeout)
            if r.ok:
                out = str(r.json().get("response",""))
                if _loss_detected(src, out):
                    _dbg("ollama produced loss → fallback to normalized original")
                    return normalized_src
                _dbg("ollama ok")
                return _normalize_conservative(out)
            else:
                _dbg(f"ollama HTTP {r.status_code}")
        except Exception as e:
            _dbg(f"ollama exception: {e}")

    # 4) Try local ctransformers
    if have_ctrans and local_path and Path(local_path).exists():
        m = _load_local_model(local_path)
        if m is not None:
            prompt = f"{FORMATTER_SYSTEM_PROMPT}\n\n{src}"
            try:
                out = m(prompt, max_new_tokens=GEN_TOKENS, temperature=TEMP,
                        top_p=TOP_P, repetition_penalty=REPEAT_P)
                out_s = str(out or "")
                if _loss_detected(src, out_s):
                    _dbg("ctransformers produced loss → fallback to normalized original")
                    return normalized_src
                _dbg("ctransformers ok")
                return _normalize_conservative(out_s)
            except Exception as e:
                _dbg(f"ctransformers exception: {e}")

    # 5) No usable result → normalized original
    _dbg("no usable result → normalized original")
    return normalized_src

if __name__ == "__main__":
    sample = "A speedtest is finished:\nPing: 48 ms\nUpload: 119.40 Mbps\nDownload: 672.17 Mbps"
    print(rewrite(sample))
