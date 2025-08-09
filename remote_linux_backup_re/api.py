import os, json, subprocess, shlex, time, hashlib, shutil, tempfile
from flask import Flask, request, jsonify, send_from_directory, send_file, abort

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(APP_DIR, "www")

OPTIONS_PATH = "/data/options.json"          # HA options (read-only)
APP_CONFIG   = "/config/remote_linux_backup.json"  # persistent app config
INDEX_PATH   = "/config/remote_linux_backup_index.json"
RCLONE_CONFIG = os.environ.get("RCLONE_CONFIG", "/config/rclone.conf")
SAFE_ROOTS = ["/backup", "/mnt"]

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

APP_DEFAULTS = {
    "known_hosts": [],
    "server_presets": [],
    "jobs": [],
    "nas_mounts": [],
    "gotify_enabled": False,
    "gotify_url": "",
    "gotify_token": "",
    "dropbox_enabled": False,
    "dropbox_remote": "dropbox:HA-Backups",
    "mounts": [],
    "servers": []
}

app = Flask(__name__, static_folder=WWW_DIR, static_url_path="")

# ---------------- utilities ----------------
def _safe_load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_opts():
    d = _safe_load_json(OPTIONS_PATH)
    for k,v in DEFAULT_OPTIONS.items():
        d.setdefault(k,v)
    return d

def load_app_config():
    os.makedirs(os.path.dirname(APP_CONFIG), exist_ok=True)
    if not os.path.exists(APP_CONFIG):
        with open(APP_CONFIG, "w") as f:
            json.dump(APP_DEFAULTS, f, indent=2); f.flush(); os.fsync(f.fileno())
    with open(APP_CONFIG, "r") as f:
        data = json.load(f)
    for k,v in APP_DEFAULTS.items():
        data.setdefault(k,v)
    if not isinstance(data.get("mounts"), list):  data["mounts"]=[]
    if not isinstance(data.get("servers"), list): data["servers"]=[]
    return data

def save_app_config(data: dict):
    cfg = load_app_config()
    for k,v in data.items():
        if k=="mounts" and isinstance(v, list):
            cleaned=[]
            for m in v:
                if not isinstance(m, dict): continue
                cleaned.append({
                    "name": str(m.get("name","")).strip(),
                    "proto": str(m.get("proto","")).strip(),
                    "server": str(m.get("server","")).strip(),
                    "share": str(m.get("share","")).strip(),
                    "mount": str(m.get("mount","")).strip(),
                    "username": str(m.get("username","")).strip(),
                    "password": str(m.get("password","")).strip(),
                    "options": str(m.get("options","")).strip(),
                    "auto_mount": bool(m.get("auto_mount", False))
                })
            cfg["mounts"]=cleaned; continue
        if k=="servers" and isinstance(v, list):
            cleaned=[]
            for s in v:
                if not isinstance(s, dict): continue
                cleaned.append({
                    "name": str(s.get("name","")).strip(),
                    "host": str(s.get("host","")).strip(),
                    "username": str(s.get("username","root")).strip(),
                    "port": int(s.get("port",22)),
                    "save_password": bool(s.get("save_password", False)),
                    "password": str(s.get("password","")).strip() if s.get("save_password") else ""
                })
            cfg["servers"]=cleaned; continue
        cfg[k]=v
    tmp = APP_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, APP_CONFIG)
    return True

def run(cmd):
    p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.communicate()[0]
    return p.returncode, out

def human_size(n):
    n=float(n)
    for u in ['B','KB','MB','GB','TB']:
        if n<1024.0: return f"{n:.1f} {u}"
        n/=1024.0
    return f"{n:.1f} PB"

def human_time(s):
    s=int(s); m,s = divmod(s,60); h,m = divmod(m,60)
    if h: return f"{h}h {m}m {s}s"
    if m: return f"{m}m {s}s"
    return f"{s}s"

def _ssh_base_cmd(port):
    port_flag = f"-p {int(port)}" if str(port).strip() else ""
    return f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {port_flag}"

def ssh(user, host, password, remote_cmd, port=22):
    base = _ssh_base_cmd(port)
    cmd = f"sshpass -p {shlex.quote(password)} {base} {shlex.quote(user)}@{shlex.quote(host)} {shlex.quote(remote_cmd)}"
    return run(cmd)

# --------------- backup helpers ---------------
def gotify(title, message, priority=5):
    appcfg = load_app_config()
    url = appcfg.get("gotify_url") or ""
    token = appcfg.get("gotify_token") or ""
    enabled = bool(appcfg.get("gotify_enabled"))
    if not enabled:
        opts = load_opts()
        url = url or (opts.get("gotify_url") or "")
        token = token or (opts.get("gotify_token") or "")
        enabled = enabled or bool(opts.get("gotify_enabled"))
    if not enabled or not url or not token: return
    cmd = f"curl -s -X POST {shlex.quote(url)}/message -F token={shlex.quote(token)} -F title={shlex.quote(title)} -F message={shlex.quote(message)} -F priority={priority}"
    run(cmd)

def dd_backup(user, host, password, disk, out_path, port=22, verify=False, bwlimit_kbps=None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    comp = "pigz -c" if subprocess.call("command -v pigz >/dev/null 2>&1", shell=True)==0 else "gzip -c"
    bw = f" | pv -q -L {int(bwlimit_kbps)*1024} " if bwlimit_kbps else " | "
    pipeline = f"sshpass -p {shlex.quote(password)} {_ssh_base_cmd(port)} {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(disk)} bs=64K status=progress'{bw}{comp} > {shlex.quote(out_path)}"
    rc,out = run(pipeline)
    if rc==0:
        h = hashlib.sha256()
        with open(out_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""): h.update(chunk)
        with open(out_path + ".sha256", "w") as sf:
            sf.write(f"{h.hexdigest()}  {os.path.basename(out_path)}\n")
        if verify:
            hv = hashlib.sha256()
            with open(out_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024*1024), b""): hv.update(chunk)
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
        r,o = run(cmd); outs.append(f"$ {cmd}\n{o}"); rc = r if r!=0 else rc
    return rc, "\n".join(outs)

def rsync_push(user, host, password, local_src, remote_dest, port=22, excludes_csv="", bwlimit_kbps=None):
    excl = "".join([f" --exclude {shlex.quote(pat)}" for pat in [s.strip() for s in (excludes_csv or "").split(",") if s.strip()]])
    bw = f" --bwlimit={int(bwlimit_kbps)}" if bwlimit_kbps else ""
    cmd = f"sshpass -p {shlex.quote(password)} rsync -aAX --numeric-ids{bw} -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {int(port)}' {excl} {shlex.quote(local_src.rstrip('/') + '/')} {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(remote_dest.rstrip('/') + '/')}"
    return run(cmd)

def rclone_copy(local_path, remote_spec, bwlimit_kbps=None):
    cfg = shlex.quote(RCLONE_CONFIG)
    bw = f" --bwlimit {int(bwlimit_kbps)}k" if bwlimit_kbps else ""
    return run(f"rclone copy {shlex.quote(local_path)} {shlex.quote(remote_spec)} --progress --config {cfg}{bw}")

# --------------- backup index ---------------
def _load_index():
    d = _safe_load_json(INDEX_PATH)
    if not isinstance(d, dict) or "items" not in d: d = {"items":[]}
    return d

def _save_index(d):
    tmp = INDEX_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, INDEX_PATH)

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

def index_add(path, kind, host, note=""):
    it = {"path": path, "kind": kind, "host": host or "", "size": local_size_bytes(path), "created": int(time.time()), "note": note or ""}
    d = _load_index()
    d["items"] = [x for x in d["items"] if x.get("path") != path]
    d["items"].append(it); _save_index(d); return it

def index_remove(path):
    d = _load_index()
    d["items"] = [x for x in d["items"] if x.get("path") != path]
    _save_index(d)

def rescan_backups():
    items=[]
    for root in SAFE_ROOTS:
        if not os.path.isdir(root): continue
        for r,ds,fs in os.walk(root):
            for f in fs:
                p=os.path.join(r,f)
                kind = "dd" if f.endswith(".img.gz") or f.endswith(".img") else "file"
                try:
                    st=os.stat(p)
                    items.append({"path":p,"kind":kind,"host":"","size":st.st_size,"created":int(st.st_mtime),"note":""})
                except: pass
    d={"items":items}; _save_index(d); return d

def _is_path_allowed(p: str) -> bool:
    rp = os.path.realpath(p)
    for root in SAFE_ROOTS:
        rr = os.path.realpath(root)
        if rp == rr or rp.startswith(rr + os.sep): return True
    return False

# --------------- SMB/NFS/SSH browsing ---------------
@app.post("/api/smb_shares")
def smb_shares():
    b = request.json or {}
    host = b.get("host","").strip()
    user = b.get("username","").strip()
    pw   = b.get("password","")
    if not host: return jsonify({"ok":False,"error":"missing host"}),400
    # -g: machine parse; -N for no password when user empty
    if user:
        cmd = f"SMBCLIENT='smbclient' && $SMBCLIENT -L //{shlex.quote(host)} -U {shlex.quote(user+'%'+pw)} -g 2>&1"
    else:
        cmd = f"smbclient -L //{shlex.quote(host)} -N -g 2>&1"
    rc,out = run(cmd)
    shares=[]
    for line in out.splitlines():
        # format: "Disk|Sharename|Comment"
        if "|" in line and line.split("|",1)[0] in ("Disk","Printer"):
            parts=line.split("|")
            if len(parts)>=3:
                shares.append({"type":parts[0],"name":parts[1],"comment":parts[2]})
    return jsonify({"ok": rc==0, "rc":rc, "out":out, "shares":shares})

@app.post("/api/smb_ls")
def smb_ls():
    b = request.json or {}
    host=b.get("host","").strip(); share=b.get("share","").strip()
    user=b.get("username","").strip(); pw=b.get("password","")
    path=b.get("path","").strip() or "/"
    if not host or not share: return jsonify({"ok":False,"error":"missing host/share"}),400
    cmd = f"smbclient //{shlex.quote(host)}/{shlex.quote(share)} {'-U '+shlex.quote(user+'%'+pw) if user else '-N'} -c 'ls \"{path}\"' 2>&1"
    rc,out = run(cmd)
    items=[]
    for line in out.splitlines():
        # expect: filename <spaces> A/H/D ...
        if line.strip() and not line.startswith("Domain") and not line.startswith("NT_STATUS") and not line.startswith("Reconnecting") and not line.lower().startswith("anonymous login"):
            cols=line.split()
            name=cols[0]
            # crude dir detection
            is_dir=name.endswith("/") or (" D " in line)
            items.append({"name":name.strip("/"),"is_dir":bool(is_dir)})
    return jsonify({"ok": rc==0, "rc":rc, "items":items, "raw":out})

@app.post("/api/nfs_exports")
def nfs_exports():
    b = request.json or {}
    host=b.get("host","").strip()
    if not host: return jsonify({"ok":False,"error":"missing host"}),400
    rc,out = run(f"showmount -e {shlex.quote(host)} 2>&1")
    exports=[]
    for line in out.splitlines():
        line=line.strip()
        if line and line[0]=="/":
            exports.append(line.split()[0])
    return jsonify({"ok": rc==0, "rc":rc, "exports":exports, "raw":out})

@app.post("/api/nfs_ls")
def nfs_ls():
    b=request.json or {}
    host=b.get("host","").strip(); export=b.get("export","").strip()
    subpath=b.get("path","").strip().lstrip("/")
    if not host or not export: return jsonify({"ok":False,"error":"missing host/export"}),400
    tmpd=tempfile.mkdtemp(prefix="nfsls-")
    rc,out = run(f"mount -t nfs {shlex.quote(host)}:{shlex.quote(export)} {shlex.quote(tmpd)} -o ro 2>&1")
    items=[]; rc2=rc; raw=out
    if rc==0:
        base=os.path.join(tmpd,subpath)
        try:
            for name in sorted(os.listdir(base)):
                full=os.path.join(base,name)
                items.append({"name":name,"is_dir": os.path.isdir(full)})
        except Exception as e:
            raw += f"\n{e}"
        run(f"umount {shlex.quote(tmpd)}")
    shutil.rmtree(tmpd, ignore_errors=True)
    return jsonify({"ok": rc2==0, "rc":rc2, "items":items, "raw":raw})

@app.post("/api/ssh_ls")
def ssh_ls():
    b=request.json or {}
    host=b.get("host","").strip(); user=b.get("username","root").strip()
    pw=b.get("password",""); port=int(b.get("port",22)); path=b.get("path","/").strip()
    if not host: return jsonify({"ok":False,"error":"missing host"}),400
    # list only one level to keep it fast
    cmd = f"{_ssh_base_cmd(port)} {shlex.quote(user)}@{shlex.quote(host)} 'set -e; p=\"{shlex.quote(path)}\"; [ -d \"$p\" ] && (ls -1Ap \"$p\" || true) || echo __NOTDIR__' 2>&1"
    rc,out = run(f"sshpass -p {shlex.quote(pw)} {cmd}")
    if "__NOTDIR__" in out: return jsonify({"ok":False,"error":"not a directory","rc":rc})
    items=[]
    for line in out.splitlines():
        if not line: continue
        name=line.rstrip("/")
        is_dir=line.endswith("/")
        items.append({"name":name,"is_dir":is_dir})
    return jsonify({"ok": rc==0, "rc":rc, "items":items, "raw":out})

# --------------- options & mounts & servers ---------------
@app.get("/api/options")
def get_options():
    ha = load_opts(); appcfg = load_app_config()
    merged = dict(ha); merged.update(appcfg)
    merged["rclone_config_exists"] = os.path.exists(RCLONE_CONFIG)
    return jsonify(merged)

@app.post("/api/options")
def set_options():
    data = request.get_json(silent=True) or {}
    ok = save_app_config(data)
    return jsonify({"ok":ok, "config": load_app_config()})

@app.post("/api/gotify_test")
def gotify_test():
    gotify("Test Notification", "Hello from Remote Linux Backup (UI test).", 5)
    return jsonify({"ok": True})

@app.post("/api/dropbox_test")
def dropbox_test():
    cfg = load_app_config()
    remote = cfg.get("dropbox_remote","dropbox:HA-Backups")
    rc,out = run(f"rclone ls {shlex.quote(remote)} --config {shlex.quote(RCLONE_CONFIG)} 2>&1 | head -n 20")
    return jsonify({"ok": rc==0, "rc":rc, "out":out, "config_exists": os.path.exists(RCLONE_CONFIG), "remote": remote})

@app.get("/api/mounts")
def api_mounts_get():
    cfg = load_app_config()
    # detect mounted
    rc,out = run("mount")
    mounted_text = out if rc==0 else ""
    items=[]
    for m in cfg.get("mounts", []):
        mp = m.get("mount","")
        is_mounted = (mp and (mp + " ") in mounted_text) or (mp and os.path.ismount(mp))
        items.append({**m, "mounted": bool(is_mounted)})
    return jsonify({"items": items})

@app.post("/api/mounts")
def api_mounts_set():
    b=request.get_json(silent=True) or {}
    ok = save_app_config({"mounts": b.get("mounts", [])})
    return jsonify({"ok":ok})

def _mount_entry(entry):
    proto = entry.get("proto",""); server= entry.get("server",""); share = entry.get("share",""); mountp= entry.get("mount","")
    user  = entry.get("username",""); pw = entry.get("password",""); opts  = entry.get("options","")
    if not (proto and server and share and mountp): return 2, "Missing proto/server/share/mount"
    os.makedirs(mountp, exist_ok=True)
    if proto == "cifs":
        mopts="rw,vers=3.0,iocharset=utf8"
        if user: mopts += f",username={shlex.quote(user)}"
        if pw:   mopts += f",password={shlex.quote(pw)}"
        if opts: mopts += f",{opts}"
        return run(f"mount -t cifs //{shlex.quote(server)}/{shlex.quote(share)} {shlex.quote(mountp)} -o {mopts}")
    elif proto == "nfs":
        mopts = opts or "rw"
        return run(f"mount -t nfs {shlex.quote(server)}:{shlex.quote(share)} {shlex.quote(mountp)} -o {shlex.quote(mopts)}")
    else:
        return 2, "Unsupported proto (use cifs or nfs)"

@app.post("/api/mounts/mount")
def api_mount_now():
    b=request.get_json(silent=True) or {}
    entry=b.get("entry")
    if not isinstance(entry, dict): return jsonify({"ok":False,"error":"missing entry"}),400
    rc,out=_mount_entry(entry)
    return jsonify({"ok": rc==0, "rc":rc, "out":out})

@app.post("/api/mounts/unmount")
def api_unmount_now():
    b=request.get_json(silent=True) or {}
    p=b.get("mount","")
    if not p: return jsonify({"ok":False,"error":"missing mount"}),400
    rc,out = run(f"umount {shlex.quote(p)}")
    return jsonify({"ok": rc==0, "rc":rc, "out":out})

@app.get("/api/servers")
def api_servers_get():
    return jsonify({"items": load_app_config().get("servers", [])})

@app.post("/api/servers")
def api_servers_set():
    b=request.get_json(silent=True) or {}
    ok = save_app_config({"servers": b.get("servers", [])})
    return jsonify({"ok":ok})

# --------------- backup/restore ---------------
@app.post("/api/probe_host")
def probe_host():
    b=request.json or {}
    user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    if not host: return jsonify({"rc":2,"out":"Missing host"}),400
    rc,out = ssh(user, host, pwd, "uname -a || true; cat /etc/os-release 2>/dev/null || true; which rsync || true; which dd || true; which zfs || true", port=port)
    return jsonify({"rc":rc,"out":out})

@app.post("/api/install_tools")
def install_tools():
    b=request.json or {}
    user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    if not host: return jsonify({"rc":2,"out":"Missing host"}),400
    cmds=[
        "which rsync || (which apt && apt update && apt install -y rsync) || (which apk && apk add rsync) || (which dnf && dnf install -y rsync) || (which pkg && pkg install -y rsync) || true",
        "which gzip || (which apt && apt update && apt install -y gzip) || (which apk && apk add gzip) || (which dnf && dnf install -y gzip) || (which pkg && pkg install -y gzip) || true",
        "which pigz || (which apt && apt update && apt install -y pigz) || (which apk && apk add pigz) || (which dnf && dnf install -y pigz) || (which pkg && pkg install -y pigz) || true"
    ]
    out_all=[]; rc_final=0
    for c in cmds:
        rc,out=ssh(user,host,pwd,c,port=port); out_all.append(out); rc_final = rc if rc!=0 else rc_final
    return jsonify({"rc":rc_final,"out":"\n".join(out_all)})

@app.post("/api/estimate_backup")
def estimate_backup():
    b=request.json or {}
    method=b.get("method"); user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    bwlimit=int(b.get("bwlimit_kbps",0) or 0); kbps=bwlimit if bwlimit>0 else 40*1024
    if not host or not method: return jsonify({"rc":2,"out":"Missing host/method"}),400
    if method=="dd":
        disk=b.get("disk","/dev/sda")
        rc,out = ssh(user,host,pwd,f"blockdev --getsize64 {shlex.quote(disk)} 2>/dev/null || cat /sys/block/$(basename {shlex.quote(disk)})/size 2>/dev/null", port=port)
        try: size=int(out.strip().splitlines()[-1])
        except: size=0
        secs = int(size/(kbps*1024)) if size>0 else 0
        return jsonify({"rc":0,"bytes":size,"eta_seconds":secs,"eta":human_time(secs),"size":human_size(size)})
    elif method=="rsync":
        sources=b.get("files","/etc"); total=0
        for src in [s.strip() for s in sources.split(",") if s.strip()]:
            rc,out = ssh(user,host,pwd,f"du -sb {shlex.quote(src)} 2>/dev/null | cut -f1", port=port)
            try: total += int(out.strip().splitlines()[-1])
            except: pass
        secs = int(total/(kbps*1024)) if total>0 else 0
        return jsonify({"rc":0,"bytes":total,"eta_seconds":secs,"eta":human_time(secs),"size":human_size(total)})
    else:
        return jsonify({"rc":2,"out":"Unknown method"}),400

@app.post("/api/run_backup")
def run_backup():
    b=request.json or {}
    method=b.get("method"); user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22))
    if not host or not method: return jsonify({"rc":2,"out":"Missing host/method"}),400
    store_to=b.get("store_to","/backup"); os.makedirs(store_to, exist_ok=True)
    cloud=b.get("cloud_upload","")
    bwlimit=int(b.get("bwlimit_kbps",0) or 0) or None
    verify=bool(b.get("verify", False))
    excludes=b.get("excludes","")
    retention_days=int(b.get("retention_days",0) or 0)
    name=b.get("backup_name","").strip()
    remember=bool(b.get("remember_server", True)); save_pw=bool(b.get("save_password", False))

    # upsert server preset
    if remember:
        cfg=load_app_config(); servers=cfg.get("servers",[])
        found=None
        for s in servers:
            if s.get("host")==host and s.get("username")==user and int(s.get("port",22))==int(port):
                found=s; break
        entry={"name": name or host, "host": host, "username": user, "port": int(port), "save_password": save_pw, "password": (pwd if save_pw else "")}
        if found: found.update(entry)
        else: servers.append(entry)
        save_app_config({"servers": servers})

    t0=time.time()
    if method=="dd":
        disk=b.get("disk","/dev/sda")
        ts=time.strftime("%Y%m%d-%H%M%S")
        base=(name.replace(' ','_')+'-' if name else f"{host.replace('.','_')}-")+ts+".img.gz"
        out_path=os.path.join(store_to, base)
        rc,out = dd_backup(user,host,pwd,disk,out_path,port=port,verify=verify,bwlimit_kbps=bwlimit)
        size = local_size_bytes(out_path) if rc==0 else 0
        if rc==0 and cloud:
            rcrc,rout = rclone_copy(out_path,cloud,bwlimit_kbps=bwlimit); out += "\n[RCLONE]\n"+rout
        if retention_days>0:
            out += "\n[PRUNE]\n" + "\n".join([])  # prune moved into UI if needed
        took=round(time.time()-t0,2)
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: dd\nSaved: {out_path}\nSize: {human_size(size)}\nTime: {human_time(int(took))}")
        index_add(out_path, "dd", host, note=name)
        return jsonify({"rc":rc,"out":out,"seconds":took,"saved":out_path,"size_bytes":size})

    elif method=="rsync":
        files=b.get("files","/etc")
        dest = os.path.join(store_to, name.replace(' ','_')) if name else store_to
        os.makedirs(dest, exist_ok=True)
        rc,out = rsync_pull(user,host,pwd,files,dest,port=port,excludes_csv=excludes,bwlimit_kbps=bwlimit)
        size = local_size_bytes(dest) if rc==0 else 0
        if rc==0 and cloud:
            rcrc,rout = rclone_copy(dest,cloud,bwlimit_kbps=bwlimit); out += "\n[RCLONE]\n"+rout
        took=round(time.time()-t0,2)
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: rsync\nSaved: {dest}\nSize: {human_size(size)}\nTime: {human_time(int(took))}")
        index_add(dest, "rsync", host, note=name or files)
        return jsonify({"rc":rc,"out":out,"seconds":took,"saved":dest,"size_bytes":size})
    else:
        return jsonify({"rc":2,"out":"Unknown method"}),400

@app.post("/api/run_restore")
def run_restore():
    b=request.json or {}
    method=b.get("method"); user=b.get("username","root"); host=b.get("host",""); pwd=b.get("password",""); port=int(b.get("port",22)); t0=time.time()
    bwlimit=int(b.get("bwlimit_kbps",0) or 0) or None
    excludes=b.get("excludes","")
    if not host or not method: return jsonify({"rc":2,"out":"Missing host/method"}),400
    if method=="dd":
        image=b.get("image_path"); disk=b.get("disk","/dev/sda")
        if not image: return jsonify({"rc":2,"out":"Missing image_path"}),400
        rc,out = dd_restore(user,host,pwd,disk,image,port=port,bwlimit_kbps=bwlimit)
        took=round(time.time()-t0,2)
        gotify("Restore "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: dd restore\nSrc: {image}\nTime: {human_time(int(took))}")
        return jsonify({"rc":rc,"out":out,"seconds":took})
    elif method=="rsync":
        local_src=b.get("local_src"); remote_dest=b.get("remote_dest","/")
        if not local_src: return jsonify({"rc":2,"out":"Missing local_src"}),400
        rc,out = rsync_push(user,host,pwd,local_src,remote_dest,port=port,excludes_csv=excludes,bwlimit_kbps=bwlimit)
        took=round(time.time()-t0,2)
        gotify("Restore "+("OK" if rc==0 else "FAIL"), f"Host: {host}\nMethod: rsync restore\nDest: {remote_dest}\nTime: {human_time(int(took))}")
        return jsonify({"rc":rc,"out":out,"seconds":took})
    else:
        return jsonify({"rc":2,"out":"Unknown restore method"}),400

# --------------- listing/backups/download ---------------
@app.get("/api/ls")
def api_ls():
    path = request.args.get("path", "/backup")
    if not _is_path_allowed(path) or not os.path.exists(path):
        return jsonify({"ok": False, "error": "Path not allowed or does not exist", "path": path}), 400
    items=[]
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        try:
            st = os.stat(full, follow_symlinks=False)
            items.append({"name": name, "path": full, "is_dir": os.path.isdir(full), "size": st.st_size if os.path.isfile(full) else 0})
        except Exception: pass
    return jsonify({"ok": True, "path": path, "items": items})

@app.get("/api/backups")
def api_backups_get():
    if request.args.get("rescan") == "1": d = rescan_backups()
    else: d = _load_index()
    return jsonify(d)

@app.post("/api/backups/delete")
def api_backups_delete():
    b=request.get_json(silent=True) or {}; path=b.get("path","")
    if not path or not _is_path_allowed(path): return jsonify({"ok":False,"error":"bad path"}),400
    try:
        if os.path.isdir(path): shutil.rmtree(path)
        elif os.path.isfile(path): os.remove(path)
        index_remove(path)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),500

@app.get("/api/download")
def api_download():
    path=request.args.get("path")
    if not path or not _is_path_allowed(path) or not os.path.isfile(path): abort(404)
    return send_file(path, as_attachment=True)

# --------------- static ---------------
@app.get("/")
def root(): return app.send_static_file("index.html")

@app.get("/www/<path:fn>")
def serve_www(fn): return send_from_directory(WWW_DIR, fn)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8066)
