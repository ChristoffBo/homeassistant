# /app/llm_client.py - tiny local LLM client with CPU/timeout guards
import time, json, requests
try:
    import psutil
except Exception:
    psutil = None

class DisabledError(Exception): pass
class GuardError(Exception): pass

def rewrite(text: str, mood: str, timeout: int, cpu_limit: int, models_priority, base_url: str) -> str:
    if not text:
        return ""
    # CPU guard
    if psutil is not None:
        try:
            if psutil.cpu_percent(interval=0.2) > cpu_limit:
                raise GuardError(f"CPU>{cpu_limit}%")
        except Exception:
            pass

    prompt = (
        f"Rewrite the following message concisely in a {mood} tone. "
        "Keep all critical data (titles, URLs, numbers, image links). "
        "Do not remove posters or links. Do not fabricate details.\n"
        f"Message:\n{text}"
    )

    last_err = None
    for model in models_priority or []:
        try:
            r = requests.post(
                f"{base_url.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=timeout
            )
            if r.status_code == 200:
                js = r.json()
                if isinstance(js, dict) and js.get("response"):
                    return str(js["response"]).strip()
            else:
                last_err = Exception(f"HTTP {r.status_code}")
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    raise TimeoutError("No model responded in time")
