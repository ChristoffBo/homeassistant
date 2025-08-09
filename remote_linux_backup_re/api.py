import os, json, subprocess, shlex, time, hashlib
from flask import Flask, request, jsonify, send_from_directory, send_file, abort

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(APP_DIR, "www")

# HA-managed options (read-only for us)
OPTIONS_PATH = "/data/options.json"
DEFAULT_OPTIONS = {
    "known_hosts": [],
    "ui_port": 8066,
    "gotify_enabled": False,
    "gotify_url": "",
    "gotify_token": "",
    "auto_install_tools": True,
    "dropbox_enabled": False,
    "dropbox_remote": "dropbox:HA-Backups",
    "nas_mounts": [],
    "server_presets": [],
    "jobs": []
}

# App-owned config (UI writes go here) - PERSISTENT
APP_CONFIG = "/config/remote_linux_backup.json"
APP_DEFAULTS = {
    # UI-managed keys (we prefer these over HA options if present)
    "known_hosts": [],
    "server_presets": [],
    "jobs": [],
    "nas_mounts": [],
    "gotify_enabled": False,
    "gotify_url": "",
    "gotify_token": "",
    "dropbox_enabled": False,
    "dropbox_remote": "dropbox:HA-Backups"
}

# File explorer roots (read-only browsing)
SAFE_ROOTS = ["/backup", "/mnt"]

app = Flask(__name__, static_folder=WWW_DIR, static_url_path="")

# ---------- helpers ----------
def _safe_load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_opts():
    """Load HA-managed options (read-only)."""
    d = _safe_load_json(OPTIONS_PATH)
    for k, v in DEFAULT_OPTIONS.items():
        d.setdefault(k, v)
    return d

def load_app_config():
    """Load UI-managed config stored under /config."""
    os.makedirs(os.path.dirname(APP_CONFIG), exist_ok=True)
    if not os.path.exists(APP_CONFIG):
        with open(APP_CONFIG, "w") as f:
            json.dump(APP_DEFAULTS, f, indent=2)
            f.flush(); os.fsync(f.fileno())
    with open(APP_CONFIG, "r") as f:
        data = json.load(f)
    # ensure defaults exist
    for k, v in APP_DEFAULTS.items():
        data.setdefault(k, v)
    return data

def save_app_config(data: dict):
    """Persist UI-managed config to /config (atomic)."""
    cfg = load_app_config()
    for k, v in data.items():
        # Normalize list-like strings
        if k in ("known_hosts","server_presets","jobs","nas_mounts") and isinstance(v, str):
            v = [s.strip() for s in v.replace("\r","").replace("\n",",").split(",") if s.strip()]
        # accept sane JSON types
        if isinstance(v, (str, int, float, bool)) or v is None or isinstance(v, (list, dict)):
            cfg[k] = v
    tmp = APP_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, APP_CONFIG)
    return True

def human_size(n):
    n=float(n)
    for u in ['B','KB','MB','GB','TB']:
        if n<1024.0: return f"{n:.1f} {u}"
        n/=1024.0
    return f"{n:.1f} PB"

def human_time(s):
    s=int(s)
    m,s=divmod(s,60)
    h,m=divmod(m,60)
    if h: return f"{h}h {m}m {s}s"
    if m: return f"{m}m {s}s"
    return f"{s}s"

def run(cmd):
    p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out_lines = []
    for line in p.stdout:
        out_lines.append(line)
    rc = p.wait()
    return rc, "".join(out_lines)

def _ssh_base_cmd(port):
    port_flag = f"-p {int(port)}" if str(port).strip() else ""
    return f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {port_flag}"

def ssh(user, host, password, remote_cmd, port=22):
    base = _ssh_base_cmd(port)
    cmd = f"sshpass -p {shlex.quote(password)} {base} {shlex.quote(user)}@{shlex.quote(host)} {shlex.quote(remote_cmd)}"
    return run(cmd)

def gotify(title, message, priority=5):
    # Prefer app config (user UI values), fallback to HA options
    appcfg = load_app_config()
    url = appcfg.get("gotify_url") or ""
    token = appcfg.get("gotify_token") or ""
    enabled = bool(appcfg.get("gotify_enabled"))
    if not enabled:
        # fallback
        opts = load_opts()
        url = url or opts.get("gotify_url") or ""
        token = token or opts.get("gotify_token") or ""
        enabled = enabled or bool(opts.get("gotify_enabled"))
    if not enabled or not url or not token:
        return
    cmd = f"curl -s -X POST {shlex.quote(url)}/message -F token={shlex.quote(token)} -F title={shlex.quote(title)} -F message={shlex.quote(message)} -F priority={priority}"
    run(cmd)

# ---------- backup/restore operations ----------
def dd_backup(user, host, password, disk, out_path, port=22, verify=False, bwlimit_kbps=None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    comp = "pigz -c" if subprocess.call("command -v pigz >/dev/null 2>&1", shell=True)==0 else "gzip -c"
    bw = f" | pv -q -L {int(bwlimit_kbps)*1024} " if bwlimit_kbps else " | "
    pipeline = f"sshpass -p {shlex.quote(password)} {_ssh_base_cmd(port)} {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(disk)} bs=64K status=progress'{bw}{comp} > {shlex.quote(out_path)}"
    rc,out = run(pipeline)
    sha_path = out_path + ".sha256"
    if rc==0:
        h = hashlib.sha256()
        with open(out_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk)
        with open(sha_path, "w") as sf:
            sf.write(f"{h.hexdigest()}  {os.path.basename(out_path)}\n")
        if verify:
            hv = hashlib.sha256()
            with open(out_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024*1024), b""):
                    hv.update(chunk)
            if hv.hexdigest()!=h.hexdigest():
                out += "\n[VERIFY] SHA256 mismatch!"; rc = 2
            else:
                out += "\n[VERIFY] SHA256 OK"
    return rc, out

def dd_restore(user, host, password, disk, image_path, port=22, bwlimit_kbps=None):
    comp = "pigz -dc" if subprocess.call("command -v pigz >/dev/null 2>&1", shell=True)==0 else "gzip -dc"
    bw = f" | pv -q -L {int(bwlimit_kbps)*1024} " if bwlimit_kbps else " | "
    pipeline = f"{comp} {shlex.quote(image_path)}{bw}sshpass -p {shlex.quote(password)} {_ssh_base_cmd(port)} {shlex.quote(user)}@{shlex.quote(host)} 'dd of={shlex.quote(disk)} bs=64K status=progress'"
    return run(pipeline)

def rsync_pull(user, host, password, sources_csv, dest, port=22, excludes_csv="", bwlimit_kbps=None):
    outs, rc = [], 0
    excl = "".join([f" --exclude {shlex.quote(pat)}" for pat in [s.strip() for s in (excludes_csv or "").split(",") if s.strip()]])
    bw = f" --bwlimit={int(bwlimit_kbps)}" if bwlimit_kbps else ""
    for src in [s.strip() for s in sources_csv.split(",") if s.strip()]:
        cmd = f"sshpass -p {shlex.quote(password)} rsync -aAX --numeric-ids{bw} -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {int(port)}' {excl} {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)} {shlex.quote(dest.rstrip('/') + '/')}"
        r, o = run(cmd)
        outs.append(f"$ {cmd}\n{o}");  rc = r if r != 0 else rc
    return rc, "\n".join(outs)

def rsync_push(user, host, password, local_src, remote_dest, port=22, excludes_csv="", bwlimit_kbps=None):
    excl = "".join([f" --exclude {shlex.quote(pat)}" for pat in [s.strip() for s in (excludes_csv or "").split(",") if s.strip()]])
    bw = f" --bwlimit={int(bwlimit_kbps)}" if bwlimit_kbps else ""
    cmd = f"sshpass -p {shlex.quote(password)} rsync -aAX --numeric-ids{bw} -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {int(port)}' {excl} {shlex.quote(local_src.rstrip('/') + '/')} {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(remote_dest.rstrip('/') + '/')}"
    return run(cmd)

def rclone_copy(local_path, remote_spec, bwlimit_kbps=None):
    bw = f" --bwlimit {int(bwlimit_kbps)}k" if bwlimit_kbps else ""
    return run(f"rclone copy {shlex.quote(local_path)} {shlex.quote(remote_spec)} --progress{bw}")

# ---------- routes ----------
@app.get("/")
def root():
    return app.send_static_file("index.html")

# Unified options: HA options overlaid with app config (UI-writable)
@app.get("/api/options")
def get_options():
    ha = load_opts()
    appcfg = load_app_config()
    merged = dict(ha)
    for k, v in appcfg.items():
        merged[k] = v
    return jsonify(merged)

@app.post("/api/options")
def set_options():
    # Accept JSON, form, or raw text JSON
    data = request.get_json(silent=True)
    if data is None and request.form:
        data = request.form.to_dict(flat=True)
        for key in ("known_hosts","server_presets","jobs","nas_mounts"):
            if key in data and isinstance(data[key], str):
                data[key] = [s.strip() for s in data[key].replace("\r","").replace("\n",",").split(",") if s.strip()]
    if data is None and request.data:
        try:
            data = json.loads(request.data.decode("utf-8"))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    ok = save_app_config(data)
    return jsonify({"ok": ok, "config": load_app_config()})

@app.post("/api/apply_schedule")
def apply_schedule():
    rc, out = run("python3 /app/scheduler.py apply")
    return jsonify({"rc": rc, "out": out})

@app.post("/api/probe_host")
def probe_host():
    b = request.json or {}
    user = b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    if not host:
        return jsonify({"rc":2,"out":"Missing host"}),400
    rc, out = ssh(user, host, pwd, "uname -a || true; cat /etc/os-release 2>/dev/null || true; which rsync || true; which dd || true; which zfs || true", port=port)
    return jsonify({"rc": rc, "out": out})

@app.post("/api/install_tools")
def install_tools():
    b = request.json or {}
    user = b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    if not host:
        return jsonify({"rc":2,"out":"Missing host"}),400
    cmds = [
        "which rsync || (which apt && apt update && apt install -y rsync) || (which apk && apk add rsync) || (which dnf && dnf install -y rsync) || (which pkg && pkg install -y rsync) || true",
        "which gzip || (which apt && apt install -y gzip) || (which apk && apk add gzip) || (which dnf && dnf install -y gzip) || (which pkg && pkg install -y gzip) || true",
        "which pigz || (which apt && apt install -y pigz) || (which apk && apk add pigz) || (which dnf && dnf install -y pigz) || (which pkg && pkg install -y pigz) || true"
    ]
    out_all, rc_final = [], 0
    for c in cmds:
        rc, out = ssh(user, host, pwd, c, port=port)
        out_all.append(out)
        if rc != 0: rc_final = rc
    return jsonify({"rc": rc_final, "out": "\n".join(out_all)})

@app.post("/api/estimate_backup")
def estimate_backup():
    b = request.json or {}
    method=b.get("method"); user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    bwlimit = int(b.get("bwlimit_kbps",0) or 0)
    kbps = bwlimit if bwlimit>0 else (40*1024)
    if not host or not method:
        return jsonify({"rc":2,"out":"Missing host/method"}),400
    if method=="dd":
        disk=b.get("disk","/dev/sda")
        rc,out = ssh(user,host,pwd,f"blockdev --getsize64 {shlex.quote(disk)} 2>/dev/null || cat /sys/block/$(basename {shlex.quote(disk)})/size 2>/dev/null", port=port)
        try: size_bytes=int(out.strip().splitlines()[-1])
        except Exception: size_bytes=0
        secs = int(size_bytes/(kbps*1024)) if size_bytes>0 else 0
        return jsonify({"rc":0,"bytes":size_bytes,"eta_seconds":secs,"eta":human_time(secs),"size":human_size(size_bytes)})
    elif method=="rsync":
        sources=b.get("files","/etc")
        total=0
        for src in [s.strip() for s in sources.split(",") if s.strip()]:
            rc,out = ssh(user,host,pwd,f"du -sb {shlex.quote(src)} 2>/dev/null | cut -f1", port=port)
            try: val=int(out.strip().splitlines()[-1])
            except Exception: val=0
            total+=val
        secs = int(total/(kbps*1024)) if total>0 else 0
        return jsonify({"rc":0,"bytes":total,"eta_seconds":secs,"eta":human_time(secs),"size":human_size(total)})
    elif method=="zfs":
        return jsonify({"rc":0,"bytes":0,"eta_seconds":5,"eta":"~5s","size":"n/a"})
    else:
        return jsonify({"rc":2,"out":"Unknown method"}),400

@app.post("/api/run_backup")
def run_backup():
    b = request.json or {}
    method=b.get("method"); user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    if not host or not method:
        return jsonify({"rc":2,"out":"Missing host/method"}),400
    store_to=b.get("store_to","/backup"); os.makedirs(store_to, exist_ok=True)
    cloud=b.get("cloud_upload",""); t0=time.time()
    bwlimit = int(b.get("bwlimit_kbps",0) or 0) or None
    verify = bool(b.get("verify", False))
    excludes = b.get("excludes","")
    retention_days = int(b.get("retention_days",0) or 0)
    name = b.get("backup_name","").strip()

    if method=="dd":
        disk=b.get("disk","/dev/sda")
        ts=time.strftime("%Y%m%d-%H%M%S")
        base_name=(name.replace(' ','_')+'-' if name else f"{host.replace('.','_')}-")+ts+".img.gz"
        out_path=os.path.join(store_to, base_name)
        rc,out = dd_backup(user,host,pwd,disk,out_path,port=port,verify=verify,bwlimit_kbps=bwlimit)
        size_bytes = local_size_bytes(out_path) if rc==0 else 0
        if rc==0 and cloud:
            rcrc,rout = rclone_copy(out_path,cloud,bwlimit_kbps=bwlimit); out += "\n[RCLONE]\n"+rout
        if retention_days>0:
            out += "\n[PRUNE]\n" + prune_old(store_to, retention_days)
        took=round(time.time()-t0,2)
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: dd\nSaved: {out_path}\nSize: {human_size(size_bytes)}\nTime: {human_time(int(took)))}")
        return jsonify({"rc":rc,"out":out,"seconds":took,"saved":out_path,"size_bytes":size_bytes})

    elif method=="rsync":
        files=b.get("files","/etc")
        dest = os.path.join(store_to, name.replace(' ','_')) if name else store_to
        os.makedirs(dest, exist_ok=True)
        rc,out = rsync_pull(user,host,pwd,files,dest,port=port,excludes_csv=excludes,bwlimit_kbps=bwlimit)
        size_bytes = local_size_bytes(dest) if rc==0 else 0
        if rc==0 and cloud:
            rcrc,rout = rclone_copy(dest,cloud,bwlimit_kbps=bwlimit); out += "\n[RCLONE]\n"+rout
        if retention_days>0:
            out += "\n[PRUNE]\n" + prune_old(dest, retention_days)
        took=round(time.time()-t0,2)
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: rsync\nSaved: {dest}\nSize: {human_size(size_bytes)}\nTime: {human_time(int(took))}")
        return jsonify({"rc":rc,"out":out,"seconds":took,"saved":dest,"size_bytes":size_bytes})

    elif method=="zfs":
        dataset=b.get("zfs_dataset")
        if not dataset:
            return jsonify({"rc":2,"out":"Missing zfs_dataset"}),400
        snap=b.get("snapshot_name", time.strftime("backup-%Y%m%d-%H%M%S"))
        rc,out = ssh(user,host,pwd,f"zfs snapshot {shlex.quote(dataset)}@{shlex.quote(snap)}", port=port)
        took=round(time.time()-t0,2)
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: zfs snapshot\nSnapshot: {dataset}@{snap}\nTime: {human_time(int(took))}")
        return jsonify({"rc":rc,"out":out,"seconds":took})

    else:
        return jsonify({"rc":2,"out":"Unknown method"}),400

@app.post("/api/run_restore")
def run_restore():
    b = request.json or {}
    method=b.get("method"); user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22)); t0=time.time()
    bwlimit = int(b.get("bwlimit_kbps",0) or 0) or None
    excludes = b.get("excludes","")
    if not host or not method:
        return jsonify({"rc":2,"out":"Missing host/method"}),400
    if method=="dd":
        image=b.get("image_path"); disk=b.get("disk","/dev/sda")
        if not image:
            return jsonify({"rc":2,"out":"Missing image_path"}),400
        rc,out = dd_restore(user,host,pwd,disk,image,port=port,bwlimit_kbps=bwlimit)
        took=round(time.time()-t0,2)
        gotify("Restore "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: dd restore\nSrc: {image}\nTime: {human_time(int(took)))}")
        return jsonify({"rc":rc,"out":out,"seconds":took})
    elif method=="rsync":
        local_src=b.get("local_src"); remote_dest=b.get("remote_dest","/")
        if not local_src:
            return jsonify({"rc":2,"out":"Missing local_src"}),400
        rc,out = rsync_push(user,host,pwd,local_src,remote_dest,port=port,excludes_csv=excludes,bwlimit_kbps=bwlimit)
        took=round(time.time()-t0,2)
        gotify("Restore "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: rsync restore\nDest: {remote_dest}\nTime: {human_time(int(took))}")
        return jsonify({"rc":rc,"out":out,"seconds":took})
    else:
        return jsonify({"rc":2,"out":"Unknown restore method"}),400

@app.get("/api/list_backups")
def list_backups():
    base = request.args.get("path","/backup")
    res = []
    for r,ds,fs in os.walk(base):
        for f in fs:
            p=os.path.join(r,f)
            try: sz=os.path.getsize(p)
            except: sz=0
            res.append({"path":p,"size":sz})
    return jsonify(sorted(res,key=lambda x:x["path"]))

# -------- File Explorer APIs --------

def _is_path_allowed(p: str) -> bool:
    rp = os.path.realpath(p)
    for root in SAFE_ROOTS:
        rr = os.path.realpath(root)
        if rp == rr or rp.startswith(rr + os.sep):
            return True
    return False

@app.get("/api/ls")
def api_ls():
    path = request.args.get("path", "/backup")
    if not _is_path_allowed(path) or not os.path.exists(path):
        return jsonify({"ok": False, "error": "Path not allowed or does not exist", "path": path}), 400
    items = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            try:
                st = os.stat(full, follow_symlinks=False)
                items.append({
                    "name": name,
                    "path": full,
                    "is_dir": os.path.isdir(full),
                    "size": st.st_size if os.path.isfile(full) else 0
                })
            except Exception:
                pass
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "path": path, "items": items})

@app.get("/api/download")
def api_download():
    path = request.args.get("path")
    if not path or not _is_path_allowed(path) or not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True)

@app.get("/www/<path:fn>")
def serve_www(fn):
    return send_from_directory(WWW_DIR, fn)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8066)
