#!/usr/bin/env python3
# /app/intakes/apprise.py
# Apprise/Apprise-API compatible intake for Jarvis
# Exposes (now accepts multiple common patterns):
#   POST /intake/apprise/notify?token=<secret>&key=<config_key>
#   POST /intake/apprise/notify/<config_key>
#   POST /intake/apprise
#   POST /notify
#   POST /notify/<config_key>
# Accepts: JSON with {title, body, type, tags[]} as used by Apprise API /notify
# Normalizes and emits into Jarvis via the provided emit() callback.

from __future__ import annotations
import json, time
from typing import Callable, Dict, Any, List, Optional, Tuple
from flask import Blueprint, request, jsonify

apprise_bp = Blueprint("apprise", __name__)

# This will be set by register()
_emit: Optional[Callable[[Dict[str, Any]], None]] = None
_expected_token: Optional[str] = None
_accept_any_key: bool = True
_allowed_keys: Optional[List[str]] = None

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
        # Apprise API sometimes passes comma/space-separated tags
        parts = [p.strip() for p in v.replace(";", ",").split(",")]
        return [p for p in parts if p]
    return [str(v)]

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
        except Exception as _e:
            # fall through to other modes
            pass

    # Try form
    if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
        form = request.form or {}
        # map common keys found in Apprise-style posts
        obj = {
            "title": form.get("title") or form.get("subject") or "",
            "body": form.get("body") or form.get("message") or "",
            "type": form.get("type") or form.get("priority") or "",
            "tags": form.get("tags") or form.get("tag") or "",
        }
        # keep all form fields in extras
        extras["form"] = {k: v for k, v in form.items()}
        return obj, extras

    # Raw text fallback
    try:
        raw = request.get_data(cache=False, as_text=True) or ""
        raw = raw.strip()
        if raw:
            # Single-string payload: treat as body-only
            obj = {"body": raw}
            extras["raw"] = True
            return obj, extras
    except Exception:
        pass

    # Default empty
    return {}, extras

def _normalize(payload: Dict[str, Any], extras_in: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Apprise-style JSON into Jarvis's internal message shape.
    Apprise API commonly uses fields like 'title', 'body', 'type', 'tag(s)'.
    """
    title = payload.get("title") or payload.get("subject") or ""
    body  = payload.get("body")  or payload.get("message") or ""
    mtype = (payload.get("type") or payload.get("priority") or "info")
    try:
        mtype = str(mtype).lower()
    except Exception:
        mtype = "info"
    tags  = _as_list(payload.get("tags") or payload.get("tag"))

    # Pass-through unknown fields into extras (non-destructive)
    passthrough = {k: v for k, v in payload.items() if k not in ("title", "subject", "body", "message", "type", "priority", "tags", "tag")}
    extras = {"payload": passthrough}
    extras.update(extras_in or {})

    # Allow caller to hint riff behavior (?riff=1 or header X-Jarvis-Riff: 1)
    riff_param = request.args.get("riff", "").strip()
    riff_hdr = (request.headers.get("X-Jarvis-Riff", "") or "").strip()
    riff_hint = None
    if riff_param != "":
        riff_hint = _norm_bool(riff_param)
    elif riff_hdr != "":
        riff_hint = _norm_bool(riff_hdr)
    # Default to True (safe: emitter may ignore if LLM/Beautify disabled)
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
      - If _expected_token is set (non-empty) and token matches → allow.
      - Else if token missing:
          * allow if cfg_key provided AND (_accept_any_key == True OR cfg_key in _allowed_keys)
      - Else if _expected_token empty (no token required) → allow.
    """
    # If a token is configured, prefer it
    if _expected_token:
        if token and token == _expected_token:
            return True
        # allow via key fallback when token not supplied
        if cfg_key:
            if _accept_any_key:
                return True
            if _allowed_keys is not None and cfg_key in _allowed_keys:
                return True
        return False

    # No token configured → accept, optionally checking key list if provided
    if cfg_key and _allowed_keys is not None and len(_allowed_keys) > 0:
        return (cfg_key in _allowed_keys)
    return True

def _handle_post_common(path_key: Optional[str] = None):
    token, cfg_key = _extract_auth(path_key)

    if not _authorized(token, cfg_key):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # --- payload (JSON / form / raw) ---
    payload, extras_in = _coerce_payload()
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad json: root must be object or form/raw text"}), 400

    msg = _normalize(payload, extras_in)

    # --- emit into Jarvis pipeline (Beautify + Personas + fanout) ---
    try:
        if _emit is not None:
            _emit(msg)
    except Exception as e:
        return jsonify({"ok": False, "error": f"emit failed: {e}"}), 500

    return jsonify({
        "ok": True,
        "received": {"title": msg["title"], "type": msg["type"], "tags": msg["tags"]},
        "auth": {
            "via": "token" if (token and token == _expected_token) else ("key" if cfg_key else "open"),
        }
    }), 200

# ===== Primary route you originally had =====
@apprise_bp.route("/intake/apprise/notify", methods=["POST"])
def intake_apprise_notify():
    return _handle_post_common()

# ===== ADD: accept path-style key (…/notify/<key>) =====
@apprise_bp.route("/intake/apprise/notify/<path:path_key>", methods=["POST"])
def intake_apprise_notify_with_key(path_key: str):
    return _handle_post_common(path_key)

# ===== ADD: accept base /intake/apprise (some clients post here without /notify) =====
@apprise_bp.route("/intake/apprise", methods=["POST"])
def intake_apprise_base():
    return _handle_post_common()

# ===== ADD: generic Apprise endpoints at root (clients that only know /notify[/<key>]) =====
@apprise_bp.route("/notify", methods=["POST"])
def notify_root():
    return _handle_post_common()

@apprise_bp.route("/notify/<path:path_key>", methods=["POST"])
def notify_root_with_key(path_key: str):
    return _handle_post_common(path_key)

def register(app, emit: Callable[[Dict[str, Any]], None], *,
            token: Optional[str],
            accept_any_key: bool = True,
            allowed_keys: Optional[List[str]] = None) -> None:
    """
    Called by bot.py on startup when enabled.
    - app: Flask app
    - emit: callable that accepts a normalized message dict and enqueues it
    - token: shared secret to accept requests (query ?token=... or header X-Jarvis-Token)
    - accept_any_key / allowed_keys: optional extra gate for Apprise "configuration key"
    """
    global _emit, _expected_token, _accept_any_key, _allowed_keys
    _emit = emit
    _expected_token = token or ""
    _accept_any_key = _norm_bool(accept_any_key)
    _allowed_keys = allowed_keys[:] if allowed_keys else None

    app.register_blueprint(apprise_bp)