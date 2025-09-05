#!/usr/bin/env python3
# /app/heartbeat.py

import asyncio
from datetime import datetime, time as dtime, timedelta

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

def schedule(register, options: dict, send_message):
    """
    Register the heartbeat loop with the main bot.
    - register: function from bot.py that starts async jobs
    - options: merged config.json/options.json dict
    - send_message: core Jarvis sender (does persona riffs automatically)
    """
    if not options.get("heartbeat_enabled", False):
        return

    interval_min = int(options.get("heartbeat_interval_minutes", 120))
    start_str = str(options.get("heartbeat_start", "06:00"))
    end_str   = str(options.get("heartbeat_end", "20:00"))
    win_start, win_end = _parse_hhmm(start_str), _parse_hhmm(end_str)

    async def _loop():
        while True:
            now = datetime.now()
            if _within_window(now, win_start, win_end):
                msg = f"Pulse at {now.strftime('%H:%M')} — all systems nominal"
                try:
                    send_message("Heartbeat", msg, priority=3)
                except Exception as e:
                    print(f"[heartbeat] send failed: {e}")
            await asyncio.sleep(interval_min * 60)

    # run immediately at startup, then repeat
    async def _kickoff():
        try:
            now = datetime.now()
            if _within_window(now, win_start, win_end):
                msg = f"Initial heartbeat at {now.strftime('%H:%M')}"
                send_message("Heartbeat", msg, priority=3)
        except Exception as e:
            print(f"[heartbeat] initial send failed: {e}")
        await _loop()

    # bot.py's register() can handle named jobs, here we just spin up the loop
    asyncio.create_task(_kickoff())