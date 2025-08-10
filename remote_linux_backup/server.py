#!/usr/bin/env python3
import os, re, json, shlex, subprocess, threading, time, argparse, datetime, tarfile
from flask import Flask, request, jsonify, send_file, send_from_directory

try:
    import paramiko
except Exception:
    paramiko=None

app = Flask(__name__, static_folder="www", static_url_path="")

DATA_DIR   = "/config/remote_linux_backup"
STATE_DIR  = os.path.join(DATA_DIR, "state")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
MOUNTS_BASE= "/mnt/rlb"
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
        with open(path, "w") as f: json.dump(default, f)
for k,p in PATHS.items():
    _init(p, [] if k in ("connections","mounts","schedules","history") else {})

def read_json(p, d): 
    try:
        with open(p,"r") as f: return json.load(f)
    except Exception:
        return d
def write_json(p, d):
    tmp=p+".tmp"
    with open(tmp,"w") as f: json.dump(d,f,indent=2)
    os.replace(tmp,p)

def run_cmd(cmd:str):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True, executable="/bin/bash")
    out, err = p.communicate()
    return p.returncode, out, err

def mountpoint(name:str)->str: return os.path.join(MOUNTS_BASE, name)
def ensure_mount(name:str)->bool:
    data=read_json(PATHS["mounts"],[])
    m=next((x for x in data if x.get("name")==name), None)
    if not m: return False
    mp=mountpoint(name)
    if os.path.ismount(mp): return True
    os.makedirs(mp, exist_ok=True)
    if m["type"]=="smb":
        unc=f"//{m['host']}/{m['share']}"
        auth = f"username={m['username']},password={m.get('password','')}" if m.get("username") else "guest"
        opts = m.get("options","")
        opts = auth + ("," + opts if opts else "")
        cmd = f"mount -t cifs {shlex.quote(unc)} {shlex.quote(mp)} -o {shlex.quote(opts)}"
    else:
        export = m["share"] if str(m["share"]).startswith("/") else "/"+m["share"]
        opts = m.get("options","")
        cmd = f"mount -t nfs {shlex.quote(m['host'] + ':' + export)} {shlex.quote(mp)}" + (f" -o {shlex.quote(opts)}" if opts else "")
    rc,out,err=run_cmd(cmd + " 2>&1 || true")
    ok=os.path.ismount(mp)
    m["last_error"] = "" if ok else (out or err)
    write_json(PATHS["mounts"], data)
    return ok


def smb_ls(host:str, share:str, user:str, pw:str, rel:str="/"):
    """Return items under share/rel using smbclient -g. Items: [{name,dir,size}]"""
    rel = rel or "/"
    auth = f"-U {shlex.quote(user+'%'+pw)}" if user else "-N"
    # Build the smbclient command: cd into rel then ls with machine-readable (-g)
    cmd = f"smbclient -g //{shlex.quote(host)}/{shlex.quote(share)} {auth} -c " + shlex.quote(f"cd {rel}; ls")
    rc,out,err = run_cmd(cmd + " 2>&1 || true")
    items=[]
    for line in (out or "").splitlines():
        # Expect forms like: D|folder or N|file|1234|...
        if not line or line.startswith(".");
            continue
        parts = line.split("|")
        if not parts:
            continue
        tag = parts[0]
        if tag in ("D","d"):
            name = parts[1] if len(parts)>1 else ""
            if name in (".",".."): continue
            items.append({"name":name,"dir":True,"size":0})
        elif tag in ("N","n","A"):  # file
            name = parts[1] if len(parts)>1 else ""
            if name in (".",".."): continue
            try: size = int(parts[2]) if len(parts)>2 else 0
            except: size = 0
            items.append({"name":name,"dir":False,"size":size})
    items = sorted(items, key=lambda x:(not x["dir"], x["name"].lower()))
    return items
def sum_dir_bytes(path:str)->int:
    total=0
    for root, dirs, files in os.walk(path):
        for f in files:
            p=os.path.join(root,f)
            try: total += os.path.getsize(p)
            except: pass
    return total

# ---- Notifier (Gotify) ----
def get_notify():
    n=read_json(PATHS["notify"],{})
    n.setdefault("enabled", False)
    n.setdefault("url","")
    n.setdefault("token","")
    n.setdefault("include", {"date":True,"time":True,"name":True,"size":True,"duration":True})
    n.setdefault("on_success", True); n.setdefault("on_failure", True)
    return n
def send_gotify(title:str, message:str):
    n=get_notify()
    if not n.get("enabled"): return
    url=n.get("url","").rstrip("/") + "/message?token=" + n.get("token","")
    msg=message.replace('"',"'")
    cmd=f'curl -s -X POST "{url}" -F "title={shlex.quote(title)}" -F "message={shlex.quote(msg)}" >/dev/null 2>&1 || true'
    run_cmd(cmd)

# ---- Job worker ----
class JobWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True); self.queue=[]; self.cur=None; self.lock=threading.Lock(); self.cv=threading.Condition(self.lock)
    def submit(self, job):
        with self.lock: self.queue.append(job); self.cv.notify_all()
        return {"ok":True,"queued":True}
    def cancel(self):
        run_cmd("pkill -f 'rsync|ssh .* dd|smbclient|pv' || true"); return {"ok":True}
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
                    m=re.search(r"(\d+)%", line); 
                    if m: 
                        try: job["progress"]=max(0,min(100,int(m.group(1))))
                        except: pass
                rc=p.wait(); job["status"]='success' if rc==0 else 'error'
                if rc==0: job["progress"]=100
            except Exception as e:
                job["status"]='error'; job.setdefault("log",[]).append(str(e))
            finally:
                job["ended"]=int(time.time())
                # append to history
                hist = read_json(PATHS["history"], [])
                hist.append({k:job.get(k) for k in ("id","kind","label","status","started","ended","dest","mode")})
                write_json(PATHS["history"], hist)
                # notify
                try:
                    n = get_notify()
                    if (job["status"]=="success" and n.get("on_success")) or (job["status"]!="success" and n.get("on_failure")):
                        dur = job.get("ended",0)-job.get("started",0)
                        size = 0
                        if job.get("kind") in ("backup","image"):
                            dest=job.get("dest_dir") or job.get("dest") or ""
                            if dest and os.path.exists(dest): size=sum_dir_bytes(dest)
                        inc=n.get("include", {})
                        parts=[]
                        if inc.get("name"): parts.append(f"name={job.get('label','')}")
                        if inc.get("size"): parts.append(f"size={size}B")
                        if inc.get("duration"): parts.append(f"duration={dur}s")
                        when=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if inc.get("date") or inc.get("time"): parts.append(when)
                        send_gotify(f"RLB {job['status']}: {job.get('label','')}", ", ".join(parts))
                except Exception as e:
                    pass
                with self.lock: self.cur=None

worker=JobWorker(); worker.start()

# ---- Schedule worker ----
def _parse_hhmm(s): 
    try: h,m=map(int,s.split(":")); return h,m
    except: return 3,0
def _next_from_rule(rule, now=None):
    if now is None: now=datetime.datetime.now()
    typ=rule.get("type","daily"); hhmm=rule.get("time","03:00"); h,m=_parse_hhmm(hhmm)
    if typ=="daily":
        dt=now.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt<=now: dt+=datetime.timedelta(days=1)
        return int(dt.timestamp())
    if typ=="weekly":
        days=rule.get("dow",[0]) # 0=Mon
        dt=now
        for i in range(8):
            cand=now+datetime.timedelta(days=i)
            if cand.weekday() in days:
                t=cand.replace(hour=h,minute=m,second=0,microsecond=0)
                if t>now: return int(t.timestamp())
        return int((now+datetime.timedelta(days=7)).timestamp())
    if typ=="monthly":
        dom=sorted(set(rule.get("dom",[1])))
        for i in range(62):
            cand=now+datetime.timedelta(days=i)
            if cand.day in dom:
                t=cand.replace(hour=h,minute=m,second=0,microsecond=0)
                if t>now: return int(t.timestamp())
        return int((now+datetime.timedelta(days=31)).timestamp())
    return int((now+datetime.timedelta(days=1)).timestamp())

class ScheduleWorker(threading.Thread):
    def __init__(self): super().__init__(daemon=True)
    def run(self):
        while True:
            try:
                sched=read_json(PATHS["schedules"],[])
                now=int(time.time())
                changed=False
                for s in sched:
                    if not s.get("enabled",True): continue
                    nxt=s.get("next_run") or 0
                    if nxt<=now:
                        # submit job
                        tpl=s.get("template",{})
                        r=api_backup_start_impl(tpl, scheduled=True)
                        # compute next
                        s["next_run"]=_next_from_rule(s.get("rule",{}))
                        changed=True
                if changed: write_json(PATHS["schedules"], sched)
            except Exception:
                pass
            time.sleep(30)
sched_worker=ScheduleWorker(); sched_worker.start()

# ------- API: jobs
@app.get("/api/jobs")
def api_jobs():
    with worker.lock: cur=worker.cur
    return jsonify([cur] if cur else [])

@app.post("/api/jobs/cancel")
def api_jobs_cancel(): return jsonify(worker.cancel())

# ------- SSH browse/test
@app.post("/api/ssh/test")
def api_ssh_test():
    b=request.json or {}; host=b.get("host",""); port=int(b.get("port") or 22); user=b.get("username",""); pw=b.get("password","")
    keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6"
    cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 {keep} -p {port} {shlex.quote(user)}@{shlex.quote(host)} echo OK"
    rc,out,err=run_cmd(cmd); return jsonify({"ok": rc==0 and 'OK' in out, "out": out, "err": err})


@app.post("/api/ssh/listdir")
def api_ssh_listdir():
    b=request.json or {}
    host=b.get("host"); port=int(b.get("port") or 22)
    user=b.get("username"); pw=b.get("password")
    path=b.get("path") or "/"
    # Try Paramiko first
    if paramiko:
        try:
            t=paramiko.Transport((host,port))
            t.connect(username=user,password=pw)
            s=paramiko.SFTPClient.from_transport(t)
            use_path = path
            try:
                items_attr = s.listdir_attr(use_path)
            except Exception:
                # fallback to user's home if root not browsable
                try:
                    s.chdir(".")  # ensure session
                    home = s.normalize(".")
                    use_path = home
                    items_attr = s.listdir_attr(use_path)
                except Exception:
                    items_attr = []
            items=[{"name":e.filename,"dir":bool(e.st_mode & 0o040000),"size":getattr(e,'st_size',0),
                    "path": (use_path.rstrip('/') + '/' + e.filename).replace('//','/')} for e in items_attr if e.filename not in ('.','..')]
            s.close(); t.close()
            return jsonify({"ok":True,"items":items,"base":use_path})
        except Exception:
            pass
    # Fallback via ssh/ls; try requested path then $HOME
    quoted_path = shlex.quote(path)
    remote = f"sh -lc 'ls -1p {quoted_path} 2>/dev/null || ls -1p ~'"
    cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p {port} {shlex.quote(user)}@{shlex.quote(host)} {remote}"
    rc,out,err=run_cmd(cmd + " 2>&1 || true")
    items=[]; base="/"
    for line in (out or '').splitlines():
        name=line.strip()
        if not name: continue
        is_dir=name.endswith('/')
        name=name.rstrip('/')
        items.append({"name":name,"dir":is_dir,"size":0,"path": ("/" if base=="/" else base.rstrip('/')+'/') + name})
    return jsonify({"ok":True,"items":items,"base":base})

        except Exception: pass
    remote=f"ls -1p {shlex.quote(path)} || true"
    cmd=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no -p {port} {shlex.quote(user)}@{shlex.quote(host)} {remote}"
    rc,out,err=run_cmd(cmd+" 2>&1 || true"); items=[]
    for line in out.splitlines():
        name=line.strip(); 
        if not name: continue
        items.append({"name":name.rstrip('/'),"dir":name.endswith('/')})
    return jsonify({"ok":True,"items":items})

# ------- Local / mount browse + mkdir
@app.get("/api/local/listdir")
def api_local_listdir():
    path=request.args.get("path") or "/config"
    try:
        items=[{"name":e.name,"dir":e.is_dir(),"size":(0 if e.is_dir() else e.stat().st_size)} for e in os.scandir(path)]
        items=sorted(items,key=lambda x:(not x["dir"], x["name"].lower()))
        return jsonify({"ok":True,"items":items})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})

@app.post("/api/local/mkdir")
def api_local_mkdir():
    b=request.json or {}; base=b.get("path","/config"); name=b.get("name","new_folder")
    full=os.path.normpath(os.path.join(base,name)); 
    if not full.startswith("/"):
        return jsonify({"ok":False,"error":"bad path"}),400
    os.makedirs(full, exist_ok=True); return jsonify({"ok":True,"path":full})

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
    write_json(PATHS["mounts"],data); os.makedirs(mountpoint(name),exist_ok=True); return jsonify({"ok":True})

@app.post("/api/mounts/delete")
def api_mounts_delete():
    name=(request.json or {}).get("name","")
    data=read_json(PATHS["mounts"],[]); data=[x for x in data if x.get("name")!=name]; write_json(PATHS["mounts"],data)
    run_cmd(f"umount {shlex.quote(mountpoint(name))} 2>&1 || true"); return jsonify({"ok":True})

@app.post("/api/mounts/mount")
def api_mounts_mount():
    name=(request.json or {}).get("name",""); return jsonify({"ok":ensure_mount(name)})

@app.post("/api/mounts/unmount")
def api_mounts_unmount():
    name=(request.json or {}).get("name",""); run_cmd(f"umount {shlex.quote(mountpoint(name))} 2>&1 || true"); return jsonify({"ok":True})

@app.post("/api/mounts/test")
def api_mounts_test():
    b=request.json or {}; t=b.get("type"); host=b.get("host"); user=b.get("username",""); pw=b.get("password","")
    if t=="smb":
        auth=f"-U {shlex.quote(user+'%'+pw)}" if user else "-N"
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
    data=read_json(PATHS["mounts"],[])
    m=next((x for x in data if x.get("name")==name), None)
    if not m: return jsonify({"ok":False,"error":"unknown mount"}),400
    mp=mountpoint(name)
    if os.path.ismount(mp) and ensure_mount(name):
        path=os.path.normpath(os.path.join(mp, rel.lstrip("/")))
        if not path.startswith(mp): return jsonify({"ok":False,"error":"bad path"}),400
        items=[{"name":e.name,"dir":e.is_dir(),"size":(0 if e.is_dir() else e.stat().st_size)} for e in os.scandir(path)]
        items=sorted(items,key=lambda x:(not x["dir"], x["name"].lower()))
        return jsonify({"ok":True,"base":mp,"path":path,"items":items})
    # Fallback to smbclient listing (no kernel mount)
    if m.get("type")=="smb":
        rel = rel.lstrip("/")
        items = smb_ls(m.get("host",""), m.get("share",""), m.get("username",""), m.get("password",""), rel if rel else "/")
        return jsonify({"ok":True,"base":"//%s/%s"%(m.get("host",""),m.get("share","")), "path":"/"+rel, "items":items, "fallback":True})
    return jsonify({"ok":False,"error":"mount failed"}),400

@app.post("/api/mounts/mkdir")
def api_mounts_mkdir():
    b=request.json or {}; name=b.get("name",""); rel=b.get("path","/"); folder=b.get("folder","new_folder")
    data=read_json(PATHS["mounts"],[])
    m=next((x for x in data if x.get("name")==name), None)
    if not m: return jsonify({"ok":False,"error":"unknown mount"}),400
    mp=mountpoint(name)
    if os.path.ismount(mp) and ensure_mount(name):
        base=os.path.normpath(os.path.join(mp, rel.lstrip("/")))
        if not base.startswith(mp): return jsonify({"ok":False,"error":"bad path"}),400
        full=os.path.join(base,folder); os.makedirs(full,exist_ok=True); return jsonify({"ok":True,"path":full})
    if m.get("type")=="smb":
        rel = (rel.strip('/') + '/' if rel.strip('/') else '') + folder
        auth = f"-U {shlex.quote(m.get('username','')+'%'+m.get('password',''))}" if m.get("username") else "-N"
        cmd = f"smbclient //{shlex.quote(m.get('host',''))}/{shlex.quote(m.get('share',''))} {auth} -c " + shlex.quote(f"mkdir {rel}")
        rc,out,err = run_cmd(cmd + " 2>&1 || true")
        ok = (rc==0) or ('created directory' in (out or '').lower())
        return jsonify({"ok": ok, "path":"/"+rel})
    return jsonify({"ok":False,"error":"mkdir failed"}),400

# ------- Estimate
@app.post("/api/estimate")
def api_estimate():
    b=request.json or {}; mode=b.get("mode","local"); path=b.get("path","/")
    if mode=="local":
        size=sum_dir_bytes(path) if os.path.exists(path) else 0; return jsonify({"ok":True,"bytes":size})
    elif mode=="mount":
        name=b.get("name",""); 
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

# ------- Backups list/download/delete
def man_path(p): return os.path.join(p,"MANIFEST.json")
def write_manifest(p,d): 
    with open(man_path(p),"w") as f: json.dump(d,f,indent=2)
def read_manifest(p):
    try: 
        with open(man_path(p),"r") as f: return json.load(f)
    except Exception: return {}

@app.get("/api/backups")
def api_backups():
    items=[]
    for name in os.listdir(BACKUP_DIR):
        p=os.path.join(BACKUP_DIR,name)
        if not os.path.isdir(p): continue
        man=read_manifest(p); size=sum_dir_bytes(p)
        items.append({"id":name, "label":man.get("label",name), "when":man.get("started",0), "size":size, "mode":man.get("mode",""),
                      "source":man.get("source",{}), "dest":man.get("dest",{}), "dir":p})
    items.sort(key=lambda x:x["when"], reverse=True)
    return jsonify({"items":items})

@app.get("/api/backups/download-archive")
def api_backups_download():
    bid=request.args.get("id",""); p=os.path.normpath(os.path.join(BACKUP_DIR,bid))
    if not p.startswith(BACKUP_DIR) or not os.path.isdir(p): return ("not found",404)
    tmp=os.path.join(UPLOAD_DIR, f"{bid}.tar.gz")
    with tarfile.open(tmp,"w:gz") as tar: tar.add(p, arcname=os.path.basename(p))
    return send_file(tmp, as_attachment=True)

@app.post("/api/backups/delete")
def api_backups_delete():
    bid=(request.json or {}).get("id",""); p=os.path.normpath(os.path.join(BACKUP_DIR,bid))
    if not p.startswith(BACKUP_DIR) or not os.path.isdir(p): return jsonify({"ok":False}),400
    run_cmd(f"rm -rf {shlex.quote(p)}"); return jsonify({"ok":True})

# ------- Rsync helpers
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
    rate = f"| pv -n -L {int(limit_kbps)*1024}" if limit_kbps and int(limit_kbps)>0 else "| pv -n"
    return f"{ssh} 'dd if={shlex.quote(dev)} bs=4M status=none iflag=fullblock' {rate} | gzip > {shlex.quote(out_file)}"

# ------- Backup start (impl for schedule reuse)
def api_backup_start_impl(b, scheduled=False):
    mode=b.get("mode","rsync"); label=b.get("label","backup")
    dest_type=b.get("dest_type","local"); dest_mount=b.get("dest_mount_name",""); dest_path=b.get("dest_path","")
    bwkb=int(b.get("bwlimit_kbps") or 0); dry=bool(b.get("dry_run",False)); profile=(b.get("profile") or "").lower()

    if dest_type=="local": base=dest_path or BACKUP_DIR
    else:
        if not ensure_mount(dest_mount): return {"ok":False,"error":"destination mount failed"}, 400
        base=os.path.join(mountpoint(dest_mount), dest_path.lstrip("/")) if dest_path else mountpoint(dest_mount)
    os.makedirs(base,exist_ok=True)
    out_dir=os.path.join(base, f"{label}-{int(time.time())}"); os.makedirs(out_dir,exist_ok=True)

    excludes=[]
    if profile in ("opnsense","pfsense"): excludes=["/dev","/proc","/sys","/tmp","/run","/mnt","/media"]
    elif profile in ("proxmox","pve"):     excludes=["/proc","/sys","/run","/dev","/tmp","/var/lib/vz/tmp"]
    elif profile in ("unraid","omv"):      excludes=["/proc","/sys","/run","/dev","/tmp"]

    keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"

    manifest={"label":label,"mode":mode,"profile":profile,"started":int(time.time()),"out_dir":out_dir,
              "dest":{"type":dest_type,"mount":dest_mount,"base":base},"source":{}}

    def submit(cmd, kind):
        write_manifest(out_dir, manifest)
        job={"id":int(time.time()),"cmd":cmd,"kind":kind,"label":label,"mode":mode,"dest":base,"dest_dir":out_dir}
        return worker.submit(job)

    if mode=="rsync":
        host=b.get("host"); user=b.get("username"); pw=b.get("password"); src=b.get("source_path","/")
        rsh=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
        cmd=rsync_cmd(f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)}", out_dir, bwkb=bwkb, rsh=rsh, excludes=excludes, dry=dry)
        manifest["source"]={"type":"ssh","host":host,"user":user,"path":src}; 
        return submit(cmd,"backup")

    elif mode=="copy_local":
        src=b.get("source_path","/config"); cmd=rsync_cmd(shlex.quote(src), out_dir, bwkb=bwkb, excludes=excludes, dry=dry)
        manifest["source"]={"type":"local","path":src}; 
        return submit(cmd,"backup")

    elif mode=="copy_mount":
        name=b.get("mount_name"); src=b.get("source_path","/")
        if not ensure_mount(name): return {"ok":False,"error":"source mount failed"}, 400
        mp=mountpoint(name); cmd=rsync_cmd(shlex.quote(os.path.join(mp, src.lstrip('/'))), out_dir, bwkb=bwkb, excludes=excludes, dry=dry)
        manifest["source"]={"type":"mount","name":name,"path":src}; 
        return submit(cmd,"backup")

    elif mode=="image":
        host=b.get("host"); user=b.get("username"); pw=b.get("password"); dev=b.get("device","/dev/sda")
        out_file=os.path.join(out_dir,"disk.img.gz"); cmd=dd_image_cmd(host,user,pw,dev,out_file,limit_kbps=bwkb)
        manifest["source"]={"type":"ssh","host":host,"user":user,"device":dev,"image_gz":"disk.img.gz"}; 
        return submit(cmd,"image")

    return {"ok":False,"error":"unknown mode"}, 400

@app.post("/api/backup/start")
def api_backup_start(): 
    b=request.json or {}
    r=api_backup_start_impl(b)
    if isinstance(r, tuple): return jsonify(r[0]), r[1]
    return jsonify(r)

# ------- Restore
@app.post("/api/restore/start")
def api_restore_start():
    b=request.json or {}; bid=b.get("id",""); src_dir=os.path.normpath(os.path.join(BACKUP_DIR,bid))
    if not src_dir.startswith(BACKUP_DIR) or not os.path.isdir(src_dir): return jsonify({"ok":False,"error":"bad backup id"}),400
    man=read_manifest(src_dir); 
    if not man: return jsonify({"ok":False,"error":"manifest missing"}),400
    original=bool(b.get("original",False)); bwkb=int(b.get("bwlimit_kbps") or 0)

    def submit(cmd,label,to):
        return worker.submit({"id":int(time.time()),"cmd":cmd,"kind":"restore","label":label,"mode":"restore","dest":to})

    srcq=shlex.quote(src_dir)
    if original:
        s=man.get("source",{}); st=s.get("type")
        if st=="local":
            dst=shlex.quote(s.get("path","/")); cmd=rsync_cmd(srcq, dst, bwkb=bwkb)
            return jsonify(submit(cmd, f"restore->local", s.get("path","/")))
        elif st=="ssh":
            keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"
            host=s.get("host"); user=s.get("user"); pw=b.get("password","")
            if not pw: return jsonify({"ok":False,"error":"password required for original (ssh)"}),400
            rsh=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
            dst=f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(s.get('path','/'))}"
            cmd=rsync_cmd(srcq, dst, bwkb=bwkb, rsh=rsh)
            return jsonify(submit(cmd, f"restore->ssh", s.get("path","/")))
        elif st=="mount":
            name=s.get("name"); path=s.get("path","/")
            if not ensure_mount(name): return jsonify({"ok":False,"error":"mount failed"}),400
            mp=mountpoint(name); dst=os.path.join(mp, path.lstrip("/"))
            cmd=rsync_cmd(srcq, shlex.quote(dst), bwkb=bwkb)
            return jsonify(submit(cmd, f"restore->mount", dst))
        else: return jsonify({"ok":False,"error":"unsupported source type"}),400
    else:
        to_mode=b.get("to_mode","local"); to_path=b.get("to_path","/")
        if to_mode=="local":
            cmd=rsync_cmd(srcq, shlex.quote(to_path), bwkb=bwkb)
            return jsonify(submit(cmd, "restore->local", to_path))
        elif to_mode=="ssh":
            keep="-o ServerAliveInterval=30 -o ServerAliveCountMax=6 -p 22"
            host=b.get("host"); user=b.get("username"); pw=b.get("password")
            rsh=f"sshpass -p {shlex.quote(pw)} ssh -o StrictHostKeyChecking=no {keep}"
            dst=f"{shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(to_path)}"
            cmd=rsync_cmd(srcq, dst, bwkb=bwkb, rsh=rsh)
            return jsonify(submit(cmd, "restore->ssh", to_path))
        elif to_mode=="mount":
            name=b.get("mount_name"); 
            if not ensure_mount(name): return jsonify({"ok":False,"error":"mount failed"}),400
            mp=mountpoint(name); dst=os.path.join(mp, to_path.lstrip("/"))
            cmd=rsync_cmd(srcq, shlex.quote(dst), bwkb=bwkb)
            return jsonify(submit(cmd, "restore->mount", dst))
        else: return jsonify({"ok":False,"error":"unknown to_mode"}),400

# ------- Notify API
@app.get("/api/notify/get")
def api_notify_get(): return jsonify(get_notify())

@app.post("/api/notify/save")
def api_notify_save():
    n=request.json or {}; cur=get_notify(); cur.update(n); write_json(PATHS["notify"], cur); return jsonify({"ok":True})

@app.post("/api/notify/test")
def api_notify_test():
    send_gotify("RLB test","This is a test notification."); return jsonify({"ok":True})

# ------- Schedule API
@app.get("/api/schedules")
def api_sched_list(): return jsonify({"items": read_json(PATHS["schedules"],[])})

@app.post("/api/schedules/save")
def api_sched_save():
    b=request.json or {}; sid=b.get("id") or int(time.time()); b["id"]=sid
    sched=read_json(PATHS["schedules"],[])
    sched=[x for x in sched if x.get("id")!=sid]
    # compute next run
    b["next_run"]=_next_from_rule(b.get("rule",{}))
    sched.append(b); write_json(PATHS["schedules"],sched); return jsonify({"ok":True,"id":sid})

@app.post("/api/schedules/delete")
def api_sched_delete():
    sid=(request.json or {}).get("id"); sched=read_json(PATHS["schedules"],[]); sched=[x for x in sched if x.get("id")!=sid]; write_json(PATHS["schedules"],sched); return jsonify({"ok":True})

# ------- UI
@app.get("/")
def ui(): return send_from_directory("www","index.html")

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--port",type=int,default=8066); args=ap.parse_args()
    app.run(host="0.0.0.0", port=args.port)
