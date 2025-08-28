import os
import time
import json
import hashlib
import re
from pathlib import Path
from typing import Optional, Tuple, List

import requests

try:
    from ctransformers import AutoModelForCausalLM
except Exception as e:
    AutoModelForCausalLM = None
    print(f"[Jarvis Prime] ⚠️ ctransformers import failed: {e}", flush=True)

# Known-good tiny CPU models (smallest first)
CATALOG = [
    {
        "key": "qwen2.5-0.5b-instruct",
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "model_type": "qwen",
    },
    {
        "key": "phi-2",
        "repo": "TheBloke/phi-2-GGUF",
        "filename": "phi-2.Q4_K_M.gguf",
        "model_type": "phi",
    },
    {
        "key": "tinyllama-1.1b-chat",
        "repo": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
        "filename": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "model_type": "llama",
    },
]

def _hf_resolve(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _download(url: str, dest: Path, sha256: str = "", timeout: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        if sha256:
            if _sha256_file(dest).lower() == sha256.lower():
                print(f"[Jarvis Prime] ✅ Neural Core already present and verified: {dest}", flush=True)
                return
            dest.unlink(missing_ok=True)
            print(f"[Jarvis Prime] ♻️ Re-downloading Neural Core: {dest}", flush=True)
        else:
            print(f"[Jarvis Prime] ✅ Neural Core already present: {dest}", flush=True)
            return
    print(f"[Jarvis Prime] 📥 Downloading Neural Core: {url}", flush=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)
    if sha256:
        dl = _sha256_file(dest)
        if dl.lower() != sha256.lower():
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"SHA256 mismatch for {dest.name}: {dl} != {sha256}")
    print(f"[Jarvis Prime] ✅ Neural Core downloaded to {dest}", flush=True)

def _guess_model_type_from_path(path: str) -> Optional[str]:
    s = path.lower()
    if "qwen" in s: return "qwen"
    if "phi" in s: return "phi"
    return "llama"

def _load_model(model_path: Path, model_type_hint: Optional[str] = None):
    if AutoModelForCausalLM is None:
        raise RuntimeError("ctransformers is not available in this image")
    t0 = time.time()
    mt = model_type_hint or _guess_model_type_from_path(str(model_path))
    print(f"[Jarvis Prime] 🔧 Spinning up Neural Core: {model_path.name} (type={mt})", flush=True)
    llm = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        model_type=mt,
        gpu_layers=0,
        context_length=4096,
    )
    print(f"[Jarvis Prime] 🧩 Neural Core ready in {time.time()-t0:.1f}s", flush=True)
    return llm

def _fix_known_url_mistakes(model_url: str, model_path: str):
    url, path = model_url, model_path
    if "TinyLlama-1.1B-Chat" in url and "chat-v1.0" not in url:
        url = re.sub(r"(tinyllama-1\.1b-chat)(\.Q\d_.*\.gguf)$", r"\1-v1.0\2", url, flags=re.IGNORECASE)
    try:
        fname = url.split("/")[-1]
        if fname and not path.endswith(fname):
            path = str(Path(path).parent / fname)
    except Exception:
        pass
    return url, path

def _ensure_model(model_url: str, model_path: str, sha256: str, models_priority=None):
    # Try explicit first
    if model_url and model_path:
        fixed_url, fixed_path = _fix_known_url_mistakes(model_url, model_path)
        try:
            _download(fixed_url, Path(fixed_path), sha256 or "")
            return Path(fixed_path), _guess_model_type_from_path(fixed_path)
        except Exception as e:
            print(f"[Jarvis Prime] ⚠️ Explicit Neural Core download failed: {e}", flush=True)

    # Fallback catalog
    prio = models_priority or ["qwen2.5:0.5b-instruct", "phi:2", "tinyllama:1.1b-chat"]
    norm = {"qwen2.5:0.5b-instruct":"qwen2.5-0.5b-instruct","phi:2":"phi-2","tinyllama:1.1b-chat":"tinyllama-1.1b-chat"}
    wanted = [norm.get(p.lower(), p.lower()) for p in prio]

    for m in CATALOG:
        if m["key"] not in wanted: continue
        url = _hf_resolve(m["repo"], m["filename"])
        local = Path("/share/jarvis_prime/models") / m["filename"]
        try:
            _download(url, local)
            return local, m.get("model_type")
        except Exception as e:
            print(f"[Jarvis Prime] ⚠️ Fallback '{m['key']}' failed: {e}", flush=True)

    raise RuntimeError("No Neural Core model could be downloaded. Check network/URLs.")

def _build_prompt(text: str, mood: str) -> str:
    mood = (mood or "serious").strip().lower()
    persona = {
        "serious": "direct, concise, professional",
        "sarcastic": "dry wit, playful jabs, still helpful",
        "playful": "light, fun, friendly",
        "hacker-noir": "noir monologue, terse, technical",
        "angry": "brutally honest but helpful, short sentences",
    }.get(mood, "direct, concise, professional")
    system = (
        "You are Jarvis Prime. Rewrite the incoming message for a human.\n"
        f"Style: {persona}.\n"
        "Keep ALL important info intact (titles, links/URLs, poster/image URLs, names).\n"
        "Preserve markdown, lists, and emoji. Do NOT invent facts. Be brief and readable.\n"
        "If the input already looks good, lightly polish only."
    )
    return f"{system}\n\n--- INPUT START ---\n{text}\n--- INPUT END ---\n\nRewrite:"

def rewrite(
    text: str,
    mood: str = "serious",
    timeout: int = 5,
    cpu_limit: int = 70,
    models_priority: Optional[List[str]] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
) -> str:
    local_path, model_type_hint = _ensure_model(model_url, model_path, model_sha256, models_priority)
    llm = _load_model(local_path, model_type_hint)

    prompt = _build_prompt(text, mood)
    start = time.time()
    out = []
    try:
        for token in llm(
            prompt,
            max_new_tokens=160,
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.05,
            stream=True,
        ):
            out.append(token)
            if time.time() - start > timeout:
                print("[Jarvis Prime] ⏱️ Neural Core timeout; returning partial output.", flush=True)
                break
    except Exception as e:
        print(f"[Jarvis Prime] ❌ Neural Core generation failed: {e}", flush=True)
        raise

    text_out = "".join(out).strip()
    return text_out or text

def _envflag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1","true","yes","on")

if __name__ == "__main__":
    if _envflag("LLM_ENABLED") or _envflag("llm_enabled"):
        print("[Jarvis Prime] 🔮 Prefetching Neural Core...", flush=True)
        try:
            url = os.getenv("LLM_MODEL_URL", os.getenv("llm_model_url", ""))
            path = os.getenv("LLM_MODEL_PATH", os.getenv("llm_model_path", ""))
            sha = os.getenv("LLM_MODEL_SHA256", os.getenv("llm_model_sha256", ""))
            prio_raw = os.getenv("LLM_MODELS_PRIORITY", os.getenv("llm_models_priority", ""))
            prio = [p.strip() for p in prio_raw.split(",") if p.strip()] if prio_raw else None
            if not path:
                path = str(Path("/share/jarvis_prime/models") / CATALOG[0]["filename"])
            local, _ = _ensure_model(url, path, sha, prio)
            print(f"[Jarvis Prime] ✅ Prefetch complete: {local}", flush=True)
        except Exception as e:
            print(f"[Jarvis Prime] ⚠️ Prefetch failed: {e}", flush=True)
    else:
        print("[Jarvis Prime] ℹ️ Neural Core disabled; skipping prefetch.", flush=True)
