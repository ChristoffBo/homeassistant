#!/usr/bin/env python3
# /app/heartbeat.py
#
# Jarvis Prime — Heartbeat helper
# Minimal, no extra knobs. Designed to work with bot.py's _heartbeat_scheduler_loop(),
# which calls build_heartbeat(options) on schedule and handles sending.
#
# You can also import schedule(register, options, send_message) from older bots; it
# remains as a compatibility wrapper that simply emits a basic heartbeat on an interval.

from __future__ import annotations
import asyncio
from datetime import datetime, time as dtime
from typing import Dict, Tuple

# -----------------------------
# Small helpers
# -----------------------------
def _parse_hhmm(s: str) -> dtime:
    """Parse 'HH:MM' into a datetime.time."""
    try:
        h, m = s.strip().split(":")
        return dtime(int(h), int(m))
    except Exception:
        return dtime(0, 0)

def _within_window(now: datetime, start: dtime, end: dtime) -> bool:
    """Check if current time is inside the allowed heartbeat window."""
    if start <= end:
        return start <= now.time() <= end
    # overnight window (e.g. 22:00–06:00)
    return now.time() >= start or now.time() <= end

def _ck(b: bool) -> str:
    return "✓" if bool(b) else "—"

def _onoff(b: bool) -> str:
    return "ON" if bool(b) else "OFF"

# -----------------------------
# Public API expected by bot.py
# -----------------------------
def build_heartbeat(options: Dict) -> Tuple[str, str]:
    """
    Return (title, message) for a heartbeat card.
    bot.py takes care of sending and adding the footer.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    llm_enabled   = bool(options.get("llm_enabled", False))
    riffs_enabled = bool(options.get("llm_persona_riffs_enabled", True))
    rewrite_on    = bool(options.get("llm_rewrite_enabled", False))

    env_on   = bool(options.get("llm_enviroguard_enabled", False))
    hot_c    = options.get("llm_enviroguard_hot_c", None)
    cold_c   = options.get("llm_enviroguard_cold_c", None)
    poll_min = options.get("llm_enviroguard_poll_minutes", None)

    # Intakes
    smtp_in   = bool(options.get("ingest_smtp_enabled", False))
    proxy_in  = bool(options.get("proxy_enabled", False))
    webhook   = bool(options.get("webhook_enabled", False))
    apprise   = bool(options.get("ingest_apprise_enabled", False))

    # Modules
    weather   = bool(options.get("weather_enabled", False))
    kuma      = bool(options.get("uptimekuma_enabled", False))
    technit   = bool(options.get("technitium_enabled", False))
    digest    = bool(options.get("digest_enabled", False))
    chat      = bool(options.get("chat_enabled", False))

    persona = str(options.get("active_persona", "auto"))

    lines = []
    lines.append(f"🫀 Heartbeat — {now}")
    lines.append(f"🧠 LLM: {_onoff(llm_enabled)}  |  Riffs: {_onoff(riffs_enabled)}  |  Rewrite: {_onoff(rewrite_on)}")
    if env_on:
        extra = []
        if isinstance(hot_c, (int, float)):  extra.append(f"hot≥{hot_c}°C")
        if isinstance(cold_c, (int, float)): extra.append(f"cold≤{cold_c}°C")
        if isinstance(poll_min, int):         extra.append(f"poll {poll_min}m")
        suffix = (" (" + ", ".join(extra) + ")") if extra else ""
        lines.append(f"🌡️ EnviroGuard: ON{suffix}")
    else:
        lines.append("🌡️ EnviroGuard: OFF")

    lines.append("")
    lines.append("Intakes")
    lines.append(f"• SMTP {_ck(smtp_in)}  • Proxy {_ck(proxy_in)}  • Webhook {_ck(webhook)}  • Apprise {_ck(apprise)}")
    lines.append("")
    lines.append("Modules")
    lines.append(f"• Weather {_ck(weather)}  • Uptime Kuma {_ck(kuma)}  • Technitium {_ck(technit)}  • Digest {_ck(digest)}  • Chat {_ck(chat)}")
    lines.append("")
    lines.append(f"Persona mode: {persona}")

    return "Heartbeat", "\n".join(lines)

# -----------------------------
# Back-compat shim (older bots)
# -----------------------------
def schedule(register, options: dict, send_message):
    """
    Legacy helper for older bots. New bot.py uses its own scheduler and this
    function is not called. Kept here to avoid breaking old setups.
    """
    if not options.get("heartbeat_enabled", False):
        return

    interval_min = int(options.get("heartbeat_interval_minutes", 120))
    win_start = _parse_hhmm(str(options.get("heartbeat_start", "06:00")))
    win_end   = _parse_hhmm(str(options.get("heartbeat_end", "20:00")))

    async def _loop():
        while True:
            now = datetime.now()
            if _within_window(now, win_start, win_end):
                title, msg = build_heartbeat(options)
                try:
                    # bot.py will add persona header and footer itself; keep decorate False to avoid double decoration
                    send_message(title, msg, priority=3, decorate=False)
                except Exception as e:
                    print(f"[heartbeat] send failed: {e}")
            await asyncio.sleep(max(1, int(interval_min)) * 60)

    asyncio.create_task(_loop())
