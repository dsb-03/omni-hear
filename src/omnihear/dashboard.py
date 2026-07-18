"""Localhost web dashboard for omnihear (stdlib http.server only)."""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config as config_mod

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>omnihear</title>
<style>
:root {
  --surface: #f5f8fc; --card: #ffffff; --border: #dde5ef;
  --text: #0b0b0b; --text-2: #52514e; --accent: #2a78d6;
  --accent-soft: #e8f0fa;
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1a1a19; --card: #232322; --border: #3a3a38;
    --text: #ffffff; --text-2: #c3c2b7; --accent: #3987e5;
    --accent-soft: #22334a;
  }
}
:root[data-theme="light"] {
  --surface: #f5f8fc; --card: #ffffff; --border: #dde5ef;
  --text: #0b0b0b; --text-2: #52514e; --accent: #2a78d6;
  --accent-soft: #e8f0fa;
}
:root[data-theme="dark"] {
  --surface: #1a1a19; --card: #232322; --border: #3a3a38;
  --text: #ffffff; --text-2: #c3c2b7; --accent: #3987e5;
  --accent-soft: #22334a;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
  font: 15px/1.5 system-ui, sans-serif; }
.wrap { max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }
header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
h1 { font-size: 20px; margin: 0; color: var(--accent); }
h2 { font-size: 14px; margin: 26px 0 10px; color: var(--text-2);
  text-transform: uppercase; letter-spacing: .05em; }
nav { display: flex; gap: 4px; }
nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none;
  color: var(--text-2); font-size: 14px; }
nav a.active { background: var(--accent-soft); color: var(--accent);
  font-weight: 600; }
#theme-toggle { margin-left: auto; }
#status { color: var(--text-2); font-size: 13px; margin-top: 4px; }
.screen { display: none; }
.screen.active { display: block; }
td.num, th.num { text-align: right; white-space: nowrap;
  font-variant-numeric: tabular-nums; }
input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr));
  gap: 10px; }
.tile { background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; }
.tile .v { font-size: 22px; font-weight: 600; }
.tile .l { font-size: 12px; color: var(--text-2); }
.card { background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
th { color: var(--text-2); font-weight: 500; }
input, select, button { font: inherit; color: var(--text); background: var(--card);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; }
button { cursor: pointer; }
button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.cfg-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr));
  gap: 10px 16px; }
.cfg-grid label { display: block; font-size: 12px; color: var(--text-2); }
.cfg-grid input, .cfg-grid select { width: 100%; margin-top: 2px; }
#cfg-msg { font-size: 13px; margin-left: 10px; color: var(--text-2); }
.bar { fill: var(--accent); }
.axis { font-size: 11px; fill: var(--text-2); }
svg { display: block; width: 100%; height: auto; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>omnihear</h1>
    <nav>
      <a href="#/" id="nav-history">History</a>
      <a href="#/settings" id="nav-settings">Settings</a>
    </nav>
    <button id="theme-toggle" type="button" title="Toggle light/dark">◐ theme</button>
  </header>
  <div id="status">loading…</div>

  <section class="screen" id="screen-history">
    <h2>Usage</h2>
    <div class="tiles" id="tiles"></div>
    <h2>Words per day (last 30 days)</h2>
    <div class="card"><div id="chart"></div></div>

    <h2>History</h2>
    <div class="card">
      <input id="q" placeholder="Search transcriptions…"
             style="width:100%;margin-bottom:10px">
      <table><thead><tr><th>Time</th><th>Text</th><th class="num">Audio</th>
      <th class="num">Latency</th><th class="num">CPU</th><th class="num">Mem</th></tr></thead>
      <tbody id="hist"></tbody></table>
    </div>
  </section>

  <section class="screen" id="screen-settings">
    <h2>Config</h2>
    <div class="card">
      <form id="cfg" class="cfg-grid"></form>
      <div style="margin-top:12px">
        <button class="primary" id="save">Save config</button>
        <button id="restart" type="button">Restart service</button>
        <span id="cfg-msg"></span>
      </div>
    </div>
    <p style="font-size:13px;color:var(--text-2)">Changes are written to
    <code>~/.config/omnihear/config.toml</code> and take effect after a restart.</p>
  </section>
</div>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api = (p, opts) => fetch(p, opts).then(r => r.json());

// --- theme toggle (persisted; default follows prefers-color-scheme) ---
const savedTheme = localStorage.getItem('omnihear-theme');
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
$('#theme-toggle').addEventListener('click', () => {
  const cur = document.documentElement.dataset.theme ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('omnihear-theme', next);
});

// --- hash routing: #/ (History, home) and #/settings ---
function route() {
  const settings = location.hash === '#/settings';
  $('#screen-history').classList.toggle('active', !settings);
  $('#screen-settings').classList.toggle('active', settings);
  $('#nav-history').classList.toggle('active', !settings);
  $('#nav-settings').classList.toggle('active', settings);
}
window.addEventListener('hashchange', route);
route();

function fmtSec(s) { return s >= 60 ? (s/60).toFixed(1)+' min' : s.toFixed(1)+' s'; }

async function loadStatus() {
  const s = await api('/api/status');
  $('#status').textContent =
    `model ${s.model} · hotkey ${s.hotkey} · ` +
    (s.model_loaded ? 'model loaded in RAM' : 'model unloaded (loads on first press)');
}

async function loadStats() {
  const st = await api('/api/stats');
  const t = st.totals;
  $('#tiles').innerHTML = [
    [t.n, 'transcriptions'],
    [t.words, 'words'],
    [fmtSec(t.audio_seconds), 'dictated audio'],
    [Math.round(t.avg_transcribe_ms) + ' ms', 'avg latency'],
    [t.avg_cpu_percent ? t.avg_cpu_percent.toFixed(0) + '%' : '\\u2013', 'avg CPU'],
    [t.avg_memory_mb ? Math.round(t.avg_memory_mb) + ' MB' : '\\u2013', 'avg memory'],
  ].map(([v,l]) => `<div class="tile"><div class="v">${esc(v)}</div>` +
                   `<div class="l">${esc(l)}</div></div>`).join('');
  drawChart(st.per_day);
}

function drawChart(days) {
  if (!days.length) { $('#chart').textContent = 'No data yet.'; return; }
  const W = 860, H = 200, padL = 36, padB = 22, padT = 8;
  const max = Math.max(...days.map(d => d.words), 1);
  const bw = (W - padL) / days.length;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Words per day">`;
  // recessive gridlines + y labels
  for (let i = 0; i <= 2; i++) {
    const val = Math.round(max * i / 2);
    const y = H - padB - (H - padB - padT) * i / 2;
    svg += `<line x1="${padL}" x2="${W}" y1="${y}" y2="${y}" stroke="var(--border)"/>` +
           `<text class="axis" x="${padL-6}" y="${y+4}" text-anchor="end">${val}</text>`;
  }
  days.forEach((d, i) => {
    const h = Math.max(2, (H - padB - padT) * d.words / max);
    const x = padL + i * bw + 1, y = H - padB - h;
    const w = Math.max(2, bw - 2);
    svg += `<path class="bar" d="M${x},${y+4} q0,-4 4,-4 h${w-8} q4,0 4,4 v${h-4} h${-w} z">` +
           `<title>${esc(d.day)}: ${d.words} words, ${d.n} transcriptions</title></path>`;
    if (days.length <= 15 || i % Math.ceil(days.length/10) === 0)
      svg += `<text class="axis" x="${x + w/2}" y="${H-6}" text-anchor="middle">` +
             `${esc(d.day.slice(5))}</text>`;
  });
  $('#chart').innerHTML = svg + '</svg>';
}

async function loadHistory() {
  const q = $('#q').value;
  const rows = await api('/api/history?limit=100&q=' + encodeURIComponent(q));
  $('#hist').innerHTML = rows.map(r =>
    `<tr><td style="white-space:nowrap">${esc(r.ts.replace('T',' '))}</td>` +
    `<td>${esc(r.text)}</td>` +
    `<td class="num">${r.audio_seconds ? r.audio_seconds.toFixed(1)+'s' : ''}</td>` +
    `<td class="num">${r.transcribe_ms ? Math.round(r.transcribe_ms)+'ms' : ''}</td>` +
    `<td class="num">${r.cpu_percent != null ? r.cpu_percent.toFixed(0)+'%' : '\\u2013'}</td>` +
    `<td class="num">${r.memory_mb != null ? Math.round(r.memory_mb)+' MB' : '\\u2013'}</td></tr>`
  ).join('') || '<tr><td colspan="6">No transcriptions.</td></tr>';
}

async function loadConfig() {
  const cfg = await api('/api/config');
  const bools = ['dashboard','notify','beep','history'];
  $('#cfg').innerHTML = Object.entries(cfg).map(([k,v]) => {
    if (bools.includes(k))
      return `<label>${k}<select name="${k}">` +
        `<option value="true"${v?' selected':''}>true</option>` +
        `<option value="false"${v?'':' selected'}>false</option></select></label>`;
    if (k === 'device')
      return `<label>${k}<select name="${k}">` +
        `<option${v==='cpu'?' selected':''}>cpu</option>` +
        `<option${v==='cuda'?' selected':''}>cuda</option></select></label>`;
    if (k === 'type_method')
      return `<label>${k}<select name="${k}">` +
        `<option${v==='pynput'?' selected':''}>pynput</option>` +
        `<option${v==='xdotool'?' selected':''}>xdotool</option></select></label>`;
    return `<label>${k}<input name="${k}" value="${esc(v)}"></label>`;
  }).join('');
}

$('#save').addEventListener('click', async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData($('#cfg')).entries());
  const res = await api('/api/config',
    {method:'POST', headers:{'Content-Type':'application/json'},
     body: JSON.stringify(data)});
  $('#cfg-msg').textContent = res.errors && res.errors.length
    ? 'Errors: ' + res.errors.join('; ') : res.message;
});

$('#restart').addEventListener('click', async () => {
  const res = await api('/api/restart', {method:'POST'});
  $('#cfg-msg').textContent = res.message;
});

let t; $('#q').addEventListener('input',
  () => { clearTimeout(t); t = setTimeout(loadHistory, 250); });

loadStatus(); loadStats(); loadHistory(); loadConfig();
setInterval(() => { loadStatus(); loadStats(); loadHistory(); }, 15000);
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    # set on the server: server.db, server.effective_config, server.status_fn

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        db = self.server.db
        if url.path in ("/", "/settings"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/api/history":
            if db is None:
                self._send(200, [])
                return
            try:
                rows = db.search(
                    q=qs.get("q", [""])[0],
                    limit=int(qs.get("limit", ["50"])[0]),
                    offset=int(qs.get("offset", ["0"])[0]),
                )
            except ValueError:
                self._send(400, {"error": "bad limit/offset"})
                return
            self._send(200, rows)
        elif url.path == "/api/stats":
            if db is None:
                self._send(200, {"totals": {"n": 0, "words": 0,
                                            "audio_seconds": 0,
                                            "avg_transcribe_ms": 0,
                                            "avg_cpu_percent": 0,
                                            "avg_memory_mb": 0},
                                 "per_day": []})
            else:
                self._send(200, db.stats())
        elif url.path == "/api/config":
            self._send(200, config_mod.load_config())
        elif url.path == "/api/status":
            self._send(200, self.server.status_fn())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                updates = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(updates, dict):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                self._send(400, {"error": "invalid JSON body"})
                return
            clean, errors = config_mod.validate_updates(updates)
            if clean:
                cfg = config_mod.load_config()
                cfg.update(clean)
                config_mod.save_config(cfg)
            msg = ("Saved. Restart omnihear for changes to take effect."
                   if clean else "Nothing saved.")
            self._send(200, {"saved": sorted(clean), "errors": errors,
                             "message": msg})
        elif url.path == "/api/restart":
            if os.environ.get("INVOCATION_ID"):
                # Running under systemd: ask it to restart us.
                threading.Timer(0.5, lambda: subprocess.Popen(
                    ["systemctl", "--user", "restart", "omnihear"]
                )).start()
                self._send(200, {"message": "Restarting via systemd…"})
            else:
                self._send(200, {"message":
                                 "Not running under systemd; restart omnihear manually."})
        else:
            self._send(404, {"error": "not found"})


def start_dashboard(db, status_fn, port: int = 4738):
    """Start the dashboard server on 127.0.0.1 in a daemon thread.

    Returns the server, or None if the port could not be bound.
    """
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    except OSError as e:
        print(f"omnihear: dashboard disabled (port {port}: {e})")
        return None
    server.daemon_threads = True
    server.db = db
    server.status_fn = status_fn
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"omnihear: dashboard at http://127.0.0.1:{port}")
    return server
