import os
import re
import base64
import requests
from typing import Dict, Tuple, Optional

# =============================
# Config from env (set by run.sh)
# =============================
KUMA_URL: str = (os.getenv("uptimekuma_url", "") or "").rstrip("/")
KUMA_API_KEY: str = os.getenv("uptimekuma_api_key", "") or ""
ENABLED: bool = os.getenv("uptimekuma_enabled", "false").strip().lower() in ("1", "true", "yes")

# Optional: if you ever expose a (private) status page internally and want to use it:
STATUS_SLUG: str = os.getenv("uptimekuma_status_slug", "") or ""

# Shared session
_session = requests.Session()

# =============================
# Helpers
# =============================
def _basic_auth_header_for_api_key() -> Optional[str]:
    """
    Uptime Kuma API Keys secure the /metrics endpoint via **HTTP Basic**:
    - username: (blank)
    - password: <API KEY>
    -> So the header is 'Authorization: Basic base64(":<key>")'
    """
    if not KUMA_API_KEY:
        return None
    token = ":" + KUMA_API_KEY
    return "Basic " + base64.b64encode(token.encode("utf-8")).decode("ascii")

def _get_metrics_text(timeout: int = 8) -> Optional[str]:
    if not KUMA_URL:
        return None
    url = f"{KUMA_URL}/metrics"
    headers = {}
    # Prefer API key if provided
    ba = _basic_auth_header_for_api_key()
    if ba:
        headers["Authorization"] = ba
    try:
        r = _session.get(url, headers=headers, timeout=timeout)
        # If API key path is misconfigured, try without auth as a fallback
        if r.status_code in (401, 403):
            r2 = _session.get(url, timeout=timeout)
            if r2.ok:
                return r2.text
        if r.ok:
            return r.text
    except Exception:
        pass
    return None

_METRIC_RE = re.compile(
    r'^\s*monitor_status\s*\{\s*([^}]*)\s*\}\s+([0-9]+(?:\.[0-9]+)?)\s*$',
    re.IGNORECASE
)
_LABEL_RE = re.compile(r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"(.*?)"\s*')

def _parse_labels(label_block: str) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for m in _LABEL_RE.finditer(label_block or ""):
        labels[m.group(1)] = m.group(2)
    return labels

def _summarize_from_metrics(text: str) -> Tuple[int, int, Dict[str, float]]:
    """
    Returns: (up_count, down_count, down_by_name{ name: value })
    """
    up = 0
    down = 0
    down_by: Dict[str, float] = {}
    for line in (text or "").splitlines():
        m = _METRIC_RE.match(line)
        if not m:
            continue
        labels = _parse_labels(m.group(1))
        val_str = m.group(2)
        try:
            val = float(val_str)
        except Exception:
            continue
        name = labels.get("monitor_name") or labels.get("monitor_url") or labels.get("monitor_hostname") or "monitor"
        # In Kuma, 1 = UP, 0 = DOWN
        if val >= 0.5:
            up += 1
        else:
            down += 1
            down_by[name] = val
    return up, down, down_by

def _kv(label: str, value) -> str:
    return f"    {label}: {value}"

# =============================
# Public router
# =============================
def handle_kuma_command(cmd: str):
    """
    Trigger with messages like:
      - 'kuma'
      - 'kuma status'
      - 'uptime kuma'
    """
    if not ENABLED or not KUMA_URL:
        return "⚠️ Uptime Kuma module not enabled or misconfigured", None

    c = (cmd or "").lower().strip()
    if not (c == "kuma" or "kuma" in c or "uptime" in c or "status" in c):
        # Not our command
        return None

    # Prefer private metrics mode for LAN setups
    metrics = _get_metrics_text()
    if metrics:
        up, down, down_by = _summarize_from_metrics(metrics)
        lines = []
        lines.append("🩺 Uptime Kuma — LAN Metrics")
        lines.append(_kv("URL", KUMA_URL))
        lines.append(_kv("Monitors UP", up))
        lines.append(_kv("Monitors DOWN", down))
        if down_by:
            lines.append("")
            lines.append("⚠️ Down:")
            for name in sorted(down_by.keys()):
                lines.append(f"    • {name}")
        return "\n".join(lines), None

    # If metrics failed, optionally try status page (when you set STATUS_SLUG)
    if STATUS_SLUG:
        try:
            r = _session.get(f"{KUMA_URL}/api/status-page/heartbeat/{STATUS_SLUG}", timeout=8)
            if r.ok:
                j = r.json()
                # Count "down" by checking last heartbeat status: 1=UP, 0=DOWN
                items = j.get("monitors", j.get("heartbeatList", {}))
                up = 0
                down = 0
                down_names = []
                # V1/v2 formats vary; handle both lightly
                if isinstance(items, dict):
                    for key, hb in items.items():
                        status = 1
                        name = key
                        if isinstance(hb, list) and hb:
                            status = 1 if (hb[0].get("status", 1) == 1) else 0
                        elif isinstance(hb, dict):
                            status = 1 if (hb.get("status", 1) == 1) else 0
                        if status == 1:
                            up += 1
                        else:
                            down += 1
                            down_names.append(name)
                lines = []
                lines.append("🩺 Uptime Kuma — Status Page")
                lines.append(_kv("URL", KUMA_URL))
                lines.append(_kv("Monitors UP", up))
                lines.append(_kv("Monitors DOWN", down))
                if down_names:
                    lines.append("")
                    lines.append("⚠️ Down:")
                    for n in sorted(down_names):
                        lines.append(f"    • {n}")
                return "\n".join(lines), None
        except Exception:
            pass

    # Nothing worked
    return ("⚠️ Could not read Kuma status.\n"
            "💡 Tip: set `uptimekuma_api_key` (for /metrics) or `uptimekuma_status_slug` (for a status page)."), None
