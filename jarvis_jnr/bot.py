import os, json, time, asyncio, requests, websockets, schedule, datetime, random, re, yaml
from tabulate import tabulate
import copy

# -----------------------------
# Config
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

jarvis_app_id = None

# ANSI color codes
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "white": "\033[97m",
}

def colorize(text, level="info"):
    if "error" in level.lower() or "fail" in level.lower():
        return f"{ANSI['red']}{text}{ANSI['reset']}"
    if "success" in level.lower() or "completed" in level.lower() or "running" in level.lower():
        return f"{ANSI['green']}{text}{ANSI['reset']}"
    if "warn" in level.lower():
        return f"{ANSI['yellow']}{text}{ANSI['reset']}"
    return f"{ANSI['cyan']}{text}{ANSI['reset']}"

# -----------------------------
# Send message
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": message,
        "priority": priority,
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ send_message failed: {e}")
        return False

# -----------------------------
# Purge helpers
# -----------------------------
def purge_app_messages(appid):
    url = f"{GOTIFY_URL}/application/{appid}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        requests.delete(url, headers=headers, timeout=10)
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ purge_app_messages failed: {e}")

def purge_non_jarvis_apps():
    global jarvis_app_id
    if not jarvis_app_id:
        return
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        for app in r.json():
            if app.get("id") != jarvis_app_id:
                purge_app_messages(app.get("id"))
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ purge_non_jarvis_apps failed: {e}")

def purge_old_messages():
    url = f"{GOTIFY_URL}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        messages = r.json().get("messages", [])
        now = datetime.datetime.utcnow().timestamp()
        cutoff = now - (RETENTION_HOURS * 3600)
        for msg in messages:
            ts = msg.get("date")
            if ts:
                msg_time = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if msg_time < cutoff:
                    del_url = f"{GOTIFY_URL}/message/{msg['id']}"
                    requests.delete(del_url, headers=headers, timeout=5)
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ purge_old_messages failed: {e}")

# -----------------------------
# Resolve app_id
# -----------------------------
def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ resolve_app_id failed: {e}")

# -----------------------------
# Beautifier Helpers
# -----------------------------
def format_logs(msg):
    if re.search(r"\d{4}-\d{2}-\d{2}|\[INFO\]|\[ERROR\]|\[WARN\]", msg):
        return f"```log\n{msg}\n```"
    return msg

def dict_to_report(obj, header):
    lines = []
    for k, v in obj.items():
        icon = "🔖"
        key = k.capitalize()
        if isinstance(v, list):
            if all(isinstance(i, dict) for i in v):
                # Make safe copy without ANSI
                plain_list = []
                colored_list = []
                for row in v:
                    plain_row = {}
                    colored_row = {}
                    for kk, vv in row.items():
                        val = str(vv)
                        plain_row[kk] = val
                        # colorize status values
                        if "status" in kk.lower():
                            if "fail" in val.lower() or "error" in val.lower():
                                colored_row[kk] = colorize(val.upper(), "error")
                            elif "success" in val.lower() or "completed" in val.lower() or "running" in val.lower():
                                colored_row[kk] = colorize(val, "success")
                            else:
                                colored_row[kk] = colorize(val, "info")
                        else:
                            colored_row[kk] = val
                    plain_list.append(plain_row)
                    colored_list.append(colored_row)
                # Tabulate using plain data, then replace values with colored ones
                table_plain = tabulate(plain_list, headers="keys", tablefmt="github")
                for pr, cr in zip(plain_list, colored_list):
                    for kk, vv in pr.items():
                        table_plain = table_plain.replace(vv, cr[kk], 1)
                lines.append(f"{icon} {key}:\n{table_plain}")
            else:
                bullets = "\n  • ".join([str(i) for i in v])
                lines.append(f"{icon} {key}:\n  • {bullets}")
        else:
            val = str(v)
            if "status" in k.lower():
                if "fail" in val.lower() or "error" in val.lower():
                    icon, val = "🔴", colorize(val.upper(), "error")
                elif "success" in val.lower() or "completed" in val.lower() or "running" in val.lower():
                    icon, val = "🟢", colorize(val, "success")
                else:
                    icon = "⚪"
            elif "host" in k.lower():
                icon = "🖥"
            elif "size" in k.lower() or "disk" in k.lower():
                icon = "💾"
            elif "time" in k.lower() or "duration" in k.lower():
                icon = "⏱"
            elif "event" in k.lower():
                icon = "🔖"
            elif "error" in k.lower():
                icon = "❌"
                val = colorize(val, "error")
            lines.append(f"{icon} {key}: {val}")
    return f"{ANSI['bold']}{header}{ANSI['reset']}\n╾━━━━━━━━━━━━━━━━╼\n" + "\n".join(lines)

def try_parse_json(msg):
    try:
        obj = json.loads(msg)
        if isinstance(obj, dict):
            return dict_to_report(obj, "📡 JSON EVENT REPORT")
    except Exception:
        return None
    return None

def try_parse_yaml(msg):
    try:
        obj = yaml.safe_load(msg)
        if isinstance(obj, dict):
            return dict_to_report(obj, "📡 YAML EVENT REPORT")
    except Exception:
        return None
    return None

# -----------------------------
# Beautifier Main
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()

    # JSON first
    json_report = try_parse_json(raw)
    if json_report:
        formatted = json_report
    # YAML next
    elif try_parse_yaml(raw):
        formatted = try_parse_yaml(raw)
    elif "error" in lower or "failed" in lower or "exception" in lower:
        formatted = f"⛔ SYSTEM ERROR DETECTED\n╾━━━━━━━━━━━━━━━━╼\n🔴 ERROR: {colorize(format_logs(raw), 'error')}\n\n🛠 Action → Investigate issue"
    elif "warning" in lower or "caution" in lower:
        formatted = f"⚠ SYSTEM WARNING\n╾━━━━━━━━━━━━━━━━╼\n🟡 WARNING: {colorize(format_logs(raw), 'warn')}\n\n🛠 Action → Review conditions"
    elif "success" in lower or "completed" in lower or "done" in lower:
        formatted = f"✅ OPERATION SUCCESSFUL\n╾━━━━━━━━━━━━━━━━╼\n🟢 SUCCESS: {colorize(format_logs(raw), 'success')}\n\n✨ All systems nominal"
    else:
        formatted = f"🛰 SYSTEM MESSAGE\n╾━━━━━━━━━━━━━━━━╼\n{colorize(format_logs(raw), 'info')}"

    closing = random.choice([
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🛡 Guarded by {BOT_NAME}",
        f"📊 Sorted with care — {BOT_NAME}",
        f"🚀 Executed at velocity — {BOT_NAME}",
    ])
    return f"{formatted}\n\n{closing}"

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(10).minutes.do(purge_old_messages)
    if BEAUTIFY_ENABLED:
        schedule.every(5).minutes.do(purge_non_jarvis_apps)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        appid = data.get("appid")
                        message = data.get("message", "")
                        extras = data.get("extras", {})

                        if jarvis_app_id and appid == jarvis_app_id:
                            continue

                        has_image = extras.get("client::display", {}).get("image") if extras else False

                        if BEAUTIFY_ENABLED:
                            final_msg = beautify_message(data.get("title", ""), message)
                            repost_priority = 0 if SILENT_REPOST else 5
                            if send_message(data.get("title", ""), final_msg, priority=repost_priority):
                                if not has_image:
                                    purge_non_jarvis_apps()
                        else:
                            print(f"[{BOT_NAME}] Beautify disabled — keeping original")
                    except Exception as e:
                        print(f"[{BOT_NAME}] ❌ Error processing message: {e}")
        except Exception as e:
            print(f"[{BOT_NAME}] ❌ WebSocket connection failed: {e}")
            await asyncio.sleep(10)

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    resolve_app_id()
    startup_msgs = [
        f"🤖 JARVIS JNR ONLINE\n╾━━━━━━━━━━━━━━━━╼\n👑 Ready to rule notifications\n📡 Listening for events\n⚡ Systems nominal\n\n🧠 Standing by",
        f"🚀 BOOT COMPLETE\n╾━━━━━━━━━━━━━━━━╼\n✅ Initialization finished\n📡 Awaiting input\n⚡ Operational",
    ]
    send_message("Startup", random.choice(startup_msgs), priority=5)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
