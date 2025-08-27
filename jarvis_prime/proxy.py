import os
import threading
import requests
from flask import Flask, request, jsonify

# =============================
# Config (from env / options.json)
# =============================
PROXY_ENABLED = os.getenv("proxy_enabled", "false").lower() in ("1", "true", "yes")
PROXY_PORT = int(os.getenv("proxy_port", "8099"))

# Real servers to forward to
PROXY_GOTIFY_URL = os.getenv("proxy_gotify_url", "").rstrip("/")
PROXY_NTFY_URL = os.getenv("proxy_ntfy_url", "").rstrip("/")

app = Flask(__name__)

# =============================
# Helpers
# =============================
def _forward_to_gotify(payload, args):
    """Forward POST to real Gotify instance."""
    if not PROXY_GOTIFY_URL:
        return {"error": "proxy_gotify_url not configured"}, 500
    try:
        url = f"{PROXY_GOTIFY_URL}/message"
        if args:
            url += "?" + "&".join([f"{k}={v}" for k, v in args.items()])
        r = requests.post(url, json=payload, timeout=8)
        return r.json(), r.status_code
    except Exception as e:
        return {"error": str(e)}, 500

def _forward_to_ntfy(topic, raw_data, headers):
    """Forward POST to real ntfy instance."""
    if not PROXY_NTFY_URL:
        return {"error": "proxy_ntfy_url not configured"}, 500
    try:
        url = f"{PROXY_NTFY_URL}/{topic}"
        # Pass through body + headers (light sanitization if needed)
        r = requests.post(url, data=raw_data, headers=headers, timeout=8)
        return r.text, r.status_code
    except Exception as e:
        return {"error": str(e)}, 500

# =============================
# Routes
# =============================
@app.route("/gotify/message", methods=["POST"])
def gotify_message():
    payload = request.get_json(force=True, silent=True) or {}
    args = request.args.to_dict()
    resp, code = _forward_to_gotify(payload, args)
    return jsonify(resp), code

@app.route("/ntfy/<topic>", methods=["POST", "PUT"])
def ntfy_message(topic):
    raw_data = request.get_data()
    headers = dict(request.headers)
    resp, code = _forward_to_ntfy(topic, raw_data, headers)
    return resp, code

# =============================
# Runner
# =============================
def start_proxy():
    if not PROXY_ENABLED:
        print("[Proxy] Disabled by config")
        return
    def _run():
        print(f"[Proxy] Listening on 0.0.0.0:{PROXY_PORT} (Gotify + ntfy proxy)")
        app.run(host="0.0.0.0", port=PROXY_PORT, debug=False, use_reloader=False)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
