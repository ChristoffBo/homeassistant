import os, json, time, shlex, subprocess

def run(cmd):
    p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out,_ = p.communicate()
    return out

def gotify(title, message, priority=5):
    try:
        opts = json.load(open("/app/data/options.json"))
        if not opts.get("gotify_enabled"): return
        url = opts.get("gotify_url"); token = opts.get("gotify_token")
        if not url or not token: return
        cmd = f"curl -s -X POST {shlex.quote(url)}/message -F token={shlex.quote(token)} -F title={shlex.quote(title)} -F message={shlex.quote(message)} -F priority={priority}"
        run(cmd)
    except Exception:
        pass

def main():
    jtxt = os.environ.get("JOB_JSON","")
    if not jtxt:
        print("No JOB_JSON"); return 1
    j = json.loads(jtxt)
    method = j.get("method","dd")
    user = j.get("username","root")
    host = j["host"]
    pwd = j["password"]
    store = j.get("store_to","/backup")
    cloud = j.get("cloud_upload","")
    os.makedirs(store, exist_ok=True)
    t0 = time.time()

    if method == "dd":
        disk = j.get("disk","/dev/sda")
        outp = os.path.join(store, f"{host.replace('.','_')}-{time.strftime('%Y%m%d-%H%M%S')}.img.gz")
        cmd = f"sshpass -p {shlex.quote(pwd)} ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {shlex.quote(user)}@{shlex.quote(host)} 'dd if={shlex.quote(disk)} bs=64K status=progress | gzip -c' > {shlex.quote(outp)}"
        out = run(cmd)
        if cloud:
            out += '\n[RCLONE]\n' + run(f"rclone copy {shlex.quote(outp)} {shlex.quote(cloud)} --progress")
        gotify("Scheduled Backup (dd)", f"Host: {host}\nSaved: {outp}\nTook: {round(time.time()-t0,2)}s")
        print(out); return 0

    elif method == "rsync":
        outs = []
        for src in [s.strip() for s in j.get("files","/etc").split(",") if s.strip()]:
            outs.append(run(f"sshpass -p {shlex.quote(pwd)} rsync -aAX --numeric-ids -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null' {shlex.quote(user)}@{shlex.quote(host)}:{shlex.quote(src)} {shlex.quote(store.rstrip('/') + '/')}"))
        if cloud:
            outs.append('\n[RCLONE]\n' + run(f"rclone copy {shlex.quote(store)} {shlex.quote(cloud)} --progress"))
        gotify("Scheduled Backup (rsync)", f"Host: {host}\nSaved to: {store}\nTook: {round(time.time()-t0,2)}s")
        print("\n".join(outs)); return 0

    else:
        print("Unknown method"); return 2

if __name__ == "__main__":
    raise SystemExit(main())