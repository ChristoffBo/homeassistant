
import os, json, time, threading, subprocess, shlex, datetime, pathlib, re, argparse, shutil
from flask import Flask, request, jsonify, send_from_directory, Response, send_file
from flask_socketio import SocketIO, emit
from apscheduler.schedulers.background import BackgroundScheduler
import paramiko
import psutil
import humanize

# ---------------- Config & Paths ----------------
DATA_ROOT = "/config/remote_linux_backup"
BACKUPS_DIR = os.environ.get("RLB_STORAGE_PATH", os.path.join(DATA_ROOT, "backups"))
LOGS_DIR = os.path.join(DATA_ROOT, "logs")
STATE_DIR = os.path.join(DATA_ROOT, "state")
MOUNTS_DIR = os.path.join(DATA_ROOT, "mnt")
MOUNTS_FILE = os.path.join(STATE_DIR, "mounts.json")
RETENTION_FILE = os.path.join(STATE_DIR, "retention.json")
os.makedirs(MOUNTS_DIR, exist_ok=True)
CONN_FILE = os.path.join(STATE_DIR, "connections.json")
SCHEDULE_FILE = os.path.join(STATE_DIR, "schedules.json")
os.makedirs(BACKUPS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

GOTIFY_URL = os.environ.get("RLB_GOTIFY_URL", "")
GOTIFY_TOKEN = os.environ.get("RLB_GOTIFY_TOKEN", "")
AUTO_CHECK_HOURS = int(os.environ.get("RLB_AUTO_CHECK_HOURS", "0") or 0)

app = Flask(__name__, static_folder="www", static_url_path="")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

scheduler = BackgroundScheduler(timezone=os.environ.get("TZ", "Africa/Johannesburg"))
scheduler.start()

# ---------------- Utilities ----------------

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False

def is_path_mounted(path):
    try:
        with open("/proc/mounts","r") as f:
            for line in f:
                parts = line.split()
                if len(parts)>=2 and os.path.abspath(parts[1]) == os.path.abspath(path):
                    return True
        return False
    except Exception:
        return False

def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def now_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def safe_name(s):
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s)

def human_bytes(n):
    try:
        return humanize.naturalsize(int(n), binary=True)
    except Exception:
        return str(n)

def log_event(kind, msg, job_id=None):
    line = f"[{datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}] {kind}: {msg}"
    with open(os.path.join(LOGS_DIR, "app.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    socketio.emit("log", {"kind": kind, "msg": msg, "job_id": job_id})

def send_gotify(title, message, priority=5):
    if not GOTIFY_URL or not GOTIFY_TOKEN:
        return False
    try:
        import urllib.request, urllib.parse
        data = urllib.parse.urlencode({"title": title, "message": message, "priority": priority}).encode()
        req = urllib.request.Request(f"{GOTIFY_URL.rstrip('/')}/message?token={GOTIFY_TOKEN}", data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception as e:
        log_event("ERROR", f"Gotify send failed: {e}")
        return False

# ---------------- SSH helpers ----------------

def ssh_connect(host, port, username, password, timeout=15):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=username, password=password, timeout=timeout, allow_agent=False, look_for_keys=False)
    return client

def sftp_listdir(ssh_client, path):
    sftp = ssh_client.open_sftp()
    try:
        items = []
        for attr in sftp.listdir_attr(path):
            items.append({
                "name": attr.filename,
                "path": os.path.join(path, attr.filename).replace("\\","/"),
                "is_dir": paramiko.SFTPAttributes.from_stat(attr.st_mode).st_mode & 0o040000 == 0o040000 if hasattr(paramiko, "SFTPAttributes") else bool(attr.st_mode & 0o040000),
                "size": attr.st_size
            })
        return items
    finally:
        sftp.close()

def remote_detect_pkgmgr(ssh):
    # Return a command prefix to install packages (rsync pv gzip)
    cmds = [
        ("apt-get", "sudo apt-get update -y && sudo apt-get install -y rsync pv gzip"),
        ("yum", "sudo yum install -y rsync pv gzip"),
        ("dnf", "sudo dnf install -y rsync pv gzip"),
        ("apk", "sudo apk add --no-cache rsync pv gzip"),
        ("pacman", "sudo pacman -Sy --noconfirm rsync pv gzip"),
        ("pkg", "sudo pkg install -y rsync pv gzip")
    ]
    for bin_name, cmd in cmds:
        stdin, stdout, stderr = ssh.exec_command(f"command -v {bin_name} || echo ''")
        out = stdout.read().decode().strip()
        if out:
            return cmd
    return None

def remote_disk_size_cmd(dev):
    # Try Linux then FreeBSD
    return f"{{ sudo blockdev --getsize64 {shlex.quote(dev)} 2>/dev/null || sudo lsblk -nb -o SIZE -d {shlex.quote(dev)} 2>/dev/null || sudo diskinfo -v {shlex.quote(dev)} 2>/dev/null | awk '/^\s*mediasize in bytes/ {{print $4}}'; }}"

# ---------------- Jobs & Progress ----------------

JOBS = {}  # job_id -> dict

def register_job(kind, params):
    job_id = f"{kind}-{int(time.time()*1000)}"
    JOBS[job_id] = {
        "id": job_id,
        "kind": kind,
        "params": params,
        "status": "running",
        "progress": 0,
        "eta": None,
        "bytes": 0,
        "total_bytes": None,
        "started": time.time(),
        "ended": None,
        "log": []
    }
    return job_id

def update_job(job_id, **fields):
    if job_id in JOBS:
        JOBS[job_id].update(fields)
        socketio.emit("job_update", JOBS[job_id])

def finish_job(job_id, status="done"):
    if job_id in JOBS:
        JOBS[job_id]["status"] = status
        JOBS[job_id]["ended"] = time.time()
        socketio.emit("job_update", JOBS[job_id])

# ---------------- Flask endpoints ----------------

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "time": datetime.datetime.now().isoformat(), "backups_dir": BACKUPS_DIR})

@app.post("/api/gotify/test")
def api_gotify_test():
    ok = send_gotify("RLB Test", "This is a test notification from Remote Linux Backup.", 5)
    return jsonify({"sent": ok})


@app.get("/api/retention")
def api_retention_get():
    cfg = get_retention()
    free, total = free_gb_at(BACKUPS_DIR)
    return jsonify({"config": cfg, "backups_dir": BACKUPS_DIR, "free_gb": round(free,2), "total_gb": round(total,2)})

@app.post("/api/retention")
def api_retention_set():
    data = request.json or {}
    keep_last = int(data.get("keep_last") or 0)
    max_age_days = int(data.get("max_age_days") or 0)
    min_free_gb = float(data.get("min_free_gb") or 0)
    cfg = {"keep_last": keep_last, "max_age_days": max_age_days, "min_free_gb": min_free_gb}
    save_retention(cfg)
    return jsonify({"ok": True, "config": cfg})

@app.get("/api/health_fs")
def api_health_fs():
    free, total = free_gb_at(BACKUPS_DIR)
    return jsonify({"backups_dir": BACKUPS_DIR, "free_gb": round(free,2), "total_gb": round(total,2)})

@app.get("/api/backups")
def api_backups_list():
    res = []
    for root, dirs, files in os.walk(BACKUPS_DIR):
        for f in files:
            full = os.path.join(root, f)
            try:
                st = os.stat(full)
                res.append({
                    "path": full,
                    "rel": os.path.relpath(full, BACKUPS_DIR),
                    "size": st.st_size,
                    "size_h": human_bytes(st.st_size),
                    "mtime": st.st_mtime
                })
            except FileNotFoundError:
                pass
    res.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(res)

@app.post("/api/backups/delete")
def api_backups_delete():
    data = request.json or {}
    rel = data.get("rel")
    if not rel:
        return jsonify({"ok": False, "error": "Missing rel"}), 400
    target = os.path.normpath(os.path.join(BACKUPS_DIR, rel))
    if not target.startswith(BACKUPS_DIR):
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    try:
        os.remove(target)
        return jsonify({"ok": True})
    except IsADirectoryError:
        import shutil
        shutil.rmtree(target, ignore_errors=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/backups/download")
def api_backups_download():
    rel = request.args.get("rel")
    if not rel:
        return "Missing rel", 400
    target = os.path.normpath(os.path.join(BACKUPS_DIR, rel))
    if not target.startswith(BACKUPS_DIR) or not os.path.exists(target):
        return "Invalid path", 400
    return send_file(target, as_attachment=True)

@app.post("/api/connections/test")
def api_conn_test():
    data = request.json or {}
    host = data.get("host")
    port = int(data.get("port") or 22)
    username = data.get("username")
    password = data.get("password")
    path = data.get("path","/")
    try:
        ssh = ssh_connect(host, port, username, password)
        # List to confirm SFTP works
        _ = sftp_listdir(ssh, path)
        ssh.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/connections")
def api_conn_get():
    data = load_json(CONN_FILE, {"connections": []})
    # Do not leak passwords
    redacted = []
    for c in data.get("connections", []):
        c2 = {k:v for k,v in c.items() if k!="password"}
        c2["has_password"] = bool(c.get("password"))
        redacted.append(c2)
    return jsonify({"connections": redacted})

@app.post("/api/connections/save")
def api_conn_save():
    data = request.json or {}
    required = ["name","host","username"]
    for r in required:
        if not data.get(r):
            return jsonify({"ok": False, "error": f"Missing {r}"}), 400
    conf = load_json(CONN_FILE, {"connections": []})
    # Replace existing by name
    conf["connections"] = [c for c in conf["connections"] if c.get("name") != data["name"]]
    conf["connections"].append({
        "name": data["name"],
        "host": data["host"],
        "port": int(data.get("port") or 22),
        "username": data["username"],
        "password": data.get("password") if data.get("persist_password") else None
    })
    save_json(CONN_FILE, conf)
    return jsonify({"ok": True})

@app.post("/api/connections/delete")
def api_conn_delete():
    data = request.json or {}
    name = data.get("name")
    conf = load_json(CONN_FILE, {"connections": []})
    conf["connections"] = [c for c in conf["connections"] if c.get("name") != name]
    save_json(CONN_FILE, conf)
    return jsonify({"ok": True})

def _get_conn_by_name(name):
    conf = load_json(CONN_FILE, {"connections": []})
    for c in conf["connections"]:
        if c.get("name")==name:
            return c
    return None

@app.post("/api/remote/listdir")
def api_remote_listdir():
    data = request.json or {}
    name = data.get("connection_name")
    path = data.get("path","/")
    if name:
        conn = _get_conn_by_name(name)
        if not conn:
            return jsonify({"ok": False, "error": "Connection not found"}), 404
        password = data.get("password") or conn.get("password")
        if not password:
            return jsonify({"ok": False, "error": "Password required"}), 400
        host, port, user = conn["host"], int(conn.get("port") or 22), conn["username"]
    else:
        host = data.get("host")
        port = int(data.get("port") or 22)
        user = data.get("username")
        password = data.get("password")
        if not (host and user and password):
            return jsonify({"ok": False, "error": "Missing host/username/password"}), 400
    try:
        ssh = ssh_connect(host, port, user, password)
        items = sftp_listdir(ssh, path)
        ssh.close()
        for it in items:
            # paramiko attr check for dir flag is unreliable; recheck:
            it["is_dir"] = it["is_dir"] or it["path"].endswith("/.")
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



# ---------- Retention & Storage ----------
def get_retention():
    return load_json(RETENTION_FILE, {"keep_last": 7, "max_age_days": 0, "min_free_gb": 0})

def save_retention(cfg):
    save_json(RETENTION_FILE, cfg)

def backups_groups():
    # returns mapping group->list of (path, mtime), where group is top-level folder (host or mount name)
    groups = {}
    if not os.path.isdir(BACKUPS_DIR):
        return groups
    for root, dirs, files in os.walk(BACKUPS_DIR):
        # Only consider first-level subdirs as groups
        break
    for name in sorted(os.listdir(BACKUPS_DIR)):
        gpath = os.path.join(BACKUPS_DIR, name)
        if not os.path.isdir(gpath): 
            continue
        entries = []
        for sub in os.listdir(gpath):
            sp = os.path.join(gpath, sub)
            try:
                st = os.stat(sp)
                entries.append((sp, st.st_mtime))
            except FileNotFoundError:
                pass
        entries.sort(key=lambda x: x[1], reverse=True)
        groups[name] = entries
    return groups

def prune_by_policy():
    cfg = get_retention()
    keep_last = int(cfg.get("keep_last") or 0)
    max_age_days = int(cfg.get("max_age_days") or 0)
    now = time.time()
    for group, entries in backups_groups().items():
        # keep_last policy
        if keep_last > 0 and len(entries) > keep_last:
            for path, _ in entries[keep_last:]:
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
                    log_event("INFO", f"Pruned old backup: {os.path.relpath(path, BACKUPS_DIR)}")
                except Exception as e:
                    log_event("ERROR", f"Prune failed {path}: {e}")
        # max_age_days policy
        if max_age_days > 0:
            cutoff = now - max_age_days*86400
            for path, mtime in entries:
                if mtime < cutoff:
                    try:
                        if os.path.isdir(path):
                            shutil.rmtree(path, ignore_errors=True)
                        else:
                            os.remove(path)
                        log_event("INFO", f"Pruned expired backup: {os.path.relpath(path, BACKUPS_DIR)}")
                    except Exception as e:
                        log_event("ERROR", f"Prune failed {path}: {e}")

def free_gb_at(path):
    try:
        du = shutil.disk_usage(path)
        return du.free / (1024**3), du.total / (1024**3)
    except Exception:
        return 0.0, 0.0

# ---------- Backup/Restore ----------

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _local_copy(job_id, src_path, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    cmd = ["bash","-lc", f"rsync -az --info=progress2 {shlex.quote(src_path.rstrip('/') )}/ {shlex.quote(dest_dir)}/"]
    log_event("INFO", f"LOCAL RSYNC start: {' '.join(cmd)}", job_id)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
    for line in proc.stdout:
        line = line.strip()
        if not line: continue
        m = re.search(r"(\\d[\\d,]*)\\s+(\\d+)%", line)
        if m:
            bytes_copied = int(m.group(1).replace(",",""))
            percent = int(m.group(2))
            update_job(job_id, progress=percent, bytes=bytes_copied)
        log_event("OUT", line, job_id)
    code = proc.wait()
    if code != 0:
        finish_job(job_id, status=f"error:{code}")
        log_event("ERROR", f"LOCAL RSYNC failed with code {code}", job_id)
        return
    finish_job(job_id, status="done")
    log_event("INFO", f"LOCAL RSYNC finished", job_id)


def _rsync_copy(job_id, host, port, user, password, src_path, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    # Using sshpass to avoid keys; ensure installed in container
    # --info=progress2 prints progress lines with total bytes
    cmd = [
        "bash","-lc",
        f"sshpass -p {shlex.quote(password)} "
        f"rsync -az --dry-run --info=progress2 -e 'ssh -o StrictHostKeyChecking=no -p {int(port)}' "
        f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src_path)} "
        f"{shlex.quote(dest_dir)}/"
    ]
    log_event("INFO", f"RSYNC start: {' '.join(cmd)}", job_id)
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
    total = None
    last_bytes = 0
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        # Parse progress2 lines: "123,456,789  99%   12.34MB/s    0:00:01 (xfr#1, to-chk=0/0)"
        m = re.search(r"(\d[\d,]*)\s+(\d+)%", line)
        if m:
            bytes_copied = int(m.group(1).replace(",",""))
            percent = int(m.group(2))
            update_job(job_id, progress=percent, bytes=bytes_copied)
        log_event("OUT", line, job_id)
    code = proc.wait()
    if code != 0:
        finish_job(job_id, status=f"error:{code}")
        log_event("ERROR", f"RSYNC failed with code {code}", job_id)
        return
    finish_job(job_id, status="done")
    elapsed = time.time()-start
    log_event("INFO", f"RSYNC finished in {elapsed:.1f}s", job_id)

def _remote_install_requirements(ssh):
    cmd = remote_detect_pkgmgr(ssh)
    if not cmd:
        return "No supported package manager detected; skipping auto-install."
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode(errors="ignore")
    err = stderr.read().decode(errors="ignore")
    return out or err or "OK"

def _image_backup(job_id, host, port, user, password, device, dest_file):
    # Connect to fetch disk size and ensure dd+gzip present; attempt install
    ssh = ssh_connect(host, port, user, password)
    try:
        # Ensure tools installed
        install_msg = _remote_install_requirements(ssh)
        log_event("INFO", f"Auto-install on remote: {install_msg}", job_id)

        # Detect size
        stdin, stdout, stderr = ssh.exec_command(remote_disk_size_cmd(device))
        size_txt = stdout.read().decode().strip()
        total_bytes = int(size_txt) if size_txt.isdigit() else None
    finally:
        ssh.close()

    # Do transfer with dd over SSH to local gzip
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    # dd status=progress writes to stderr; we capture that
    remote_cmd = f"sudo dd if={shlex.quote(device)} bs=4M status=progress 2>/dev/stderr"
    local_cmd = f"gzip -1 > {shlex.quote(dest_file)}"
    cmd = ["bash","-lc", f"sshpass -p {shlex.quote(password)} ssh -o StrictHostKeyChecking=no -p {int(port)} {shlex.quote(user)}@{shlex.quote(host)} {shlex.quote(remote_cmd)} | pv -n {'-s '+str(total_bytes) if total_bytes else ''} | {local_cmd}"]
    log_event("INFO", f"IMAGE start: {' '.join(cmd)}", job_id)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
    # pv -n prints percentage to stdout as numbers, newline separated
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        # pv -n emits integer percent
        if line.isdigit():
            percent = int(line)
            update_job(job_id, progress=percent, total_bytes=total_bytes)
        else:
            log_event("OUT", line, job_id)
    code = proc.wait()
    if code != 0:
        finish_job(job_id, status=f"error:{code}")
        log_event("ERROR", f"IMAGE failed with code {code}", job_id)
        return
    finish_job(job_id, status="done")
    log_event("INFO", f"IMAGE finished -> {dest_file}", job_id)

def _restore_rsync(job_id, host, port, user, password, src_dir, dest_path, dry_run=False):
    cmd = [
        "bash","-lc",
        f"sshpass -p {shlex.quote(password)} "
        f"rsync -az --dry-run --info=progress2 -e 'ssh -o StrictHostKeyChecking=no -p {int(port)}' "
        f"{shlex.quote(src_dir)}/ "
        f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(dest_path)}/"
    ]
    log_event("INFO", f"RESTORE-RSYNC start: {' '.join(cmd)}", job_id)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        m = re.search(r"(\d[\\d,]*)\\s+(\\d+)%", line)
        if m:
            bytes_copied = int(m.group(1).replace(",",""))
            percent = int(m.group(2))
            update_job(job_id, progress=percent, bytes=bytes_copied)
        log_event("OUT", line, job_id)
    code = proc.wait()
    if code != 0:
        finish_job(job_id, status=f"error:{code}")
        log_event("ERROR", f"RESTORE-RSYNC failed with code {code}", job_id)
        return
    finish_job(job_id, status="done")
    log_event("INFO", f"RESTORE-RSYNC finished", job_id)

def _restore_image(job_id, host, port, user, password, image_path, device):
    # Stream gzip -> ssh -> dd
    remote_cmd = f"sudo dd of={shlex.quote(device)} bs=4M status=progress 2>/dev/stderr"
    cmd = ["bash","-lc", f"pv -n {shlex.quote(image_path)} | gunzip -c | sshpass -p {shlex.quote(password)} ssh -o StrictHostKeyChecking=no -p {int(port)} {shlex.quote(user)}@{shlex.quote(host)} {shlex.quote(remote_cmd)}"]
    log_event("INFO", f"RESTORE-IMAGE start: {' '.join(cmd)}", job_id)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            percent = int(line)
            update_job(job_id, progress=percent)
        else:
            log_event("OUT", line, job_id)
    code = proc.wait()
    if code != 0:
        finish_job(job_id, status=f"error:{code}")
        log_event("ERROR", f"RESTORE-IMAGE failed with code {code}", job_id)
        return
    finish_job(job_id, status="done")
    log_event("INFO", f"RESTORE-IMAGE finished", job_id)

@app.post("/api/backup/start")
def api_backup_start():
    data = request.json or {}
    mode = data.get("mode")  # "copy" or "image"
    conn_name = data.get("connection_name")
    host = data.get("host")
    port = int(data.get("port") or 22)
    user = data.get("username")
    password = data.get("password")
    src_path = data.get("source_path", "/")
    mount_name = data.get("mount_name")
    device = data.get("device")  # for image mode
    label = safe_name(data.get("label") or "")
    if conn_name and (not host):
        conn = _get_conn_by_name(conn_name)
        if not conn:
            return jsonify({"ok": False, "error": "Connection not found"}), 404
        host = conn["host"]; port = int(conn.get("port") or 22); user = conn["username"]
        password = password or conn.get("password")
    if not (host and user and password):
        return jsonify({"ok": False, "error": "Missing host/user/password"}), 400

    ts = now_ts()
    target_dir = os.path.join(BACKUPS_DIR, safe_name(host), f"{ts}_{label}" if label else ts)
    os.makedirs(target_dir, exist_ok=True)


# Local copy from mounted share (no SSH)
if mode == "copy" and mount_name:
    ts = now_ts()
    target_dir = os.path.join(BACKUPS_DIR, safe_name(mount_name), ts)
    job_id = register_job("local_backup", {"mount": mount_name, "src": src_path, "dest": target_dir})
    base = os.path.join(MOUNTS_DIR, safe_name(mount_name))
    abs_src = os.path.join(base, src_path.lstrip("/"))
    threading.Thread(target=_local_copy, args=(job_id, abs_src, target_dir), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "dest": target_dir})

if mode == "image":

        if not device:
            return jsonify({"ok": False, "error": "Missing device"}), 400
        dest_file = os.path.join(target_dir, f"{safe_name(host)}_{ts}{('_'+label) if label else ''}.img.gz")
        job_id = register_job("image_backup", {"host": host, "device": device, "dest": dest_file})
        threading.Thread(target=_image_backup, args=(job_id, host, port, user, password, device, dest_file), daemon=True).start()
        return jsonify({"ok": True, "job_id": job_id, "dest": dest_file})
    else:
        job_id = register_job("rsync_backup", {"host": host, "src": src_path, "dest": target_dir})
        threading.Thread(target=_rsync_copy, args=(job_id, host, port, user, password, src_path, target_dir), daemon=True).start()
        return jsonify({"ok": True, "job_id": job_id, "dest": target_dir})

@app.post("/api/restore/start")
def api_restore_start():
    data = request.json or {}
    mode = data.get("mode")  # "rsync" or "image"
    conn_name = data.get("connection_name")
    host = data.get("host")
    port = int(data.get("port") or 22)
    user = data.get("username")
    password = data.get("password")
    dest_path = data.get("dest_path")  # for rsync
    image_device = data.get("device")  # for image
    local_src = data.get("local_src")  # file or directory under BACKUPS_DIR
    if conn_name and (not host):
        conn = _get_conn_by_name(conn_name)
        if not conn:
            return jsonify({"ok": False, "error": "Connection not found"}), 404
        host = conn["host"]; port = int(conn.get("port") or 22); user = conn["username"]
        password = password or conn.get("password")
    if not (host and user and password):
        return jsonify({"ok": False, "error": "Missing host/user/password"}), 400
    if not local_src:
        return jsonify({"ok": False, "error": "Missing local_src"}), 400
    full_src = os.path.normpath(os.path.join(BACKUPS_DIR, local_src))
    if not full_src.startswith(BACKUPS_DIR) or not os.path.exists(full_src):
        return jsonify({"ok": False, "error": "Invalid local_src"}), 400


# Local copy from mounted share (no SSH)
if mode == "copy" and mount_name:
    ts = now_ts()
    target_dir = os.path.join(BACKUPS_DIR, safe_name(mount_name), ts)
    job_id = register_job("local_backup", {"mount": mount_name, "src": src_path, "dest": target_dir})
    base = os.path.join(MOUNTS_DIR, safe_name(mount_name))
    abs_src = os.path.join(base, src_path.lstrip("/"))
    threading.Thread(target=_local_copy, args=(job_id, abs_src, target_dir), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "dest": target_dir})

if mode == "image":

        if not image_device or not os.path.isfile(full_src):
            return jsonify({"ok": False, "error": "Need image file and device"}), 400
        job_id = register_job("image_restore", {"host": host, "image": full_src, "device": image_device})
        threading.Thread(target=_restore_image, args=(job_id, host, port, user, password, full_src, image_device), daemon=True).start()
        return jsonify({"ok": True, "job_id": job_id})
    else:
        if not dest_path or not os.path.isdir(full_src):
            return jsonify({"ok": False, "error": "Need directory backup and destination path"}), 400
        job_id = register_job("rsync_restore", {"host": host, "src": full_src, "dest": dest_path})
        threading.Thread(target=_restore_rsync, args=(job_id, host, port, user, password, full_src, dest_path, bool(data.get('dry_run'))), daemon=True).start()
        return jsonify({"ok": True, "job_id": job_id})

@app.get("/api/jobs")
def api_jobs():
    return jsonify(list(JOBS.values()))

# ---------- Schedules ----------

@app.get("/api/schedule")
def api_schedule_get():
    return jsonify(load_json(SCHEDULE_FILE, {"jobs": []}))

@app.post("/api/schedule/save")
def api_schedule_save():
    data = request.json or {}
    # jobs: [{name, connection_name, mode, source_path, device, cron: {type: daily/weekly/monthly, day?, time}}]
    save_json(SCHEDULE_FILE, data)
    _reload_schedules()
    return jsonify({"ok": True})

def _schedule_wrapper(spec):
    def run():
        try:
            params = spec.copy()
            params.pop("cron", None)
            # Use saved connection_name; rely on backend defaults
            with app.test_request_context():
                if params.get("mode") == "image":
                    api_backup_start()
                else:
                    api_backup_start()
        except Exception as e:
            log_event("ERROR", f"Scheduled run failed: {e}")
    return run

def _reload_schedules():
    scheduler.remove_all_jobs()
    conf = load_json(SCHEDULE_FILE, {"jobs": []})
    for i, job in enumerate(conf.get("jobs", [])):
        cron = job.get("cron", {})
        ttype = cron.get("type")
        hour = int((cron.get("hour") or 3))
        minute = int((cron.get("minute") or 0))
        if ttype == "daily":
            scheduler.add_job(_schedule_wrapper(job), "cron", hour=hour, minute=minute, id=f"job{i}")
        elif ttype == "weekly":
            dow = int((cron.get("weekday") or 0))  # 0=mon
            scheduler.add_job(_schedule_wrapper(job), "cron", day_of_week=dow, hour=hour, minute=minute, id=f"job{i}")
        elif ttype == "monthly":
            dom = int((cron.get("day") or 1))
            scheduler.add_job(_schedule_wrapper(job), "cron", day=dom, hour=hour, minute=minute, id=f"job{i}")

if AUTO_CHECK_HOURS and AUTO_CHECK_HOURS > 0:
    scheduler.add_job(lambda: None, "interval", hours=AUTO_CHECK_HOURS, id="noop")



# ---------- Estimation ----------
@app.post("/api/estimate/ssh_size")
def api_estimate_ssh():
    data = request.json or {}
    host = data.get("host"); port = int(data.get("port") or 22)
    user = data.get("username"); password = data.get("password"); path = data.get("path") or "/"
    if not (host and user and password): return jsonify({"ok": False, "error":"Missing host/user/password"}), 400
    try:
        ssh = ssh_connect(host, port, user, password)
        stdin, stdout, stderr = ssh.exec_command(f"du -sb {shlex.quote(path)} 2>/dev/null | awk '{'{print $1}'}'")
        out = stdout.read().decode().strip()
        ssh.close()
        size = int(out) if out.isdigit() else None
        return jsonify({"ok": True, "bytes": size})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/estimate/mount_size")
def api_estimate_mount():
    name = request.args.get("name"); path = request.args.get("path") or "/"
    if not name: return jsonify({"ok": False, "error":"Missing name"}), 400
    base = os.path.join(MOUNTS_DIR, safe_name(name))
    root = os.path.normpath(os.path.join(base, path.lstrip("/")))
    if not root.startswith(base): return jsonify({"ok": False, "error":"Invalid path"}), 400
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            try:
                total += os.stat(os.path.join(dirpath, f)).st_size
            except FileNotFoundError:
                pass
    return jsonify({"ok": True, "bytes": total})

# ---------- Mounts: SMB/NFS ----------
@app.get("/api/mounts")
def api_mounts_get():
    data = load_json(MOUNTS_FILE, {"mounts": []})
    # attach live status
    for m in data.get("mounts", []):
        mntp = os.path.join(MOUNTS_DIR, safe_name(m["name"]))
        m["mountpoint"] = mntp
        m["mounted"] = is_path_mounted(mntp)
    return jsonify(data)

@app.post("/api/mounts/save")
def api_mounts_save():
    data = request.json or {}
    required = ["name","type","host"]
    for r in required:
        if not data.get(r):
            return jsonify({"ok": False, "error": f"Missing {r}"}), 400
    conf = load_json(MOUNTS_FILE, {"mounts": []})
    conf["mounts"] = [m for m in conf["mounts"] if m.get("name") != data["name"]]
    conf["mounts"].append({
        "name": data["name"],
        "type": data["type"], # smb or nfs
        "host": data["host"],
        "share": data.get("share",""),
        "export": data.get("export",""),
        "username": data.get("username",""),
        "password": data.get("password",""),
        "options": data.get("options",""),
        "auto_mount": bool(data.get("auto_mount", True))
    })
    save_json(MOUNTS_FILE, conf)
    return jsonify({"ok": True})

@app.post("/api/mounts/delete")
def api_mounts_delete():
    data = request.json or {}
    name = data.get("name")
    conf = load_json(MOUNTS_FILE, {"mounts": []})
    conf["mounts"] = [m for m in conf["mounts"] if m.get("name") != name]
    save_json(MOUNTS_FILE, conf)
    return jsonify({"ok": True})

@app.post("/api/mounts/mount")
def api_mounts_mount():
    data = request.json or {}
    name = data.get("name")
    conf = load_json(MOUNTS_FILE, {"mounts": []})
    m = next((x for x in conf.get("mounts",[]) if x.get("name")==name), None)
    if not m:
        return jsonify({"ok": False, "error": "Not found"}), 404
    mntp = os.path.join(MOUNTS_DIR, safe_name(name))
    os.makedirs(mntp, exist_ok=True)
    if m.get("type")=="smb":
        if not m.get("share"):
            return jsonify({"ok": False, "error": "Missing SMB share"}), 400
        opts = m.get("options") or ""
        cred = []
        if m.get("username"):
            cred.append(f"username={m.get('username')}"); cred.append(f"password={m.get('password','')}")
        if opts: cred.append(opts)
        opt_str = ",".join([o for o in cred if o])
        cmd = ["bash","-lc", f"mount -t cifs //{shlex.quote(m['host'])}/{shlex.quote(m['share'])} {shlex.quote(mntp)} -o {opt_str or 'guest,ro'}"]
    else:
        if not m.get("export"):
            return jsonify({"ok": False, "error": "Missing NFS export"}), 400
        opts = m.get("options") or "ro"
        cmd = ["bash","-lc", f"mount -t nfs {shlex.quote(m['host'])}:{shlex.quote(m['export'])} {shlex.quote(mntp)} -o {opts}"]
    code,out,err = run_cmd(cmd)
    log_event("INFO", f"Mount run ({name}): code={code} out={out.strip()} err={err.strip()}")
    return jsonify({"ok": code==0, "code":code, "out":out, "err":err})

@app.post("/api/mounts/umount")
def api_mounts_umount():
    data = request.json or {}
    name = data.get("name")
    mntp = os.path.join(MOUNTS_DIR, safe_name(name))
    cmd = ["bash","-lc", f"umount {shlex.quote(mntp)}"]
    code,out,err = run_cmd(cmd)
    log_event("INFO", f"Umount run ({name}): code={code} out={out.strip()} err={err.strip()}")
    return jsonify({"ok": code==0, "code":code, "out":out, "err":err})

@app.get("/api/mounts/listdir")
def api_mounts_listdir():
    name = request.args.get("name","")
    path = request.args.get("path","/")
    base = os.path.join(MOUNTS_DIR, safe_name(name))
    target = os.path.normpath(os.path.join(base, path.lstrip("/")))
    if not target.startswith(base):
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    try:
        items = []
        for entry in os.scandir(target):
            items.append({"name": entry.name, "path": os.path.join(path, entry.name).replace("\\","/"), "is_dir": entry.is_dir(), "size": entry.stat().st_size})
        return jsonify({"ok": True, "items": items, "cwd": path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/mounts/smb_shares")
def api_mounts_smb_shares():
    data = request.json or {}
    host = data.get("host"); user = data.get("username",""); pw = data.get("password","")
    if not host: return jsonify({"ok": False, "error":"Missing host"}), 400
    # smbclient -L //host -U user%pass
    auth = f"-U {shlex.quote(user+'%'+pw) }" if user else "-N"
    cmd = ["bash","-lc", f"smbclient -L //{shlex.quote(host)} {auth} 2>/dev/null | awk '/Disk|IPC/ {print $1}'"]
    code,out,err = run_cmd(cmd)
    shares = [x for x in out.splitlines() if x and x not in ('IPC$',)]
    return jsonify({"ok": code==0, "shares": shares, "out": out, "err": err})

@app.post("/api/mounts/nfs_exports")
def api_mounts_nfs_exports():
    data = request.json or {}
    host = data.get("host")
    if not host: return jsonify({"ok": False, "error":"Missing host"}), 400
    cmd = ["bash","-lc", f"showmount -e {shlex.quote(host)} 2>/dev/null | awk 'NR>1 {print $1}'"]
    code,out,err = run_cmd(cmd)
    exports = [x for x in out.splitlines() if x]
    return jsonify({"ok": code==0, "exports": exports, "out": out, "err": err})

def auto_remount_configured():
    conf = load_json(MOUNTS_FILE, {"mounts": []})
    for m in conf.get("mounts", []):
        if not m.get("auto_mount", True): continue
        mntp = os.path.join(MOUNTS_DIR, safe_name(m["name"]))
        if is_path_mounted(mntp): continue
        # attempt mount
        try:
            if m.get("type")=="smb":
                opts = m.get("options") or ""
                cred = []
                if m.get("username"):
                    cred.append(f"username={m.get('username')}"); cred.append(f"password={m.get('password','')}")
                if opts: cred.append(opts)
                opt_str = ",".join([o for o in cred if o])
                cmd = ["bash","-lc", f"mount -t cifs //{shlex.quote(m['host'])}/{shlex.quote(m['share'])} {shlex.quote(mntp)} -o {opt_str or 'guest,ro'}"]
            else:
                opts = m.get("options") or "ro"
                cmd = ["bash","-lc", f"mount -t nfs {shlex.quote(m['host'])}:{shlex.quote(m['export'])} {shlex.quote(mntp)} -o {opts}"]
            code,out,err = run_cmd(cmd)
            log_event('INFO', f'Auto mount {m.get(\"name\")}: code={code} out={out.strip()} err={err.strip()}')
        except Exception as e:
            log_event('ERROR', f'Auto mount {m.get(\"name\")} failed: {e}')

# Ensure auto-remount at startup
auto_remount_configured()

# ---------- Static assets ----------
@app.get("/api/logs/tail")
def api_logs_tail():
    path = os.path.join(LOGS_DIR, "app.log")
    if not os.path.exists(path):
        open(path, "a").close()
    def stream():
        with open(path, "r", encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line:
                    yield line
                else:
                    time.sleep(0.5)
    return Response(stream(), mimetype="text/plain")

# Fallback to SPA
@app.errorhandler(404)
def spa(_):
    return app.send_static_file("index.html")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="8066")
    args = parser.parse_args()
    port = int(args.port)
    print(f"[RLB] Launching on 0.0.0.0:{port}, backups at {BACKUPS_DIR}")
    socketio.run(app, host="0.0.0.0", port=port)
