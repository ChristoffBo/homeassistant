#!/usr/bin/env python3
import os, re, json, shlex, subprocess, threading, time, argparse
from flask import Flask, request, jsonify, send_file, send_from_directory

app = Flask(__name__, static_folder="www", static_url_path="")

DATA_DIR = "/config/remote_linux_backup"
STATE_DIR = os.path.join(DATA_DIR, "state")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
MOUNTS_BASE = "/mnt/rlb"

for d in (DATA_DIR, STATE_DIR, BACKUP_DIR, MOUNTS_BASE):
    os.makedirs(d, exist_ok=True)

STATE = {
    "connections_file": os.path.join(STATE_DIR, "connections.json"),
    "mounts_file": os.path.join(STATE_DIR, "mounts.json"),
    "notify_file": os.path.join(STATE_DIR, "notify.json"),
    "schedules_file": os.path.join(STATE_DIR, "schedules.json"),
}
for k,v in STATE.items():
    if not os.path.exists(v):
        with open(v, "w") as f: f.write(json.dumps([] if "connections" in k or "mounts" in k or "schedules" in k else {}))

JOBS = {"current": None, "history": []}
job_lock = threading.Lock()

def read_json(path, default):
    try:
        with open(path, "r") as f: return json.load(f)
    except Exception: return default

def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(data, f, indent=2)
    os.replace(tmp, path)

def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
    out, err = p.communicate()
    return p.returncode, out, err

def mountpoint(name): return os.path.join(MOUNTS_BASE, name)

# ---------- Static UI ----------
@app.get("/")
def ui_root(): return send_from_directory("www", "index.html")

# ---------- Connections ----------
@app.get("/api/connections")
def api_connections():
    return jsonify({"connections": read_json(STATE["connections_file"], [])})

@app.post("/api/connections/save")
def api_connections_save():
    b = request.json or {}
    data = read_json(STATE["connections_file"], [])
    data = [x for x in data if x.get("name") != b.get("name")]
    data.append({
        "name": b.get("name","").strip(),
        "host": b.get("host","").strip(),
        "port": int(b.get("port") or 22),
        "username": b.get("username","").strip(),
        "password": b.get("password",""),
    })
    write_json(STATE["connections_file"], data)
    return jsonify({"ok": True})

@app.post("/api/ssh/test")
def api_ssh_test():
    b = request.json or {}
    host = b.get("host",""); port = int(b.get("port") or 22)
    user = b.get("username",""); pw = b.get("password","")
    cmd = f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 -p {port} {shlex.quote(user)}@{shlex.quote(host)} echo OK"
    rc,out,err = run_cmd(cmd)
    return jsonify({"ok": rc==0 and 'OK' in out, "out": out, "err": err})

@app.post("/api/ssh/listdir")
def api_ssh_listdir():
    b = request.json or {}
    host=b.get("host"); port=int(b.get("port") or 22)
    user=b.get("username"); pw=b.get("password"); path=b.get("path") or "/"
    remote = f"ls -1p {shlex.quote(path)} || true"
    cmd = f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -p {port} {shlex.quote(user)}@{shlex.quote(host)} {remote}"
    rc,out,err = run_cmd(cmd)
    if rc!=0 and not out: return jsonify({"ok": False, "error": err})
    items=[]
    for line in out.splitlines():
        name=line.strip()
        if not name: continue
        if name.endswith("/"):
            items.append({"name":name[:-1], "dir": True})
        else:
            items.append({"name":name, "dir": False})
    return jsonify({"ok": True, "items": items})

@app.get("/api/local/listdir")
def api_local_listdir():
    path = request.args.get("path") or "/config"
    try:
        items=[]
        for e in os.scandir(path):
            items.append({"name": e.name, "dir": e.is_dir()})
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ---------- Mounts ----------
@app.get("/api/mounts")
def api_mounts():
    data = read_json(STATE["mounts_file"], [])
    for m in data:
        mp = mountpoint(m.get("name",""))
        m["mountpoint"] = mp
        m["mounted"] = os.path.ismount(mp)
        m.setdefault("last_error","")
    return jsonify({"mounts": data})

@app.post("/api/mounts/save")
def api_mounts_save():
    b = request.json or {}
    name=b.get("name","").strip()
    if not name: return jsonify({"ok": False, "error": "name required"}), 400
    data = read_json(STATE["mounts_file"], [])
    data = [x for x in data if x.get("name")!=name]
    item = {
        "name": name,
        "type": b.get("type","smb"),
        "host": b.get("host","").strip(),
        "share": b.get("share","").strip(),
        "username": b.get("username",""),
        "password": b.get("password",""),
        "options": b.get("options",""),
        "auto_retry": bool(int(b.get("auto_retry", 1))),
        "last_error": ""
    }
    data.append(item)
    write_json(STATE["mounts_file"], data)
    os.makedirs(mountpoint(name), exist_ok=True)
    return jsonify({"ok": True})

@app.post("/api/mounts/mount")
def api_mounts_mount():
    name=(request.json or {}).get("name","")
    data = read_json(STATE["mounts_file"], [])
    m = next((x for x in data if x.get("name")==name), None)
    if not m: return jsonify({"ok": False, "error":"not found"}), 404
    mp = mountpoint(name); os.makedirs(mp, exist_ok=True)
    if m["type"]=="smb":
        unc=f"//{m['host']}/{m['share']}"
        opts=m.get("options","")
        if m.get("username"): opts=f"username={m['username']},password={m.get('password','')}" + ("," + opts if opts else "")
        else: opts="guest" + ("," + opts if opts else "")
        cmd=f"mount -t cifs {shlex.quote(unc)} {shlex.quote(mp)} -o {shlex.quote(opts)}"
    else:
        export = m["share"] if m["share"].startswith("/") else "/"+m["share"]
        opts=m.get("options","")
        cmd=f"mount -t nfs {shlex.quote(m['host']+':'+export)} {shlex.quote(mp)}" + (f" -o {shlex.quote(opts)}" if opts else "")
    rc,out,err = run_cmd(cmd + " 2>&1 || true")
    ok = os.path.ismount(mp)
    if not ok:
        # userspace fallback for SMB: copy without mounting
        if m["type"]=="smb":
            m["last_error"]= "kernel mount failed; will use userspace copy when selected"
            write_json(STATE["mounts_file"], data)
            return jsonify({"ok": False, "error": "kernel mount failed; userspace copy will be used"})
        m["last_error"]= out or err
        write_json(STATE["mounts_file"], data)
        return jsonify({"ok": False, "error": out or err})
    m["last_error"]=""; write_json(STATE["mounts_file"], data)
    return jsonify({"ok": True})

@app.post("/api/mounts/unmount")
def api_mounts_unmount():
    name=(request.json or {}).get("name","")
    rc,out,err = run_cmd(f"umount {shlex.quote(mountpoint(name))} 2>&1 || true")
    return jsonify({"ok": True})

@app.post("/api/mounts/test")
def api_mounts_test():
    b=request.json or {}
    t=b.get("type"); host=b.get("host"); user=b.get("username",""); pw=b.get("password","")
    if t=="smb":
        auth = f"-U {shlex.quote(user+'%'+pw)}" if user else "-N"
        rc,out,err = run_cmd(f"smbclient -L //{shlex.quote(host)} {auth} -g 2>&1 || true")
        shares = [x.split('|')[1] for x in out.splitlines() if x.startswith('Disk|')]
        return jsonify({"ok": len(shares)>0, "shares": shares, "raw": out})
    else:
        rc,out,err = run_cmd(f"showmount -e {shlex.quote(host)} 2>&1 || true")
        exports = [line.split()[0] for line in out.splitlines() if line.strip().startswith('/')]
        return jsonify({"ok": len(exports)>0, "exports": exports, "raw": out})

# ---------- SMB userspace list + copy ----------
@app.post("/api/smb/listdir")
def api_smb_listdir():
    b=request.json or {}
    host=b.get("host"); share=b.get("share"); user=b.get("username",""); pw=b.get("password",""); path=b.get("path","/")
    auth = f"-U {shlex.quote(user+'%'+pw)}" if user else "-N"
    # smbclient 'ls' shows directories ending with /
    cmd = f"smbclient //{shlex.quote(host)}/{shlex.quote(share)} {auth} -c 'cd {shlex.quote(path)}; ls' 2>&1 || true"
    rc,out,err = run_cmd(cmd)
    items=[]
    for line in out.splitlines():
        line=line.strip()
        if not line or line.startswith('  .') or line.startswith('  ..'): continue
        parts = line.split()
        name = parts[0]
        is_dir = name.endswith('/')
        items.append({"name": name.rstrip('/'), "dir": is_dir})
    return jsonify({"ok": True, "items": items, "raw": out})

@app.post("/api/smb/copy")
def api_smb_copy():
    b=request.json or {}
    host=b.get("host"); share=b.get("share"); user=b.get("username",""); pw=b.get("password","")
    src=b.get("source_path","/"); label=b.get("label","smbcopy")
    dest_root = os.path.join(BACKUP_DIR, f"{label}-{int(time.time())}")
    os.makedirs(dest_root, exist_ok=True)
    auth = f"-U {shlex.quote(user+'%'+pw)}" if user else "-N"
    # Recursively get everything from src
    cmd = f"smbclient //{shlex.quote(host)}/{shlex.quote(share)} {auth} -c 'prompt OFF; recurse ON; cd {shlex.quote(src)}; mget *' -D {shlex.quote(dest_root)}"
    return start_job(cmd, "rsync_like")

# ---------- Backups management ----------
@app.get("/api/backups")
def api_backups():
    items=[]
    for root,_,files in os.walk(BACKUP_DIR):
        for f in files:
            p=os.path.join(root,f)
            try: sz=os.path.getsize(p)
            except: sz=0
            items.append({"id": os.path.relpath(p, BACKUP_DIR), "label": f, "size": sz, "location": os.path.relpath(root, BACKUP_DIR)})
    return jsonify({"items": sorted(items, key=lambda x: x['label'], reverse=True)})

@app.post("/api/backups/delete")
def api_backups_delete():
    bid=(request.json or {}).get("id","")
    p=os.path.normpath(os.path.join(BACKUP_DIR,bid))
    if not p.startswith(BACKUP_DIR): return jsonify({"ok": False}), 400
    try: os.remove(p); return jsonify({"ok": True})
    except Exception as e: return jsonify({"ok": False, "error": str(e)})

@app.get("/api/backups/download")
def api_backups_download():
    bid=request.args.get("id",""); p=os.path.normpath(os.path.join(BACKUP_DIR,bid))
    if not p.startswith(BACKUP_DIR) or not os.path.exists(p): return ("not found",404)
    return send_file(p, as_attachment=True)

# ---------- Jobs ----------
def start_job(cmd, kind, size_hint=0):
    with job_lock:
        if JOBS["current"]:
            return jsonify({"ok": False, "error": "job already running"})
        JOBS["current"]={"id": int(time.time()), "cmd": cmd, "kind": kind, "progress":0, "status":"running", "log":[]}

    def runner():
        job=JOBS["current"]
        try:
            p=subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True, bufsize=1)
            for line in p.stdout:
                job["log"].append(line.rstrip())
                # Try parse percent
                m=re.search(r"(\\d+)%", line); 
                if m: job["progress"]=int(m.group(1))
            rc=p.wait(); job["status"]="success" if rc==0 else "error"
            if rc==0: job["progress"]=100
        except Exception as e:
            job["status"]="error"; job["log"].append(str(e))
        finally:
            JOBS["history"].append(job); JOBS["current"]=None
    threading.Thread(target=runner, daemon=True).start()
    return jsonify({"ok": True})

@app.get("/api/jobs")
def api_jobs():
    j=JOBS["current"]
    return jsonify([j] if j else [])

@app.post("/api/jobs/cancel")
def api_jobs_cancel():
    run_cmd("pkill -f 'rsync|ssh .* dd|smbclient' || true")
    return jsonify({"ok": True})

# ---------- Backup start ----------
@app.post("/api/backup/start")
def api_backup_start():
    b=request.json or {}
    mode=b.get("mode","rsync")
    label=b.get("label","backup")
    dest_type=b.get("dest_type","local")
    dest_mount=b.get("dest_mount_name","")
    bwkb=int(b.get("bwlimit_kbps") or 0)
    dest_root = BACKUP_DIR if dest_type=="local" else os.path.join(mountpoint(dest_mount), "rlb_backups")
    os.makedirs(dest_root, exist_ok=True)
    out_dir=os.path.join(dest_root, f"{label}-{int(time.time())}")
    os.makedirs(out_dir, exist_ok=True)

    if mode=="rsync":
        host=b.get("host"); user=b.get("username"); pw=b.get("password"); src=b.get("source_path","/")
        bw = f"--bwlimit={bwkb}" if bwkb>0 else ""
        cmd = f"RSYNC_RSH='sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -p 22' rsync -a --info=progress2 {bw} {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src).rstrip('/')}/ {shlex.quote(out_dir)}/"
        return start_job(cmd, "rsync")
    elif mode=="copy_local":
        src=b.get("source_path","/config"); bw=f'--bwlimit={bwkb}' if bwkb>0 else ''
        cmd=f"rsync -a --info=progress2 {bw} {shlex.quote(src).rstrip('/')}/ {shlex.quote(out_dir)}/"; return start_job(cmd,"rsync")
    elif mode=="copy_mount":
        # If kernel mount exists, copy from mountpoint; else fallback via smbclient copy endpoint
        name=b.get("mount_name"); src=b.get("source_path","/")
        mp=mountpoint(name)
        if os.path.ismount(mp):
            cmd=f"rsync -a --info=progress2 {shlex.quote(os.path.join(mp, src.lstrip('/'))).rstrip('/')}/ {shlex.quote(out_dir)}/"
            return start_job(cmd,"rsync")
        else:
            # userspace smbclient fallback
            mounts=read_json(STATE['mounts_file'],[])
            m=next((x for x in mounts if x.get('name')==name),None)
            if not m or m.get('type')!='smb':
                return jsonify({'ok': False, 'error':'Mount not available (kernel) and no SMB fallback'}), 400
            auth = f"-U {shlex.quote((m.get('username','')+'%'+m.get('password','')))}" if m.get('username') else "-N"
            cmd = f"smbclient //{shlex.quote(m['host'])}/{shlex.quote(m['share'])} {auth} -c 'prompt OFF; recurse ON; cd {shlex.quote(src)}; mget *' -D {shlex.quote(out_dir)}"
            return start_job(cmd,"rsync_like")
    else:
        host=b.get("host"); user=b.get("username"); pw=b.get("password"); dev=b.get("device","/dev/sda")
        size_cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {shlex.quote(user)}@{shlex.quote(host)} 'blockdev --getsize64 {shlex.quote(dev)}'"
        rc,out,err = run_cmd(size_cmd)
        try: size=int(out.strip())
        except: size=0
        out_file=os.path.join(out_dir,"disk.img.gz")
        cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(dev)} bs=4M status=none' | pv -n -s {size} | gzip > {shlex.quote(out_file)}"
        return start_job(cmd,"pv",size_hint=size)

# ---------- Notifications / Gotify ----------
@app.get("/api/notify/config")
def api_notify_get(): return jsonify(read_json(STATE["notify_file"], {}))

@app.post("/api/notify/config")
def api_notify_set(): write_json(STATE["notify_file"], request.json or {}); return jsonify({"ok": True})

@app.post("/api/notify/test")
def api_notify_test():
    cfg=read_json(STATE["notify_file"], {})
    if not cfg.get("url") or not cfg.get("token"): return jsonify({"ok": False, "error":"missing url/token"})
    msg="RLB test message"; pr=int(cfg.get("priority") or 5)
    cmd=f"curl -fsSL -X POST {shlex.quote(cfg['url'].rstrip('/')+'/message')} -H 'X-Gotify-Key: {cfg['token']}' -F title='RLB Test' -F priority='{pr}' -F message='{msg}'"
    rc,out,err = run_cmd(cmd + " 2>&1 || true")
    return jsonify({"ok": rc==0, "out": out or err})

# ---------- System update (safe) ----------
@app.post("/api/system/apt_upgrade")
def api_system_apt_upgrade():
    # Prechecks: DNS, dpkg/apt locks, internet
    checks=[
        "getent hosts deb.debian.org >/dev/null 2>&1 || getent hosts google.com >/dev/null 2>&1",
        "test ! -e /var/lib/dpkg/lock-frontend",
        "test ! -e /var/lib/apt/lists/lock"
    ]
    for c in checks:
        rc,_,_ = run_cmd(c); if rc!=0: return jsonify({"ok": False, "error": f"Pre-check failed: {c}"})
    cmds="export DEBIAN_FRONTEND=noninteractive; apt-get update -y && apt-get -y --with-new-pkgs upgrade"
    rc,out,err = run_cmd(cmds + " 2>&1 || true")
    ok=("E:" not in out and "Failed to fetch" not in out)
    return jsonify({"ok": ok, "output": (out[-4000:] if len(out)>4000 else out)})

# ---------- CLI ----------
if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8066); args=ap.parse_args()
    app.run(host="0.0.0.0", port=args.port)
