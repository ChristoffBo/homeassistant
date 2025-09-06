#!/usr/bin/env python3
# AegisOps runner.py
# - Reads schedules.json
# - Executes ansible-playbook at intervals
# - Pushes results via callback plugin (aegisops_notify)

import os, json, time, asyncio, subprocess, signal
from datetime import datetime, timedelta

BASE = "/share/jarvis_prime/aegisops"
SCHEDULES_FILE = os.path.join(BASE, "schedules.json")
PLAYBOOKS_DIR = os.path.join(BASE, "playbooks")

DEFAULT_INTERVALS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "24h": 24 * 60 * 60,
}

class Schedule:
    def __init__(self, entry: dict):
        self.id = entry.get("id")
        self.playbook = entry.get("playbook")
        self.servers = entry.get("servers", ["all"])
        self.every = entry.get("every", "1h")
        self.forks = int(entry.get("forks", 1))
        self.notify = entry.get("notify", {})
        self.next_run = datetime.now()

    def interval_seconds(self):
        return DEFAULT_INTERVALS.get(self.every, 3600)

    def due(self):
        return datetime.now() >= self.next_run

    def bump(self):
        self.next_run = datetime.now() + timedelta(seconds=self.interval_seconds())

async def run_playbook(schedule: Schedule):
    pb_path = os.path.join(PLAYBOOKS_DIR, schedule.playbook)
    if not os.path.isfile(pb_path):
        print(f"[runner] missing playbook {pb_path}")
        return
    cmd = [
        "ansible-playbook", pb_path,
        "-i", os.path.join(BASE, "inventory.ini"),
        "--forks", str(schedule.forks)
    ]
    if schedule.servers and schedule.servers != ["all"]:
        cmd.extend(["-l", ",".join(schedule.servers)])

    env = os.environ.copy()
    # Pass notify flags for callback plugin
    for k, v in schedule.notify.items():
        env[f"J_{k.upper()}"] = str(v)

    print(f"[runner] running schedule {schedule.id} → {cmd}")
    try:
        subprocess.run(cmd, env=env, check=False)
    except Exception as e:
        print(f"[runner] error executing {cmd}: {e}")

async def main():
    while True:
        try:
            if not os.path.isfile(SCHEDULES_FILE):
                await asyncio.sleep(30)
                continue

            with open(SCHEDULES_FILE, "r") as f:
                data = json.load(f)
            schedules = [Schedule(entry) for entry in data]

            while True:
                for sched in schedules:
                    if sched.due():
                        await run_playbook(sched)
                        sched.bump()
                await asyncio.sleep(5)
        except Exception as e:
            print(f"[runner] loop error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[runner] stopped by user")
        try:
            os.killpg(0, signal.SIGTERM)
        except Exception:
            pass
