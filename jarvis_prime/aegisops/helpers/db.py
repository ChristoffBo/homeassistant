import os, sqlite3
from contextlib import contextmanager

DB_PATH = "/share/jarvis_prime/aegisops/db/aegisops.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS aegisops_runs (
  id INTEGER PRIMARY KEY,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  playbook TEXT,
  status TEXT,
  ok_count INTEGER,
  changed_count INTEGER,
  fail_count INTEGER,
  unreachable_count INTEGER,
  target_key TEXT
);
CREATE TABLE IF NOT EXISTS uptime_runs (
  id INTEGER PRIMARY KEY,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  host TEXT,
  check_name TEXT,
  mode TEXT,
  status TEXT,
  detail TEXT
);
"""

def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            db.execute(stmt + ";")
        db.commit()

@contextmanager
def connect():
    init()
    db = sqlite3.connect(DB_PATH)
    try:
        yield db
    finally:
        db.close()

def purge_older_than_days(days: int = 30):
    with connect() as db:
        db.execute("DELETE FROM aegisops_runs WHERE ts < DATETIME('now', ?)", (f'-{days} days',))
        db.execute("DELETE FROM uptime_runs WHERE ts < DATETIME('now', ?)", (f'-{days} days',))
        db.commit()
