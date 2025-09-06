# AegisOps Ansible callback plugin
# - Records playbook summaries into /share/jarvis_prime/aegisops/db/aegisops.db
# - Optionally sends a short toast to Jarvis inbox via /internal/aegisops
#
# Enable in ansible.cfg:
#   [defaults]
#   callback_plugins = /share/jarvis_prime/aegisops/callback_plugins
#   callbacks_enabled = aegisops_notify
#
# Env toggles (optional):
#   AEGISOPS_NOTIFY_INBOX=true|false     (default: true)
#   JARVIS_INTERNAL_POST=http://127.0.0.1:2599/internal/aegisops
#   JARVIS_INTERNAL_TOKEN=<bearer token if not localhost>
#   AEGISOPS_PLAYBOOK=<playbook name override>
#   AEGISOPS_TARGET_KEY=<target key to tag runs>

from __future__ import annotations
import os, sqlite3
from pathlib import Path
from ansible.plugins.callback import CallbackBase

# ---- Inbox post (optional) ----
def _post_inbox(title: str, message: str, status: str, target: str):
    if os.getenv("AEGISOPS_NOTIFY_INBOX", "true").lower() != "true":
        return
    try:
        import requests  # optional dependency
        url = os.getenv("JARVIS_INTERNAL_POST", "http://127.0.0.1:2599/internal/aegisops")
        headers = {"Content-Type": "application/json"}
        tok = os.getenv("JARVIS_INTERNAL_TOKEN", "")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        requests.post(url, headers=headers, json={
            "title": title,
            "message": message,
            "status": status,
            "target": target,
            "priority": 5
        }, timeout=3)
    except Exception:
        # Never break the play because of notifications.
        pass

# ---- DB helpers ----
AEGIS_DB = "/share/jarvis_prime/aegisops/db/aegisops.db"

def _db_init(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS aegisops_runs (
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

def _db_insert(playbook: str, status: str, ok: int, changed: int, failed: int, unreachable: int, target_key: str):
    Path(os.path.dirname(AEGIS_DB)).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AEGIS_DB)
    try:
        _db_init(conn)
        conn.execute(
            "INSERT INTO aegisops_runs(playbook,status,ok_count,changed_count,fail_count,unreachable_count,target_key) "
            "VALUES(?,?,?,?,?,?,?)",
            (playbook, status, ok, changed, failed, unreachable, target_key)
        )
        conn.commit()
    finally:
        conn.close()

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "aegisops_notify"
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()
        self._reset()
        self._playbook_name = None

    def _reset(self):
        self.ok = 0
        self.changed = 0
        self.failures = 0
        self.unreachable = 0

    # Runner event counters
    def v2_runner_on_ok(self, result, **kwargs):
        self.ok += 1

    def v2_runner_on_changed(self, result, **kwargs):
        self.changed += 1

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self.failures += 1

    def v2_runner_on_unreachable(self, result):
        self.unreachable += 1

    # Capture playbook name if available
    def v2_playbook_on_start(self, playbook):
        try:
            self._playbook_name = getattr(playbook, "_file_name", None) or getattr(playbook, "_name", None)
        except Exception:
            self._playbook_name = None

    # Final summary hook
    def v2_playbook_on_stats(self, stats):
        status = "ok" if (self.failures == 0 and self.unreachable == 0) else "fail"
        # Allow override via env to keep names clean in DB
        playbook = os.getenv("AEGISOPS_PLAYBOOK") or (self._playbook_name or "playbook")
        target_key = os.getenv("AEGISOPS_TARGET_KEY", "")

        # 1) Persist run summary to AegisOps DB
        _db_insert(
            playbook=playbook,
            status=status,
            ok=self.ok,
            changed=self.changed,
            failed=self.failures,
            unreachable=self.unreachable,
            target_key=target_key
        )

        # 2) Optional inbox toast for Jarvis UI
        title = f"AegisOps: {playbook} → {status.upper()}"
        message = f"ok={self.ok} changed={self.changed} failed={self.failures} unreachable={self.unreachable}"
        _post_inbox(title, message, status, target_key)

        # Reset counters for safety on next run
        self._reset()
