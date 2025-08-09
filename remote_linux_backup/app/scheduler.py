import os, json, subprocess, shlex

OPTIONS_PATH = "/data/options.json"
CRON_FILE = "/etc/cron.d/remote_linux_backup"

def load_opts():
    try:
        with open(OPTIONS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def parse_job(item):
    # Accept dict, JSON string, key=value pairs (semicolon), or pipe form
    if isinstance(item, dict):
        return item
    s = str(item).strip()
    if not s:
        return None
    # Try JSON
    try:
        return json.loads(s)
    except Exception:
        pass
    # key=value;key=value
    if "=" in s and ";" in s:
        d={}
        for kv in [x for x in s.split(";") if x.strip()]:
            k, _, v = kv.partition("=")
            d[k.strip()] = v.strip()
        return d
    # pipe: name|host|user|method|disk|files|store|cloud|cron|password
    parts = s.split("|")
    if len(parts) >= 10:
        name, host, user, method, disk, files, store, cloud, cron, pwd = [p.strip() for p in parts[:10]]
        return {"name": name, "host": host, "username": user, "method": method, "disk": disk, "files": files,
                "store_to": store, "cloud_upload": cloud, "schedule": cron, "password": pwd}
    return None

def build_cron_line(j: dict):
    sched = j.get("schedule", "").strip()
    if not sched:
        return None
    payload = json.dumps(j).replace('"','\\\"')
    # Ensure PATH is available to cron
    return f'{sched} root JOB_JSON="{payload}" /usr/bin/python3 /app/job_runner.py >> /var/log/remote_linux_backup.log 2>&1\n'

def apply():
    opts = load_opts()
    jobs_raw = opts.get("jobs", [])
    lines = [
        "SHELL=/bin/bash\n",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
    ]
    for item in jobs_raw:
        j = parse_job(item)
        if not j:
            continue
        line = build_cron_line(j)
        if line:
            lines.append(line)

    with open(CRON_FILE, "w") as f:
        f.write("".join(lines))
    os.chmod(CRON_FILE, 0o644)
    # Try to reload cron, but not fatal if not available
    subprocess.run(["/usr/sbin/service", "cron", "reload"], check=False)
    return "".join(lines)

if __name__ == "__main__":
    print(apply())
