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
h2 { font-size: 16px; font-weight: 600; margin: 26px 0 10px; color: var(--text); }
nav { display: flex; gap: 4px; }
nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none;
  color: var(--text-2); font-size: 14px; }
nav a.active { background: var(--accent-soft); color: var(--accent);
  font-weight: 600; }
#theme-toggle { margin-left: auto; display: flex; align-items: center;
  padding: 7px; line-height: 0; }
#theme-toggle svg { width: 18px; height: 18px; stroke: var(--text-2);
  fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
#hotkey-capture { width: 100%; margin-top: 2px; text-align: left; }
#hotkey-capture.capturing { outline: 2px solid var(--accent);
  outline-offset: -1px; color: var(--accent); }
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
.cfg-section { margin-bottom: 18px; }
.cfg-section h3 { font-size: 15px; font-weight: 600; margin: 0 0 8px;
  color: var(--accent); }
.cfg-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px,1fr));
  gap: 10px 16px; }
.cfg-grid label { display: block; font-size: 12px; color: var(--text-2); }
.cfg-grid input:not([type=checkbox]), .cfg-grid select { width: 100%; margin-top: 2px; }
label.check { display: flex !important; align-items: center; gap: 8px;
  font-size: 14px !important; color: var(--text) !important; padding-top: 14px; }
label.check input { width: 16px !important; height: 16px; accent-color: var(--accent); }
#cfg-msg { font-size: 13px; margin-left: 10px; color: var(--text-2);
  transition: opacity .6s; }
#cfg-msg.ok { color: #0ca30c; font-weight: 600; }
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
    <button id="theme-toggle" type="button" aria-label="Toggle light/dark theme">
      <svg id="icon-moon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>
      </svg>
      <svg id="icon-sun" viewBox="0 0 24 24" aria-hidden="true" style="display:none">
        <circle cx="12" cy="12" r="4"/>
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>
      </svg>
    </button>
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
      <form id="cfg"></form>
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
const effectiveTheme = () => document.documentElement.dataset.theme ||
  (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
function updateThemeIcon() {
  const dark = effectiveTheme() === 'dark';
  // sun shown in dark mode (click = go light), moon in light mode
  $('#icon-sun').style.display = dark ? 'block' : 'none';
  $('#icon-moon').style.display = dark ? 'none' : 'block';
}
const savedTheme = localStorage.getItem('omnihear-theme');
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
updateThemeIcon();
$('#theme-toggle').addEventListener('click', () => {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('omnihear-theme', next);
  updateThemeIcon();
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
    `model ${s.model} · hotkey ${s.hotkey_display || keyDisplay(s.hotkey)} · ` +
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

// --- settings form ---
const KEY_NAMES = __KEY_NAMES__;    // canonical -> display name
const MODELS = __MODELS__;          // official faster-whisper model list
const LANGUAGE_NAMES = __LANGS__;   // official code -> English name (100)
const LANGUAGES = [['auto','Auto-detect']].concat(
  Object.entries(LANGUAGE_NAMES).map(([c,n]) => [c, `${n} (${c})`]));
const COMPUTE_TYPES = ['int8','float16','int8_float16','float32'];
const BOOLS = ['dashboard','notify','beep','history','verbose'];
const NUMBERS = {
  sample_rate: {min: 8000, step: 1000},
  beam_size: {min: 1, step: 1},
  min_duration: {min: 0, step: 0.1},
  dashboard_port: {min: 1, max: 65535, step: 1},
  idle_unload_minutes: {min: 0, step: 1},
};
const SECTIONS = [
  ['Transcription', ['model','language','device','compute_type','beam_size']],
  ['Input', ['hotkey','sample_rate','min_duration','type_method']],
  ['Dashboard', ['dashboard','dashboard_port','history']],
  ['Behavior', ['notify','beep','idle_unload_minutes','verbose']],
];
const pretty = k => k.replace(/_/g, ' ');
const keyDisplay = hk => String(hk).split('+').filter(Boolean)
  .map(p => KEY_NAMES[p] || p.toUpperCase()).join(' + ');
const selectOf = (k, opts, v) => `<label>${pretty(k)}<select name="${k}">` +
  opts.map(o => `<option value="${esc(o)}"${o===v?' selected':''}>${esc(o)}</option>`)
      .join('') + `</select></label>`;

// select with a "custom..." option that reveals a free-text input
function customSelect(k, opts, v, placeholder) {
  const known = opts.some(o => o[0] === v);
  return `<label>${pretty(k)}<select name="${k}" id="${k}-sel" data-custom="1">` +
    opts.map(([val, lab]) =>
      `<option value="${esc(val)}"${val===v?' selected':''}>${esc(lab)}</option>`).join('') +
    `<option value="__custom__"${known?'':' selected'}>custom\\u2026</option>` +
    `</select><input id="${k}-custom" placeholder="${placeholder}"` +
    ` value="${known?'':esc(v)}" style="margin-top:6px;` +
    `display:${known?'none':'block'}"></label>`;
}

function fieldHtml(k, v) {
  if (BOOLS.includes(k))
    return `<label class="check"><input type="checkbox" name="${k}"` +
           `${v?' checked':''}>${pretty(k)}</label>`;
  if (k === 'device') return selectOf(k, ['cpu','cuda'], v);
  if (k === 'type_method') return selectOf(k, ['pynput','xdotool'], v);
  if (k === 'compute_type') return selectOf(k, COMPUTE_TYPES, v);
  if (k === 'model')
    return customSelect(k,
      MODELS.map(m => [m, m === 'base.en' ? 'base.en (default)' : m]),
      v, 'model name or HF repo id');
  if (k === 'language')
    return `<label>${pretty(k)}<select name="language">` +
      LANGUAGES.map(([c, lab]) =>
        `<option value="${c}"${c===v?' selected':''}>${esc(lab)}</option>`).join('') +
      `</select></label>`;
  if (k === 'hotkey')
    return `<label>hotkey (push to talk)` +
      `<button type="button" id="hotkey-capture" data-value="${esc(v)}">` +
      `${esc(keyDisplay(v))}</button></label>`;
  if (k in NUMBERS) {
    const n = NUMBERS[k];
    return `<label>${pretty(k)}<input type="number" name="${k}" value="${esc(v)}"` +
      ` min="${n.min}"${n.max?` max="${n.max}"`:''} step="${n.step}"></label>`;
  }
  return `<label>${pretty(k)}<input name="${k}" value="${esc(v)}"></label>`;
}

// --- hotkey capture: map KeyboardEvent.code -> canonical pynput names ---
const CODE_MAP = {
  ControlRight:'ctrl_r', ControlLeft:'ctrl_l', AltLeft:'alt_l', AltRight:'alt_r',
  ShiftLeft:'shift_l', ShiftRight:'shift_r', Space:'space', CapsLock:'caps_lock',
  Pause:'pause', ScrollLock:'scroll_lock',
};
for (let i = 1; i <= 12; i++) CODE_MAP['F'+i] = 'f'+i;
function codeToName(code) {
  if (CODE_MAP[code]) return CODE_MAP[code];
  let m = code.match(/^Key([A-Z])$/);   if (m) return m[1].toLowerCase();
  m = code.match(/^Digit([0-9])$/);     if (m) return m[1];
  return null;
}

let capture = null;  // {seen:Set, active:Set, prev:string} while capturing

function setupHotkeyCapture() {
  const btn = $('#hotkey-capture');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (capture) return;
    capture = {seen: new Set(), active: new Set(), prev: btn.dataset.value};
    btn.classList.add('capturing');
    btn.textContent = 'Press keys\\u2026 (Esc to cancel)';
  });
}

function endCapture(canceled) {
  const btn = $('#hotkey-capture');
  if (!btn || !capture) return;
  if (canceled || !capture.seen.size) btn.dataset.value = capture.prev;
  else btn.dataset.value = [...capture.seen].join('+');
  btn.textContent = keyDisplay(btn.dataset.value);
  btn.classList.remove('capturing');
  capture = null;
}

document.addEventListener('keydown', e => {
  if (!capture) return;
  e.preventDefault();
  if (e.key === 'Escape') { endCapture(true); return; }
  if (e.repeat) return;
  const name = codeToName(e.code);
  if (!name) return;
  capture.seen.add(name);
  capture.active.add(name);
  const btn = $('#hotkey-capture');
  btn.textContent = keyDisplay([...capture.seen].join('+'));
});
document.addEventListener('keyup', e => {
  if (!capture) return;
  e.preventDefault();
  const name = codeToName(e.code);
  if (name) capture.active.delete(name);
  if (capture.seen.size && !capture.active.size) endCapture(false);
});

async function loadConfig() {
  const cfg = await api('/api/config');
  $('#cfg').innerHTML = SECTIONS.map(([title, keys]) =>
    `<div class="cfg-section"><h3>${title}</h3><div class="cfg-grid">` +
    keys.filter(k => k in cfg).map(k => fieldHtml(k, cfg[k])).join('') +
    `</div></div>`).join('');
  setupHotkeyCapture();
  document.querySelectorAll('select[data-custom]').forEach(sel => {
    sel.addEventListener('change', () => {
      $('#' + sel.name + '-custom').style.display =
        sel.value === '__custom__' ? 'block' : 'none';
    });
  });
}

function showMsg(text, ok) {
  const m = $('#cfg-msg');
  m.textContent = text;
  m.classList.toggle('ok', !!ok);
  m.style.opacity = 1;
  if (ok) setTimeout(() => { m.style.opacity = 0; }, 2500);
}

async function saveConfig() {
  const form = $('#cfg');
  const data = {};
  for (const [, keys] of SECTIONS) for (const k of keys) {
    if (k === 'hotkey') { data[k] = $('#hotkey-capture').dataset.value; continue; }
    const el = form.elements[k];
    if (!el) continue;
    if (BOOLS.includes(k)) data[k] = el.checked;
    else if (el.dataset && el.dataset.custom)
      data[k] = el.value === '__custom__' ? $('#' + k + '-custom').value : el.value;
    else data[k] = el.value;
  }
  const res = await api('/api/config',
    {method:'POST', headers:{'Content-Type':'application/json'},
     body: JSON.stringify(data)});
  if (res.errors && res.errors.length)
    showMsg('Errors: ' + res.errors.join('; '), false);
  else showMsg('\\u2713 ' + res.message, true);
}
$('#cfg').addEventListener('submit', e => { e.preventDefault(); saveConfig(); });
$('#save').addEventListener('click', e => { e.preventDefault(); saveConfig(); });

$('#restart').addEventListener('click', async () => {
  const res = await api('/api/restart', {method:'POST'});
  showMsg(res.message, false);
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
            page = (PAGE
                    .replace("__KEY_NAMES__",
                             json.dumps(config_mod.KEY_DISPLAY_NAMES))
                    .replace("__MODELS__",
                             json.dumps(config_mod.MODEL_NAMES))
                    .replace("__LANGS__",
                             json.dumps(config_mod.LANGUAGE_NAMES)))
            self._send(200, page.encode(), "text/html; charset=utf-8")
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
