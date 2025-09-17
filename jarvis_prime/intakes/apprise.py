#!/usr/bin/env python3
# /app/apprise.py
# Apprise/Apprise-API compatible intake for Jarvis — standalone HTTP sidecar
# Exposes (accepts multiple common patterns):
#   POST /intake/apprise/notify?token=<secret>&key=<config_key>
#   POST /intake/apprise/notify/<config_key>
#   POST /intake/apprise
#   POST /notify
#   POST /notify/<config_key>
# Accepts: JSON with {title, body, type, tags[]} as used by Apprise API /notify
# Normalizes and emits into Jarvis via INTERNAL_EMIT_URL.

from __future__ import annotations
import os
import json
import time
from typing import Dict, Any, List, Optional, Tuple
import requests
from flask import Flask, request, jsonify

# ---------- configuration from env ----------
BIND = os.getenv("INTAKE_APPRISE_BIND", "0.0.0.0")
try:
    PORT = int(os.getenv("INTAKE_APPRISE_PORT", "2591"))
except Exception:
    PORT = 2591

EXPECTED_TOKEN = os.getenv("INTAKE_APPRISE_TOKEN", "")  # optional
ACCEPT_ANY_KEY = (os.getenv("INTAKE_APPRISE_ACCEPT_ANY_KEY", "true").strip().lower() in ("1","true","yes","on"))
ALLOWED_KEYS   = [k for k in (os.getenv("INTAKE_APPRISE_ALLOWED_KEYS", "") or "").split(",") if k.strip()] or None

INTERNAL_EMIT_URL = os.getenv("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

# ---------- optional riff hook from beautify.py ----------
riff_message = None
try:
    import importlib.util as _imp
    _rspec = _imp.spec_from_file_location("beautify", "/app/beautify.py")
    if _rspec and _rspec.loader:
        _beautify = _imp.module_from_spec(_rspec)
        _rspec.loader.exec_module(_beautify)
        if hasattr(_beautify, "riff_message"):
            riff_message = _beautify.riff_message
except Exception as e:
    riff_message = None
    print(f"[apprise] ⚠️ riff unavailable: {e}")

# ---------- helpers ----------
def _now_ts() -> int:
    return int(time.time())

def _norm_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        return x.strip().lower() in ("1", "true", "yes", "on", "y")
    return False

def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        parts = [p.strip() for p in v.replace(";", ",").split(",")]
        return [p for p in parts if p]
    return [str(v)]

def _extract_auth(path_key: Optional[str] = None) -> tuple[str, str]:
    """
    Returns tuple(token, cfg_key) gathered from query, headers, or path.
    token may be empty string if not provided.
    """
    token = request.args.get("token", "") or request.headers.get("X-Jarvis-Token", "") or request.headers.get("X-Apprise-Token", "")
    cfg_key = path_key or request.args.get("key", "") or request.headers.get("X-Apprise-Key", "")
    return token, cfg_key

def _authorized(token: str, cfg_key: str) -> bool:
    """
    Authorization rules:
      - If EXPECTED_TOKEN is set (non-empty) and token matches → allow.
      - Else if token missing:
          * allow if cfg_key provided AND (ACCEPT_ANY_KEY == True OR cfg_key in ALLOWED_KEYS)
      - Else if EXPECTED_TOKEN empty (no token required) → allow.
    """
    if EXPECTED_TOKEN:
        if token and token == EXPECTED_TOKEN:
            return True
        if cfg_key:
            if ACCEPT_ANY_KEY:
                return True
            if ALLOWED_KEYS is not None and cfg_key in ALLOWED_KEYS:
                return True
        return False

    if cfg_key and ALLOWED_KEYS is not None and len(ALLOWED_KEYS) > 0:
        return (cfg_key in ALLOWED_KEYS)
    return True

def _coerce_payload() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Accept JSON, form-encoded, or raw text.
    Returns (payload_dict, extras_pass_through)
    """
    ctype = (request.headers.get("Content-Type") or "").lower()
    extras: Dict[str, Any] = {
        "headers": {k: v for k, v in request.headers.items()},
        "query": {k: v for k, v in request.args.items()},
    }

    # Try JSON (strict)
    if "application/json" in ctype or "json" in ctype:
        try:
            obj = request.get_json(force=True, silent=False)
            if isinstance(obj, dict):
                return obj, extras
        except Exception:
            pass

    # Try form
    if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
        form = request.form or {}
        obj = {
            "title": form.get("title") or form.get("subject") or "",
            "body":  form.get("body")  or form.get("message") or "",
            "type":  form.get("type")  or form.get("priority") or "",
            "tags":  form.get("tags")  or form.get("tag") or "",
        }
        extras["form"] = {k: v for k, v in form.items()}
        return obj, extras

    # Raw text fallback
    try:
        raw = request.get_data(cache=False, as_text=True) or ""
        raw = raw.strip()
        if raw:
            obj = {"body": raw}
            extras["raw"] = True
            return obj, extras
    except Exception:
        pass

    return {}, extras

def _normalize(payload: Dict[str, Any], extras_in: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Apprise-style JSON into Jarvis's internal message shape.
    """
    title = payload.get("title") or payload.get("subject") or ""
    body  = payload.get("body")  or payload.get("message") or ""
    mtype = (payload.get("type") or payload.get("priority") or "info")
    try:
        mtype = str(mtype).lower()
    except Exception:
        mtype = "info"
    tags  = _as_list(payload.get("tags") or payload.get("tag"))

    passthrough = {k: v for k, v in payload.items() if k not in ("title","subject","body","message","type","priority","tags","tag")}
    extras = {"payload": passthrough}
    extras.update(extras_in or {})

    riff_param = request.args.get("riff", "").strip()
    riff_hdr   = (request.headers.get("X-Jarvis-Riff", "") or "").strip()
    riff_hint = None
    if riff_param != "":
        riff_hint = _norm_bool(riff_param)
    elif riff_hdr != "":
        riff_hint = _norm_bool(riff_hdr)
    if riff_hint is None:
        riff_hint = True
    extras["riff_hint"] = bool(riff_hint)

    return {
        "source": "apprise",
        "title": str(title),
        "body":  str(body),
        "type":  mtype,
        "tags":  tags,
        "ts":    _now_ts(),
        "extras": extras,
    }

def _emit_to_jarvis(msg: Dict[str, Any]) -> None:
    """
    Forward a normalized message into Jarvis internal pipeline.
    """
    r = requests.post(
        INTERNAL_EMIT_URL,
        json={
            "title": msg.get("title", "Notification"),
            "body":  msg.get("body", ""),
            "priority": 5,
            "source": "apprise",
            "id": ""
        },
        timeout=20
    )
    r.raise_for_status()

def _handle_post_common(path_key: Optional[str] = None):
    token, cfg_key = _extract_auth(path_key)
    if not _authorized(token, cfg_key):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload, extras_in = _coerce_payload()
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad json: root must be object or form/raw text"}), 400

    msg = _normalize(payload, extras_in)

    try:
        if riff_message and msg.get("body") and msg["extras"].get("riff_hint", True):
            riffed = riff_message(msg["title"], msg["body"])
            if riffed:
                msg["body"] = riffed
                msg["extras"]["used_riff"] = True
    except Exception as e:
        print(f"[apprise] riff failed: {e}")

    try:
        _emit_to_jarvis(msg)
    except Exception as e:
        return jsonify({"ok": False, "error": f"emit failed: {e}"}), 500

    return jsonify({
        "ok": True,
        "received": {"title": msg["title"], "type": msg["type"], "tags": msg["tags"]},
        "auth": {"via": "token" if (token and token == EXPECTED_TOKEN) else ("key" if cfg_key else "open")}
    }), 200

# ---------- Flask app + routes ----------
app = Flask(__name__)

@app.get("/health")
def _health():
    return jsonify({"ok": True, "bind": BIND, "port": PORT}), 200

# Primary routes
@app.post("/intake/apprise/notify")
def intake_apprise_notify():
    return _handle_post_common()

@app.post("/intake/apprise/notify/<path:path_key>")
def intake_apprise_notify_with_key(path_key: str):
    return _handle_post_common(path_key)

@app.post("/intake/apprise")
def intake_apprise_base():
    return _handle_post_common()

@app.post("/notify")
def notify_root():
    return _handle_post_common()

@app.post("/notify/<path:path_key>")
def notify_root_with_key(path_key: str):
    return _handle_post_common(path_key)

def _run_with_waitress():
    try:
        from waitress import serve
        print(f"[apprise] waitress serving on {BIND}:{PORT} (token={'set' if EXPECTED_TOKEN else 'none'}, accept_any_key={ACCEPT_ANY_KEY}, allowed_keys={ALLOWED_KEYS})")
        serve(app, host=BIND, port=PORT, threads=8)
    except Exception as e:
        print(f"[apprise] waitress failed, falling back to Flask dev server: {e}")
        app.run(host=BIND, port=PORT, threaded=True)

if __name__ == "__main__":
    _run_with_waitress()
