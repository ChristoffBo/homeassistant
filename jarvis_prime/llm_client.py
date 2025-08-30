#!/usr/bin/env python3
# Formatter-only LLM client for Jarvis Prime (STRICT NO-LOSS)
# - Purpose: read incoming text and NEATEN ONLY. Keep ALL information. Remove NOTHING.
# - Persona/styling handled later by Beautifier/Personas. No emojis, no quips, no added words.
# - Preserves links, code blocks, emojis, markdown, numbers/units, and line breaks.
# - If LLM output loses numbers/keywords, FALL BACK to original (normalized).
#
from __future__ import annotations

import os, re
from pathlib import Path
from typing import Optional, List, Dict

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

# -------- Conservative helpers (preserve all info) --------

IMG_MD_RE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)

def _normalize_conservative(text: str) -> str:
    \"\"\"Conservative cleanup that keeps all tokens:
      - collapse >1 spaces to single (but do NOT touch inside code fences)
      - normalize mixed Windows/Mac newlines
      - ensure a space after punctuation if missing
      - trim trailing spaces per line
    \"\"\"
    if not text:
        return text
    # Preserve code fences by placeholdering them
    CODE_RE = re.compile(r\"```.*?```\", re.S)
    blocks = []
    def _hold(m):
        blocks.append(m.group(0))
        return f\"@@CODEBLOCK{len(blocks)-1}@@\"
    s = CODE_RE.sub(_hold, text)

    # normalize newlines and spaces (not removing content)
    s = s.replace(\"\\r\\n\", \"\\n\").replace(\"\\r\", \"\\n\")
    s = \"\\n\".join([ln.rstrip() for ln in s.split(\"\\n\")])
    s = re.sub(r\"[ \\t]{2,}\", \" \", s)
    s = re.sub(r\"([,:;.!?])(?=\\S)\", r\"\\1 \", s)

    # restore code blocks
    for i,blk in enumerate(blocks):
        s = s.replace(f\"@@CODEBLOCK{i}@@\", blk, 1)
    return s

# --- Loss guard helpers ---
NUM_RE = re.compile(r'[-+]?\\d+(?:\\.\\d+)?')
SPEED_KWS = (\"ping\", \"upload\", \"download\", \"mbps\", \"ms\", \"speedtest\")

def _numbers_in(text: str) -> List[str]:
    return NUM_RE.findall(text or \"\" )

def _has_speedtest_shape(text: str) -> bool:
    low = (text or \"\").lower()
    if any(k in low for k in SPEED_KWS):
        if re.search(r\"(?mi)^(ping|upload|download)\\s*:\\s*[-+0-9]\", low):
            return True
        if \"speedtest\" in low and len(_numbers_in(text)) >= 2:
            return True
    return False

def _loss_detected(original: str, candidate: str) -> bool:
    orig_nums = _numbers_in(original)
    if not orig_nums:
        return False
    cand = candidate or \"\"
    for n in orig_nums:
        if n not in cand:
            return True
    if _has_speedtest_shape(original):
        low_c = cand.lower()
        for kw in (\"ping\",\"upload\",\"download\"):
            if kw in original.lower() and kw not in low_c:
                return True
    return False

# -------- LLM loading --------

def _first_gguf_under(p: Path) -> Optional[Path]:
    try:
        if p.is_file() and p.suffix.lower() == \".gguf\":
            return p
        if p.is_dir():
            cands = sorted(list(p.rglob(\"*.gguf\")),
                           key=lambda x: (0 if str(x).startswith(\"/share/jarvis_prime/models\")
                                          else (1 if str(x).startswith(\"/share/jarvis_prime\") else 2),
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
            model_type=\"llama\",
            gpu_layers=int(os.getenv(\"LLM_GPU_LAYERS\", \"0\")),
            context_length=CTX,
        )
        return _loaded_model
    except Exception as e:
        print(f\"[{BOT_NAME}] ⚠️ LLM load failed: {e}\", flush=True)
        return None

# -------- Formatter-only prompt (neutral & strict) --------

FORMATTER_SYSTEM_PROMPT = (
    \"You are a formatter. Rewrite the text to be clean and readable.\\n\"
    \"CRITICAL RULES:\\n\"
    \" - Do NOT add or remove ANY information.\\n\"
    \" - Do NOT paraphrase or summarize.\\n\"
    \" - Preserve ALL numbers and units exactly.\\n\"
    \" - Preserve line breaks, URLs, code, emojis, and markdown.\\n\"
    \" - Return ONLY the rewritten text, with minimal punctuation fixes.\"
)

# -------- Public API --------

def rewrite(text: str, mood: str=\"serious\", timeout: int=8, cpu_limit: int=70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str]=None,
            model_url: Optional[str]=None, model_path: Optional[str]=None,
            model_sha256: Optional[str]=None, allow_profanity: bool=False) -> str:
    \"\"\"Read inbound text and NEATEN ONLY while keeping ALL information.
    If the LLM is unavailable or output loses content, fall back to conservative normalization.\"\"\"
    src = (text or \"\").strip()
    if not src:
        return src

    if _has_speedtest_shape(src):
        return _normalize_conservative(src)

    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * 4)
    if len(src) > max(500, budget_chars - len(FORMATTER_SYSTEM_PROMPT)):
        return _normalize_conservative(src)

    # 1) Try Ollama (if configured)
    base = (base_url or OLLAMA_BASE_URL or \"\").strip()
    if base and requests:
        try:
            payload = {
                \"model\": (models_priority[0] if models_priority else \"llama3.1\"),
                \"prompt\": FORMATTER_SYSTEM_PROMPT + \"\\n\\n\" + src,
                \"stream\": False,
                \"options\": {
                    \"temperature\": TEMP, \"top_p\": TOP_P, \"repeat_penalty\": REPEAT_P,
                    \"num_ctx\": CTX, \"num_predict\": GEN_TOKENS
                }
            }
            r = requests.post(base.rstrip(\"/\") + \"/api/generate\", json=payload, timeout=timeout)
            if r.ok:
                out = str(r.json().get(\"response\",\"\"))
                if _loss_detected(src, out):
                    return _normalize_conservative(src)
                return _normalize_conservative(out)
        except Exception as e:
            print(f\"[{BOT_NAME}] ⚠️ Ollama call failed: {e}\", flush=True)

    # 2) Try local ctransformers (.gguf)
    p = _resolve_any_path(model_path, model_url)
    if p and p.exists():
        m = _load_local_model(p)
        if m is not None:
            prompt = f\"{FORMATTER_SYSTEM_PROMPT}\\n\\n{src}\"
            try:
                out = m(prompt, max_new_tokens=GEN_TOKENS, temperature=TEMP,
                        top_p=TOP_P, repetition_penalty=REPEAT_P)
                out = str(out or \"\")
                if _loss_detected(src, out):
                    return _normalize_conservative(src)
                return _normalize_conservative(out)
            except Exception as e:
                print(f\"[{BOT_NAME}] ⚠️ Generation failed: {e}\", flush=True)

    return _normalize_conservative(src)

if __name__ == \"__main__\":
    sample = \"A speedtest is finished:\\nPing: 48 ms\\nUpload: 119.40 Mbps\\nDownload: 672.17 Mbps\"
    print(rewrite(sample))
