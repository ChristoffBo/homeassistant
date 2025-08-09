#!/usr/bin/env python3
# Remote Linux Backup – API (mounts + gotify + presets + backups listing)

import os
import json
import shlex
import time
import pathlib
import mimetypes
import subprocess
from typing import Dict, Any, List

from flask import Flask, request, jsonify, send_file, abort, send_from_directory

app = Flask(__name__, static_folder=None)

DATA_DIR = "/data"
CONF_PATH = os.path.join(DATA_DIR, "config.json")
WWW_DIR = "/app/www"

DEFAULT_CONFIG = {
    "options": {
        "ui_port": 8066,
        "gotify_enabled": False,
        "gotify_url": "",
        "gotify_token": "",
        "dropbox_enabled": False,
        "dropbox_remote": "dropbox:HA-Backups"
    },
    "servers": [],
    "mounts": []
}

# ---------- storage helpers ----------
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

# ---------- command runner ----------
def run_cmd(cmd: str, timeout: int = 30):
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 99, "", str(e)

# ---------- SMB/NFS discovery ----------
def _smb_try_modes():
    return ["SMB3", "SMB2", "NT1"]

def smb_list_shares(host: str, username: str = "", password: str = ""):
    creds = ""
    if username or password:
        creds = f" -U {shlex.quote(f'{username}%{password}')}"
    last = ""
    shares = []
    for mode in _smb_try_modes():
        cmd = f"smbclient -L //{shlex.quote(host)} -g -m {mode}{creds}"
        rc, out, err = run_cmd(cmd, timeout=25)
        if rc == 0 and out:
            for line in out.splitlines():
                if line.startswith("Disk|"):
                    parts = line.split("|", 2)
                    if len(parts) >= 2:
                        name = parts[1].strip()
                        if name and name not in ("print$", "IPC$"):
                            shares.append(name)
            if shares:
                return {"ok": True, "shares": sorted(set(shares)), "mode": mode}
        last = err or out or f"rc={rc}"
    return {"ok": False, "error": last}

def smb_ls(host: str, share: str, path: str = "/", username: str = "", password: str = ""):
    if not path:
        path = "/"
    creds = f" -U {shlex.quote(f'{username}%{password}')}" if (username or password) else ""
    last = ""
    items = []
    qpath = path.replace('"', '\\"')
    for mode in _smb_try_modes():
        cmd = f'smbclient //{shlex.quote(host)}/{shlex.quote(share)} -g -m {mode}{creds} -c "ls \\"{qpath}\\""'
        rc, out, err = run_cmd(cmd, timeout=35)
        if rc == 0 and out:
            for line in out.splitlines():
                parts = line.split("|")
                if len(parts) >= 2:
                    kind = parts[0].strip().upper()
                    name = parts[1].strip()
                    if name in (".", "..", ""):
                        continue
                    if kind == "D":
                        items.append({"type": "dir", "name": name})
                    elif kind in ("A", "N"):
                        items.append({"type": "file", "name": name})
            return {"ok": True, "items": items, "mode": mode}
        last = err or out or f"rc={rc}"
    return {"ok": False, "error": last}

def nfs_list_exports(host: str):
    rc, out, err = run_cmd(f"showmount -e {shlex.quote(host)}", timeout=25)
    if rc != 0:
        return {"ok": False, "error": err or out or f"rc={rc}"}
    exports = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("export list"):
            continue
        path = line.split()[0]
        if path.startswith("/"):
            exports.append(path)
    return {"ok": True, "exports": exports}

# ---------- mounts ----------
def ensure_dir(path: str):
    try:
        pathlib.Path(path).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def mount_cifs(server: str, share: str, mount_point: str, username: str = "", password: str = "", extra: str = ""):
    ensure_dir(mount_point)
    opts = [f"username={username}", f"password={password}", "iocharset=utf8", "vers=3.0"]
    if extra:
        opts.append(extra)
    opt_str = ",".join([o for o in opts if o])
    cmd = f"mount -t cifs //{shlex.quote(server)}/{shlex.quote(share)} {shlex.quote(mount_point)} -o {shlex.quote(opt_str)}"
    return run_cmd(cmd, timeout=40)

def mount_nfs(server: str, export: str, mount_point: str, extra: str = ""):
    ensure_dir(mount_point)
    opt_str = extra if extra else "rw"
    cmd = f"mount -t nfs {shlex.quote(server)}:{shlex.quote(export)} {shlex.quote(mount_point)} -o {shlex.quote(opt_str)}"
    return run_cmd(cmd, timeout=40)

def umount_path(mount_point: str):
    return run_cmd(f"umount -l {shlex.quote(mount_point)}", timeout=20)

# ---------- gotify ----------
def gotify_send(title: str, message: str, priority: int = 5, cfg: Dict[str, Any] = None, verify_tls: bool = True):
    import urllib.request
    import ssl

    if cfg is None:
        cfg = _load_config()
    opts = cfg.get("options", {})
    if not opts.get("gotify_enabled"):
        return {"ok": False, "error": "gotify disabled"}

    url = (opts.get("gotify_url") or "").rstrip("/")
    token = (opts.get("gotify_token") or "").strip()
    if not url or not token:
        return {"ok": False, "error": "missing gotify url/token"}

    endpoint = f"{url}/message"
    data = json.dumps({"title": title, "message": message, "priority": int(priority)}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Gotify-Key", token)

    ctx = None
    if not verify_tls and endpoint.lower().startswith("https"):
        ctx = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            _ = resp.read()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------- options ----------
@app.get("/api/options")
def api_options_get():
    cfg = _load_config()
    return jsonify(cfg.get("options", {}))

@app.post("/api/options")
def api_options_post():
    body = request.get_json(silent=True) or {}
    cfg = _load_config()
    opts = cfg.get("options", {})
    for k in ["ui_port", "gotify_enabled", "gotify_url", "gotify_token", "dropbox_enabled", "dropbox_remote"]:
        if k in body:
            opts[k] = body[k]
    cfg["options"] = opts
    _save_config(cfg)
    return jsonify({"ok": True, "config": opts})

# ---------- servers ----------
@app.get("/api/servers")
def api_servers_get():
    cfg = _load_config()
    return jsonify({"servers": cfg.get("servers", [])})

@app.post("/api/server_add_update")
def api_server_add_update():
    b = request.get_json(silent=True) or {}
    name = (b.get("name") or "").strip() or (b.get("host") or "")
    host = (b.get("host") or "").strip()
    if not host:
        return jsonify({"ok": False, "error": "host required"}), 400
    server = {
        "name": name,
        "host": host,
        "username": (b.get("username") or "root").strip(),
        "port": int(b.get("port") or 22),
        "save_password": bool(b.get("save_password")),
    }
    if server["save_password"]:
        server["password"] = b.get("password") or ""
    cfg = _load_config()
    arr = cfg.get("servers", [])
    idx = -1
    for i, s in enumerate(arr):
        if (s.get("host") == server["host"] and s.get("username") == server["username"] and int(s.get("port", 22)) == server["port"]) or (name and s.get("name") == name):
            idx = i
            break
    if idx >= 0:
        arr[idx] = {**arr[idx], **server}
    else:
        arr.append(server)
    cfg["servers"] = arr
    _save_config(cfg)
    return jsonify({"ok": True, "server": server})

@app.post("/api/server_delete")
def api_server_delete():
    b = request.get_json(silent=True) or {}
    key = (b.get("name") or "").strip()
    cfg = _load_config()
    old = cfg.get("servers", [])
    if key:
        new = [s for s in old if s.get("name") != key]
    else:
        host = (b.get("host") or "").strip()
        new = [s for s in old if s.get("host") != host]
    cfg["servers"] = new
    _save_config(cfg)
    return jsonify({"ok": True, "deleted": key or b.get("host")})

# ---------- mounts (CRUD + actions) ----------
@app.get("/api/mounts")
def api_mounts_get():
    cfg = _load_config()
    rows = []
    for m in cfg.get("mounts", []):
        mounted = os.path.ismount(m.get("mount", ""))
        rows.append({**m, "mounted": mounted})
    return jsonify({"mounts": rows})

@app.post("/api/mounts")
def api_mounts_set_all():
    b = request.get_json(silent=True) or {}
    mounts = b.get("mounts") or []
    cfg = _load_config()
    cfg["mounts"] = mounts
    _save_config(cfg)
    return jsonify({"ok": True, "count": len(mounts)})

@app.post("/api/mount_add_update")
def api_mount_add_update():
    b = request.get_json(silent=True) or {}
    name = (b.get("name") or "").strip()
    proto = (b.get("proto") or "cifs").lower()
    server = (b.get("server") or "").strip()
    share = (b.get("share") or "").strip().lstrip("/").rstrip("/")
    mountp = (b.get("mount") or (f"/mnt/{name}" if name else "")).strip()
    username = (b.get("username") or "").strip()
    password = b.get("password") or ""
    options = (b.get("options") or "").strip()
    auto_mount = bool(b.get("auto_mount", False))

    if not (proto and server and share and mountp):
        return jsonify({"ok": False, "error": "name/proto/server/share/mount required"}), 400

    entry = {
        "name": name,
        "proto": proto,
        "server": server,
        "share": share,
        "mount": mountp,
        "username": username,
        "password": password,
        "options": options,
        "auto_mount": auto_mount,
    }

    cfg = _load_config()
    arr = cfg.get("mounts", [])
    idx = -1
    for i, m in enumerate(arr):
        if (m.get("name") and m.get("name") == name) or m.get("mount") == mountp:
            idx = i
            break
    if idx >= 0:
        arr[idx] = {**arr[idx], **entry}
    else:
        arr.append(entry)
    cfg["mounts"] = arr
    _save_config(cfg)
    return jsonify({"ok": True, "entry": entry})

@app.post("/api/mount_delete")
def api_mount_delete():
    b = request.get_json(silent=True) or {}
    key = (b.get("name") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "name required"}), 400
    cfg = _load_config()
    arr = cfg.get("mounts", [])
    arr = [m for m in arr if m.get("name") != key]
    cfg["mounts"] = arr
    _save_config(cfg)
    return jsonify({"ok": True, "deleted": key})

@app.post("/api/mount_now")
def api_mount_now():
    b = request.get_json(silent=True) or {}
    proto = (b.get("proto") or "cifs").lower()
    server = (b.get("server") or "").strip()
    share = (b.get("share") or "").strip().lstrip("/").rstrip("/")
    mountp = (b.get("mount") or "").strip()
    username = (b.get("username") or "").strip()
    password = b.get("password") or ""
    options = (b.get("options") or "").strip()

    if not (server and share and mountp):
        return jsonify({"ok": False, "error": "server/share/mount required"}), 400

    if proto in ("cifs", "smb"):
        rc, out, err = mount_cifs(server, share, mountp, username, password, options)
    else:
        rc, out, err = mount_nfs(server, share, mountp, options)

    return jsonify({"ok": rc == 0, "rc": rc, "out": out, "err": err})

@app.post("/api/unmount_now")
def api_unmount_now():
    b = request.get_json(silent=True) or {}
    mountp = (b.get("mount") or "").strip()
    if not mountp:
        return jsonify({"ok": False, "error": "mount required"}), 400
    rc, out, err = umount_path(mountp)
    return jsonify({"ok": rc == 0, "rc": rc, "out": out, "err": err})

# ---------- SMB/NFS browse ----------
@app.get("/api/mount_list")
def api_mount_list_get():
    proto = (request.args.get("proto") or "cifs").lower()
    server = (request.args.get("server") or "").strip()
    username = (request.args.get("username") or "").strip()
    password = request.args.get("password") or ""
    if not server:
        return jsonify({"ok": False, "error": "missing server"}), 400

    if proto in ("cifs", "smb"):
        r = smb_list_shares(server, username, password)
        if not r.get("ok"):
            return jsonify({"ok": False, "error": r.get("error", "SMB list failed")})
        items = [{"type": "share", "name": s} for s in r["shares"]]
        return jsonify({"ok": True, "items": items})
    else:
        r = nfs_list_exports(server)
        if not r.get("ok"):
            return jsonify({"ok": False, "error": r.get("error", "NFS exports failed")})
        items = [{"type": "export", "name": p, "path": p} for p in r["exports"]]
        return jsonify({"ok": True, "items": items})

@app.post("/api/mount_list")
def api_mount_list_post():
    b = request.get_json(silent=True) or {}
    proto = (b.get("proto") or "cifs").lower()
    server = (b.get("server") or "").strip()
    username = (b.get("username") or "").strip()
    password = b.get("password") or ""
    if not server:
        return jsonify({"ok": False, "error": "missing server"}), 400

    if proto in ("cifs", "smb"):
        r = smb_list_shares(server, username, password)
        if not r.get("ok"):
            return jsonify({"ok": False, "error": r.get("error", "SMB list failed")})
        items = [{"type": "share", "name": s} for s in r["shares"]]
        return jsonify({"ok": True, "items": items})
    else:
        r = nfs_list_exports(server)
        if not r.get("ok"):
            return jsonify({"ok": False, "error": r.get("error", "NFS exports failed")})
        items = [{"type": "export", "name": p, "path": p} for p in r["exports"]]
        return jsonify({"ok": True, "items": items})

@app.post("/api/mount_browse")
def api_mount_browse():
    b = request.get_json(silent=True) or {}
    proto = (b.get("proto") or "cifs").lower()
    server = (b.get("server") or "").strip()
    username = (b.get("username") or "").strip()
    password = b.get("password") or ""
    share = (b.get("share") or "").strip().lstrip("/").rstrip("/")
    path = (b.get("path") or "").strip().lstrip("/")

    if not server:
        return jsonify({"ok": False, "error": "missing server"}), 400

    if proto in ("cifs", "smb"):
        if not share:
            r = smb_list_shares(server, username, password)
            if not r.get("ok"):
                return jsonify({"ok": False, "error": r.get("error", "SMB list failed")})
            items = [{"type": "share", "name": s} for s in r["shares"]]
            return jsonify({"ok": True, "items": items})
        r = smb_ls(server, share, ("/" + path) if path else "/", username, password)
        if not r.get("ok"):
            return jsonify({"ok": False, "error": r.get("error", "SMB ls failed")})
        return jsonify({"ok": True, "items": r.get("items", [])})
    else:
        r = nfs_list_exports(server)
        if not r.get("ok"):
            return jsonify({"ok": False, "error": r.get("error", "NFS exports failed")})
        items = [{"type": "export", "name": p, "path": p} for p in r["exports"]]
        return jsonify({"ok": True, "items": items})

# ---------- Backups listing + download ----------
BACKUP_EXTS = (".img", ".img.gz", ".img.xz", ".dd", ".dd.gz", ".tar", ".tgz", ".tar.gz", ".zip")

def _roots_and_map(cfg: Dict[str, Any]):
    roots: List[str] = []
    mapping = {}  # mount_path -> preset name
    roots.append("/backup")  # local default (optional)
    for m in cfg.get("mounts", []):
        mp = m.get("mount")
        if not mp:
            continue
        if os.path.isdir(mp):
            roots.append(mp)
            mapping[mp] = m.get("name") or mp
    return roots, mapping

def _list_files(root: str):
    items = []
    for base, _, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            try:
                st = os.stat(p)
            except Exception:
                continue
            items.append({
                "path": p,
                "size": st.st_size,
                "created": int(st.st_mtime),
                "kind": ("image" if f.lower().endswith(BACKUP_EXTS) else "file")
            })
    return items

@app.get("/api/backups")
def api_backups():
    cfg = _load_config()
    roots, mapping = _roots_and_map(cfg)
    out = []
    for r in roots:
        if os.path.isdir(r):
            out.extend(_list_files(r))

    # add location (preset)
    for it in out:
        it["location"] = "Local"
        for mp, nm in mapping.items():
            if it["path"].startswith(mp.rstrip("/") + "/") or it["path"] == mp:
                it["location"] = nm
                break
    return jsonify({"items": out})

@app.get("/api/download")
def api_download():
    path = request.args.get("path", "").strip()
    if not path:
        abort(400)
    cfg = _load_config()
    roots, _ = _roots_and_map(cfg)
    # security: ensure path is within an allowed root
    path = os.path.realpath(path)
    allowed = False
    for r in roots:
        rreal = os.path.realpath(r)
        if path == rreal or path.startswith(rreal + os.sep):
            allowed = True
            break
    if not allowed or not os.path.isfile(path):
        abort(404)
    mime, _ = mimetypes.guess_type(path)
    return send_file(path, as_attachment=True, download_name=os.path.basename(path), mimetype=mime or "application/octet-stream")

# ---------- gotify test ----------
@app.post("/api/gotify_test")
def api_gotify_test():
    b = request.get_json(silent=True) or {}
    cfg = _load_config()
    if "url" in b:
        cfg["options"]["gotify_url"] = b.get("url") or ""
    if "token" in b:
        cfg["options"]["gotify_token"] = b.get("token") or ""
    if "enabled" in b:
        cfg["options"]["gotify_enabled"] = bool(b.get("enabled"))
    else:
        if b.get("url") and b.get("token"):
            cfg["options"]["gotify_enabled"] = True
    verify = not bool(b.get("insecure"))
    r = gotify_send("Remote Linux Backup", "This is a test from the add-on UI.", priority=5, cfg=cfg, verify_tls=verify)
    return jsonify(r)

# ---------- static root (optional) ----------
@app.get("/")
def root():
    index = os.path.join(WWW_DIR, "index.html")
    if os.path.exists(index):
        return send_from_directory(WWW_DIR, "index.html")
    return "OK", 200

# gunicorn entry
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8066, debug=False)
