#!/usr/bin/env python3
# /app/llm_client.py
# -----------------------------------------------------------------------------
# Local/Ollama LLM client for Jarvis Prime
# - rewrite(text): safe cleanup (optional LLM). Falls back cleanly.
# - persona_riff(persona, context): 1–3 punchy persona lines; no summaries.
# - engine_status(): quick readiness check.
#
# Hardenings:
#   • Ultra-conservative decoding (TEMP/TOP_P/REPEAT_P)
#   • Aggressive stop tokens (kills echoes: Rules:/Persona:/Context:/User:)
#   • Strong post-filters: drop tutorials/ads/game blurbs/instruction echoes
#   • New _is_bad_line() guard + quote/colon/numbered-list filters
#   • Persona clamp + profanity gate (rager only via env)
#   • Fallback canned quips if model output is nuked
#   • LLM_DEBUG to inspect pre-filter text in logs
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import re
import json
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
LLM_DEBUG = os.getenv("LLM_DEBUG", "false").lower() in ("1", "true", "yes")

# =============================================================================
# ENV & KNOBS
# =============================================================================

def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return default

def _float_env(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, default)).strip())
    except Exception:
        return default

CTX             = _int_env("LLM_CTX_TOKENS", 4096)
GEN_TOKENS      = _int_env("LLM_GEN_TOKENS", 180)
MAX_LINES       = _int_env("LLM_MAX_LINES", 10)
CHARS_PER_TOKEN = 4
SAFETY_TOKENS   = 64

TEMP     = _float_env("LLM_TEMPERATURE", 0.12)
TOP_P    = _float_env("LLM_TOP_P", 0.88)
REPEAT_P = _float_env("LLM_REPEAT_PENALTY", 1.55)

SEARCH_ROOTS = [Path("/share/jarvis_prime/models"), Path("/share/jarvis_prime"), Path("/share")]
OLLAMA_BASE_URL = (os.getenv("LLM_OLLAMA_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or "").strip()
MODEL_PREF = [s for s in os.getenv("LLM_MODEL_PREFERENCE", "phi,qwen,tinyllama,llama").lower().split(",") if s]

def _cpu_threads_for_limit(limit_pct: int) -> int:
    cores = max(1, os.cpu_count() or 1)
    limit = max(1, min(100, int(limit_pct or 100)))
    return max(1, int(round(cores * (limit / 100.0))))

# =============================================================================
# GGUF DISCOVERY / DOWNLOAD
# =============================================================================

_loaded_model = None
_model_path: Optional[Path] = None

def _list_local_models() -> List[Path]:
    out: List[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            out.extend(root.rglob("*.gguf"))
    uniq, seen = [], set()
    for p in sorted(out):
        s = str(p)
        if s not in seen:
            seen.add(s); uniq.append(p)
    return uniq

def _choose_preferred(paths: List[Path]) -> Optional[Path]:
    if not paths:
        return None
    def score(p: Path):
        name = p.name.lower()
        fam = min([i for i, f in enumerate(MODEL_PREF) if f and f in name] + [999])
        bias = 0 if str(p).startswith("/share/jarvis_prime/") else (1 if str(p).startswith("/share/") else 2)
        size = p.stat().st_size if p.exists() else 1 << 60
        return (fam, bias, size)
    return sorted(paths, key=score)[0]

def _first_gguf_under(p: Path) -> Optional[Path]:
    try:
        if p.is_file() and p.suffix.lower() == ".gguf":
            return p
        if p.is_dir():
            cands = list(p.rglob("*.gguf"))
            if cands:
                return _choose_preferred(cands)
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
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Download failed: {e}", flush=True)
        return False

def _resolve_model_path() -> Optional[Path]:
    env_model_path = os.getenv("LLM_MODEL_PATH", "").strip()
    if env_model_path:
        p = Path(env_model_path)
        f = _first_gguf_under(p)
        if f: return f

    best = _choose_preferred(_list_local_models())
    if best:
        return best

    urls_raw = os.getenv("LLM_MODEL_URLS", "").strip()
    url_one  = os.getenv("LLM_MODEL_URL", "").strip()
    urls = [u for u in (urls_raw.split(",") if urls_raw else []) + ([url_one] if url_one else []) if u]
    for u in urls:
        name = u.split("/")[-1] or "model.gguf"
        if not name.endswith(".gguf"):
            name += ".gguf"
        dest = Path("/share/jarvis_prime/models") / name
        if dest.exists(): return dest
        if _download_to(u, dest): return dest
    return None

def prefetch_model(model_path: Optional[str] = None, model_url: Optional[str] = None) -> None:
    global _model_path
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f: _model_path = f; return
    _model_path = _resolve_model_path()

def _resolve_any_path(model_path: Optional[str], model_url: Optional[str]) -> Optional[Path]:
    if model_path:
        p = Path(model_path)
        f = _first_gguf_under(p)
        if f: return f
    if _model_path and Path(_model_path).exists():
        return _first_gguf_under(Path(_model_path)) or Path(_model_path)
    return _resolve_model_path()

def _load_local_model(path: Path):
    global _loaded_model
    if _loaded_model is not None:
        return _loaded_model
    if AutoModelForCausalLM is None:
        return None
    if path.is_dir():
        gg = _first_gguf_under(path)
        if gg: path = gg
    try:
        _loaded_model = AutoModelForCausalLM.from_pretrained(
            str(path),
            model_type="llama",  # llama.cpp backend (llama/phi/qwen/tinyllama gguf)
            context_length=CTX,
            gpu_layers=int(os.getenv("LLM_GPU_LAYERS", "0")),
        )
        if LLM_DEBUG:
            print(f"[{BOT_NAME}] ctransformers loaded: {path}", flush=True)
        return _loaded_model
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM load failed: {e}", flush=True)
        return None

# =============================================================================
# CLEANING / FILTERS
# =============================================================================

IMG_MD_RE       = re.compile(r'!\[[^\]]*\]\([^)]+\)')
IMG_URL_RE      = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp))', re.I)
PLACEHOLDER_RE  = re.compile(r'\[([A-Z][A-Z0-9 _:/\-\.,]{2,})\]')

UPSELL_RE = re.compile(
    r'(?i)\b(please review|confirm|support team|contact .*@|let us know|thank you|'
    r'stay in touch|new feature|check out|subscribe|download now|learn more|sign up)\b'
)

TUTORIAL_RE = re.compile(
    r'(?is)\b(click|tap|go to|navigate|open your browser|add to favorites|step \d|how to|tutorial|use bullet points?)\b'
)

GAME_BLURB_RE = re.compile(
    r'(?is)\b(3d horror|undead creature|devours living flesh|newest addition to our lineup|thrilling experience)\b'
)

INSTRUCTION_ECHO_RE = re.compile(
    r'(?is)\b(persona|rules?|guideline|instruction|system prompt|style hint|produce (only|at most)|respond with at most|no labels|no meta|return just the lines)\b'
)

UPDATE_SUMMARY_RE = re.compile(
    r'(?is)\b(updated to version|has been updated|added support|release notes|changelog|version \d)\b'
)

NUMBERED_PREFIX_RE = re.compile(r'^\s*(?:\d+[\).]|[-•*])\s+')

QUOTE_LINE_RE = re.compile(r'^\s*["“].*["”]\s*$')
COLONY_RE = re.compile(r':\s')  # colon that usually starts instruction-y clauses

def _extract_images(src: str) -> str:
    imgs = IMG_MD_RE.findall(src or "") + IMG_URL_RE.findall(src or "")
    out, seen = [], set()
    for i in imgs:
        if i not in seen:
            seen.add(i); out.append(i)
    return "\n".join(out)

def _strip_reasoning(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t: continue
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

def _strip_meta_lines(text: str) -> str:
    out = []
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t: continue
        low = t.lower()
        if INSTRUCTION_ECHO_RE.search(low):
            continue
        out.append(t)
    return "\n".join(out)

def _remove_placeholders(text: str) -> str:
    s = PLACEHOLDER_RE.sub("", text or "")
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

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
            prev, count = wl, 1
            out.append(w)
    s2 = " ".join(out)
    s2 = re.sub(r"(\b\w+\s+\w+)(?:\s+\1){2,}", r"\1 \1", s2, flags=re.I)
    return s2

def _polish(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    s = re.sub(r"([,:;.!?])(?=\S)", r"\1 ", s)
    s = re.sub(r"\s*…+\s*", ". ", s)
    s = re.sub(r"\s+([,:;.!?])", r"\1", s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    fixed = [(ln if re.search(r"[.!?]$", ln) else ln + ".") for ln in lines]
    s = "\n".join(fixed)
    seen, out = set(), []
    for ln in s.splitlines():
        key = ln.lower()
        if key in seen: continue
        seen.add(key); out.append(ln)
    return "\n".join(out)

def _cap(text: str, max_lines: int = MAX_LINES, max_chars: int = 800) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out

def _sanitize_system_prompt(s: str) -> str:
    if '"$schema"' in s or "SCHEMA:" in s or "USER TEMPLATE:" in s:
        return "YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."
    return s

def _load_system_prompt() -> str:
    sp = os.getenv("LLM_SYSTEM_PROMPT")
    if sp: return _sanitize_system_prompt(sp)
    for p in (Path("/share/jarvis_prime/memory/system_prompt.txt"),
              Path("/app/memory/system_prompt.txt")):
        if p.exists():
            try:
                return _sanitize_system_prompt(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return "YOU ARE JARVIS PRIME. Keep facts exact; rewrite clearly; obey mood={mood}."

def _trim_to_ctx(src: str, system: str) -> str:
    if not src: return src
    budget_tokens = max(256, CTX - GEN_TOKENS - SAFETY_TOKENS)
    budget_chars  = max(1000, budget_tokens * CHARS_PER_TOKEN)
    remaining     = max(500, budget_chars - len(system))
    return src if len(src) <= remaining else src[-remaining:]

def _finalize(text: str, imgs: str) -> str:
    out = _strip_reasoning(text)
    out = _strip_meta_lines(out)
    out = _remove_placeholders(out)
    out = _drop_boilerplate(out)
    out = _squelch_repeats(out)
    out = _polish(out)
    out = _cap(out, MAX_LINES)
    return out + ("\n" + imgs if imgs else "")

# =============================================================================
# rewrite()
# =============================================================================

def rewrite(text: str, mood: str = "serious", timeout: int = 8, cpu_limit: int = 70,
            models_priority: Optional[List[str]] = None, base_url: Optional[str] = None,
            model_url: Optional[str] = None, model_path: Optional[str] = None,
            model_sha256: Optional[str] = None, allow_profanity: bool = False) -> str:
    src = (text or "").strip()
    if not src:
        return src

    imgs   = _extract_images(src)
    system = _load_system_prompt().format(mood=mood)
    src    = _trim_to_ctx(src, system)

    # 1) Ollama
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload = {
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": system + "\n\nINPUT:\n" + src + "\n\nOUTPUT:\n",
                "stream": False,
                "options": {
                    "temperature": TEMP,
                    "top_p": TOP_P,
                    "repeat_penalty": REPEAT_P,
                    "num_ctx": CTX,
                    "num_predict": GEN_TOKENS,
                    "stop": ["[SYSTEM]", "[INPUT]", "[OUTPUT]", "Persona:", "Rules:", "Context:", "Quips:", "Instruction:", "User:"]
                }
            }
            r = requests.post(base.rstrip("/") + "/api/generate", json=payload, timeout=timeout)
            if r.ok:
                out = str(r.json().get("response", ""))
                if LLM_DEBUG:
                    print(f"[{BOT_NAME}] Ollama rewrite raw:\n{out}\n", flush=True)
                return _finalize(out, imgs)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama rewrite failed: {e}", flush=True)

    # 2) Local
    p = _resolve_any_path(model_path, model_url)
    if p and p.exists():
        m = _load_local_model(p)
        if m is not None:
            prompt  = f"[SYSTEM]\n{system}\n[INPUT]\n{src}\n[OUTPUT]\n"
            threads = _cpu_threads_for_limit(cpu_limit)
            def _gen() -> str:
                out = m(
                    prompt,
                    max_new_tokens=GEN_TOKENS,
                    temperature=TEMP,
                    top_p=TOP_P,
                    repetition_penalty=REPEAT_P,
                    stop=["[SYSTEM]", "[INPUT]", "[OUTPUT]", "Persona:", "Rules:", "Context:", "Quips:", "Instruction:", "User:"],
                    threads=threads,
                )
                return str(out or "")
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_gen)
                try:
                    result = fut.result(timeout=max(2, int(timeout or 8)))
                    if LLM_DEBUG:
                        print(f"[{BOT_NAME}] Local rewrite raw:\n{result}\n", flush=True)
                    return _finalize(result, imgs)
                except TimeoutError:
                    print(f"[{BOT_NAME}] ⚠️ LLM rewrite timed out after {timeout}s", flush=True)
                except Exception as e:
                    print(f"[{BOT_NAME}] ⚠️ LLM rewrite failed: {e}", flush=True)

    return _finalize(src, imgs)

# =============================================================================
# persona_riff()
# =============================================================================

_ALLOWED_PERSONAS = {"dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops"}

_FALLBACK_QUIPS = {
    "ops": ["ack.", "noted.", "synced.", "validated.", "applied.", "green.", "stable.", "running.", "queued.", "done."],
    "jarvis": ["Handled with grace.", "All signals nominal.", "Telemetry aligned.", "As you wish.", "Consider it done.", "Elegance maintained.", "Diagnostics clear.", "Quietly resolved."],
    "rager": ["Ship or shush.", "No excuses—results.", "Kill the flake.", "Pin versions or perish.", "Green checks or bust.", "Talk less, fix more.", "Stop guessing; prove it."],
    "nerd": ["Feature flags save feelings.", "Unit tests love the future.", "Reality is eventually consistent.", "Determinism > drama.", "We lint our lives."],
    "dude": ["The Dude abides.", "Most excellent.", "Keep it mellow.", "Let it ride.", "Zen deploys only."],
    "chick": ["Zero-downtime slays.", "Make it sleek.", "Obsessed with uptime.", "Glam ops only.", "Serving metrics, darling."],
    "comedian": ["Adequate—my favorite.", "Remarkably unremarkable.", "I’ve seen worse.", "Calm is suspicious.", "If it sinks, call it a submarine."],
    "action": ["Consider it deployed.", "Hasta la vista, downtime.", "Logs in, chaos out.", "Mission accomplished.", "Targets greenlit."],
}

def _canon_persona(name: str) -> str:
    n = (name or "ops").strip().lower()
    return n if n in _ALLOWED_PERSONAS else "ops"

def _is_bad_line(ln: str) -> bool:
    low = ln.lower().strip()

    if not low:
        return True
    if QUOTE_LINE_RE.match(ln):        # pure quoted lines
        return True
    if NUMBERED_PREFIX_RE.match(ln):   # numbered/bulleted
        return True
    if COLONY_RE.search(ln):           # instruction-like colon
        # allow short emojis only lines with colon-like glyphs? Not needed.
        return True

    # kill generic meta/instruction/tutorial/sales/game blurbs/update summaries
    if INSTRUCTION_ECHO_RE.search(low):
        return True
    if TUTORIAL_RE.search(low):
        return True
    if GAME_BLURB_RE.search(low):
        return True
    if UPSELL_RE.search(low):
        return True
    if UPDATE_SUMMARY_RE.search(low):
        return True

    # kill “version/updated/support/added” heuristic if too factual
    if re.search(r'\b(version|updated|support|added|release|build|patch)\b', low):
        # keep if extremely short and clearly quippy (<= 5 words)
        if len(low.split()) > 5:
            return True

    # kill sentences that look like explanations (“this line …”, “for example …”)
    if re.search(r'\b(this line|for example|example:|e\.g\.)\b', low):
        return True

    return False

def _cleanup_quip_block(text: str, max_lines: int) -> List[str]:
    if not text:
        return []
    s = _strip_reasoning(text)
    s = _strip_meta_lines(s)

    # split lines and sentences
    parts: List[str] = []
    for ln in s.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        for seg in re.split(r'(?<=[.!?])\s+|\n+', ln):
            seg = seg.strip()
            if seg:
                parts.append(seg)

    out, seen = [], set()
    for ln in parts:
        if not ln:
            continue
        ln = re.sub(r'^\s*[-•*]+\s*', '', ln)  # bullets
        # clamp to ~22 words
        words = ln.split()
        if len(words) > 22:
            ln = " ".join(words[:22])
        # strip quotes
        ln = ln.strip(' "\'“”‘’[]()')
        # tidy punctuation spacing
        ln = re.sub(r'\s+([.!?])$', r'\1', ln)
        key = ln.lower()
        if key in seen:
            continue
        if _is_bad_line(ln):
            continue
        seen.add(key)
        out.append(ln)
        if len(out) >= max_lines:
            break

    return out[:max_lines]

def persona_riff(persona: str, context: str, max_lines: int = 3, timeout: int = 8,
                 cpu_limit: int = 70, models_priority: Optional[List[str]] = None,
                 base_url: Optional[str] = None, model_url: Optional[str] = None,
                 model_path: Optional[str] = None) -> List[str]:
    key = _canon_persona(persona)
    ctx = (context or "").strip()
    n = max(1, min(3, int(max_lines or 3)))

    if not ctx:
        return _FALLBACK_QUIPS.get(key, _FALLBACK_QUIPS["ops"])[:n]

    allow_profanity = os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1", "true", "yes")
    style_hint = {
        "dude": "Laid-back surfer/dude: mellow, supportive, funny.",
        "chick": "Glam, sassy, confident. Playful ops banter.",
        "nerd": "Precise, witty, technically savvy. Smart quips.",
        "rager": "Intense, blunt, spicy." + (" Profanity allowed." if allow_profanity else " No profanity."),
        "comedian": "Deadpan one-liners (Leslie Nielsen vibe).",
        "action": "Action-hero catchphrases; decisive; terse.",
        "jarvis": "Polite, refined AI butler; supportive and elegant.",
        "ops": "Short, neutral ops acknowledgements.",
    }[key]

    instruction = (
        f"You speak as '{key}'. Style: {style_hint} "
        f"Produce ONLY {n} separate lines. Each line < 140 characters. "
        "No labels, no bullets, no numbering, no JSON, no quotes. "
        "Do NOT summarize or restate message facts. Do NOT invent details. "
        "Return just the lines."
    )

    # 1) Ollama
    base = (base_url or OLLAMA_BASE_URL or "").strip()
    if base and requests:
        try:
            payload = {
                "model": (models_priority[0] if models_priority else "llama3.1"),
                "prompt": instruction + "\n\nContext (vibe only):\n" + ctx + "\n\nLines:\n",
                "stream": False,
                "options": {
                    "temperature": TEMP,
                    "top_p": TOP_P,
                    "repeat_penalty": REPEAT_P,
                    "num_ctx": CTX,
                    "num_predict": max(64, min(220, GEN_TOKENS // 2 + 64)),
                    "stop": ["Lines:", "Rules:", "Persona:", "Context:", "Instruction:", "[SYSTEM]", "[INPUT]", "[OUTPUT]", "User:"]
                }
            }
            r = requests.post(base.rstrip("/") + "/api/generate", json=payload, timeout=timeout)
            if r.ok:
                raw = str(r.json().get("response", ""))
                if LLM_DEBUG:
                    print(f"[{BOT_NAME}] Ollama riff raw:\n{raw}\n", flush=True)
                lines = _cleanup_quip_block(raw, n)
                if not lines:
                    lines = _FALLBACK_QUIPS.get(key, _FALLBACK_QUIPS["ops"])[:n]
                return lines
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Ollama quip failed: {e}", flush=True)

    # 2) Local
    p = _resolve_any_path(model_path, model_url)
    if p and p.exists():
        m = _load_local_model(p)
        if m is not None:
            prompt = f"{instruction}\n\nContext (vibe only):\n{ctx}\n\nLines:\n"
            threads = _cpu_threads_for_limit(cpu_limit)
            def _gen() -> str:
                out = m(
                    prompt,
                    max_new_tokens=max(64, min(220, GEN_TOKENS // 2 + 64)),
                    temperature=TEMP,
                    top_p=TOP_P,
                    repetition_penalty=REPEAT_P,
                    stop=["Lines:", "Rules:", "Persona:", "Context:", "Instruction:", "[SYSTEM]", "[INPUT]", "[OUTPUT]", "User:"],
                    threads=threads,
                )
                return str(out or "")
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_gen)
                try:
                    result = fut.result(timeout=max(2, int(timeout or 8)))
                    if LLM_DEBUG:
                        print(f"[{BOT_NAME}] Local riff raw:\n{result}\n", flush=True)
                    lines = _cleanup_quip_block(result, n)
                    if not lines:
                        lines = _FALLBACK_QUIPS.get(key, _FALLBACK_QUIPS["ops"])[:n]
                    return lines
                except TimeoutError:
                    print(f"[{BOT_NAME}] ⚠️ Quip generation timed out after {timeout}s", flush=True)
                except Exception as e:
                    print(f"[{BOT_NAME}] ⚠️ Quip generation failed: {e}", flush=True)

    return _FALLBACK_QUIPS.get(key, _FALLBACK_QUIPS["ops"])[:n]

llm_quips = persona_riff  # alias

# =============================================================================
# status
# =============================================================================

def engine_status() -> Dict[str, object]:
    base = (OLLAMA_BASE_URL or "").strip()
    if base and requests:
        ok = False
        try:
            r = requests.get(base.rstrip("/") + "/api/version", timeout=3)
            ok = r.ok
        except Exception:
            ok = False
        return {"ready": bool(ok), "model_path": "", "backend": "ollama"}

    p = _resolve_any_path(os.getenv("LLM_MODEL_PATH", ""), os.getenv("LLM_MODEL_URL", ""))
    return {"ready": bool(p and Path(p).exists()), "model_path": str(p or ""), "backend": "ctransformers" if p else "none"}