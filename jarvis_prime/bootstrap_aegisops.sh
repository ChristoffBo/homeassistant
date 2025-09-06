#!/usr/bin/env bash
# /share/jarvis_prime/bootstrap_aegisops.sh
set -euo pipefail

BASE="/share/jarvis_prime/aegisops"
mkdir -p "$BASE"/{playbooks,helpers,callback_plugins,db}

# ---------- ansible.cfg ----------
cat > "$BASE/ansible.cfg" <<'EOF'
[defaults]
inventory = /share/jarvis_prime/aegisops/inventory.ini
callback_plugins = /share/jarvis_prime/aegisops/callback_plugins
callbacks_enabled = jarvis_notify
retry_files_enabled = False
stdout_callback = yaml
host_key_checking = False
EOF

# ---------- inventory.ini ----------
cat > "$BASE/inventory.ini" <<'EOF'
[all]
jarvis ansible_host=127.0.0.1 ansible_user=root
EOF

# ---------- callback_plugins/jarvis_notify.py ----------
cat > "$BASE/callback_plugins/jarvis_notify.py" <<'EOF'
# AegisOps → Jarvis internal intake (separate from Jarvis DB)
# Posts summaries to http://127.0.0.1:2599/internal/aegisops
from __future__ import annotations
import json, os, urllib.request

DOCUMENTATION = r'''
callback: jarvis_notify
type: notification
short_description: Post AegisOps run summaries to Jarvis internal endpoint
description:
  - Sends a concise summary of each Ansible run to the Jarvis internal webhook.
options:
  url:
    description: Internal endpoint
    type: str
    default: http://127.0.0.1:2599/internal/aegisops
'''

class CallbackModule(object):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'jarvis_notify'

    def __init__(self):
        self.url = os.getenv("AEGISOPS_NOTIFY_URL", "http://127.0.0.1:2599/internal/aegisops")
        self.playbook = ""
        self.result_accum = { "ok":0, "changed":0, "failures":0, "unreachable":0 }

    def v2_playbook_on_start(self, playbook):
        self.playbook = getattr(playbook, "_file_name", "") or ""

    def v2_runner_on_ok(self, result):
        self.result_accum["ok"] += 1

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self.result_accum["failures"] += 1

    def v2_runner_on_unreachable(self, result):
        self.result_accum["unreachable"] += 1

    def v2_playbook_on_stats(self, stats):
        # Aggregate changed via stats (some modules report changed on ok path)
        try:
            for h in stats.processed.keys():
                s = stats.summarize(h)
                self.result_accum["changed"] += int(s.get("changed",0))
        except Exception:
            pass
        status = "ok" if (self.result_accum["failures"]==0 and self.result_accum["unreachable"]==0) else "fail"
        payload = {
            "title": "AegisOps",
            "message": f"Playbook: {self.playbook}\nStatus: {status}\nOK={self.result_accum['ok']} Changed={self.result_accum['changed']} Fail={self.result_accum['failures']} Unreach={self.result_accum['unreachable']}",
            "priority": 5 if status=="ok" else 7,
            "source": "aegisops",
            "playbook": self.playbook,
            "status": status,
            "ok": self.result_accum["ok"],
            "changed": self.result_accum["changed"],
            "failures": self.result_accum["failures"],
            "unreachable": self.result_accum["unreachable"],
            "target": "uptime"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers={"Content-Type":"application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as _:
                pass
        except Exception:
            # Never break the play if notify fails
            pass
EOF

# ---------- playbooks/check_services.yml ----------
cat > "$BASE/playbooks/check_services.yml" <<'EOF'
---
- name: AegisOps Uptime-lite
  hosts: "{{ target | default('all') }}"
  gather_facts: false
  vars_files:
    - /share/jarvis_prime/aegisops/uptime_targets.yml
  vars:
    default_timeout_s: 5
  tasks:
    - name: collect checks
      ansible.builtin.set_fact:
        host_checks: "{{ (checks | selectattr('target','equalto', inventory_hostname) | list) }}"
    - name: skip empty
      ansible.builtin.meta: end_host
      when: host_checks | length == 0
    - name: run checks
      ansible.builtin.include_tasks: /share/jarvis_prime/aegisops/helpers/_do_check.yml
      loop: "{{ host_checks }}"
      loop_control: { loop_var: _chk }
    - name: aggregate
      ansible.builtin.set_stats:
        data:
          aegisops_status: "{{ 'ok' if (hostvars[inventory_hostname]._results | selectattr('status','equalto','fail') | list | length) == 0 else 'fail' }}"
          details:
            host: "{{ inventory_hostname }}"
            checks: "{{ hostvars[inventory_hostname]._results | default([]) }}"
EOF

# ---------- helpers/_do_check.yml ----------
cat > "$BASE/helpers/_do_check.yml" <<'EOF'
---
- name: normalize
  ansible.builtin.set_fact:
    _timeout: "{{ (_chk.timeout_s | default(default_timeout_s)) | int }}"
    _expect: "{{ _chk.expect | default([200]) }}"
- name: ping
  when: _chk.mode == 'ping'
  block:
    - ansible.builtin.ping:
      register: _r
      ignore_errors: yes
    - ansible.builtin.set_fact:
        _results: "{{ (hostvars[inventory_hostname]._results | default([])) + [ {
          'name': _chk.name, 'mode': 'ping',
          'status': ('ok' if (_r is defined and (_r.ping | default('') == 'pong')) else 'fail'),
          'detail': (_r.msg | default('')) | string
        } ] }}"
- name: tcp
  when: _chk.mode == 'tcp'
  block:
    - ansible.builtin.wait_for:
        host: "{{ inventory_hostname }}"
        port: "{{ _chk.port }}"
        timeout: "{{ _timeout }}"
        state: started
      register: _r
      ignore_errors: yes
    - ansible.builtin.set_fact:
        _results: "{{ (hostvars[inventory_hostname]._results | default([])) + [ {
          'name': _chk.name, 'mode': 'tcp', 'port': _chk.port,
          'status': ('ok' if (_r is defined and not _r.failed) else 'fail'),
          'detail': (_r.msg | default('')) | string
        } ] }}"
- name: http
  when: _chk.mode == 'http'
  block:
    - ansible.builtin.uri:
        url: "{{ _chk.url }}"
        method: GET
        return_content: false
        timeout: "{{ _timeout }}"
        status_code: "{{ _expect }}"
        validate_certs: false
      register: _r
      ignore_errors: yes
    - ansible.builtin.set_fact:
        _results: "{{ (hostvars[inventory_hostname]._results | default([])) + [ {
          'name': _chk.name, 'mode': 'http', 'url': _chk.url,
          'status': ('ok' if (_r is defined and not _r.failed) else 'fail'),
          'detail': (_r.msg | default('')) | string
        } ] }}"
EOF

# ---------- uptime_targets.yml ----------
cat > "$BASE/uptime_targets.yml" <<'EOF'
checks:
  - { name: proxmox reachability, target: jarvis,  mode: ping }
  - { name: jarvis api http,      target: jarvis,  mode: http, url: "http://127.0.0.1:2581/api/messages?limit=1", expect: [200] }
  - { name: webhook tcp,          target: jarvis,  mode: tcp,  port: 2590, timeout_s: 5 }
EOF

# ---------- schedules.json ----------
cat > "$BASE/schedules.json" <<'EOF'
[
  {
    "id": "uptime-5m",
    "playbook": "check_services.yml",
    "servers": ["all"],
    "every": "5m",
    "forks": 1,
    "notify": {
      "on_success": false,
      "on_fail": true,
      "only_on_state_change": true,
      "cooldown_min": 30,
      "quiet_hours": "22:00-06:00",
      "target_key": "uptime"
    }
  }
]
EOF

# ---------- runner.py (own DB: /share/jarvis_prime/aegisops/db/aegisops.db) ----------
cat > "$BASE/runner.py" <<'EOF'
#!/usr/bin/env python3
import os, json, time, sqlite3, subprocess, threading, re
from datetime import datetime, timedelta

BASE = os.getenv("AEGISOPS_BASE", "/share/jarvis_prime/aegisops").rstrip("/")
DB   = f"{BASE}/db/aegisops.db"
SCH  = f"{BASE}/schedules.json"

def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS uptime_runs (
      id INTEGER PRIMARY KEY,
      ts DATETIME DEFAULT CURRENT_TIMESTAMP,
      host TEXT,
      check_name TEXT,
      mode TEXT,
      status TEXT,
      detail TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS ansible_runs (
      id INTEGER PRIMARY KEY,
      ts DATETIME DEFAULT CURRENT_TIMESTAMP,
      playbook TEXT,
      status TEXT,
      ok_count INTEGER,
      changed_count INTEGER,
      fail_count INTEGER,
      unreachable_count INTEGER,
      target_key TEXT
    )""")
    conn.commit()
    return conn

def _parse_every(s: str) -> int:
    m = re.match(r"^\s*(\d+)\s*([smhd])\s*$", str(s))
    if not m: return 300
    n, u = int(m.group(1)), m.group(2)
    return n * (1 if u=="s" else 60 if u=="m" else 3600 if u=="h" else 86400)

def _load_schedules():
    try:
        with open(SCH,"r") as f: return json.load(f)
    except Exception: return []

def _log_run(playbook, status, ok, changed, fail, unreach, target):
    try:
        conn = _db()
        conn.execute("INSERT INTO ansible_runs(playbook,status,ok_count,changed_count,fail_count,unreachable_count,target_key) VALUES (?,?,?,?,?,?,?)",
            (playbook, status, ok, changed, fail, unreach, target or ""))
        conn.commit()
        conn.close()
    except Exception as e:
        print("[aegisops] db log error:", e)

def _ansible_cmd(playbook, forks, limit):
    pb_path = f"{BASE}/playbooks/{playbook}"
    inv     = f"{BASE}/inventory.ini"
    cmd = ["ansible-playbook", "-i", inv, pb_path, "-f", str(int(forks or 1))]
    if limit and len(limit)>0:
        cmd += ["-l", ",".join(limit)]
    return cmd

def _run_once(job):
    playbook = job.get("playbook")
    forks    = job.get("forks",1)
    servers  = job.get("servers",[])
    cmd = _ansible_cmd(playbook, forks, servers)
    print("[aegisops] exec:", " ".join(cmd))
    # Let callback plugin post rich summary; here we capture simple exit
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        ok = (p.returncode == 0)
        status = "ok" if ok else "fail"
        # best-effort counters from output if present
        m = re.search(r"ok=(\d+).*changed=(\d+).*unreachable=(\d+).*failed=(\d+)", p.stdout + p.stderr)
        okc = chg = unreach = fail = 0
        if m:
            okc = int(m.group(1)); chg = int(m.group(2)); unreach = int(m.group(3)); fail = int(m.group(4))
        _log_run(playbook, status, okc, chg, fail, unreach, (job.get("notify") or {}).get("target_key",""))
    except Exception as e:
        print("[aegisops] run error:", e)
        _log_run(playbook, "fail", 0,0,0,0, (job.get("notify") or {}).get("target_key",""))

def _worker(job):
    every = _parse_every(job.get("every","5m"))
    next_ts = time.time()
    while True:
        now = time.time()
        if now >= next_ts:
            _run_once(job)
            next_ts = now + every
        time.sleep(1)

def main():
    os.environ.setdefault("ANSIBLE_CONFIG", f"{BASE}/ansible.cfg")
    if not os.path.isdir(BASE): print("[aegisops] base missing:", BASE); return
    print("[aegisops] runner online; schedules:", SCH)
    jobs = _load_schedules()
    if not jobs: print("[aegisops] no schedules.json entries found"); return
    for j in jobs:
        t = threading.Thread(target=_worker, args=(j,), daemon=True)
        t.start()
    while True:
        time.sleep(5)

if __name__ == "__main__":
    main()
EOF
chmod +x "$BASE/runner.py"

echo "✔ AegisOps bootstrap complete at $BASE"
echo "→ Now restart the Jarvis add-on. Logs should show: [launcher] starting AegisOps runner (runner.py)"
