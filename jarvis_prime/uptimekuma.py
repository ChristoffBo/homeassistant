import os, requests

KUMA_URL = (os.getenv("uptimekuma_url", "") or "").rstrip("/")
KUMA_KEY = os.getenv("uptimekuma_api_key", "")
ENABLED  = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")

def _get_json(path):
    try:
        url = f"{KUMA_URL}{path}"
        headers = {"Authorization": f"Bearer {KUMA_KEY}"} if KUMA_KEY else {}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def handle_kuma_command(cmd: str):
    if not ENABLED or not KUMA_URL:
        return "⚠️ Uptime Kuma not enabled or misconfigured", None
    c = (cmd or "").strip().lower()

    # Status summary (monitors)
    if "kuma" in c and "status" in c:
        data = _get_json("/api/status-page/summary")
        if isinstance(data, dict) and data.get("monitors"):
            lines = ["📡 Uptime Kuma — Status"]
            for m in data["monitors"]:
                name = m.get("name","?")
                status = str(m.get("status","unknown")).lower()
                icon = "✅" if status in ("up","ok","healthy","operational") else "❌"
                lines.append(f"- {icon} {name}: {status}")
            return "\n".join(lines), None
        return "⚠️ Could not read Kuma status", None

    # Incidents (if status page uses them)
    if "kuma" in c and ("incident" in c or "incidents" in c):
        data = _get_json("/api/status-page/summary")
        if isinstance(data, dict) and isinstance(data.get("incidents"), list):
            inc = data.get("incidents") or []
            if not inc:
                return "✅ No active incidents", None
            out = ["🚨 Active Incidents:"]
            for i in inc:
                out.append(f"- {i.get('title','?')} — {i.get('status','?')}")
            return "\n".join(out), None
        return "⚠️ No incidents found", None

    return None, None
