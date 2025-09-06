#!/usr/bin/env python3
import os, json, time, subprocess, sys, threading, signal
from datetime import datetime

BASE = "/share/jarvis_prime/aegisops"
INV  = f"{BASE}/inventory.ini"
PB_DIR = f"{BASE}/playbooks"
CFG  = f"{BASE}/ansible.cfg"
SCHEDULES = f"{BASE}/schedules.json"

INTERVALS = {"5m":300, "15m":900, "1h":3600, "6h":21600, "24h":86400}

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[aegisops] {ts} {msg}", flush=True)

def load_schedules():
    try:
        with open(SCHEDULES, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            if not raw:
                return []
            data = json.loads(raw)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        log(f"waiting: {SCHEDULES} not found")
    except json.JSONDecodeError as e:
        log(f"schedules.json invalid JSON: {e}; treating as empty")
    except Exception as e:
        log(f"error reading schedules.json: {e}")
    return []

def seconds_for(every):
    return INTERVALS.get(str(every).lower().strip())

def run_playbook_once(item):
    pb_name = (item or {}).get("playbook")
    servers = (item or {}).get("servers", ["all"])
    forks = int((item or {}).get("forks", 1))

    if not pb_name:
        log("schedule missing playbook")
        return

    pb_path = f"{PB_DIR}/{pb_name}"
    if not os.path.isfile(pb_path):
        log(f"playbook not found: {pb_path}")
        return

    env = os.environ.copy()
    notify = (item or {}).get("notify", {}) or {}
    env["J_ON_SUCCESS"] = str(bool(notify.get("on_success", False))).lower()
    env["J_ON_FAIL"] = str(bool(notify.get("on_fail", True))).lower()
    env["J_ONLY_ON_STATE_CHANGE"] = str(bool(notify.get("only_on_state_change", True))).lower()
    env["J_COOLDOWN_MIN"] = str(int(notify.get("cooldown_min", 30)))
    env["J_QUIET_HOURS"] = str(notify.get("quiet_hours", "") or "")
    env["J_TARGET_KEY"] = str(notify.get("target_key", "") or "")
    env["ANSIBLE_CONFIG"] = CFG

    cmd = [
        "ansible-playbook", pb_path,
        "-i", INV,
        "--forks", str(forks),
        "--limit", ",".join(servers)
    ]

    log(f"run: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        log("ansible-playbook not found in PATH; install Ansible in the image")
    except Exception as e:
        log(f"playbook error: {e}")

def scheduler_loop():
    last_sig = 0
    while True:
        items = load_schedules()
        if not items:
            time.sleep(5)
            continue

        # build slots
        slots = []
        now = time.time()
        for it in items:
            every = seconds_for((it or {}).get("every"))
            if every:
                slots.append({"spec": it, "period": every, "next_due": now})

        if not slots:
            time.sleep(5)
            continue

        while True:
            now = time.time()
            for slot in slots:
                if now >= slot["next_due"]:
                    threading.Thread(target=run_playbook_once, args=(slot["spec"],), daemon=True).start()
                    slot["next_due"] = now + slot["period"]
            time.sleep(1)
            # Periodically break to re-read schedules.json (updates take effect)
            if int(now) % 30 == 0:
                break

def main():
    log(f"runner starting; BASE={BASE}")
    if not os.path.isdir(BASE):
        log(f"missing {BASE}; create it and add schedules.json / playbooks/")

    def handle_sig(sig, frame):
        log(f"signal {sig}; exiting")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sig)
    signal.signal(signal.SIGINT, handle_sig)

    while True:
        try:
            scheduler_loop()
        except Exception as e:
            log(f"scheduler crash: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
