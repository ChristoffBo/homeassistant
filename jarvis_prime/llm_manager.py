#!/usr/bin/env python3
import requests
from pathlib import Path

MODELS = {
    "tinyllama": {
        "url": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat.Q4_K_M.gguf",
        "path": "/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf"
    },
    "llama32_3b": {
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "path": "/share/jarvis_prime/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
    },
    "mistral7b": {
        "url": "https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
        "path": "/share/jarvis_prime/models/Mistral-7B-Instruct-v0.3-Q4_K_M.gguf"
    }
}

def _download(url, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)

def prepare_model(opts: dict) -> str | None:
    for key, spec in MODELS.items():
        toggle = bool(opts.get(f"{key}_enabled", False))
        path = Path(spec["path"])
        if toggle:
            if not path.exists():
                print(f"[LLM Manager] Downloading {key} model...")
                _download(spec["url"], path)
            return str(path)
        else:
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass
    return None
