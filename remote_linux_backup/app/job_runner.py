import os, json, time, shlex, subprocess, sys

OPTIONS_PATH = "/data/options.json"

def run(cmd):
    p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out,_ = p.communicate()
    return out

def gotify(title, message, priority=5):
    try:
        opts = json.load(open(OPTIONS_PATH))
        if not opts.get("gotify_enabled"): return
        url = opts.get("gotify_url"); token = opts.get("gotify_token")
        if not url or not token: return
        cmd = f"curl -s -X POST {shlex.quote(url)}/message -F token={shlex.quote(token)} -F title={shlex.quote(title)} -F message={shlex.quote(message)} -F priority={priority}"
        run(cmd)
    except Exception:
        pass

def main():
    jtxt = os.environ.get("JOB_JSON", "")
    if not jtxt:
        print("No JOB_JSON provided")
        return 2
    try:
        j = json.loads(jtxt)
    except Exception as e:
        print(f"Invalid JOB_JSON: {e}")
        return 2

    host = j.get("host"); user=j.get("username","root"); pwd=j.get("password","")
    method = j.get("method"); store=j.get("store_to","/backup"); cloud=j.get("cloud_upload","")
    if not host or not method:
        print("Missing host/method"); return 2

    t0=time.time()
    if method == "dd":
        disk=j.get("disk","/dev/sda")
        ts=time.strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(store, f"{host.replace('.','_')}-{ts}.img.gz")
        os.makedirs(store, exist_ok=True)
        cmd = f"sshpass -p {shlex.quote(pwd)} ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(disk)} bs=64K status=progress | gzip -c' > {shlex.quote(out_path)}"
        out = run(cmd)
        if cloud:
            out += "\n[RCLONE]\n" + run(f"rclone copy {shlex.quote(out_path)} {shlex.quote(cloud)} --progress")
        gotify("Scheduled Backup (dd)", f"Host: {host}\nSaved: {out_path}\nTook: {round(time.time()-t0,2)}s")
        print(out); return 0

    elif method == "rsync":
        outs = []
        os.makedirs(store, exist_ok=True)
        for src in [s.strip() for s in j.get("files","/etc").split(",") if s.strip()]:
            outs.append(run(f"sshpass -p {shlex.quote(pwd)} rsync -aAX --numeric-ids -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null' {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)} {shlex.quote(store.rstrip('/') + '/')}"))
        if cloud:
            outs.append('\n[RCLONE]\n' + run(f"rclone copy {shlex.quote(store)} {shlex.quote(cloud)} --progress"))
        gotify("Scheduled Backup (rsync)", f"Host: {host}\nSaved to: {store}\nTook: {round(time.time()-t0,2)}s")
        print("\n".join(outs)); return 0

    elif method == "zfs":
        dataset = j.get("zfs_dataset")
        if not dataset:
            print("Missing zfs_dataset"); return 2
        snap = j.get("snapshot_name", time.strftime("backup-%Y%m%d-%H%M%S"))
        out = run(f"sshpass -p {shlex.quote(pwd)} ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {shlex.quote(user)}@{shlex.quote(host)} 'zfs snapshot {shlex.quote(dataset)}@{shlex.quote(snap)}'")
        gotify("Scheduled Backup (zfs)", f"Host: {host}\nSnapshot: {dataset}@{snap}")
        print(out); return 0

    else:
        print("Unknown method"); return 2

if __name__ == "__main__":
    raise SystemExit(main())
