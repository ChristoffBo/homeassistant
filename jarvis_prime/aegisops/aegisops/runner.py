#!/usr/bin/env python3
import os, json, time, subprocess
from helpers.db import init as db_init, purge_older_than_days

SCHEDULES = "/share/jarvis_prime/aegisops/schedules.json"
ANSIBLE_CFG_DIR = "/share/jarvis_prime/aegisops"
DEFAULT_KEEP_DAYS = int(os.getenv("AEGISOPS_KEEP_DAYS", "30"))

def _load_schedules():
    if not os.path.exists(SCHEDULES):
        return []
    with open(SCHEDULES, "r", encoding="utf-8") as f:
        return json.load(f)

def _parse_every(s):
    n = int(''.join([c for c in s if c.isdigit()]) or "5")
    u = ''.join([c for c in s if c.isalpha()]) or "m"
    if u == "m": return n * 60
    if u == "h": return n * 3600
    if u == "d": return n * 86400
    return 300

def run_playbook(playbook, servers, forks, target_key):
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = os.path.join(ANSIBLE_CFG_DIR, "ansible.cfg")
    env["AEGISOPS_PLAYBOOK"] = playbook
    env["AEGISOPS_TARGET_KEY"] = target_key
    cmd = [
        "ansible-playbook",
        os.path.join(ANSIBLE_CFG_DIR, "playbooks", playbook),
        "-i", os.path.join(ANSIBLE_CFG_DIR, "inventory.ini"),
        "--forks", str(forks),
        "--limit", ",".join(servers)
    ]
    subprocess.run(cmd, env=env)

def main():
    db_init()
    last_run = {}
    while True:
        schedules = _load_schedules()
        now = time.time()
        for sch in schedules:
            interval = _parse_every(sch.get("every", "5m"))
            sid = sch["id"]
            if sid not in last_run or now - last_run[sid] >= interval:
                run_playbook(
                    sch["playbook"],
                    sch.get("servers", ["all"]),
                    sch.get("forks", 1),
                    sch.get("notify", {}).get("target_key", "")
                )
                last_run[sid] = now
        purge_older_than_days(DEFAULT_KEEP_DAYS)
        time.sleep(30)

if __name__ == "__main__":
    main()
