#!/usr/bin/env python3
# /app/llm_client.py
# GGUF-only LLM client for Jarvis Prime (no Ollama). Full file for copy/paste.

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, List, Dict

# ========================= ctransformers backend =========================
try:
    from ctransformers import AutoModelForCausalLM
except Exception:
    AutoModelForCausalLM = None  # type: ignore

# ========================= Optional requests (only for future downloads) =========================
try:
    import requests
except Exception:
    requests = None  # type: ignore

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")

# ========================= Config knobs =========================
CTX = int(os.getenv("LLM_CTX_TOKENS", "4096"))
GEN_TOKENS = int(os.getenv("LLM_GEN_TOKENS", "180"))
CHARS_PER_TOKEN = 4
SAFETY_TOKENS = 32

# Decoding knobs (precise, low-temp)
TEMP = float(os.getenv("LLM_TEMPERATURE", "0.05"))
TOP_P = float(os.getenv("LLM_TOP_P", "0.8"))
REPEAT_P = float(os.getenv("LLM_REPEAT_PENALTY", "1.4"))

# Model discovery roots
SEARCH_ROOTS = [
    Path("/share/jarvis_prime"),
    Path("/share/jarvis_prime/models"),
    Path("/share"),
]

MODEL_PATH = Path(os.getenv("LLM_MODEL_PATH", ""))
MODEL_URL = os.getenv("LLM_MODEL_URL", "")
MODEL_URLS = [u.strip() for u in os.getenv("LLM_MODEL_URLS", "").split(",") if u.strip()]

# Globals
_loaded_model = None
_model_path: Optional[Path] = None


# ========================= Utility: local model discovery =========================
def _list_local_models() -> List[Path]:
    out: List[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out += list(root.rglob("*.gguf"))
    # unique, stable
    seen: set[str] = set()
    uniq: List[Path] = []
    for p in out:
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


def _choose_preferred(paths: List[Path]) -> Optional[Path]:
    if not paths:
        return None
    pref = (os.getenv("LLM_MODEL_PREFERENCE", "phi,qwen,tinyllama,llama").lower()).split(",")
    def score(p: Path):
        name = p.name.lower()
        fam = min([i for i, f in enumerate(pref) if f and f in name] + [999])
        # Prefer /share/jarvis_prime/models, then /share/jarvis_prime, then others; then smaller size
        bias = 0 if str(p).startswith("/share/jarvis_prime/models") else (1 if str(p).startswith("/share/jarvis_prime") else 2)
        size = p.stat().st_size if p.exists() else (1 << 60)
        return (fam, bias, size)
    return sorted(paths, key=score)[0]


def _first_gguf_under(p: Path) -> Optional[Path]:
    try:
        if p.is_file() and p.suffix.lower() == ".gguf":
            return p
        if p.is_dir():
            cands = sorted(list(p.rglob("*.gguf")), key=lambda x: (0 if str(x).startswith("/share/jarvis_prime/models") else (1 if str(x).startswith("/share/jarvis_prime") else 2), x.stat().st_size if x.exists() else 1 << 60))
            return cands[0] if cands else None
    except Exception:
        pass
    return None


def _download_to(url: str, dest: Path) -> bool:
    if not requests:
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if chunk:
                        f.write(chunk)
        tmp.replace(dest)
        print(f"[{BOT_NAME}] Downloaded model -> {dest}", flush=True)
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
        return False


def _resolve_model_path() -> Optional[Path]:
    # 1) Explicit path (file or dir)
    if str(MODEL_PATH):
        p = Path(MODEL_PATH)
        f = _first_gguf_under(p)
        if f:
            return f
    # 2) Known local locations
    best = _choose_preferred(_list_local_models())
    if best:
        return best
    # 3) Optional download (if URL(s) provided)
    urls = MODEL_URLS or ([MODEL_URL] if MODEL_URL else [])
    for u in urls:
        if not u:
            continue
        name = u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"):
            name += ".gguf"
        dest = Path("/share/jarvis_prime/models") / name
        if dest.exists():
            return dest
        if _download_to(u, dest):
            return dest
    return None


def _resolve_any_path(model_path: Optional[str], model_url: Optional[str]) -> Optional[Path]:
    # explicit first
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f:
            return f
    # already prefetched
    global _model_path
    if _model_path and Path(_model_path).exists():
        mp = Path(_model_path)
        return _first_gguf_under(mp) or mp
    # default resolver (may download if URL is provided via env)
    return _resolve_model_path()


def prefetch_model(model_path: Optional[str] = None, model_url: Optional[str] = None) -> None:
    """Resolve and cache the model path ahead of time, so first use is fast."""
    global _model_path
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f:
            _model_path = f
            print(f"[{BOT_NAME}] LLM prefetch -> {_model_path}", flush=True)
            return
    _model_path = _resolve_model_path()
    if _model_path:
        print(f"[{BOT_NAME}] LLM prefetch -> {_model_path}", flush=True)
    else:
        print(f"[{BOT_NAME}] ⚠️ LLM prefetch: no GGUF model found.", flush=True)


# ========================= Engine status =========================
def engine_status() -> Dict[str, object]:
    p = _model_path or _resolve_model_path()
    return {
        "ready": bool(p and Path(p).exists() and AutoModelForCausalLM is not None),
        "model_path": str(p or ""),
        "backend": "ctransformers" if p else "none",
    }


# ========================= ctransformers load =========================
def _load_local_model(path: Path):
    """Load the GGUF model once."""
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model
    if AutoModelForCausalLM is None:
        print(f"[{BOT_NAME}] ⚠️ ctransformers not available.", flush=True)
        return None
    if path.is_dir():
        gg = _first_gguf_under(path)
        if gg:
            path = gg
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",  # works for most llama/phi/qwen-gguf builds
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS", "0")),
            context_length=CTX,
        )
        print(f"[{BOT_NAME}] LLM loaded (ctransformers) -> {path}", flush=True)
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None


# ========================= Light rewrite helpers =========================
IMG_MD_RE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)
PLACEHOLDER_RE = re.compile(r'\[([A-Z][A-Z0-9 _:/\-\.,]{2,})\]')
UPSELL_RE = re.compile(r'(?i)\b(please review|confirm|support team|contact .*@|let us know|thank you|stay in touch|new feature|check out)\b')


def _extract_images(src: str) -> str:
    imgs = IMG_MD_RE.findall(src or "") + IMG_URL_RE.findall(src or "")
    seen: set[str] = set()
    out: List[str] = []
    for i in imgs:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return "\n".join(out)


def _strip_reasoning(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        tl = t.lower()
        if tl.startswith(("input:", "output:", "explanation:", "reasoning:", "analysis:", "system:")):
            continue
        if t in ("[SYSTEM]", "[INPUT]", "[OUTPUT]") or t.startswith(("[SYSTEM]", "[INPUT]", "[OUTPUT]")):
            continue
        if t.startswith("[") and t.endswith("]") and len(t) < 40:
            continue
        if tl.startswith("note:"):
            continue
        lines.append(t)
    return "\n".join(lines)


def _remove_placeholders(text: str) -> str:
    s = PLACEHOLDER_RE.sub("", text or "")
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _drop_boilerplate(text: str) -> str:
    kept = []
    for ln in (text or "").splitlines():
        if not ln.strip():
            continue
        if UPSELL_RE.search(ln):
            continue
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
    s2 = re.sub(r"(\b\w+\s+\w+)(?:\s+\1){2,}", r"\1 \1", s2, flags=re.I)
    return s2


def _polish(text: str) -> str:
    import re as _re
    s = (text or "").strip()
    s = _re.sub(r"[ \t]+", " ", s)
    s = _re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    s = _re.sub(r"([,:;.!?])(?=\S)", r"\1 ", s)
    s = _re.sub(r"\s*…+\s*", ". ", s)
    s = _re.sub(r"\s+([,:;.!?])", r"\1", s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    fixed = []
    for ln in lines:
        if not _re.search(r"[.!?]$", ln):
            fixed.append(ln + ".")
        else:
            fixed.append(ln)
    s = "\n".join(fixed)
    seen: set[str] = set()
    out: List[str] = []
    for ln in s.splitlines():
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ln)
    return "\n".join(out)


def _cap(text: str, max_lines: int = int(os.getenv("LLM_MAX_LINES", "10")), max_chars: int = 800) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out


def _load_system_prompt() -> str:
    sp = os.getenv("LLM_SYSTEM_PROMPT")
    if sp:
        return sp
    p = Path("/share/jarvis_prime/memory/system_prompt.txt")
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            pass
    p2 = Path("/app/memory/system_prompt.txt")
    if p2.exists():
        try:
            return p2.read_text(encoding="utf-8")
        except Exception:
            pass
    return "YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."


def _trim_to_ctx(src: str, system: str) -> str:
    if not src:
        return src
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars = max(1000, budget_tokens * CHARS_PER_TOKEN)
    remaining = max(500, budget_chars - len(system))
    if len(src) <= remaining:
        return src
    return src[-remaining:]


def _finalize(text: str, imgs: str) -> str:
    out = _strip_reasoning(text)
    out = _remove_placeholders(out)
    out = _drop_boilerplate(out)
    out = _squelch_repeats(out)
    out = _polish(out)
    out = _cap(out)
    return out + ("\n" + imgs if imgs else "")


# ========================= Public: rewrite =========================
def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 8,
    cpu_limit: int = 70,
    models_priority: Optional[List[str]] = None,
    base_url: Optional[str] = None,        # ignored (no Ollama)
    model_url: Optional[str] = None,       # optional for download
    model_path: Optional[str] = None,      # preferred local path/dir
    model_sha256: Optional[str] = None,    # ignored
    allow_profanity: bool = False,         # stylistic only
) -> str:
    """
    GGUF-only rewrite. Never calls Ollama.
    Keeps signature compatible with bot.py.
    """
    src = (text or "").strip()
    if not src:
        return src

    imgs = _extract_images(src)
    system = _load_system_prompt().format(mood=mood)
    src = _trim_to_ctx(src, system)

    # Resolve & load local model
    p = _resolve_any_path(model_path, model_url)
    if not p or not p.exists():
        print(f"[{BOT_NAME}] ⚠️ No GGUF model found; returning original.", flush=True)
        return _finalize(src, imgs)

    m = _load_local_model(p)
    if m is None:
        print(f"[{BOT_NAME}] ⚠️ Failed to load model; returning original.", flush=True)
        return _finalize(src, imgs)

    prompt = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
    try:
        print(f"[{BOT_NAME}] LLM generating (ctransformers, {p.name}) …", flush=True)
        out = m(
            prompt,
            max_new_tokens=GEN_TOKENS,
            temperature=TEMP,
            top_p=TOP_P,
            repetition_penalty=REPEAT_P,
            stop=["[SYSTEM]", "[INPUT]", "[OUTPUT]"],
        )
        return _finalize(str(out or ""), imgs)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Generation failed: {e}", flush=True)
        return _finalize(src, imgs)
```0