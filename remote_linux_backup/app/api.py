import os, json, subprocess, shlex, time
from flask import Flask, request, jsonify, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
WWW_DIR = os.path.join(APP_DIR, "www")
os.makedirs(DATA_DIR, exist_ok=True)

OPTIONS_PATH = "/data/options.json"
app = Flask(__name__, static_folder=WWW_DIR, static_url_path="")

# Bootstrap default options if /data/options.json not present
DEFAULT_OPTIONS = {
    "ui_port": 8066,
    "gotify_enabled": False,
    "gotify_url": "",
    "gotify_token": "",
    "auto_install_tools": True,
    "dropbox_enabled": False,
    "dropbox_remote": "dropbox:HA-Backups",
    "nas_mounts": [],
    "server_presets": [],
    "known_hosts": [],
    "jobs": []
}

def load_opts():
    try:
        if os.path.exists(OPTIONS_PATH):
            with open(OPTIONS_PATH, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # ensure all keys
                    for k,v in DEFAULT_OPTIONS.items():
                        data.setdefault(k, v)
                    return data
    except Exception:
        pass
    return dict(DEFAULT_OPTIONS)

def save_opts(d):
    os.makedirs(os.path.dirname(OPTIONS_PATH), exist_ok=True)
    data = dict(DEFAULT_OPTIONS)
    if isinstance(d, dict):
        data.update(d)
    tmp = OPTIONS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, OPTIONS_PATH)

def run(cmd):
    p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out_lines = []
    for line in p.stdout:
        out_lines.append(line)
    rc = p.wait()
    return rc, "".join(out_lines)

def gotify(title, message, priority=5):
    opts = load_opts()
    if not opts.get("gotify_enabled"):
        return
    url = opts.get("gotify_url")
    token = opts.get("gotify_token")
    if not url or not token:
        return
    cmd = f"curl -s -X POST {shlex.quote(url)}/message -F token={shlex.quote(token)} -F title={shlex.quote(title)} -F message={shlex.quote(message)} -F priority={priority}"
    run(cmd)

def ssh(user, host, password, remote_cmd):
    cmd = f"sshpass -p {shlex.quote(password)} ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {shlex.quote(user)}@{shlex.quote(host)} {shlex.quote(remote_cmd)}"
    return run(cmd)

def dd_backup(user, host, password, disk, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pipeline = f"sshpass -p {shlex.quote(password)} ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(disk)} bs=64K status=progress | gzip -c' > {shlex.quote(out_path)}"
    return run(pipeline)

def dd_restore(user, host, password, disk, image_path):
    pipeline = f"gzip -dc {shlex.quote(image_path)} | sshpass -p {shlex.quote(password)} ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {shlex.quote(user)}@{shlex.quote(host)} 'dd of={shlex.quote(disk)} bs=64K status=progress'"
    return run(pipeline)

def rsync_pull(user, host, password, sources_csv, dest):
    outs, rc = [], 0
    for src in [s.strip() for s in sources_csv.split(",") if s.strip()]:
        cmd = f"sshpass -p {shlex.quote(password)} rsync -aAX --numeric-ids -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null' {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)} {shlex.quote(dest.rstrip('/') + '/')}"
        r, o = run(cmd)
        outs.append(f"$ {cmd}\n{o}")
        if r != 0: rc = r
    return rc, "\n".join(outs)

def rsync_push(user, host, password, local_src, remote_dest):
    cmd = f"sshpass -p {shlex.quote(password)} rsync -aAX --numeric-ids -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null' {shlex.quote(local_src.rstrip('/') + '/')} {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(remote_dest.rstrip('/') + '/')}"
    return run(cmd)

def rclone_copy(local_path, remote_spec):
    return run(f"rclone copy {shlex.quote(local_path)} {shlex.quote(remote_spec)} --progress")

@app.get("/")
def root():
    return app.send_static_file("index.html")

@app.get("/api/options")
def get_options():
    return jsonify(load_opts())

@app.post("/api/options")
def set_options():
    data = request.json or {}
    save_opts(data)
    return jsonify({"ok": True})

@app.post("/api/apply_schedule")
def apply_schedule():
    rc, out = run("python3 /app/scheduler.py apply")
    return jsonify({"rc": rc, "out": out})

@app.post("/api/probe_host")
def probe_host():
    b = request.json or {}
    user = b.get("username","root"); host=b["host"]; pwd=b["password"]
    rc, out = ssh(user, host, pwd, "uname -a || true; cat /etc/os-release 2>/dev/null || true; which rsync || true; which dd || true; which zfs || true")
    return jsonify({"rc": rc, "out": out})

@app.post("/api/install_tools")
def install_tools():
    b = request.json or {}
    user = b.get("username","root"); host=b["host"]; pwd=b["password"]
    cmds = [
        "which rsync || (which apt && apt update && apt install -y rsync) || (which apk && apk add rsync) || (which dnf && dnf install -y rsync) || (which pkg && pkg install -y rsync) || true",
        "which gzip || (which apt && apt update && apt install -y gzip) || (which apk && apk add gzip) || (which dnf && dnf install -y gzip) || (which pkg && pkg install -y gzip) || true"
    ]
    out_all, rc_final = [], 0
    for c in cmds:
        rc, out = ssh(user, host, pwd, c)
        out_all.append(out)
        if rc != 0: rc_final = rc
    return jsonify({"rc": rc_final, "out": "\n".join(out_all)})

@app.post("/api/run_backup")
def run_backup():
    b = request.json or {}
    method=b["method"]; user=b.get("username","root"); host=b["host"]; pwd=b["password"]
    store_to=b.get("store_to","/backup"); os.makedirs(store_to, exist_ok=True)
    cloud=b.get("cloud_upload",""); t0=time.time()
    if method=="dd":
        disk=b.get("disk","/dev/sda")
        ts=time.strftime("%Y%m%d-%H%M%S")
        out_path=os.path.join(store_to, f"{host.replace('.','_')}-{ts}.img.gz")
        rc,out = dd_backup(user,host,pwd,disk,out_path)
        if rc==0 and cloud:
            rcrc,rout = rclone_copy(out_path,cloud); out += "\n[RCLONE]\n"+rout
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: dd\nSaved: {out_path}")
        return jsonify({"rc":rc,"out":out,"seconds":round(time.time()-t0,2),"saved":out_path})
    elif method=="rsync":
        files=b.get("files","/etc")
        rc,out = rsync_pull(user,host,pwd,files,store_to)
        if rc==0 and cloud:
            rcrc,rout = rclone_copy(store_to,cloud); out += "\n[RCLONE]\n"+rout
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: rsync\nSaved: {store_to}")
        return jsonify({"rc":rc,"out":out,"seconds":round(time.time()-t0,2)})
    elif method=="zfs":
        dataset=b["zfs_dataset"]
        snap=b.get("snapshot_name", time.strftime("backup-%Y%m%d-%H%M%S"))
        rc,out = ssh(user,host,pwd,f"zfs snapshot {shlex.quote(dataset)}@{shlex.quote(snap)}")
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: zfs snapshot\nSnapshot: {dataset}@{snap}")
        return jsonify({"rc":rc,"out":out,"seconds":round(time.time()-t0,2)})
    else:
        return jsonify({"rc":2,"out":"Unknown method"}),400

@app.post("/api/run_restore")
def run_restore():
    b = request.json or {}
    method=b["method"]; user=b.get("username","root"); host=b["host"]; pwd=b["password"]; t0=time.time()
    if method=="dd":
        image=b["image_path"]; disk=b.get("disk","/dev/sda")
        rc,out = dd_restore(user,host,pwd,disk,image)
        gotify("Restore "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: dd restore\nSrc: {image}")
        return jsonify({"rc":rc,"out":out,"seconds":round(time.time()-t0,2)})
    elif method=="rsync":
        local_src=b["local_src"]; remote_dest=b.get("remote_dest","/")
        rc,out = rsync_push(user,host,pwd,local_src,remote_dest)
        gotify("Restore "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: rsync restore\nDest: {remote_dest}")
        return jsonify({"rc":rc,"out":out,"seconds":round(time.time()-t0,2)})
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
