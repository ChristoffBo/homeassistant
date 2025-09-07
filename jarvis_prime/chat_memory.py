#!/usr/bin/env python3
# /app/chat_memory.py
#
# Jarvis Prime — Chat Memory Manager
# Keeps rolling history of chat messages (user + bot) for persona-driven chat.
# Stores to a JSON file under /share/jarvis_prime so history survives restarts.

import os
import json
import time
from typing import List, Dict, Any

# ============================
# Config
# ============================
DEFAULT_MAX_TURNS = 24
MEMORY_FILE = "/share/jarvis_prime/chat_history.json"

# ============================
# Core functions
# ============================
def _load_history() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[chat_memory] load failed: {e}", flush=True)
    return []

def _save_history(history: List[Dict[str, Any]]):
    try:
        os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[chat_memory] save failed: {e}", flush=True)

def add_message(role: str, text: str, max_turns: int = DEFAULT_MAX_TURNS):
    """
    Add a message to chat history.
    role = "user" or "bot"
    text = message string
    """
    history = _load_history()
    history.append({
        "role": role,
        "text": text.strip(),
        "ts": time.time()
    })
    # keep last 2*max_turns (user+bot per turn)
    keep = max_turns * 2
    if len(history) > keep:
        history = history[-keep:]
    _save_history(history)

def get_context(max_turns: int = DEFAULT_MAX_TURNS) -> str:
    """
    Return chat history formatted as alternating user/bot lines.
    """
    history = _load_history()
    keep = max_turns * 2
    if len(history) > keep:
        history = history[-keep:]
    lines: List[str] = []
    for h in history:
        who = "User" if h["role"] == "user" else "Jarvis"
        lines.append(f"{who}: {h['text']}")
    return "\n".join(lines)

def clear():
    """Wipe chat history completely."""
    _save_history([])

# ============================
# Self-test
# ============================
if __name__ == "__main__":
    print("chat_memory self-test")
    clear()
    add_message("user", "Hello?")
    add_message("bot", "Hi, I’m Jarvis.")
    add_message("user", "How are you?")
    add_message("bot", "Still alive, thanks for asking.")
    print(get_context())
