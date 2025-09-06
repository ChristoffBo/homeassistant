import os, json, sqlite3
from flask import request, Blueprint, g

# AegisOps → Jarvis inbox bridge (no AegisOps history here)
bp_aegisops = Blueprint("aegisops_internal", __name__)
JARVIS_DB = "/share/jarvis_prime/db/jarvis.db"

def _db():
    if "db" not in g:
        g.db = sqlite3.connect(JARVIS_DB)
    return g.db

def _auth(req):
    src = req.remote_addr or ""
    if src in ("127.0.0.1","::1"):
        return True
    token = req.headers.get("Authorization","")
    want  = os.getenv("JARVIS_INTERNAL_TOKEN","")
    return bool(want and token == f"Bearer {want}")

@bp_aegisops.post("/internal/aegisops")
def aegisops_emit():
    if not _auth(request):
        return ("forbidden", 403)
    p = request.get_json(force=True) or {}
    title = p.get("title","AegisOps")
    msg   = p.get("message","")
    prio  = int(p.get("priority", 5))
    tags  = json.dumps(["aegisops", p.get("status","ok"), p.get("target","")])

    db = _db()
    db.execute("""CREATE TABLE IF NOT EXISTS inbox (
      id INTEGER PRIMARY KEY,
      ts DATETIME DEFAULT CURRENT_TIMESTAMP,
      source TEXT, title TEXT, message TEXT,
      priority INTEGER, tags TEXT
    )""")
    db.execute("INSERT INTO inbox(source,title,message,priority,tags) VALUES(?,?,?,?,?)",
               ("aegisops", title, msg, prio, tags))
    db.commit()
    return ("ok", 200)
