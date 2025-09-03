#!/usr/bin/env python3
# /app/intakes/apprise.py
# Apprise/Apprise-API compatible intake for Jarvis
# Exposes:   POST /intake/apprise/notify?token=<secret>&key=<config_key>
# Accepts:   JSON with {title, body, type, tags[]} as used by Apprise API /notify
# Normalizes and emits into Jarvis via the provided emit() callback.

from __future__ import annotations
import json, time
from typing import Callable, Dict, Any, List, Optional
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

def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Apprise-style JSON into Jarvis's internal message shape.
    Apprise API commonly uses fields like 'title', 'body', 'type', 'tag(s)'.
    """
    title = payload.get("title") or payload.get("subject") or ""
    body  = payload.get("body")  or payload.get("message") or ""
    mtype = (payload.get("type") or payload.get("priority") or "info").lower()
    tags  = _as_list(payload.get("tags") or payload.get("tag"))

    # Attach any extras (safe copy)
    extras = {k: v for k, v in payload.items() if k not in ("title", "subject", "body", "message", "type", "priority", "tags", "tag")}
    return {
        "source": "apprise",
        "title": str(title),
        "body":  str(body),
        "type":  mtype,
        "tags":  tags,
        "ts":    _now_ts(),
        "extras": extras,
    }

@apprise_bp.route("/intake/apprise/notify", methods=["POST"])
def intake_apprise_notify():
    # --- auth: token in query (like your existing proxy intakes) ---
    token = request.args.get("token", "") or request.headers.get("X-Jarvis-Token", "")
    if _expected_token and token != _expected_token:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # --- optional apprise config key pass-through (ignored unless restricted) ---
    cfg_key = request.args.get("key", "") or request.headers.get("X-Apprise-Key", "")
    if (not _accept_any_key) and _allowed_keys is not None and cfg_key not in _allowed_keys:
        return jsonify({"ok": False, "error": "invalid apprise key"}), 403

    # --- payload ---
    try:
        payload = request.get_json(force=True, silent=False)  # raise if invalid JSON
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object")
    except Exception as e:
        return jsonify({"ok": False, "error": f"bad json: {e}"}), 400

    msg = _normalize(payload)

    # --- emit into Jarvis pipeline (Beautify + Personas + fanout) ---
    try:
        if _emit is not None:
            _emit(msg)
    except Exception as e:
        return jsonify({"ok": False, "error": f"emit failed: {e}"}), 500

    return jsonify({"ok": True, "received": {"title": msg["title"], "type": msg["type"], "tags": msg["tags"]}}), 200

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
