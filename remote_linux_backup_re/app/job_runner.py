#!/usr/bin/env python3
import sys, json, time, os
from api import dd_backup, rsync_pull, dd_restore, rsync_push, local_size_bytes, prune_old

def main():
    if len(sys.argv) < 2:
        print("usage: job_runner.py '{json_job}'")
        return 2
    try:
        job = json.loads(sys.argv[1])
    except Exception as e:
        print(f"invalid job json: {e}")
        return 2

    method = job.get("method")
    user   = job.get("username","root")
    host   = job.get("host","")
    pwd    = job.get("password","")
    port   = int(job.get("port",22))
    store_to = job.get("store_to","/backup")
    os.makedirs(store_to, exist_ok=True)
    bwlimit = int(job.get("bwlimit_kbps",0) or 0) or None
    verify  = bool(job.get("verify", False))
    excludes = job.get("excludes","")
    retention_days = int(job.get("retention_days",0) or 0)
    name = (job.get("backup_name","") or "").strip()

    t0 = time.time()
    if method == "dd":
        disk = job.get("disk","/dev/sda")
        ts = time.strftime("%Y%m%d-%H%M%S")
        base_name=(name.replace(' ','_')+'-' if name else f"{host.replace('.','_')}-")+ts+".img.gz"
        out_path=os.path.join(store_to, base_name)
        rc,out = dd_backup(user,host,pwd,disk,out_path,port=port,verify=verify,bwlimit_kbps=bwlimit)
        size_bytes = local_size_bytes(out_path) if rc==0 else 0
        if retention_days>0:
            out += "\n[PRUNE]\n" + prune_old(store_to, retention_days)
        took=round(time.time()-t0,2)
        print(out)
        print(f"[JOB] rc={rc} took={took}s saved={out_path} size={size_bytes}")
        return rc

    if method == "rsync":
        files = job.get("files","/etc")
        dest = os.path.join(store_to, name.replace(' ','_')) if name else store_to
        os.makedirs(dest, exist_ok=True)
        rc,out = rsync_pull(user,host,pwd,files,dest,port=port,excludes_csv=excludes,bwlimit_kbps=bwlimit)
        size_bytes = local_size_bytes(dest) if rc==0 else 0
        if retention_days>0:
            out += "\n[PRUNE]\n" + prune_old(dest, retention_days)
        took=round(time.time()-t0,2)
        print(out)
        print(f"[JOB] rc={rc} took={took}s saved={dest} size={size_bytes}")
        return rc

    print("Unknown method in job")
    return 2

if __name__ == "__main__":
    sys.exit(main())
