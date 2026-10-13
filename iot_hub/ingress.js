'use strict';
// Home Assistant Ingress for IOT Hub (add-on only, no change to the image).
// Listens on INGRESS_PORT, accepts ONLY Home Assistant's Ingress proxy
// (172.30.32.2, per the HA developer docs) and forwards to the hub's own
// WebUI on 127.0.0.1. Users reaching this port are already logged in to
// Home Assistant, so the hub's optional web password is added here.
const http = require('node:http');
const fs = require('node:fs');

const INGRESS_PORT = parseInt(process.env.INGRESS_PORT, 10) || 38099;
const ALLOWED = new Set(['172.30.32.2', '::ffff:172.30.32.2']);

function readJSON(file) {
    try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { return null; }
}

function validPort(v) {
    const n = parseInt(v, 10);
    return Number.isInteger(n) && n >= 1 && n <= 65535 ? n : 0;
}

// Same order the hub uses: add-on option "port", then PORT, then 3000.
function hubPort() {
    const o = readJSON('/data/options.json');
    return validPort(o && o.port) || validPort(process.env.PORT) || 3000;
}

// The hub's web password (Settings > System), read fresh on every request.
function hubPassword() {
    const s = readJSON('/data/settings.json');
    if (s && typeof s['web.password'] === 'string') return s['web.password'];
    return process.env.WEB_PASSWORD || '';
}

const server = http.createServer((req, res) => {
    if (!ALLOWED.has(req.socket.remoteAddress)) {
        res.writeHead(403, { 'Content-Type': 'text/plain' });
        return res.end('forbidden');
    }
    const headers = { ...req.headers };
    delete headers.authorization;
    const pw = hubPassword();
    if (pw) headers.authorization = 'Basic ' + Buffer.from(`admin:${pw}`).toString('base64');
    headers.host = `127.0.0.1:${hubPort()}`;

    const up = http.request({ host: '127.0.0.1', port: hubPort(), method: req.method, path: req.url, headers }, (r) => {
        res.writeHead(r.statusCode || 502, r.headers);
        // Send the headers now: the hub's live stream (api/stream) sends no
        // body until something changes, and without this it would hang.
        res.flushHeaders();
        r.pipe(res);
    });
    up.on('error', (e) => {
        if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'text/plain' });
        res.end(`IOT Hub is not reachable: ${e.message}`);
    });
    req.on('aborted', () => up.destroy());
    res.on('close', () => up.destroy());
    req.pipe(up);
});

server.listen(INGRESS_PORT, () => console.log(`[ingress] listening on ${INGRESS_PORT}, forwarding to 127.0.0.1:${hubPort()}`));
server.on('error', (e) => { console.error(`[ingress] cannot listen on ${INGRESS_PORT}: ${e.message}`); process.exit(1); });
