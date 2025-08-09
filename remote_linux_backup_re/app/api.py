#!/usr/bin/env python3
import os, json, shlex, time, pathlib, mimetypes, subprocess
from typing import Dict, Any, Tuple, List
from flask import Flask, request, jsonify, send_from_directory, abort

# ----- paths -----
APP_DIR = "/app"
DATA_DIR = "/data"
CONF_PATH = os.path.join(DATA_DIR, "config.json")
WWW_CANDIDATES = ["/www", os.path.join(APP_DIR, "www")]  # prefers /www at repo root
WWW_DIR = next((p for p in WWW_CANDIDATES if os.path.isdir(p)), WWW_CANDIDATES[-1])

DEFAULT_CONFIG = {
    "options": {
        "ui_port": 8066,
        "gotify_enabled": False,
        "gotify_url": "",
        "gotify_token": "",
        "dropbox_enabled": False,
        "dropbox_remote": "dropbox:HA-Backups",
    },
    "servers": [],
    "mounts": []
}

RUNNER = "/app/job_runner.py"
RUNNER_CMD_BACKUP = "python3 /app/job_runner.py backup"
RUNNER_CMD_RESTORE = "python3 /app/job_runner.py restore"

app = Flask(__name__)

# ======= helpers =======
def _ensure_dirs():
    pathlib.Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

def _load_config() -> Dict[str, Any]:
    _ensure_dirs()
    if not os.path.exists(CONF_PATH):
        _save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONF_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))

def _save_config(cfg: Dict[str, Any]):
    _ensure_dirs()
    tmp = CONF_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONF_PATH)

def human_bytes(n: int) -> str:
    try: n = int(n)
    except Exception: return "0 B"
    if n < 1024: return f"{n} B"
    u = ["KB","MB","GB","TB","PB"]; i=-1; v=float(n)
    while v>=1024 and i<len(u)-1: v/=1024.0; i+=1
    return f"{v:.1f} {u[i]}"

def fmt_duration(sec: float) -> str:
    sec = int(sec); h=sec//3600; m=(sec%3600)//60; s=sec%60
    return f"{h:02d}:{m:02d}:{s:02d}"

def run_cmd(cmd: str, stdin: str = "", timeout: int = 360000) -> Tuple[int,str,str]:
    try:
        p = subprocess.run(cmd, shell=True, input=stdin, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 99, "", str(e)

# ======= SMB/NFS discovery =======
def _smb_try_modes(): return ["SMB3","SMB2","NT1"]

def smb_list_shares(host, user="", pwd=""):
    creds = f" -U {shlex.quote(f'{user}%{pwd}')}" if (user or pwd) else ""
    last=""; shares=[]
    for mode in _smb_try_modes():
        rc,out,err = run_cmd(f"smbclient -L //{shlex.quote(host)} -g -m {mode}{creds}", timeout=60)
        if rc==0 and out:
            for line in out.splitlines():
                if line.startswith("Disk|"):
                    name = line.split("|",2)[1].strip()
                    if name and name not in ("print$","IPC$"): shares.append(name)
            if shares: return {"ok":True,"shares":sorted(set(shares)),"mode":mode}
        last = err or out or f"rc={rc}"
    return {"ok":False,"error":last}

def smb_ls(host, share, path="/", user="", pwd=""):
    creds = f" -U {shlex.quote(f'{user}%{pwd}')}" if (user or pwd) else ""
    path = path or "/"
    qpath = path.replace('"','\\"')
    last=""; items=[]
    for mode in _smb_try_modes():
        cmd = f'smbclient //{shlex.quote(host)}/{shlex.quote(share)} -g -m {mode}{creds} -c "ls \\"{qpath}\\""'
        rc,out,err = run_cmd(cmd, timeout=90)
        if rc==0 and out:
            for line in out.splitlines():
                parts = line.split("|")
                if len(parts)>=2:
                    kind = parts[0].strip().upper(); name = parts[1].strip()
                    if name in (".","..",""): continue
                    items.append({"type":"dir" if kind=="D" else "file","name":name})
            return {"ok":True,"items":items,"mode":mode}
        last = err or out or f"rc={rc}"
    return {"ok":False,"error":last}

def nfs_list_exports(host):
    rc,out,err = run_cmd(f"showmount -e {shlex.quote(host)}", timeout=60)
    if rc!=0: return {"ok":False,"error":err or out or f"rc={rc}"}
    exports=[]
    for line in out.splitlines():
        line=line.strip()
        if not line or line.lower().startswith("export list"): continue
        path=line.split()[0]
        if path.startswith("/"): exports.append(path)
    return {"ok":True,"exports":exports}

# ======= mounts =======
def ensure_dir(p): 
    try: pathlib.Path(p).mkdir(parents=True, exist_ok=True)
    except Exception: pass

def mount_cifs(server, share, mountp, user="", pwd="", extra=""):
    ensure_dir(mountp)
    opts = [f"username={user}", f"password={pwd}", "iocharset=utf8", "vers=3.0"]
    if extra: opts.append(extra)
    opt = ",".join([o for o in opts if o])
    return run_cmd(f"mount -t cifs //{shlex.quote(server)}/{shlex.quote(share)} {shlex.quote(mountp)} -o {shlex.quote(opt)}", timeout=180)

def mount_nfs(server, export, mountp, extra=""):
    ensure_dir(mountp)
    opt = extra if extra else "rw"
    return run_cmd(f"mount -t nfs {shlex.quote(server)}:{shlex.quote(export)} {shlex.quote(mountp)} -o {shlex.quote(opt)}", timeout=180)

def umount_path(mountp): return run_cmd(f"umount -l {shlex.quote(mountp)}", timeout=60)

# ======= gotify =======
def gotify_send(title, message, priority=5, url="", token="", verify_tls=True, cfg=None):
    import urllib.request, ssl
    if not url or not token:
        cfg = cfg or _load_config()
        opts = cfg.get("options", {})
        if not opts.get("gotify_enabled"): return {"ok":False,"error":"disabled"}
        url = (opts.get("gotify_url") or "").rstrip("/")
        token = (opts.get("gotify_token") or "").strip()
        if not url or not token: return {"ok":False,"error":"missing url/token"}
    endpoint = f"{url}/message"
    data = json.dumps({"title":title, "message":message, "priority":int(priority)}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type","application/json")
    req.add_header("X-Gotify-Key", token)
    ctx = None
    if endpoint.lower().startswith("https") and not verify_tls:
        ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            _ = resp.read()
        return {"ok":True}
    except Exception as e:
        return {"ok":False,"error":str(e)}

# ======= static: index + assets =======
@app.get("/")
def root_index():
    return send_from_directory(WWW_DIR, "index.html")

@app.get("/<path:fname>")
def static_files(fname):
    # serve only files that exist in WWW_DIR; otherwise 404 to avoid catching API routes
    fpath = os.path.join(WWW_DIR, fname)
    if os.path.isfile(fpath):
        # set proper type for js/css
        if fname.endswith(".js"): mimetypes.add_type("application/javascript",".js")
        if fname.endswith(".css"): mimetypes.add_type("text/css",".css")
        return send_from_directory(WWW_DIR, fname)
    abort(404)

# ======= options =======
@app.get("/api/options")
def api_options_get():
    return jsonify(_load_config().get("options", {}))

@app.post("/api/options")
def api_options_post():
    body = request.get_json(silent=True) or {}
    cfg = _load_config()
    opts = cfg.get("options", {})
    for k in ["ui_port","gotify_enabled","gotify_url","gotify_token","dropbox_enabled","dropbox_remote"]:
        if k in body: opts[k] = body[k]
    cfg["options"] = opts
    _save_config(cfg)
    return jsonify({"ok":True,"config":opts})

@app.post("/api/gotify_test")
def api_gotify_test():
    b = request.get_json(silent=True) or {}
    r = gotify_send(
        title="Remote Linux Backup — Test",
        message="✅ Test message",
        url=b.get("url",""),
        token=b.get("token",""),
        verify_tls=not bool(b.get("insecure", False))
    )
    return jsonify(r)

# ======= servers =======
@app.get("/api/servers")
def api_servers_get():
    return jsonify({"servers": _load_config().get("servers", [])})

@app.post("/api/server_add_update")
def api_server_add_update():
    b = request.get_json(silent=True) or {}
    name = (b.get("name") or "").strip() or (b.get("host") or "")
    host = (b.get("host") or "").strip()
    if not host: return jsonify({"ok":False,"error":"host required"}), 400
    server = {
        "name": name,
        "host": host,
        "username": (b.get("username") or "root").strip(),
        "port": int(b.get("port") or 22),
        "save_password": bool(b.get("save_password"))
    }
    if server["save_password"]: server["password"] = b.get("password") or ""
    cfg = _load_config(); arr = cfg.get("servers", [])
    idx = -1
    for i,s in enumerate(arr):
        if (s.get("name")==name and name) or (s.get("host")==server["host"] and s.get("username")==server["username"] and int(s.get("port",22))==server["port"]):
            idx = i; break
    if idx>=0: arr[idx] = {**arr[idx], **server}
    else: arr.append(server)
    cfg["servers"] = arr; _save_config(cfg)
    return jsonify({"ok":True,"server":server})

@app.post("/api/server_delete")
def api_server_delete():
    b = request.get_json(silent=True) or {}
    key = (b.get("name") or "").strip()
    cfg = _load_config(); arr = cfg.get("servers", [])
    if key: arr = [s for s in arr if s.get("name")!=key]
    else:
        host = (b.get("host") or "").strip()
        arr = [s for s in arr if s.get("host")!=host]
    cfg["servers"]=arr; _save_config(cfg)
    return jsonify({"ok":True})

# ======= mounts =======
@app.get("/api/mounts")
def api_mounts_get():
    cfg = _load_config()
    rows=[]
    for m in cfg.get("mounts", []):
        rows.append({**m, "mounted": os.path.ismount(m.get("mount",""))})
    return jsonify({"mounts":rows})

@app.post("/api/mounts")
def api_mounts_set_all():
    b = request.get_json(silent=True) or {}
    cfg = _load_config(); cfg["mounts"]=b.get("mounts") or []; _save_config(cfg)
    return jsonify({"ok":True})

@app.post("/api/mount_add_update")
def api_mount_add_update():
    b = request.get_json(silent=True) or {}
    name=(b.get("name") or "").strip()
    proto=(b.get("proto") or "cifs").lower()
    server=(b.get("server") or "").strip()
    share=(b.get("share") or "").strip().lstrip("/").rstrip("/")
    mountp=(b.get("mount") or (f"/mnt/{name}" if name else "")).strip()
    user=(b.get("username") or "").strip()
    pwd=b.get("password") or ""
    extra=(b.get("options") or "").strip()
    auto=bool(b.get("auto_mount", False))
    if not (proto and server and share and mountp):
        return jsonify({"ok":False,"error":"name/proto/server/share/mount required"}), 400
    entry={"name":name,"proto":proto,"server":server,"share":share,"mount":mountp,"username":user,"password":pwd,"options":extra,"auto_mount":auto}
    cfg=_load_config(); arr=cfg.get("mounts",[])
    idx=-1
    for i,m in enumerate(arr):
        if (m.get("name") and m.get("name")==name) or m.get("mount")==mountp: idx=i; break
    if idx>=0: arr[idx]={**arr[idx],**entry}
    else: arr.append(entry)
    cfg["mounts"]=arr; _save_config(cfg)
    return jsonify({"ok":True,"entry":entry})

@app.post("/api/mount_delete")
def api_mount_delete():
    b = request.get_json(silent=True) or {}
    name=(b.get("name") or "").strip()
    cfg=_load_config(); arr=cfg.get("mounts",[])
    arr=[m for m in arr if m.get("name")!=name]; cfg["mounts"]=arr; _save_config(cfg)
    return jsonify({"ok":True})

@app.post("/api/mount_now")
def api_mount_now():
    b=request.get_json(silent=True) or {}
    proto=(b.get("proto") or "cifs").lower()
    server=(b.get("server") or "").strip()
    share=(b.get("share") or "").strip().lstrip("/").rstrip("/")
    mountp=(b.get("mount") or "").strip()
    user=(b.get("username") or "").strip()
    pwd=b.get("password") or ""
    extra=(b.get("options") or "").strip()
    if not (server and share and mountp):
        return jsonify({"ok":False,"error":"server/share/mount required"}), 400
    rc,out,err = (mount_cifs(server,share,mountp,user,pwd,extra) if proto in ("cifs","smb") else mount_nfs(server,share,mountp,extra))
    return jsonify({"ok":rc==0,"rc":rc,"out":out,"err":err})

@app.post("/api/unmount_now")
def api_unmount_now():
    b=request.get_json(silent=True) or {}
    mountp=(b.get("mount") or "").strip()
    if not mountp: return jsonify({"ok":False,"error":"mount required"}), 400
    rc,out,err = umount_path(mountp)
    return jsonify({"ok":rc==0,"rc":rc,"out":out,"err":err})

# list shares/exports for dropdown
@app.get("/api/mount_list")
def api_mount_list_get():
    proto=(request.args.get("proto") or "cifs").lower()
    server=(request.args.get("server") or "").strip()
    user=(request.args.get("username") or "").strip()
    pwd=request.args.get("password") or ""
    if not server: return jsonify({"ok":False,"error":"missing server"}), 400
    if proto in ("cifs","smb"):
        r=smb_list_shares(server,user,pwd); 
        if not r.get("ok"): return jsonify({"ok":False,"error":r.get("error","SMB list failed")})
        return jsonify({"ok":True,"items":[{"type":"share","name":s} for s in r["shares"]]})
    r=nfs_list_exports(server)
    if not r.get("ok"): return jsonify({"ok":False,"error":r.get("error","NFS exports failed")})
    return jsonify({"ok":True,"items":[{"type":"export","name":p,"path":p} for p in r["exports"]]})

@app.post("/api/mount_browse")
def api_mount_browse():
    b=request.get_json(silent=True) or {}
    proto=(b.get("proto") or "cifs").lower()
    server=(b.get("server") or "").strip()
    user=(b.get("username") or "").strip()
    pwd=b.get("password") or ""
    share=(b.get("share") or "").strip()
    path=b.get("path") or "/"
    if proto in ("cifs","smb"):
        if not (server and share): return jsonify({"ok":False,"error":"server/share required"}), 400
        return jsonify(smb_ls(server,share,path,user,pwd))
    else:
        # For NFS we only list exports; folder browsing requires mounting first
        return jsonify({"ok":True,"items":[{"type":"export","name":share or "(select export first)"}]})

# ======= backups & filesystem helpers (basic) =======
def list_files(root: str) -> List[Dict[str,Any]]:
    out=[]
    try:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                fp = os.path.join(dirpath, fn)
                try:
                    st=os.stat(fp)
                    out.append({"path":fp, "size":st.st_size, "created":int(st.st_mtime)})
                except Exception:
                    pass
    except Exception:
        pass
    return out

@app.get("/api/backups")
def api_backups():
    roots=["/backup"]
    for m in _load_config().get("mounts", []):
        if os.path.ismount(m.get("mount","")): roots.append(m["mount"])
    items=[]
    for r in roots:
        if os.path.isdir(r): items.extend(list_files(r))
    return jsonify({"items":items})

@app.post("/api/backups/delete")
def api_backups_delete():
    b=request.get_json(silent=True) or {}
    path=(b.get("path") or "").strip()
    if not path or not os.path.isfile(path): return jsonify({"ok":False,"error":"invalid path"}), 400
    try: os.remove(path); return jsonify({"ok":True})
    except Exception as e: return jsonify({"ok":False,"error":str(e)}), 400

@app.get("/api/ls")
def api_ls():
    p=request.args.get("path") or "/"
    if not os.path.isdir(p): return jsonify({"ok":False,"error":"not a directory"}), 400
    items=[]
    for name in sorted(os.listdir(p)):
        fp=os.path.join(p,name)
        try:
            st=os.stat(fp)
            items.append({"name":name,"path":fp,"is_dir":os.path.isdir(fp),"size":st.st_size,"created":int(st.st_mtime)})
        except Exception: pass
    return jsonify({"ok":True,"items":items})

@app.get("/api/download")
def api_download():
    p=request.args.get("path") or ""
    if not p or not os.path.isfile(p): abort(404)
    d,fn = os.path.dirname(p), os.path.basename(p)
    return send_from_directory(d, fn, as_attachment=True)

# ======= estimation / jobs =======
@app.post("/api/estimate_backup")
def api_estimate_backup():
    b=request.get_json(silent=True) or {}
    method=(b.get("method") or "dd").lower()
    bw=int(b.get("bwlimit_kbps") or 0)
    # just echo back basic estimate shell
    return jsonify({"ok":True,"method":method,"bw_kbps":bw})

def _dir_size_delta(path: str, before: Dict[str,int]) -> int:
    total=0
    for dirpath,_d,files in os.walk(path):
        for f in files:
            fp=os.path.join(dirpath,f)
            try:
                total+=os.path.getsize(fp)
            except Exception: pass
    return max(0, total - before.get(path,0))

def _snapshot_sizes(paths: List[str]) -> Dict[str,int]:
    snap={}
    for p in paths:
        tot=0
        if os.path.isdir(p):
            for dirpath,_d,files in os.walk(p):
                for f in files:
                    fp=os.path.join(dirpath,f)
                    try: tot+=os.path.getsize(fp)
                    except Exception: pass
        snap[p]=tot
    return snap

def _notify_job(kind: str, ok: bool, start_ts: float, body: Dict[str,Any], out: str):
    dur = fmt_duration(time.time() - start_ts)
    store = body.get("store_to") or body.get("image_path") or body.get("local_src") or ""
    size_paths = []
    if kind=="backup":
        if store: 
            # consider target root or its parent
            p = store if os.path.isdir(store) else os.path.dirname(store)
            if p: size_paths.append(p)
    size_str = ""
    if size_paths:
        try:
            snap = _snapshot_sizes(size_paths)
            size = sum(snap.values())
            size_str = human_bytes(size)
        except Exception:
            size_str = "n/a"
    status = "✅ SUCCESS" if ok else "❌ FAILED"
    msg = f"{status}\nKind: {kind}\nHost: {body.get('host')}\nTarget: {store}\nDuration: {dur}\nSize (approx): {size_str}\n\nOutput tail:\n{(out or '').splitlines()[-10:]}"
    gotify_send(f"Remote Linux Backup — {kind.title()}", msg)

@app.post("/api/run_backup")
def api_run_backup():
    b=request.get_json(silent=True) or {}
    start=time.time()
    if not os.path.exists(RUNNER):
        return jsonify({"ok":False,"error":"runner not found"}), 500
    rc,out,err = run_cmd(RUNNER_CMD_BACKUP, stdin=json.dumps(b), timeout=360000)
    ok = (rc==0)
    _notify_job("backup", ok, start, b, out or err)
    return jsonify({"ok":ok,"rc":rc,"out":out,"err":err})

@app.post("/api/run_restore")
def api_run_restore():
    b=request.get_json(silent=True) or {}
    start=time.time()
    if not os.path.exists(RUNNER):
        return jsonify({"ok":False,"error":"runner not found"}), 500
    rc,out,err = run_cmd(RUNNER_CMD_RESTORE, stdin=json.dumps(b), timeout=360000)
    ok = (rc==0)
    _notify_job("restore", ok, start, b, out or err)
    return jsonify({"ok":ok,"rc":rc,"out":out,"err":err})

# ----- main (gunicorn will import app) -----
if __name__ == "__main__":
    port = int(_load_config().get("options",{}).get("ui_port", 8066) or 8066)
    app.run(host="0.0.0.0", port=port, debug=False)
