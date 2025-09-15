#!/usr/bin/env python3
# /app/ha_notify.py
#
# Helper for forwarding Jarvis messages into Home Assistant notify.*
# Uses the same ha_url and ha_token already in options.json.
# Controlled via "ha_notify_service" key in options.json.

import requests
import json

def push_to_ha_notify(title: str, message: str, options: dict) -> bool:
    """
    Push a Jarvis message into Home Assistant mobile_app notify service.

    Args:
        title (str): Notification title
        message (str): Notification body
        options (dict): Loaded config (must include ha_url, ha_token, ha_notify_service)

    Returns:
        bool: True if sent successfully, False otherwise
    """
    ha_url = options.get("ha_url")
    ha_token = options.get("ha_token")
    ha_service = options.get("ha_notify_service")

    if not ha_url or not ha_token or not ha_service:
        print("[ha_notify] Skipped (missing ha_url, ha_token, or ha_notify_service in config).")
        return False

    url = f"{ha_url}/api/services/{ha_service}"
    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json"
    }
    payload = {"title": title, "message": message}

    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        if r.status_code != 200:
            print(f"[ha_notify] Failed {r.status_code}: {r.text}")
            return False
        print(f"[ha_notify] Sent to {ha_service}: {title} -> {message}")
        return True
    except Exception as e:
        print(f"[ha_notify] Error: {e}")
        return False