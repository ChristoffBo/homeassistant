#!/usr/bin/env python3
import os
import time
import json
import subprocess
import argparse

def send_gotify(title, message, cfg):
    if not cfg.get("gotify_enabled"):
        return
    url = cfg.get("gotify_url")
    token = cfg.get("gotify_token")
    if not url or not token:
        return
    try:
        subprocess.run(
            [
                "curl", "-s", "-X", "POST", f"{url}/message",
                "-F", f"token={token}",
                "-F", f"title={title}",
                "-F", f"message={message}",
                "-F", "priority=5"
            ],
            check=False
        )
    except Exception as e:
        print(f"[Gotify Error] {e}")

def run_single(job, cfg):
    start = time.time()
    dest = job["destination"]
    os.makedirs(dest, exist_ok=True)

    mode = job.get("mode", "rsync")
    ssh_host = job.get("ssh_host")
    ssh_user = job.get("ssh_user")
    ssh_port = int(job.get("ssh_port", cfg.get("ssh_port", 22)))
    bandwidth = int(job.get("bandwidth_limit", 0) or cfg.get("bandwidth_limit", 0) or 0)
    excludes = (job.get("excludes") or cfg.get("rsync_excludes") or "").strip()

    name = job.get("name") or f"backup_{time.strftime('%Y%m%d_%H%M%S')}"
    if mode == "rsync":
        exclude_args = " ".join([f"--exclude '{p.strip()}'" for p in excludes.split(",") if p.strip()])
        bw = f"--bwlimit={bandwidth}" if bandwidth > 0 else ""
        cmd = f"rsync -aAX -e 'ssh -p {ssh_port}' {exclude_args} {bw} {ssh_user}@{ssh_host}:{job['source']} {dest.rstrip('/') + '/'}"
    elif mode == "dd":
        archive = os.path.join(dest, f"{name}.img.gz")
        comp = "pigz -c" if subprocess.call("command -v pigz >/dev/null 2>&1", shell=True)==0 else "gzip -c"
        device = job.get("source", "/dev/sda")
        cmd = f"ssh -p {ssh_port} {ssh_user}@{ssh_host} 'dd if={device} bs=64K status=progress' | {comp} > {archive}"
    else:
        return 2, f"Unsupported mode: {mode}"

    print(f"[JobRunner] Running: {cmd}")
    rc = subprocess.call(cmd, shell=True)

    elapsed = round(time.time() - start, 2)
    try:
        size = subprocess.check_output(["du", "-sh", dest]).split()[0].decode()
    except Exception:
        size = "unknown"

    title = "Backup Success" if rc == 0 else "Backup Failed"
    msg = f"Job: {name}\nMode: {mode}\nDest: {dest}\nTime: {elapsed}s\nSize: {size}"
    send_gotify(title, msg, cfg)
    return rc, msg

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--job", required=True, help="Path to JSON job file")
    args = parser.parse_args()
    with open(args.config, "r") as f:
        cfg = json.load(f)
    with open(args.job, "r") as f:
        job = json.load(f)
    rc, msg = run_single(job, cfg)
    print(msg)
    exit(rc)

if __name__ == "__main__":
    main()
