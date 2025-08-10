#!/usr/bin/env python3
import os, re, json, shlex, subprocess, threading, time, argparse, datetime
from flask import Flask, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename

try:
    import paramiko
except Exception:
    paramiko = None

app = Flask(__name__, static_folder="www", static_url_path="")

DATA_DIR   = "/config/remote_linux_backup"
STATE_DIR  = os.path.join(DATA_DIR, "state")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
MOUNTS_BASE = "/mnt/rlb"

for d in (DATA_DIR, STATE_DIR, BACKUP_DIR, UPLOAD_DIR, MOUNTS_BASE):
    os.makedirs(d, exist_ok=True)

PATHS = {
    "connections": os.path.join(STATE_DIR, "connections.json"),
    "mounts":      os.path.join(STATE_DIR, "mounts.json"),
    "notify":      os.path.join(STATE_DIR, "notify.json"),
    "schedules":   os.path.join(STATE_DIR, "schedules.json"),
    "settings":    os.path.join(STATE_DIR, "settings.json"),
    "history":     os.path.join(STATE_DIR, "history.json"),
}

def _init(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)
for k, p in PATHS.items():
    _init(p, [] if k in ("connections","mounts","schedules","history") else {})

def read_json(p, d):
    try:
        with open(p, "r") as f: 
            return json.load(f)
    except Exception:
        return d

def write_json(p, d):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, p)

def mountpoint(name: str) -> str:
    return os.path.join(MOUNTS_BASE, name)

def run_cmd(cmd: str):
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=True,
        executable="/bin/bash",
    )
    out, err = p.communicate()
    return p.returncode, out, err

# ----------------- Job worker -----------------
class JobWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.queue = []
        self.cur = None
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)

    def submit(self, job):
        with self.lock:
            self.queue.append(job)
            self.cv.notify_all()
        return {"ok": True, "queued": True}

    def cancel(self):
        run_cmd("pkill -f 'rsync|ssh .* dd|smbclient|pv' || true")
        return {"ok": True}

    def run(self):
        while True:
            with self.lock:
                while not self.queue:
                    self.cv.wait()
                job = self.queue.pop(0)
                self.cur = job
                job["status"] = "running"
                job["progress"] = 0
                job["log"] = []
                job["started"] = int(time.time())

            try:
                p = subprocess.Popen(
                    job["cmd"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=True,
                    executable="/bin/bash",
                    bufsize=1,
                )
                for line in p.stdout:
                    line = line.rstrip()
                    job["log"].append(line)
                    m = re.search(r"(\d+)%", line)
                    if m:
                        try:
                            job["progress"] = min(100, max(0, int(m.group(1))))
                        except Exception:
                            pass
                rc = p.wait()
                job["status"] = "success" if rc == 0 else "error"
                job["progress"] = 100 if rc == 0 else job.get("progress", 0)
            except Exception as e:
                job["status"] = "error"
                job.setdefault("log", []).append(str(e))
            finally:
                job["ended"] = int(time.time())
                hist = read_json(PATHS["history"], [])
                hist.append({
                    k: job.get(k)
                    for k in ("id","kind","label","status","started","ended","dest","mode")
                })
                write_json(PATHS["history"], hist)
                with self.lock:
                    self.cur = None

worker = JobWorker(); worker.start()

@app.get("/api/jobs")
def api_jobs():
    with worker.lock:
        cur = worker.cur
    return jsonify([cur] if cur else [])

@app.post("/api/jobs/cancel")
def api_jobs_cancel():
    return jsonify(worker.cancel())

# ----------------- Connections & SSH browse -----------------
@app.get("/api/connections")
def api_connections():
    return jsonify({"connections": read_json(PATHS["connections"], [])})

@app.post("/api/connections/save")
def api_connections_save():
    b = request.json or {}
    data = read_json(PATHS["connections"], [])
    data = [x for x in data if x.get("name") != b.get("name")]
    data.append({
        "name": b.get("name", "").strip(),
        "host": b.get("host", "").strip(),
        "port": int(b.get("port") or 22),
        "username": b.get("username", "").strip(),
        "password": b.get("password", ""),
    })
    write_json(PATHS["connections"], data)
    return jsonify({"ok": True})

@app.post("/api/ssh/test")
def api_ssh_test():
    b   = request.json or {}
    host = b.get("host", "")
    port = int(b.get("port") or 22)
    user = b.get("username", "")
    pw   = b.get("password", "")
    keep = "-o ServerAliveInterval=30 -o ServerAliveCountMax=6"
    cmd  = (
        f"sshpass -p {shlex.quote(pw)} "
        f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 {keep} -p {port} "
        f"{shlex.quote(user)}@{shlex.quote(host)} echo OK"
    )
    rc, out, err = run_cmd(cmd)
    return jsonify({"ok": rc == 0 and "OK" in out, "out": out, "err": err})

@app.post("/api/ssh/listdir")
def api_ssh_listdir():
    b = request.json or {}
    host = b.get("host"); port = int(b.get("port") or 22)
    user = b.get("username"); pw = b.get("password")
    path = b.get("path") or "/"

    if paramiko:
        try:
            t = paramiko.Transport((host, port))
            t.connect(username=user, password=pw)
            sftp = paramiko.SFTPClient.from_transport(t)
            items = [{
                "name": e.filename,
                "dir": bool(e.st_mode & 0o040000),
                "size": e.st_size
            } for e in sftp.listdir_attr(path)]
            sftp.close(); t.close()
            return jsonify({"ok": True, "items": items})
        except Exception:
            pass

    remote = f"ls -1p {shlex.quote(path)} || true"
    cmd = (
        f"sshpass -p {shlex.quote(pw)} "
        f"ssh -o StrictHostKeyChecking=no -p {port} "
        f"{shlex.quote(user)}@{shlex.quote(host)} {remote}"
    )
    rc, out, err = run_cmd(cmd)
    items = []
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        items.append({"name": name.rstrip("/"), "dir": name.endswith("/")})
    return jsonify({"ok": True, "items": items})

@app.get("/api/local/listdir")
def api_local_listdir():
    path = request.args.get("path") or "/config"
    try:
        items = []
        for e in os.scandir(path):
            items.append({
                "name": e.name,
                "dir": e.is_dir(),
                "size": (0 if e.is_dir() else e.stat().st_size)
            })
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ----------------- Mounts (SMB/NFS) -----------------
@app.get("/api/mounts")
def api_mounts():
    data = read_json(PATHS["mounts"], [])
    for m in data:
        mp = mountpoint(m.get("name",""))
        m["mountpoint"] = mp
        m["mounted"] = os.path.ismount(mp)
        m.setdefault("last_error","")
    return jsonify({"mounts": data})

@app.post("/api/mounts/save")
def api_mounts_save():
    b = request.json or {}
    name = b.get("name","").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    data = read_json(PATHS["mounts"], [])
    data = [x for x in data if x.get("name") != name]
    data.append({
        "name": name,
        "type": b.get("type","smb"),
        "host": b.get("host","").strip(),
        "share": b.get("share","").strip(),
        "username": b.get("username",""),
        "password": b.get("password",""),
        "options":  b.get("options",""),
        "auto_retry": bool(int(b.get("auto_retry",1))),
        "last_error": ""
    })
    write_json(PATHS["mounts"], data)
    os.makedirs(mountpoint(name), exist_ok=True)
    return jsonify({"ok": True})

@app.post("/api/mounts/mount")
def api_mounts_mount():
    name = (request.json or {}).get("name","")
    data = read_json(PATHS["mounts"], [])
    m = next((x for x in data if x.get("name") == name), None)
    if not m:
        return jsonify({"ok": False, "error":"not found"}), 404

    mp = mountpoint(name)
    os.makedirs(mp, exist_ok=True)

    if m["type"] == "smb":
        unc  = f"//{m['host']}/{m['share']}"
        opts = m.get("options","")
        if m.get("username"):
            auth = f"username={m['username']},password={m.get('password','')}"
        else:
            auth = "guest"
        opts = auth + ("," + opts if opts else "")
        cmd = f"mount -t cifs {shlex.quote(unc)} {shlex.quote(mp)} -o {shlex.quote(opts)}"
    else:
        export = m["share"] if m["share"].startswith("/") else "/" + m["share"]
        opts   = m.get("options","")
        cmd = f"mount -t nfs {shlex.quote(m['host'] + ':' + export)} {shlex.quote(mp)}" + (f" -o {shlex.quote(opts)}" if opts else "")

    rc, out, err = run_cmd(cmd + " 2>&1 || true")
    ok = os.path.ismount(mp)

    if not ok and m["type"] == "smb":
        m["last_error"] = "kernel mount failed; userspace smbclient fallback will be used"
        write_json(PATHS["mounts"], data)
        return jsonify({"ok": False, "error": m["last_error"]})

    if not ok:
        m["last_error"] = out or err
        write_json(PATHS["mounts"], data)
        return jsonify({"ok": False, "error": out or err})

    m["last_error"] = ""
    write_json(PATHS["mounts"], data)
    return jsonify({"ok": True})

@app.post("/api/mounts/unmount")
def api_mounts_unmount():
    name = (request.json or {}).get("name","")
    rc, out, err = run_cmd(f"umount {shlex.quote(mountpoint(name))} 2>&1 || true")
    return jsonify({"ok": True})

@app.post("/api/mounts/test")
def api_mounts_test():
    b = request.json or {}
    t    = b.get("type")
    host = b.get("host")
    user = b.get("username","")
    pw   = b.get("password","")

    if t == "smb":
        auth = f"-U {shlex.quote(user + '%' + pw)}" if user else "-N"
        rc, out, err = run_cmd(f"smbclient -L //{shlex.quote(host)} {auth} -g 2>&1 || true")
        shares = [x.split('|')[1] for x in out.splitlines() if x.startswith('Disk|')]
        return jsonify({"ok": len(shares) > 0, "shares": shares, "raw": out})
    else:
        rc, out, err = run_cmd(f"showmount -e {shlex.quote(host)} 2>&1 || true")
        exports = [line.split()[0] for line in out.splitlines() if line.strip().startswith('/')]
        return jsonify({"ok": len(exports) > 0, "exports": exports, "raw": out})

@app.post("/api/mounts/listdir")
def api_mounts_listdir():
    b   = request.json or {}
    name = b.get("name","")
    rel  = b.get("path","/")
    mp   = mountpoint(name)
    if not name or not os.path.exists(mp):
        return jsonify({"ok": False, "error": "mount not found"}), 400
    path = os.path.normpath(os.path.join(mp, rel.lstrip("/")))
    if not path.startswith(mp):
        return jsonify({"ok": False, "error": "invalid path"}), 400
    try:
        items = [{
            "name": e.name,
            "dir": e.is_dir(),
            "size": (0 if e.is_dir() else e.stat().st_size)
        } for e in os.scandir(path)]
        items = sorted(items, key=lambda x: (not x["dir"], x["name"].lower()))
        return jsonify({"ok": True, "base": mp, "path": path, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ----------------- Estimate -----------------
@app.post("/api/estimate")
def api_estimate():
    b    = request.json or {}
    mode = b.get("mode","local")
    path = b.get("path","/")

    if mode == "local":
        rc, out, err = run_cmd(
            f"du -s -B1 {shlex.quote(path)} 2>/dev/null || "
            f"du -sb {shlex.quote(path)} 2>/dev/null || "
            f"du -sk {shlex.quote(path)}"
        )
        try:
            size = int(out.split()[0])
            if out.strip().endswith("\t" + path) and " -sk " in out:
                size *= 1024
        except Exception:
            size = 0
        return jsonify({"ok": True, "bytes": size})

    elif mode == "mount":
        name = b.get("name","")
        mp   = mountpoint(name)
        real = os.path.normpath(os.path.join(mp, path.lstrip("/")))
        rc, out, err = run_cmd(
            f"du -s -B1 {shlex.quote(real)} 2>/dev/null || "
            f"du -sb {shlex.quote(real)} 2>/dev/null || "
            f"du -sk {shlex.quote(real)} 2>/dev/null"
        )
        try:
            size = int(out.split()[0])
            if out.strip().endswith("\t" + real) and " -sk " in out:
                size *= 1024
        except Exception:
            size = 0
        return jsonify({"ok": True, "bytes": size})

    elif mode == "ssh":
        host = b.get("host")
        user = b.get("username")
        pw   = b.get("password")
        keep = "-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"
        remote = (
            f"du -s -B1 {shlex.quote(path)} 2>/dev/null || "
            f"du -sb {shlex.quote(path)} 2>/dev/null || "
            f"du -sk {shlex.quote(path)}"
        )
        cmd = (
            f"sshpass -p {shlex.quote(pw)} "
            f"ssh -o StrictHostKeyChecking=no {keep} "
            f"{shlex.quote(user)}@{shlex.quote(host)} {remote}"
        )
        rc, out, err = run_cmd(cmd + " 2>&1 || true")
        try:
            size = int(out.split()[0])
            if " -sk " in remote:
                size *= 1024
        except Exception:
            size = 0
        return jsonify({"ok": True, "bytes": size, "raw": out})

    return jsonify({"ok": False, "error": "unknown mode"}), 400

# ----------------- Backups & Upload -----------------
@app.get("/api/backups")
def api_backups():
    items = []
    for root, _, files in os.walk(BACKUP_DIR):
        for f in files:
            p = os.path.join(root, f)
            try:
                sz = os.path.getsize(p)
            except Exception:
                sz = 0
            items.append({
                "id": os.path.relpath(p, BACKUP_DIR),
                "label": f,
                "size": sz,
                "location": os.path.relpath(root, BACKUP_DIR)
            })
    return jsonify({"items": sorted(items, key=lambda x: x["label"], reverse=True)})

@app.get("/api/backups/download")
def api_backups_download():
    bid = request.args.get("id","")
    p   = os.path.normpath(os.path.join(BACKUP_DIR, bid))
    if not p.startswith(BACKUP_DIR) or not os.path.exists(p):
        return ("not found", 404)
    return send_file(p, as_attachment=True)

@app.post("/api/backups/delete")
def api_backups_delete():
    bid = (request.json or {}).get("id","")
    p   = os.path.normpath(os.path.join(BACKUP_DIR, bid))
    if not p.startswith(BACKUP_DIR):
        return jsonify({"ok": False}), 400
    try:
        os.remove(p)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.post("/api/upload")
def api_upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error":"no file"}), 400
    name = secure_filename(f.filename)
    dest = os.path.join(UPLOAD_DIR, name)
    f.save(dest)
    return jsonify({"ok": True, "path": dest})

# ----------------- Health -----------------
@app.get("/api/health")
def api_health():
    rc, out, err = run_cmd(f"df -Pk {shlex.quote(BACKUP_DIR)} | tail -1")
    try:
        parts   = out.split()
        free_mb = int(parts[3]) // 1024
    except Exception:
        free_mb = None

    total_sz = 0; count = 0
    for root, _, files in os.walk(BACKUP_DIR):
        for f in files:
            count += 1
            try:
                total_sz += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass

    mounts   = read_json(PATHS["mounts"], [])
    next_run = 0
    sch = read_json(PATHS["schedules"], [])
    if sch:
        next_run = min((s.get("next_run",0) or 0) for s in sch if s.get("next_run"))

    try:
        up_secs = float(open("/proc/uptime").read().split()[0])
    except Exception:
        up_secs = None

    return jsonify({
        "backup_dir": BACKUP_DIR,
        "free_mb": free_mb,
        "backup_files": count,
        "backup_bytes": total_sz,
        "next_schedule": next_run,
        "uptime_seconds": up_secs,
        "mounts": [{
            "name": m["name"],
            "mounted": os.path.ismount(mountpoint(m["name"])),
            "mountpoint": mountpoint(m["name"]),
            "last_error": m.get("last_error","")
        } for m in mounts]
    })

# ----------------- Backup start -----------------
def rsync_cmd(src, dst, bwkb=0, rsh=None, excludes=None, dry=False):
    bw  = f"--bwlimit={bwkb}" if bwkb and int(bwkb) > 0 else ""
    exc = " ".join([f"--exclude={shlex.quote(x)}" for x in (excludes or [])])
    dr  = "--dry-run" if dry else ""
    base = f"rsync -aAXH --numeric-ids --info=progress2 {bw} {exc} {dr}"
    if rsh:
        return f"RSYNC_RSH='{rsh}' {base} {src.rstrip('/')}/ {dst.rstrip('/')}/"
    return f"{base} {src.rstrip('/')}/ {dst.rstrip('/')}/"

def dd_image_cmd(host, user, pw, dev, out_file, limit_kbps=0):
    keep = "-o ServerAliveInterval=30 -o ServerAliveCountMax=6"
    ssh  = (
        f"sshpass -p {shlex.quote(pw)} "
        f"ssh -o StrictHostKeyChecking=no {keep} {shlex.quote(user)}@{shlex.quote(host)}"
    )
    limit = f"| pv -n -L {int(limit_kbps)*1024}" if limit_kbps and int(limit_kbps) > 0 else "| pv -n"
    return f"{ssh} 'dd if={shlex.quote(dev)} bs=4M status=none iflag=fullblock' {limit} | gzip > {shlex.quote(out_file)}"

@app.post("/api/backup/start")
def api_backup_start():
    b = request.json or {}
    mode  = b.get("mode","rsync")
    label = b.get("label","backup")
    dest_type  = b.get("dest_type","local")
    dest_mount = b.get("dest_mount_name","")
    bwkb = int(b.get("bwlimit_kbps") or 0)
    dry  = bool(b.get("dry_run", False))
    profile = (b.get("profile") or "").lower()

    if dest_type == "local":
        dest_root = BACKUP_DIR
    else:
        dest_root = os.path.join(mountpoint(dest_mount), "rlb_backups")

    os.makedirs(dest_root, exist_ok=True)
    out_dir = os.path.join(dest_root, f"{label}-{int(time.time())}")
    os.makedirs(out_dir, exist_ok=True)

    excludes = []
    if profile in ("opnsense","pfsense"):
        excludes = ["/dev","/proc","/sys","/tmp","/run","/mnt","/media"]
    elif profile in ("proxmox","pve"):
        excludes = ["/proc","/sys","/run","/dev","/tmp","/var/lib/vz/tmp"]
    elif profile in ("unraid","omv"):
        excludes = ["/proc","/sys","/run","/dev","/tmp"]

    keep = "-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"

    if mode == "rsync":
        host = b.get("host"); user = b.get("username"); pw = b.get("password")
        src  = b.get("source_path","/")
        rsh  = f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
        cmd  = rsync_cmd(
            f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)}",
            out_dir,
            bwkb=bwkb, rsh=rsh, excludes=excludes, dry=dry
        )
        job = {"id": int(time.time()), "cmd": cmd, "kind":"backup", "label": label, "mode": mode, "dest": out_dir}
        return jsonify(worker.submit(job))

    elif mode == "copy_local":
        src = b.get("source_path","/config")
        cmd = rsync_cmd(shlex.quote(src), out_dir, bwkb=bwkb, excludes=excludes, dry=dry)
        job = {"id": int(time.time()), "cmd": cmd, "kind":"backup", "label": label, "mode": mode, "dest": out_dir}
        return jsonify(worker.submit(job))

    elif mode == "copy_mount":
        name = b.get("mount_name")
        src  = b.get("source_path","/")
        mp   = mountpoint(name)
        if os.path.ismount(mp):
            cmd = rsync_cmd(shlex.quote(os.path.join(mp, src.lstrip('/'))), out_dir, bwkb=bwkb, excludes=excludes, dry=dry)
        else:
            # userspace smbclient fallback
            mounts = read_json(PATHS["mounts"], [])
            m = next((x for x in mounts if x.get("name") == name), None)
            if not m or m.get("type") != "smb":
                return jsonify({"ok": False, "error":"Mount not available and no SMB fallback"}), 400
            auth = f"-U {shlex.quote((m.get('username','') + '%' + m.get('password','')))}" if m.get('username') else "-N"
            cmd  = (
                f"smbclient //{shlex.quote(m['host'])}/{shlex.quote(m['share'])} {auth} "
                f"-c 'prompt OFF; recurse ON; cd {shlex.quote(src)}; mget *' -D {shlex.quote(out_dir)}"
            )
        job = {"id": int(time.time()), "cmd": cmd, "kind":"backup", "label": label, "mode": mode, "dest": out_dir}
        return jsonify(worker.submit(job))

    elif mode == "image":
        host = b.get("host"); user = b.get("username"); pw = b.get("password")
        dev  = b.get("device","/dev/sda")
        out_file = os.path.join(out_dir, "disk.img.gz")
        cmd = dd_image_cmd(host, user, pw, dev, out_file, limit_kbps=bwkb)
        job = {"id": int(time.time()), "cmd": cmd, "kind":"image", "label": label, "mode": mode, "dest": out_dir}
        return jsonify(worker.submit(job))

    else:
        return jsonify({"ok": False, "error":"unknown mode"}), 400

# ----------------- Restore -----------------
@app.post("/api/restore/start")
def api_restore_start():
    b = request.json or {}
    from_id = b.get("from_id","")
    to_mode = b.get("to_mode","local")
    to_path = b.get("to_path","/")
    bwkb    = int(b.get("bwlimit_kbps") or 0)

    src_path = from_id if os.path.isabs(from_id) else os.path.normpath(os.path.join(BACKUP_DIR, from_id))
    if not src_path.startswith(BACKUP_DIR) or not os.path.exists(src_path):
        return jsonify({"ok": False, "error":"invalid source"}), 400

    if to_mode == "local":
        cmd = rsync_cmd(shlex.quote(src_path), shlex.quote(to_path), bwkb=bwkb)
        job = {"id": int(time.time()), "cmd": cmd, "kind":"restore", "label": f"restore->{to_path}", "mode":"restore", "dest": to_path}
        return jsonify(worker.submit(job))
    else:
        host = b.get("host"); user = b.get("username"); pw = b.get("password")
        keep = "-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"
        rsh  = f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
        dst  = f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(to_path)}"
        cmd  = rsync_cmd(shlex.quote(src_path), dst, bwkb=bwkb, rsh=rsh)
        job  = {"id": int(time.time()), "cmd": cmd, "kind":"restore", "label": f"restore->{to_path}", "mode":"restore", "dest": to_path}
        return jsonify(worker.submit(job))

# ----------------- Notifications (Gotify minimal) -----------------
@app.get("/api/notify/config")
def api_notify_get():
    return jsonify(read_json(PATHS["notify"], {}))

@app.post("/api/notify/config")
def api_notify_set():
    write_json(PATHS["notify"], request.json or {})
    return jsonify({"ok": True})

@app.post("/api/notify/test")
def api_notify_test():
    cfg = read_json(PATHS["notify"], {})
    if not cfg.get("url") or not cfg.get("token"):
        return jsonify({"ok": False, "error":"missing url/token"})
    url = cfg["url"].rstrip("/") + "/message"
    pr  = int(cfg.get("priority",5))
    cmd = (
        f"curl -fsSL -X POST {shlex.quote(url)} "
        f"-H 'X-Gotify-Key: {cfg['token']}' "
        f"-F title='RLB Test' -F priority='{pr}' -F message='This is a test from RLB'"
    )
    rc, out, err = run_cmd(cmd + " 2>&1 || true")
    return jsonify({"ok": rc == 0, "out": out or err})

# ----------------- Schedules (simple) -----------------
def _tick_schedules():
    while True:
        sch = read_json(PATHS["schedules"], [])
        now = time.time()
        changed = False
        for s in sch:
            if not s.get("enabled"):
                continue
            nxt = s.get("next_run",0) or 0
            if nxt and nxt > now:
                continue
            body = s.get("template",{}).copy()
            body["label"] = s.get("name","job")
            try:
                with app.test_request_context():
                    request.json = body
                    api_backup_start()
            except Exception:
                pass
            # calc next
            freq = s.get("frequency","daily")
            tm   = s.get("time","02:00")
            day  = int(s.get("day",0) or 0)
            hh, mm = map(int, tm.split(":"))
            dt = datetime.datetime.now()
            if freq == "daily":
                dt = (dt + datetime.timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            elif freq == "weekly":
                days = (day - dt.weekday() + 7) % 7 or 7
                dt = (dt + datetime.timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            else:
                m = dt.month + 1
                y = dt.year + (1 if m > 12 else 0)
                m = 1 if m > 12 else m
                d = max(1, min(28, day or 1))
                dt = datetime.datetime(y, m, d, hour=hh, minute=mm)
            s["next_run"] = int(dt.timestamp()); changed = True
        if changed:
            write_json(PATHS["schedules"], sch)
        time.sleep(30)

threading.Thread(target=_tick_schedules, daemon=True).start()

@app.get("/api/schedules")
def api_schedules_get():
    return jsonify({"schedules": read_json(PATHS["schedules"], [])})

@app.post("/api/schedules/save")
def api_schedules_save():
    b = request.json or {}
    sch = read_json(PATHS["schedules"], [])
    sch = [x for x in sch if x.get("name") != b.get("name")]
    b.setdefault("enabled", True)
    b.setdefault("frequency", "daily")
    b.setdefault("time", "02:00")
    b.setdefault("day", 0)
    b.setdefault("template", {})
    b.setdefault("next_run", 0)
    sch.append(b)
    write_json(PATHS["schedules"], sch)
    return jsonify({"ok": True})

# --------------- Static UI ---------------
@app.get("/")
def ui_root():
    return send_from_directory("www", "index.html")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8066)
    args = ap.parse_args()
    app.run(host="0.0.0.0", port=args.port)
