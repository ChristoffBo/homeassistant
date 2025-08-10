#!/usr/bin/env python3
import os, re, json, shlex, subprocess, threading, time, argparse
from flask import Flask, request, jsonify, send_file, send_from_directory

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
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True, executable="/bin/bash")
    out, err = p.communicate()
    return p.returncode, out, err

def sum_dir_bytes(path: str) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root,f))
            except Exception:
                pass
    return total

# ---- mount helpers ----
def ensure_mount(name:str)->bool:
    """Mount a saved mount if it's not mounted."""
    data = read_json(PATHS["mounts"], [])
    m = next((x for x in data if x.get("name")==name), None)
    if not m:
        return False
    mp = mountpoint(name)
    if os.path.ismount(mp):
        return True
    os.makedirs(mp, exist_ok=True)
    if m.get("type") == "smb":
        unc  = f"//{m.get('host','')}/{m.get('share','')}"
        opts = m.get("options","")
        if m.get("username"):
            auth = f"username={m.get('username','')},password={m.get('password','')}"
        else:
            auth = "guest"
        if opts:
            opts = auth + "," + opts
        else:
            opts = auth
        cmd = f"mount -t cifs {shlex.quote(unc)} {shlex.quote(mp)} -o {shlex.quote(opts)}"
    else:
        export = m.get("share","/")
        if not export.startswith("/"):
            export = "/" + export
        opts   = m.get("options","")
        cmd = f"mount -t nfs {shlex.quote(m.get('host','') + ':' + export)} {shlex.quote(mp)}"
        if opts:
            cmd += f" -o {shlex.quote(opts)}"
    rc, out, err = run_cmd(cmd + " 2>&1 || true")
    ok = os.path.ismount(mp)
    if not ok:
        m["last_error"] = out or err
        write_json(PATHS["mounts"], data)
        return False
    m["last_error"] = ""
    write_json(PATHS["mounts"], data)
    return True

# ----------------- Job worker -----------------
class JobWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.queue=[]; self.cur=None; self.lock=threading.Lock(); self.cv=threading.Condition(self.lock)
    def submit(self, job): 
        with self.lock: self.queue.append(job); self.cv.notify_all()
        return {"ok": True, "queued": True}
    def cancel(self):
        run_cmd("pkill -f 'rsync|ssh .* dd|smbclient|pv' || true")
        return {"ok": True}
    def run(self):
        while True:
            with self.lock:
                while not self.queue: self.cv.wait()
                job=self.queue.pop(0); self.cur=job
                job.update(status='running', progress=0, log=[], started=int(time.time()))
            try:
                p = subprocess.Popen(job["cmd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True, executable="/bin/bash", bufsize=1)
                for line in p.stdout:
                    line=line.rstrip(); job["log"].append(line)
                    m=re.search(r"(\d+)%",line)
                    if m:
                        try: job["progress"]=min(100,max(0,int(m.group(1))))
                        except: pass
                rc=p.wait(); job["status"]='success' if rc==0 else 'error'
                if rc==0: job["progress"]=100
            except Exception as e:
                job["status"]='error'; job.setdefault("log",[]).append(str(e))
            finally:
                job["ended"]=int(time.time())
                hist = read_json(PATHS["history"], [])
                hist.append({k:job.get(k) for k in ("id","kind","label","status","started","ended","dest","mode")})
                write_json(PATHS["history"], hist)
                with self.lock: self.cur=None

worker=JobWorker(); worker.start()

@app.get("/api/jobs")
def api_jobs():
    with worker.lock: cur=worker.cur
    return jsonify([cur] if cur else [])

@app.post("/api/jobs/cancel")
def api_jobs_cancel(): return jsonify(worker.cancel())

# ----------------- SSH browse/test -----------------
@app.post("/api/ssh/test")
def api_ssh_test():
    b=request.json or {}
    host=b.get("host",""); port=int(b.get("port") or 22)
    user=b.get("username",""); pw=b.get("password","" )
    keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6"
    cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 {keep} -p {port} {shlex.quote(user)}@{shlex.quote(host)} echo OK"
    rc,out,err=run_cmd(cmd); return jsonify({"ok": rc==0 and 'OK' in out, "out": out, "err": err})

@app.post("/api/ssh/listdir")
def api_ssh_listdir():
    b=request.json or {}
    host=b.get("host"); port=int(b.get("port") or 22); user=b.get("username"); pw=b.get("password"); path=b.get("path") or "/"
    if paramiko:
        try:
            t=paramiko.Transport((host,port)); t.connect(username=user,password=pw)
            s=paramiko.SFTPClient.from_transport(t)
            items=[{"name":e.filename,"dir":bool(e.st_mode & 0o040000),"size":e.st_size} for e in s.listdir_attr(path)]
            s.close(); t.close(); return jsonify({"ok":True,"items":items})
        except Exception:
            pass
    remote=f"ls -1p {shlex.quote(path)} || true"
    cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -p {port} {shlex.quote(user)}@{shlex.quote(host)} {remote}"
    rc,out,err=run_cmd(cmd+" 2>&1 || true"); items=[]
    for line in out.splitlines():
        name=line.strip()
        if not name: continue
        items.append({"name":name.rstrip('/'),"dir":name.endswith('/')})
    return jsonify({"ok":True,"items":items})

# ----------------- Local & Mount browse / mkdir -----------------
@app.get("/api/local/listdir")
def api_local_listdir():
    path=request.args.get("path") or "/config"
    try:
        items=[{"name":e.name,"dir":e.is_dir(),"size":(0 if e.is_dir() else e.stat().st_size)} for e in os.scandir(path)]
        items=sorted(items,key=lambda x:(not x["dir"],x["name"].lower()))
        return jsonify({"ok":True,"items":items})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})

@app.post("/api/local/mkdir")
def api_local_mkdir():
    b=request.json or {}
    base=b.get("path","/config"); name=b.get("name","new_folder")
    full=os.path.normpath(os.path.join(base,name))
    if not full.startswith("/"): return jsonify({"ok":False,"error":"bad path"}),400
    os.makedirs(full,exist_ok=True); return jsonify({"ok":True,"path":full})

@app.get("/api/mounts")
def api_mounts():
    data=read_json(PATHS["mounts"],[])
    for m in data:
        mp=mountpoint(m.get("name","")); m["mountpoint"]=mp; m["mounted"]=os.path.ismount(mp); m.setdefault("last_error","")
    return jsonify({"mounts":data})

@app.post("/api/mounts/save")
def api_mounts_save():
    b=request.json or {}; name=b.get("name","").strip()
    if not name: return jsonify({"ok":False,"error":"name required"}),400
    data=read_json(PATHS["mounts"],[])
    data=[x for x in data if x.get("name")!=name]
    data.append({"name":name,"type":b.get("type","smb"),"host":b.get("host","").strip(),"share":b.get("share","").strip(),
                 "username":b.get("username",""),"password":b.get("password",""),"options":b.get("options",""),
                 "auto_retry":bool(int(b.get("auto_retry",1))),"last_error":""})
    write_json(PATHS["mounts"],data)
    os.makedirs(mountpoint(name),exist_ok=True)
    return jsonify({"ok":True})

@app.post("/api/mounts/mount")
def api_mounts_mount():
    name=(request.json or {}).get("name","")
    ok=ensure_mount(name)
    return jsonify({"ok": ok})

@app.post("/api/mounts/unmount")
def api_mounts_unmount():
    name=(request.json or {}).get("name","")
    run_cmd(f"umount {shlex.quote(mountpoint(name))} 2>&1 || true")
    return jsonify({"ok":True})

@app.post("/api/mounts/test")
def api_mounts_test():
    b=request.json or {}; t=b.get("type"); host=b.get("host"); user=b.get("username"," "); pw=b.get("password"," ")
    if t=="smb":
        auth=f"-U {shlex.quote((user or '')+'%'+(pw or ''))}" if user else "-N"
        rc,out,err=run_cmd(f"smbclient -L //{shlex.quote(host)} {auth} -g 2>&1 || true")
        shares=[x.split('|')[1] for x in out.splitlines() if x.startswith('Disk|')]
        return jsonify({"ok": len(shares)>0, "shares": shares, "raw": out})
    else:
        rc,out,err=run_cmd(f"showmount -e {shlex.quote(host)} 2>&1 || true")
        exports=[line.split()[0] for line in out.splitlines() if line.strip().startswith('/')]
        return jsonify({"ok": len(exports)>0, "exports": exports, "raw": out})

@app.post("/api/mounts/listdir")
def api_mounts_listdir():
    b=request.json or {}; name=b.get("name",""); rel=b.get("path","/")
    if not ensure_mount(name): return jsonify({"ok":False,"error":"mount failed"}),400
    mp=mountpoint(name)
    path=os.path.normpath(os.path.join(mp, rel.lstrip("/")))
    if not path.startswith(mp): return jsonify({"ok":False,"error":"invalid path"}),400
    items=[{"name":e.name,"dir":e.is_dir(),"size":(0 if e.is_dir() else e.stat().st_size)} for e in os.scandir(path)]
    items=sorted(items,key=lambda x:(not x["dir"],x["name"].lower()))
    return jsonify({"ok":True,"base":mp,"path":path,"items":items})

@app.post("/api/mounts/mkdir")
def api_mounts_mkdir():
    b=request.json or {}; name=b.get("name",""); rel=b.get("path","/"); folder=b.get("folder","new_folder")
    if not ensure_mount(name): return jsonify({"ok":False,"error":"mount failed"}),400
    mp=mountpoint(name); base=os.path.normpath(os.path.join(mp, rel.lstrip("/")))
    if not base.startswith(mp): return jsonify({"ok":False,"error":"invalid path"}),400
    full=os.path.join(base,folder); os.makedirs(full,exist_ok=True)
    return jsonify({"ok":True,"path":full})

# ----------------- Estimate -----------------
@app.post("/api/estimate")
def api_estimate():
    b=request.json or {}; mode=b.get("mode","local"); path=b.get("path","/")
    if mode=="local":
        size=sum_dir_bytes(path) if os.path.exists(path) else 0; return jsonify({"ok":True,"bytes":size})
    elif mode=="mount":
        name=b.get("name","")
        if not ensure_mount(name): return jsonify({"ok":False,"error":"mount failed"}),400
        mp=mountpoint(name); real=os.path.normpath(os.path.join(mp, path.lstrip("/")))
        size=sum_dir_bytes(real) if os.path.exists(real) else 0; return jsonify({"ok":True,"bytes":size})
    elif mode=="ssh":
        host=b.get("host"); user=b.get("username"); pw=b.get("password")
        keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"
        remote=f"du -sb {shlex.quote(path)} 2>/dev/null || du -sk {shlex.quote(path)}"
        cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep} {shlex.quote(user)}@{shlex.quote(host)} {remote}"
        rc,out,err=run_cmd(cmd+" 2>&1 || true")
        try: n=int(out.split()[0])
        except: n=0
        return jsonify({"ok":True,"bytes":n})
    return jsonify({"ok":False,"error":"unknown mode"}),400

# ----------------- Backups listing / download -----------------
def manifest_path(dirpath:str)->str: return os.path.join(dirpath,"MANIFEST.json")
def write_manifest(dirpath:str,data:dict):
    with open(manifest_path(dirpath),"w") as f: json.dump(data,f,indent=2)
def read_manifest(dirpath:str)->dict:
    try: 
        with open(manifest_path(dirpath),"r") as f: return json.load(f)
    except Exception: return {}

@app.get("/api/backups")
def api_backups():
    items=[]
    for name in os.listdir(BACKUP_DIR):
        p=os.path.join(BACKUP_DIR,name)
        if not os.path.isdir(p): continue
        man=read_manifest(p); size=sum_dir_bytes(p)
        items.append({"id":name,"label":man.get("label",name),"when":man.get("started",0),"size":size,"mode":man.get("mode",""),
                      "source":man.get("source",{}),"dest":man.get("dest",{}),"has_image":os.path.exists(os.path.join(p,"disk.img.gz"))})
    items.sort(key=lambda x:x["when"],reverse=True)
    return jsonify({"items":items})

@app.get("/api/backups/download-archive")
def api_backups_download_archive():
    bid=request.args.get("id",""); src=os.path.normpath(os.path.join(BACKUP_DIR,bid))
    if not src.startswith(BACKUP_DIR) or not os.path.isdir(src): return ("not found",404)
    tmp=os.path.join(UPLOAD_DIR,f"{bid}.tar.gz")
    import tarfile
    with tarfile.open(tmp,"w:gz") as tar: tar.add(src, arcname=os.path.basename(src))
    return send_file(tmp, as_attachment=True)

# ----------------- Rsync / imaging helpers -----------------
def rsync_cmd(src, dst, bwkb=0, rsh=None, excludes=None, dry=False):
    bw=f"--bwlimit={bwkb}" if bwkb and int(bwkb)>0 else ""
    exc=" ".join([f"--exclude={shlex.quote(x)}" for x in (excludes or [])])
    dr="--dry-run" if dry else ""
    base=f"rsync -aAXH --numeric-ids --info=progress2 {bw} {exc} {dr}"
    if rsh: return f"RSYNC_RSH='{rsh}' {base} {src.rstrip('/')}/ {dst.rstrip('/')}/"
    return f"{base} {src.rstrip('/')}/ {dst.rstrip('/')}/"

def dd_image_cmd(host,user,pw,dev,out_file,limit_kbps=0):
    keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6"
    ssh=(f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep} {shlex.quote(user)}@{shlex.quote(host)}")
    pipe = f"| pv -n -L {int(limit_kbps)*1024}" if limit_kbps and int(limit_kbps)>0 else "| pv -n"
    return f"{ssh} 'dd if={shlex.quote(dev)} bs=4M status=none iflag=fullblock' {pipe} | gzip > {shlex.quote(out_file)}"

# ----------------- Backup start -----------------
@app.post("/api/backup/start")
def api_backup_start():
    b=request.json or {}
    mode=b.get("mode","rsync"); label=b.get("label","backup")
    dest_type=b.get("dest_type","local"); dest_mount=b.get("dest_mount_name",""); dest_path=b.get("dest_path","")
    bwkb=int(b.get("bwlimit_kbps") or 0); dry=bool(b.get("dry_run",False)); profile=(b.get("profile") or "").lower()

    # destination base
    if dest_type=="local":
        base=dest_path or BACKUP_DIR
    else:
        if not ensure_mount(dest_mount): return jsonify({"ok":False,"error":"destination mount failed"}),400
        base=os.path.join(mountpoint(dest_mount), dest_path.lstrip("/")) if dest_path else mountpoint(dest_mount)
    os.makedirs(base,exist_ok=True)
    out_dir=os.path.join(base, f"{label}-{int(time.time())}"); os.makedirs(out_dir,exist_ok=True)

    excludes=[]
    if profile in ("opnsense","pfsense"): excludes=["/dev","/proc","/sys","/tmp","/run","/mnt","/media"]
    elif profile in ("proxmox","pve"):     excludes=["/proc","/sys","/run","/dev","/tmp","/var/lib/vz/tmp"]
    elif profile in ("unraid","omv"):      excludes=["/proc","/sys","/run","/dev","/tmp"]

    keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"

    manifest={"label":label,"mode":mode,"profile":profile,"started":int(time.time()),"out_dir":out_dir,
              "dest":{"type":dest_type,"mount":dest_mount,"path":dest_path},"source":{}}

    if mode=="rsync":
        host=b.get("host"); user=b.get("username"); pw=b.get("password"); src=b.get("source_path","/")
        rsh=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
        cmd=rsync_cmd(f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)}", out_dir, bwkb=bwkb, rsh=rsh, excludes=excludes, dry=dry)
        manifest["source"]={"type":"ssh","host":host,"user":user,"path":src}; write_manifest(out_dir,manifest)
        return jsonify(worker.submit({"id":int(time.time()),"cmd":cmd,"kind":"backup","label":label,"mode":mode,"dest":out_dir}))

    elif mode=="copy_local":
        src=b.get("source_path","/config"); cmd=rsync_cmd(shlex.quote(src), out_dir, bwkb=bwkb, excludes=excludes, dry=dry)
        manifest["source"]={"type":"local","path":src}; write_manifest(out_dir,manifest)
        return jsonify(worker.submit({"id":int(time.time()),"cmd":cmd,"kind":"backup","label":label,"mode":mode,"dest":out_dir}))

    elif mode=="copy_mount":
        name=b.get("mount_name"); src=b.get("source_path","/")
        if not ensure_mount(name): return jsonify({"ok":False,"error":"source mount failed"}),400
        mp=mountpoint(name); cmd=rsync_cmd(shlex.quote(os.path.join(mp, src.lstrip('/'))), out_dir, bwkb=bwkb, excludes=excludes, dry=dry)
        manifest["source"]={"type":"mount","name":name,"path":src}; write_manifest(out_dir,manifest)
        return jsonify(worker.submit({"id":int(time.time()),"cmd":cmd,"kind":"backup","label":label,"mode":mode,"dest":out_dir}))

    elif mode=="image":
        host=b.get("host"); user=b.get("username"); pw=b.get("password"); dev=b.get("device","/dev/sda")
        out_file=os.path.join(out_dir,"disk.img.gz"); cmd=dd_image_cmd(host,user,pw,dev,out_file,limit_kbps=bwkb)
        manifest["source"]={"type":"ssh","host":host,"user":user,"device":dev,"image_gz":"disk.img.gz"}; write_manifest(out_dir,manifest)
        return jsonify(worker.submit({"id":int(time.time()),"cmd":cmd,"kind":"image","label":label,"mode":mode,"dest":out_dir}))

    return jsonify({"ok":False,"error":"unknown mode"}),400

# ----------------- Restore -----------------
@app.post("/api/restore/start")
def api_restore_start():
    b=request.json or {}; bid=b.get("id",""); src_dir=os.path.normpath(os.path.join(BACKUP_DIR,bid))
    if not src_dir.startswith(BACKUP_DIR) or not os.path.isdir(src_dir): return jsonify({"ok":False,"error":"bad backup id"}),400
    man=read_manifest(src_dir); 
    if not man: return jsonify({"ok":False,"error":"manifest missing"}),400
    original=bool(b.get("original",False)); bwkb=int(b.get("bwlimit_kbps") or 0)

    if original:
        srcq=shlex.quote(src_dir); src_type=man.get("source",{}).get("type")
        if src_type=="local":
            dst=man["source"]["path"]; cmd=rsync_cmd(srcq, shlex.quote(dst), bwkb=bwkb)
        elif src_type=="ssh":
            keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"
            host=man["source"]["host"]; user=man["source"]["user"]; pw=b.get("password","" )
            if not pw: return jsonify({"ok":False,"error":"password required for original (ssh)"}),400
            rsh=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
            dst=f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(man['source'].get('path','/'))}"
            cmd=rsync_cmd(srcq, dst, bwkb=bwkb, rsh=rsh)
        elif src_type=="mount":
            name=man["source"]["name"]; 
            if not ensure_mount(name): return jsonify({"ok":False,"error":"mount failed"}),400
            mp=mountpoint(name); dst=os.path.join(mp, man["source"]["path"].lstrip("/")); cmd=rsync_cmd(srcq, shlex.quote(dst), bwkb=bwkb)
        else: return jsonify({"ok":False,"error":"unsupported source type"}),400
        return jsonify(worker.submit({"id":int(time.time()),"cmd":cmd,"kind":"restore","label":f"restore->{src_type}","mode":"restore","dest":"original"}))
    else:
        to_mode=b.get("to_mode","local"); to_path=b.get("to_path","/"); srcq=shlex.quote(src_dir)
        if to_mode=="local":
            cmd=rsync_cmd(srcq, shlex.quote(to_path), bwkb=bwkb)
        elif to_mode=="ssh":
            keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"
            host=b.get("host"); user=b.get("username"); pw=b.get("password")
            rsh=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
            dst=f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(to_path)}"
            cmd=rsync_cmd(srcq, dst, bwkb=bwkb, rsh=rsh)
        elif to_mode=="mount":
            name=b.get("mount_name"); 
            if not ensure_mount(name): return jsonify({"ok":False,"error":"mount failed"}),400
            mp=mountpoint(name); dst=os.path.join(mp, to_path.lstrip("/")); cmd=rsync_cmd(srcq, shlex.quote(dst), bwkb=bwkb)
        else: return jsonify({"ok":False,"error":"unknown to_mode"}),400
        return jsonify(worker.submit({"id":int(time.time()),"cmd":cmd,"kind":"restore","label":f"restore->{to_mode}","mode":"restore","dest":to_path}))

@app.get("/api/health")
def api_health():
    import shutil as _sh
    mounts=read_json(PATHS["mounts"],[])
    for m in mounts:
        mp=mountpoint(m.get('name','')); m['mountpoint']=mp; m['mounted']=os.path.ismount(mp); m.setdefault('last_error','')
    total, used, free = _sh.disk_usage(BACKUP_DIR)
    return jsonify({"backup_dir": BACKUP_DIR, "free_mb": int(free/1024/1024), "total_mb": int(total/1024/1024), "mounts": mounts})

@app.get("/")
def ui_root(): return send_from_directory("www","index.html")

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--port",type=int,default=8066); args=ap.parse_args()
    app.run(host="0.0.0.0", port=args.port)
