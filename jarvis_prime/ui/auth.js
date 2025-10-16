// /share/jarvis_prime/ui/js/auth.js
// Handles login/setup overlay and JWT auth for Jarvis Prime
// Works with /api/auth/status, /api/auth/setup, /api/auth/login, /api/auth/validate

const Auth = {
  tokenKey: "jarvis_auth_token",
  overlayId: "auth-overlay",

  async init() {
    try {
      const token = this.getToken();
      if (token) {
        const ok = await this.validateToken(token);
        if (ok) return; // already logged in
      }
      await this.showAuthFlow();
    } catch (e) {
      console.error("[auth] init failed:", e);
      await this.showAuthFlow();
    }
  },

  getToken() {
    return localStorage.getItem(this.tokenKey);
  },

  setToken(token) {
    localStorage.setItem(this.tokenKey, token);
  },

  clearToken() {
    localStorage.removeItem(this.tokenKey);
  },

  async validateToken(token) {
    try {
      const res = await fetch("/api/auth/validate", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return false;
      const data = await res.json();
      return !!data.valid;
    } catch {
      return false;
    }
  },

  async checkStatus() {
    const res = await fetch("/api/auth/status");
    if (!res.ok) throw new Error("Failed to reach auth API");
    return res.json();
  },

  async showAuthFlow() {
    const { status } = await this.checkStatus();
    this.buildOverlay(status === "setup");
  },

  buildOverlay(isSetup) {
    let overlay = document.getElementById(this.overlayId);
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = this.overlayId;
      overlay.classList.add("active"); // ✅ make visible per CSS
      overlay.style = `
        position: fixed; inset: 0;
        background: rgba(0,0,0,0.85);
        display: flex; align-items: center; justify-content: center;
        z-index: 99999; color: #fff; font-family: sans-serif;
      `;
      document.body.appendChild(overlay);
    } else {
      overlay.classList.add("active"); // ✅ ensure visible even if already exists
    }

    overlay.innerHTML = `
      <div style="background:#111; padding:24px; border-radius:12px; width:90%; max-width:360px; text-align:center; box-shadow:0 0 20px rgba(0,0,0,0.5);">
        <h2 style="margin-bottom:16px;">${isSetup ? "Initial Setup" : "Login"}</h2>
        <div style="display:flex; flex-direction:column; gap:8px; text-align:left;">
          <label>Username</label>
          <input id="auth-username" type="text" style="padding:8px; border-radius:6px; border:none;">
          <label>Password</label>
          <input id="auth-password" type="password" style="padding:8px; border-radius:6px; border:none;">
          ${
            isSetup
              ? `<label>Confirm Password</label><input id="auth-confirm" type="password" style="padding:8px; border-radius:6px; border:none;">`
              : ""
          }
          <button id="auth-submit" style="margin-top:12px; padding:10px; background:#0af; border:none; border-radius:8px; color:#fff; font-weight:bold;">${isSetup ? "Save" : "Login"}</button>
        </div>
        <div id="auth-error" style="color:#f55; margin-top:10px; font-size:0.9em;"></div>
      </div>
    `;

    document.getElementById("auth-submit").onclick = async () => {
      const username = document.getElementById("auth-username").value.trim();
      const password = document.getElementById("auth-password").value;
      const confirm = isSetup ? document.getElementById("auth-confirm").value : null;
      if (!username || !password || (isSetup && password !== confirm)) {
        this.showError("Please fill fields correctly");
        return;
      }

      try {
        const endpoint = isSetup ? "/api/auth/setup" : "/api/auth/login";
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password, confirm }),
        });
        const data = await res.json();
        if (!res.ok || !data.token) throw new Error(data.error || "Failed");
        this.setToken(data.token);
        overlay.classList.remove("active"); // ✅ hide again
        overlay.remove();
        location.reload();
      } catch (e) {
        this.showError(e.message || "Login failed");
      }
    };
  },

  showError(msg) {
    const el = document.getElementById("auth-error");
    if (el) el.textContent = msg;
  },
};

// Automatically attach token to fetch requests
const _origFetch = window.fetch;
window.fetch = async (url, opts = {}) => {
  const token = Auth.getToken();
  if (token) {
    opts.headers = opts.headers || {};
    if (!opts.headers.Authorization) {
      opts.headers.Authorization = `Bearer ${token}`;
    }
  }
  return _origFetch(url, opts);
};

// Initialize when DOM ready
document.addEventListener("DOMContentLoaded", () => Auth.init());