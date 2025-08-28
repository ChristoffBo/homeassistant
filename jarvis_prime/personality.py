#!/usr/bin/env python3
# /app/personality.py
import random

def decorate(title: str, message: str, mood: str, chance: float = 1.0):
    """
    Prepend a strong, visible mood banner. Does not alter the content semantics.
    """
    if random.random() > float(chance or 1.0):
        return title, message

    m = (mood or "serious").lower().strip()
    banners = {
        "serious":  ("🛡️ PRIME / ANALYTIC",),
        "playful":  ("🎭 PRIME / PLAYFUL",),
        "angry":    ("⚡ PRIME / FURY",),
        "happy":    ("✨ PRIME / RADIANT",),
        "sad":      ("🌘 PRIME / CALM",),
    }
    head = banners.get(m, ("🛡️ PRIME / ANALYTIC",))[0]
    body = (message or "").strip()
    return title, f"{head}\n{body}"

def apply_priority(priority: int, mood: str) -> int:
    """
    Slightly bias priority based on mood.
    """
    m = (mood or "").lower()
    if m == "angry":   return min(10, max(1, priority + 1))
    if m == "happy":   return min(10, max(1, priority))
    if m == "playful": return min(10, max(1, priority))
    if m == "sad":     return max(1, priority - 1)
    return priority

def quip(mood: str) -> str:
    q = {
        "serious": "Status green across the board.",
        "playful": "Sparkles and uptime, baby.",
        "angry":   "If it breaks, I break it back.",
        "happy":   "Everything’s humming. Feels good.",
        "sad":     "Quiet skies… for now.",
    }
    return q.get((mood or "").lower(), "Operational.")
