import os, requests, hashlib

MODELS = {
    "tinyllama": {
        "url": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat.Q4_K_M.gguf",
        "path": "/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf"
    },
    "llama32_3b": {
        "url": "https://huggingface.co/hugging-quants/Llama-3.2-3B-Instruct-Q4_K_M-GGUF/resolve/main/Llama-3.2-3B-Instruct.Q4_K_M.gguf",
        "path": "/share/jarvis_prime/models/llama-3.2-3b-instruct.Q4_K_M.gguf"
    },
    "mistral7b": {
        "url": "https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
        "path": "/share/jarvis_prime/models/mistral-7b-instruct-v0.3.Q4_K_M.gguf"
    }
}

def download(url, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return
    print(f"[Jarvis Prime] ↓ Downloading model {os.path.basename(path)} ...")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print(f"[Jarvis Prime] ✓ Download complete: {path}")

def prepare_model(config: dict):
    chosen = None
    if config.get("tinyllama_enabled"):
        chosen = "tinyllama"
    elif config.get("llama32_3b_enabled"):
        chosen = "llama32_3b"
    elif config.get("mistral7b_enabled"):
        chosen = "mistral7b"

    if not chosen:
        print("[Jarvis Prime] ⚠️ No LLM toggle active, disabling Neural Core")
        return None

    model = MODELS[chosen]
    download(model["url"], model["path"])
    config["llm_model_url"] = model["url"]
    config["llm_model_path"] = model["path"]

    # make sure bot.py and llm_client see the new path
    os.environ["LLM_MODEL_PATH"] = model["path"]
    return model["path"]
