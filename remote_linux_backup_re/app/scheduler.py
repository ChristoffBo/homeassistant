import os, json, subprocess, tempfile

CONFIG_PATH = "/data/options.json"

def _load_opts():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _write_crontab(lines):
    fd, tmp = tempfile.mkstemp(prefix="ha-cron-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        subprocess.check_call(["crontab", tmp])
    finally:
        os.remove(tmp)

def render_cron(opts):
    jobs = opts.get("jobs") or []
    lines = [
        "# Remote Linux Backup – generated crontab",
        "# DO NOT EDIT – use the add-on UI",
        "SHELL=/bin/bash",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        ""
    ]
    for j in jobs:
        if not j or not isinstance(j, dict): 
            continue
        if not j.get("enabled", True):
            continue
        schedule = (j.get("schedule") or "").strip()
        if not schedule:
            continue
        # Pass whole job JSON to job_runner.py
        body = json.dumps(j, ensure_ascii=False)
        line = f'{schedule} /usr/bin/python3 /app/job_runner.py \'{body}\' >> /var/log/remote_linux_backup.log 2>&1'
        lines.append(line)
    return lines

def apply():
    opts = _load_opts()
    lines = render_cron(opts)
    _write_crontab(lines)

    # Reload cron gracefully; ignore failures on minimal systems
    import shutil, signal
    def _maybe(cmd):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False)
            return True
        return False
    if not (_maybe(["service", "cron", "reload"]) or
            _maybe(["systemctl", "reload", "cron"])):
        try:
            if shutil.which("pgrep"):
                for pid in subprocess.check_output(["pgrep", "cron"]).decode().split():
                    try:
                        os.kill(int(pid), signal.SIGHUP)  # type: ignore[name-defined]
                    except Exception:
                        pass
        except Exception:
            pass

    return "Applied cron with {} line(s)".format(len(lines))

if __name__ == "__main__":
    print(apply())
