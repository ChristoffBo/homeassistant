import os, json, subprocess, shlex, time, hashlib
from flask import Flask, request, jsonify, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(APP_DIR, "www")

# Persistent config
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

app = Flask(__name__, static_folder=WWW_DIR, static_url_path="")

def _safe_load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def load_opts():
    d = _safe_load_json(OPTIONS_PATH)
    changed = False
    for k, v in DEFAULT_OPTIONS.items():
        if k not in d:
            d[k] = v
            changed = True
    if changed:
        save_opts(d)
    return d

def save_opts(d):
    try:
        os.makedirs(os.path.dirname(OPTIONS_PATH), exist_ok=True)
    except Exception:
        pass
    tmp = OPTIONS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, OPTIONS_PATH)
    return True

def human_size(n):
    n=float(n)
    for u in ['B','KB','MB','GB','TB']:
        if n<1024.0:
            return f"{n:.1f} {u}"
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

def dd_backup(user, host, password, disk, out_path, port=22, verify=False, bwlimit_kbps=None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    comp = "pigz -c" if subprocess.call("command -v pigz >/dev/null 2>&1", shell=True)==0 else "gzip -c"
    base = _ssh_base_cmd(port)
    bw = f" | pv -q -L {int(bwlimit_kbps)*1024} " if bwlimit_kbps else " | "
    pipeline = f"sshpass -p {shlex.quote(password)} {base} {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(disk)} bs=64K status=progress'{bw}{comp} > {shlex.quote(out_path)}"
    rc,out = run(pipeline)
    sha_path = out_path + ".sha256"
    if rc==0:
        h = hashlib.sha256()
        with open(out_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk)
        with open(sha_path, "w", encoding="utf-8") as sf:
            sf.write(f"{h.hexdigest()}  {os.path.basename(out_path)}\n")
        if verify:
            hv = hashlib.sha256()
            with open(out_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024*1024), b""):
                    hv.update(chunk)
            if hv.hexdigest()!=h.hexdigest():
                out += "\n[VERIFY] SHA256 mismatch!"
                rc = 2
            else:
                out += "\n[VERIFY] SHA256 OK"
    return rc, out

def dd_restore(user, host, password, disk, image_path, port=22, bwlimit_kbps=None):
    comp = "pigz -dc" if subprocess.call("command -v pigz >/dev/null 2>&1", shell=True)==0 else "gzip -dc"
    base = _ssh_base_cmd(port)
    bw = f" | pv -q -L {int(bwlimit_kbps)*1024} " if bwlimit_kbps else " | "
    pipeline = f"{comp} {shlex.quote(image_path)}{bw}sshpass -p {shlex.quote(password)} {base} {shlex.quote(user)}@{shlex.quote(host)} 'dd of={shlex.quote(disk)} bs=64K status=progress'"
    return run(pipeline)

def rsync_pull(user, host, password, sources_csv, dest, port=22, excludes_csv="", bwlimit_kbps=None):
    outs, rc = [], 0
    excl = ""
    for pat in [s.strip() for s in (excludes_csv or "").split(",") if s.strip()]:
        excl += f" --exclude {shlex.quote(pat)}"
    bw = f" --bwlimit={int(bwlimit_kbps)}" if bwlimit_kbps else ""
    for src in [s.strip() for s in sources_csv.split(",") if s.strip()]:
        cmd = f"sshpass -p {shlex.quote(password)} rsync -aAX --numeric-ids{bw} -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {int(port)}' {excl} {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)} {shlex.quote(dest.rstrip('/') + '/')}"
        r, o = run(cmd)
        outs.append(f"$ {cmd}\n{o}")
        if r != 0: rc = r
    return rc, "\n".join(outs)

def rsync_push(user, host, password, local_src, remote_dest, port=22, excludes_csv="", bwlimit_kbps=None):
    excl = ""
    for pat in [s.strip() for s in (excludes_csv or "").split(",") if s.strip()]:
        excl += f" --exclude {shlex.quote(pat)}"
    bw = f" --bwlimit={int(bwlimit_kbps)}" if bwlimit_kbps else ""
    cmd = f"sshpass -p {shlex.quote(password)} rsync -aAX --numeric-ids{bw} -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {int(port)}' {excl} {shlex.quote(local_src.rstrip('/') + '/')} {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(remote_dest.rstrip('/') + '/')}"
    return run(cmd)

def rclone_copy(local_path, remote_spec, bwlimit_kbps=None):
    bw = f" --bwlimit {int(bwlimit_kbps)}k" if bwlimit_kbps else ""
    return run(f"rclone copy {shlex.quote(local_path)} {shlex.quote(remote_spec)} --progress{bw}")

def prune_old(path, days):
    if not days or days <= 0: return ""
    now = time.time()
    cutoff = now - days*86400
    deleted = []
    for r,ds,fs in os.walk(path):
        for f in fs:
            p=os.path.join(r,f)
            try:
                st = os.stat(p)
                if st.st_mtime < cutoff:
                    os.remove(p)
                    deleted.append(p)
            except Exception:
                pass
    return "\n".join(deleted)

def local_size_bytes(path):
    if os.path.isfile(path):
        try: return os.path.getsize(path)
        except: return 0
    total=0
    for r,ds,fs in os.walk(path):
        for f in fs:
            p=os.path.join(r,f)
            try: total+=os.path.getsize(p)
            except: pass
    return total

# ---------------- API ----------------

@app.get("/")
def root():
    return app.send_static_file("index.html")

@app.get("/api/options")
def get_options():
    return jsonify(load_opts())

@app.post("/api/options")
def set_options():
    data = request.json or {}
    opts = load_opts()
    opts.update(data)
    save_opts(opts)
    return jsonify({"ok": True})

@app.post("/api/apply_schedule")
def apply_schedule():
    rc, out = run("python3 /app/scheduler.py apply")
    return jsonify({"rc": rc, "out": out})

@app.post("/api/gotify_test")
def gotify_test():
    b = load_opts()
    if not (b.get("gotify_url") and b.get("gotify_token")):
        return jsonify({"ok": False, "msg": "Configure gotify_url and gotify_token first."}), 400
    url = b["gotify_url"].rstrip("/") + "/message"
    token = b["gotify_token"]
    cmd = f"curl -s -X POST {shlex.quote(url)} -F token={shlex.quote(token)} -F title='Test from Remote Linux Backup' -F message='This is a test notification.' -F priority=5"
    rc, out = run(cmd)
    return jsonify({"ok": rc==0, "rc": rc, "out": out})

@app.post("/api/probe_host")
def probe_host():
    b = request.json or {}
    user = b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    if not host:
        return jsonify({"rc":2,"out":"Missing host"}),400
    rc, out = ssh(user, host, pwd, "uname -a || true; cat /etc/os-release 2>/dev/null || true; which rsync || true; which dd || true; which zfs || true", port=port)
    return jsonify({"rc": rc, "out": out})

@app.post("/api/estimate_backup")
def estimate_backup():
    b = request.json or {}
    method=b.get("method"); user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    bwlimit = int(b.get("bwlimit_kbps",0) or 0)
    kbps = bwlimit if bwlimit>0 else (40*1024)  # default 40 MB/s
    if not host or not method:
        return jsonify({"rc":2,"out":"Missing host/method"}),400
    if method=="dd":
        disk=b.get("disk","/dev/sda")
        rc,out = ssh(user,host,pwd,f"blockdev --getsize64 {shlex.quote(disk)} 2>/dev/null || cat /sys/block/$(basename {shlex.quote(disk)})/size 2>/dev/null", port=port)
        try:
            size_bytes=int(out.strip().splitlines()[-1])
        except Exception:
            size_bytes=0
        secs = int(size_bytes/ (kbps*1024)) if size_bytes>0 else 0
        return jsonify({"rc":0,"bytes":size_bytes,"eta_seconds":secs,"eta":human_time(secs),"size":human_size(size_bytes)})
    elif method=="rsync":
        sources=b.get("files","/etc")
        total=0
        for src in [s.strip() for s in sources.split(",") if s.strip()]:
            rc,out = ssh(user,host,pwd,f"du -sb {shlex.quote(src)} 2>/dev/null | cut -f1", port=port)
            try:
                val=int(out.strip().splitlines()[-1])
            except Exception:
                val=0
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
    excludes = b.get("excludes","")  # rsync only
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
        return jsonify({"rc":rc,"out":out,"seconds":took,"saved":dest,"size_bytes":size_bytes})

    elif method=="zfs":
        dataset=b.get("zfs_dataset")
        if not dataset:
            return jsonify({"rc":2,"out":"Missing zfs_dataset"}),400
        snap=b.get("snapshot_name", time.strftime("backup-%Y%m%d-%H%M%S"))
        rc,out = ssh(user,host,pwd,f"zfs snapshot {shlex.quote(dataset)}@{shlex.quote(snap)}", port=port)
        took=round(time.time()-t0,2)
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
        return jsonify({"rc":rc,"out":out,"seconds":took})
    elif method=="rsync":
        local_src=b.get("local_src"); remote_dest=b.get("remote_dest","/")
        if not local_src:
            return jsonify({"rc":2,"out":"Missing local_src"}),400
        rc,out = rsync_push(user,host,pwd,local_src,remote_dest,port=port,excludes_csv=excludes,bwlimit_kbps=bwlimit)
        took=round(time.time()-t0,2)
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

@app.get("/www/<path:fn>")
def serve_www(fn):
    return send_from_directory(WWW_DIR, fn)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8066)
