# /app/personality_state.py
from __future__ import annotations
import json
from pathlib import Path

def save_mood(path: Path, mood: str):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            data = json.loads(path.read_text())
        data["mood"] = mood
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass

def load_mood(path: Path) -> str | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return data.get("mood")
    except Exception:
        return None
