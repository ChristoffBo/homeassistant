\
import os, json, time, shlex, subprocess, hashlib

def run(cmd):
    p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out_lines = []
    for line in p.stdout:
        out_lines.append(line)
    rc = p.wait()
    return rc, "".join(out_lines)

def gotify(title, message):
    try:
        with open("/data/options.json","r") as f:
            opts=json.load(f)
    except Exception:
        opts={}
    if not opts.get("gotify_enabled"): return
    url=opts.get("gotify_url"); token=opts.get("gotify_token")
    if not url or not token: return
    cmd=f"curl -s -X POST {shlex.quote(url)}/message -F token={shlex.quote(token)} -F title={shlex.quote(title)} -F message={shlex.quote(message)} -F priority=5"
    run(cmd)

def _ssh_base_cmd(port):
    port_flag = f"-p {int(port)}" if str(port).strip() else ""
    return f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {port_flag}"

def dd_backup(user, host, password, disk, out_path, port=22, verify=False, bwlimit_kbps=None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    comp = "pigz -c" if subprocess.call("command -v pigz >/dev/null 2>&1", shell=True)==0 else "gzip -c"
    base = _ssh_base_cmd(port)
    bw = f" | pv -q -L {int(bwlimit_kbps)*1024} " if bwlimit_kbps else " | "
    pipeline = f"sshpass -p {shlex.quote(password)} {base} {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(disk)} bs=64K status=progress'{bw}{comp} > {shlex.quote(out_path)}"
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
        outs.append(f"$ {cmd}\\n{o}")
        if r != 0: rc = r
    return rc, "\\n".join(outs)

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
    return "\\n".join(deleted)

if __name__ == "__main__":
    t0=time.time()
    job_json=os.environ.get("JOB_JSON","").strip()
    if not job_json:
        print("No JOB_JSON provided"); exit(2)
    j=json.loads(job_json)
    host=j.get("host"); user=j.get("username","root"); pwd=j.get("password",""); method=j.get("method"); port=int(j.get("port",22))
    store=j.get("store_to","/backup"); cloud=j.get("cloud_upload",""); files=j.get("files","/etc"); disk=j.get("disk","/dev/sda")
    name=j.get("backup_name","").strip(); excludes=j.get("excludes",""); bw=int(j.get("bwlimit_kbps",0) or 0) or None; verify=bool(j.get("verify",False)); ret=int(j.get("retention_days",0) or 0)
    os.makedirs(store,exist_ok=True)
    if method=="dd":
        ts=time.strftime("%Y%m%d-%H%M%S")
        base_name=(name.replace(' ','_')+'-' if name else f"{host.replace('.','_')}-")+ts+".img.gz"
        out_path=os.path.join(store, base_name)
        rc,out = dd_backup(user,host,pwd,disk,out_path,port=port,verify=verify,bwlimit_kbps=bw)
        if rc==0 and cloud: rr,ro=rclone_copy(out_path,cloud,bwlimit_kbps=bw); out+="\\n[RCLONE]\\n"+ro
        if ret>0: out+="\\n[PRUNE]\\n"+prune_old(store,ret)
        took=round(time.time()-t0,2)
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\\nMethod: dd\\nSaved: {out_path}\\nTime: {took}s")
        print(out); exit(rc)
    elif method=="rsync":
        dest = os.path.join(store, name.replace(' ','_')) if name else store
        os.makedirs(dest, exist_ok=True)
        rc,out = rsync_pull(user,host,pwd,files,dest,port=port,excludes_csv=excludes,bwlimit_kbps=bw)
        if rc==0 and cloud: rr,ro=rclone_copy(dest,cloud,bwlimit_kbps=bw); out+="\\n[RCLONE]\\n"+ro
        if ret>0: out+="\\n[PRUNE]\\n"+prune_old(dest,ret)
        took=round(time.time()-t0,2)
        gotify("Backup "+("OK" if rc==0 else "FAIL"), f"Host: {host}\\nMethod: rsync\\nSaved: {dest}\\nTime: {took}s")
        print(out); exit(rc)
    else:
        print("Unknown method"); exit(2)
