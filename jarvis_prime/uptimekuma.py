import os
import re
import requests
from typing import Dict, Tuple, Optional, List

# =============================
# Config
# =============================
KUMA_URL: str = (os.getenv("uptimekuma_url", "") or "").rstrip("/")
KUMA_API_KEY: str = os.getenv("uptimekuma_api_key", "") or ""
ENABLED: bool = os.getenv("uptimekuma_enabled", "false").strip().lower() in ("1", "true", "yes")
STATUS_SLUG: str = os.getenv("uptimekuma_status_slug", "") or ""  # optional

_session = requests.Session()

# =============================
# Helpers
# =============================
def _kv(label, value):
    return f"    {label}: {value}"

def _fetch_metrics() -> Optional[str]:
    if not KUMA_URL or not KUMA_API_KEY:
        return None
    url = f"{KUMA_URL}/metrics?token={KUMA_API_KEY}"
    try:
        r = _session.get(url, timeout=8)
        if r.ok and "text/plain" in r.headers.get("content-type",""):
            return r.text
    except Exception:
        pass
    return None

def _parse_metrics(text: str) -> Tuple[int, int, List[str]]:
    """
    Parse Prometheus-style metrics produced by Uptime Kuma.
    We look for lines like: monitor_status{monitor_name="XYZ"} 1
    where 1 = up, 0 = down.
    """
    up = down = 0
    down_names: List[str] = []
    if not text:
        return up, down, down_names
    mon_re = re.compile(r'^monitor_status\{[^}]*monitor_name="(?P<name>[^"]+)"[^}]*\}\s+(?P<val>[01])\s*$', re.M)
    for m in mon_re.finditer(text):
        name = m.group("name")
        val = int(m.group("val"))
        if val == 1:
            up += 1
        else:
            down += 1
            down_names.append(name)
    return up, down, down_names

def _fetch_status_page() -> Optional[Tuple[int, int, List[str]]]:
    """Very light fallback: scrape status page for 'down' markers if provided."""
    if not KUMA_URL or not STATUS_SLUG:
        return None
    try:
        r = _session.get(f"{KUMA_URL}/status/{STATUS_SLUG}", timeout=8)
        if not r.ok:
            return None
        html = r.text
        # Heuristic: count occurrences of status-down badges
        names = re.findall(r'data-name="([^"]+)"[^>]*class="[^"]*status-down', html)
        return (max(0, len(re.findall(r'status-up', html))), len(names), names)
    except Exception:
        return None

# =============================
# Command
# =============================
def handle_kuma_command(cmd: str, *_):
    if not ENABLED:
        return "⚠️ Uptime Kuma is disabled.", None

    c = (cmd or "").strip().lower()
    if not KUMA_URL:
        return "⚠️ Set uptimekuma_url.", None

    # Primary: metrics
    metrics = _fetch_metrics()
    if metrics:
        up, down, names = _parse_metrics(metrics)
        lines = []
        lines.append("🩺 Uptime Kuma")
        lines.append(_kv("Monitors UP", up))
        lines.append(_kv("Monitors DOWN", down))
        if down > 0:
            lines.append("")
            lines.append("⚠️ Down:")
            for n in sorted(names):
                lines.append(f"    • {n}")
        return "\n".join(lines), None

    # Fallback: status page scrape
    alt = _fetch_status_page()
    if alt:
        up, down, names = alt
        lines = []
        lines.append("🩺 Uptime Kuma")
        lines.append(_kv("Monitors UP", up))
        lines.append(_kv("Monitors DOWN", down))
        if names:
            lines.append("")
            lines.append("⚠️ Down:")
            for n in sorted(names):
                lines.append(f"    • {n}")
        return "\n".join(lines), None

    return "⚠️ Could not read Kuma status. Tip: set uptimekuma_api_key for /metrics, or uptimekuma_status_slug for status page.", None
