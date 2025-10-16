#!/usr/bin/env python3
# /app/auth.py
# Minimal, lockout-proof authentication backend for Jarvis Prime

import os
import json
import bcrypt
import jwt
from datetime import datetime, timedelta
from aiohttp import web

# --- Configuration ---
CREDS_DIR = "/share/jarvis_prime/users"
CREDS_PATH = os.path.join(CREDS_DIR, "creds.json")
JWT_SECRET = "jarvis_local_secret"  # changeable later if you want
JWT_EXP_HOURS = 168  # 7 days


# --- Helpers ---

def ensure_creds_file():
    """Ensure creds.json exists; if not, create default admin/admin."""
    if not os.path.exists(CREDS_DIR):
        os.makedirs(CREDS_DIR, exist_ok=True)
    if not os.path.exists(CREDS_PATH):
        default_creds = {
            "username": "admin",
            "password_hash": bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
        }
        with open(CREDS_PATH, "w") as f:
            json.dump(default_creds, f)
        print("[auth] Created default credentials admin/admin")


def read_creds():
    """Read credentials JSON, or recreate defaults if unreadable."""
    ensure_creds_file()
    try:
        with open(CREDS_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[auth] Failed to read creds.json: {e}")
        ensure_creds_file()
        with open(CREDS_PATH, "r") as f:
            return json.load(f)


def write_creds(username, password_plain):
    """Write new username/password."""
    ensure_creds_file()
    hashed = bcrypt.hashpw(password_plain.encode(), bcrypt.gensalt()).decode()
    with open(CREDS_PATH, "w") as f:
        json.dump({"username": username, "password_hash": hashed}, f)
    print(f"[auth] Credentials updated for {username}")


def make_token(username):
    """Generate JWT token."""
    payload = {
        "username": username,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXP_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(request):
    """Validate Authorization Bearer token; return username or None."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1]
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return decoded.get("username")
    except Exception:
        return None


# --- API Routes ---

async def auth_status(request):
    """GET /api/auth/status - tells UI whether setup or login."""
    ensure_creds_file()
    if not os.path.exists(CREDS_PATH):
        return web.json_response({"status": "setup"})
    data = read_creds()
    if data.get("username") == "admin" and bcrypt.checkpw("admin".encode(), data.get("password_hash", "").encode()):
        # Still default creds
        return web.json_response({"status": "setup"})
    return web.json_response({"status": "login"})


async def auth_setup(request):
    """POST /api/auth/setup - create initial username/password."""
    body = await request.json()
    username = body.get("username")
    password = body.get("password")
    confirm = body.get("confirm")

    if not username or not password or password != confirm:
        return web.json_response({"error": "Invalid or mismatched passwords"}, status=400)

    write_creds(username, password)
    token = make_token(username)
    return web.json_response({"ok": True, "token": token})


async def auth_login(request):
    """POST /api/auth/login - verify username/password and issue token."""
    body = await request.json()
    username = body.get("username")
    password = body.get("password")

    data = read_creds()
    if username != data.get("username"):
        return web.json_response({"error": "Invalid username"}, status=401)

    if not bcrypt.checkpw(password.encode(), data.get("password_hash", "").encode()):
        return web.json_response({"error": "Invalid password"}, status=401)

    token = make_token(username)
    return web.json_response({"ok": True, "token": token})


async def auth_validate(request):
    """GET /api/auth/validate - verify token validity."""
    username = verify_token(request)
    if not username:
        return web.json_response({"error": "Invalid or expired token"}, status=401)
    return web.json_response({"ok": True, "username": username})


# --- App Setup ---

def setup_auth_routes(app):
    """Register authentication routes."""
    app.router.add_get("/api/auth/status", auth_status)
    app.router.add_post("/api/auth/setup", auth_setup)
    app.router.add_post("/api/auth/login", auth_login)
    app.router.add_get("/api/auth/validate", auth_validate)
    print("[auth] Authentication endpoints registered.")


# --- Self-test mode ---
if __name__ == "__main__":
    ensure_creds_file()
    web_app = web.Application()
    setup_auth_routes(web_app)
    web.run_app(web_app, port=2581)