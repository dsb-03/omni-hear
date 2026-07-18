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
<title>Omnihear Dashboard</title>
<!-- Favicon: Inline SVG Logo -->
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3csvg width='200' height='200' viewBox='0 0 200 200' fill='none' xmlns='http://www.w3.org/2000/svg'%3e%3cdefs%3e%3clinearGradient id='waveGradient' x1='40' y1='100' x2='160' y2='100' gradientUnits='userSpaceOnUse'%3e%3cstop offset='0%25' stop-color='%233498db'/%3e%3cstop offset='100%25' stop-color='%232ecc71'/%3e%3c/linearGradient%3e%3c/defs%3e%3crect x='20' y='20' width='160' height='160' rx='25' fill='%232c3e50'/%3e%3cpath d='M50 100 C 60 80, 70 80, 80 100 C 90 120, 100 120, 110 100 C 120 70, 130 70, 140 100' stroke='url(%23waveGradient)' stroke-width='12' stroke-linecap='round' fill='none'/%3e%3ccircle cx='50' cy='100' r='6' fill='%233498db'/%3e%3ccircle cx='150' cy='100' r='6' fill='%232ecc71'/%3e%3c/svg%3e">
<!-- Google Fonts -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --surface: #f1f5f9;
  --card: rgba(255, 255, 255, 0.75);
  --card-solid: #ffffff;
  --border: rgba(226, 232, 240, 0.8);
  --text: #0f172a;
  --text-muted: #64748b;
  --accent: #2563eb;
  --accent-soft: rgba(37, 99, 235, 0.08);
  --accent-gradient: linear-gradient(135deg, #3b82f6, #1d4ed8);
  --shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.04);
  --glass-blur: backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  --radius: 12px;
}
:root[data-theme="dark"] {
  --surface: #0b0f19;
  --card: rgba(17, 24, 39, 0.7);
  --card-solid: #111827;
  --border: rgba(31, 41, 55, 0.6);
  --text: #f8fafc;
  --text-muted: #94a3b8;
  --accent: #60a5fa;
  --accent-soft: rgba(96, 165, 250, 0.12);
  --accent-gradient: linear-gradient(135deg, #60a5fa, #3b82f6);
  --shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.3);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface: #0b0f19;
    --card: rgba(17, 24, 39, 0.7);
    --card-solid: #111827;
    --border: rgba(31, 41, 55, 0.6);
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --accent: #60a5fa;
    --accent-soft: rgba(96, 165, 250, 0.12);
    --accent-gradient: linear-gradient(135deg, #60a5fa, #3b82f6);
    --shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.3);
  }
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--surface);
  color: var(--text);
  font-family: 'Inter', sans-serif;
  line-height: 1.6;
  min-height: 100vh;
  transition: background 0.3s ease, color 0.3s ease;
}

.wrap {
  max-width: 1000px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}

/* Glassmorphic Header */
header {
  display: flex;
  align-items: center;
  gap: 20px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 24px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  var(--glass-blur);
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-name {
  font-family: 'Outfit', sans-serif;
  font-size: 22px;
  font-weight: 800;
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.5px;
}

nav {
  display: flex;
  gap: 6px;
  margin-left: 12px;
}
nav a {
  padding: 8px 16px;
  border-radius: 8px;
  text-decoration: none;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s ease;
}
nav a:hover {
  color: var(--text);
  background: rgba(255, 255, 255, 0.1);
}
nav a.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

#theme-toggle {
  margin-left: auto;
  background: none;
  border: 1px solid var(--border);
  border-radius: 50%;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--text-muted);
}
#theme-toggle:hover {
  color: var(--text);
  border-color: var(--text);
  transform: scale(1.05);
}
#theme-toggle svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Status Banner */
.status-bar {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 20px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  font-weight: 500;
}
.indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  position: relative;
}
.indicator.pulse-active {
  background: #ef4444;
  box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7);
  animation: pulse-ring 1.2s infinite;
}
.indicator.pulse-loaded {
  background: #10b981;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4);
  animation: pulse-ring-green 2s infinite;
}
.indicator.pulse-idle {
  background: #f59e0b;
}
@keyframes pulse-ring {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}
@keyframes pulse-ring-green {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

.status-hotkey-container {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.hotkey-badge {
  background: var(--accent-soft);
  color: var(--accent);
  padding: 3px 8px;
  border-radius: 6px;
  font-family: monospace;
  font-weight: 600;
  border: 1px solid rgba(96, 165, 250, 0.2);
}

/* Base Layout Screens */
.screen { display: none; }
.screen.active { display: block; animation: fadeIn 0.3s ease; }
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

h2 {
  font-family: 'Outfit', sans-serif;
  font-size: 18px;
  font-weight: 700;
  margin: 28px 0 12px;
  color: var(--text);
  letter-spacing: -0.2px;
}

/* Dashboard Cards and Grid */
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}
.tile {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: transform 0.2s ease, border-color 0.2s ease;
}
.tile:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
}
.tile .v {
  font-size: 24px;
  font-weight: 700;
  font-family: 'Outfit', sans-serif;
  color: var(--text);
}
.tile .l {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 4px;
}

.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
  overflow: hidden;
}

/* Charts */
#chart {
  position: relative;
  width: 100%;
}
.bar {
  fill: var(--accent);
  opacity: 0.85;
  transition: opacity 0.2s ease, fill 0.2s ease;
}
.bar:hover {
  opacity: 1;
  fill: url(#barGradientHover);
  filter: drop-shadow(0 4px 6px rgba(0,0,0,0.15));
  cursor: pointer;
}
.axis {
  font-family: 'Inter', sans-serif;
  font-size: 11px;
  fill: var(--text-muted);
}
.grid-line {
  stroke: var(--border);
  stroke-width: 1;
}

/* Search bar & Table */
.search-wrapper {
  position: relative;
  margin-bottom: 16px;
}
.search-wrapper input {
  width: 100%;
  padding: 10px 14px 10px 38px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card-solid);
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  transition: all 0.2s ease;
}
.search-wrapper input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.search-wrapper::before {
  content: "";
  position: absolute;
  left: 14px;
  top: 13px;
  width: 14px;
  height: 14px;
  border: 2px solid var(--text-muted);
  border-radius: 50%;
  pointer-events: none;
}
.search-wrapper::after {
  content: "";
  position: absolute;
  left: 25px;
  top: 22px;
  width: 6px;
  height: 2px;
  background: var(--text-muted);
  transform: rotate(45deg);
  pointer-events: none;
}

.table-container {
  overflow-x: auto;
}
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
  text-align: left;
}
th {
  color: var(--text-muted);
  font-weight: 600;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.5px;
  padding: 10px 12px;
  border-bottom: 2px solid var(--border);
}
td {
  padding: 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  font-weight: 500;
}
tr:hover td {
  background: var(--accent-soft);
}
td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* Config & Settings styling */
.cfg-section {
  margin-bottom: 24px;
}
.cfg-section h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 12px;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.cfg-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}
.cfg-grid label {
  display: flex;
  flex-direction: column;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
  text-transform: capitalize;
}
.cfg-grid label[title] { cursor: help; }
.cfg-grid label select,
.cfg-grid label input:not([type=checkbox]) {
  margin-top: 6px;
  width: 100%;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card-solid);
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  transition: all 0.2s ease;
}
.cfg-grid label select:focus,
.cfg-grid label input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

/* Custom Checkbox Toggle Switch */
label.check {
  flex-direction: row !important;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  font-size: 14px !important;
  color: var(--text) !important;
  cursor: pointer;
  user-select: none;
  font-weight: 500 !important;
}
label.check input {
  display: none;
}
.switch-slider {
  width: 44px;
  height: 24px;
  background-color: var(--border);
  border-radius: 34px;
  position: relative;
  transition: background-color 0.2s ease;
}
.switch-slider::before {
  content: "";
  position: absolute;
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  border-radius: 50%;
  transition: transform 0.2s ease;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
label.check input:checked ~ .switch-slider {
  background-color: var(--accent);
}
label.check input:checked ~ .switch-slider::before {
  transform: translateX(20px);
}

/* Hotkey Capture button */
#hotkey-capture {
  width: 100%;
  margin-top: 6px;
  text-align: center;
  padding: 10px;
  font-weight: 600;
  border: 1px dashed var(--border);
  background: var(--card-solid);
  color: var(--text);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}
#hotkey-capture:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}
#hotkey-capture.capturing {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
  animation: pulse-border 1.5s infinite;
}
@keyframes pulse-border {
  0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
  70% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
  100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}

/* Buttons */
.btn-group {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 24px;
}
button.action {
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  padding: 10px 20px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card-solid);
  color: var(--text);
  cursor: pointer;
  transition: all 0.2s ease;
}
button.action:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
}
button.action.primary {
  background: var(--accent-gradient);
  color: white;
  border: none;
}
button.action.primary:hover {
  box-shadow: 0 4px 12px var(--accent-soft);
  filter: brightness(1.05);
}
#cfg-msg {
  font-size: 13px;
  margin-left: 12px;
  color: var(--text-muted);
  font-weight: 500;
  transition: opacity 0.5s;
}
#cfg-msg.ok {
  color: #10b981;
  font-weight: 600;
}

/* Animations for Listening state */
#header-logo.listening-anim {
  animation: logo-pulsate 1.2s infinite ease-in-out;
  filter: drop-shadow(0 0 8px var(--accent));
}
@keyframes logo-pulsate {
  0% { transform: scale(1); }
  50% { transform: scale(1.08); }
  100% { transform: scale(1); }
}
.listening-text-glow {
  color: #ef4444 !important;
  font-weight: 700;
  animation: text-blink 1s infinite;
}
@keyframes text-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
/* Section header row with action link */
.section-header { display:flex; align-items:center; justify-content:space-between; margin:28px 0 12px; }
.view-all-btn {
  font-size:13px; font-weight:600; color:var(--accent); text-decoration:none;
  padding:6px 16px; border-radius:8px; background:var(--accent-soft);
  border:1px solid rgba(96,165,250,0.2); transition:all 0.2s ease;
}
.view-all-btn:hover { transform:translateY(-1px); filter:brightness(1.08); }
/* Clickable table rows */
tr.clickable { cursor:pointer; }
tr.clickable td { transition:background 0.15s,color 0.15s; }
/* Log detail form view */
.log-header { display:flex; align-items:center; gap:16px; margin-bottom:20px; }
.log-field { display:grid; grid-template-columns:160px 1fr; border-bottom:1px solid var(--border); padding:14px 0; align-items:start; }
.log-field:last-child { border-bottom:none; }
.log-field-label { font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; }
.log-field-value { font-size:14px; font-weight:500; color:var(--text); word-break:break-word; }
.log-field-value.main-text { font-size:16px; font-weight:600; line-height:1.6; }
/* Pagination bars */
.pagination-bar { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding-top:16px; font-size:13px; color:var(--text-muted); }
.log-pag-bar { display:flex; align-items:center; justify-content:center; gap:16px; padding:28px 0 8px; font-size:13px; color:var(--text-muted); }
.pag-btn {
  font-family:inherit; font-size:13px; font-weight:600; padding:8px 20px;
  border-radius:8px; border:1px solid var(--border); background:var(--card-solid);
  color:var(--text); cursor:pointer; transition:all 0.2s ease;
}
.pag-btn:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); background:var(--accent-soft); }
.pag-btn:disabled { opacity:0.4; cursor:not-allowed; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <!-- Custom SVG Logo -->
      <svg id="header-logo" width="38" height="38" viewBox="0 0 200 200" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="waveGradient" x1="40" y1="100" x2="160" y2="100" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#3498db"/>
            <stop offset="100%" stop-color="#2ecc71"/>
          </linearGradient>
        </defs>
        <rect x="20" y="20" width="160" height="160" rx="25" fill="#2c3e50" />
        <path d="M50 100 C 60 80, 70 80, 80 100 C 90 120, 100 120, 110 100 C 120 70, 130 70, 140 100" stroke="url(#waveGradient)" stroke-width="12" stroke-linecap="round" fill="none"/>
        <circle cx="50" cy="100" r="6" fill="#3498db" />
        <circle cx="150" cy="100" r="6" fill="#2ecc71" />
      </svg>
      <span class="brand-name">Omnihear</span>
    </div>
    <nav>
      <a href="#/" id="nav-dashboard">Dashboard</a>
      <a href="#/history" id="nav-history">History</a>
      <a href="#/settings" id="nav-settings">Settings</a>
    </nav>
    <button id="theme-toggle" type="button" aria-label="Toggle Theme">
      <svg id="icon-moon" viewBox="0 0 24 24">
        <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>
      </svg>
      <svg id="icon-sun" viewBox="0 0 24 24" style="display:none">
        <circle cx="12" cy="12" r="4"/>
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>
      </svg>
    </button>
  </header>

  <!-- Live Status Bar -->
  <div class="status-bar">
    <span class="indicator" id="status-pulse"></span>
    <span id="status-text">loading status…</span>
    <div class="status-hotkey-container">
      <span>Push-to-talk:</span>
      <span class="hotkey-badge" id="status-hotkey-badge">...</span>
    </div>
  </div>

  <!-- Dashboard Screen -->
  <section class="screen" id="screen-dashboard">
    <h2>Analytics</h2>
    <div class="tiles" id="tiles"></div>
    <h2>Activity (last 30 days)</h2>
    <div class="card" style="margin-bottom:24px;"><div id="chart"></div></div>
    <div class="section-header">
      <h2 style="margin:0">Recent Transcriptions</h2>
      <a href="#/history" class="view-all-btn">View all →</a>
    </div>
    <div class="card">
      <div class="table-container">
        <table>
          <thead><tr><th>Time</th><th>Text</th><th class="num">Audio</th><th class="num">Latency</th></tr></thead>
          <tbody id="dash-hist"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- History Screen -->
  <section class="screen" id="screen-history">
    <h2>Transcription History</h2>
    <div class="card">
      <div class="search-wrapper"><input id="q" placeholder="Search transcriptions…"></div>
      <div class="table-container">
        <table>
          <thead><tr><th>Time</th><th>Text</th><th class="num">Audio</th><th class="num">Latency</th><th class="num">CPU</th><th class="num">Memory</th></tr></thead>
          <tbody id="hist"></tbody>
        </table>
      </div>
      <div class="pagination-bar" id="hist-pag"></div>
    </div>
  </section>

  <!-- Log Detail Screen -->
  <section class="screen" id="screen-log">
    <div class="log-header">
      <button class="action" id="back-btn" type="button">← Back</button>
      <h2 style="margin:0">Transcription Detail</h2>
    </div>
    <div class="card" id="log-detail-card"></div>
    <div class="log-pag-bar" id="log-pag"></div>
  </section>

  <!-- Settings Screen -->
  <section class="screen" id="screen-settings">
    <h2>Configuration Settings</h2>
    <div class="card">
      <form id="cfg"></form>
      <div class="btn-group">
        <button class="action primary" id="save">Save config</button>
        <button class="action" id="restart" type="button">Restart service</button>
        <span id="cfg-msg"></span>
      </div>
    </div>
    <p style="font-size:12px;color:var(--text-muted);margin-top:12px;padding-left:4px;">
      Configuration is saved to <code>~/.config/omnihear/config.toml</code> and requires a restart to take effect.
    </p>
  </section>
</div>


<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api = (p, opts) => fetch(p, opts).then(r => r.json());

// --- Theme Management ---
const effectiveTheme = () => document.documentElement.dataset.theme ||
  (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

function updateThemeIcon() {
  const dark = effectiveTheme() === 'dark';
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

// --- Hash Router ---
function getHash() { return location.hash || '#/'; }
function hashParams() {
  const h = getHash();
  return new URLSearchParams(h.includes('?') ? h.slice(h.indexOf('?') + 1) : '');
}
function route() {
  const h = getHash();
  const isDash = h === '#/' || h === '#';
  const isHist = h.startsWith('#/history');
  const isLog  = h.startsWith('#/log');
  const isSett = h === '#/settings';
  ['dashboard','history','log','settings'].forEach(id => {
    const el = document.getElementById('screen-' + id);
    if (el) el.classList.remove('active');
  });
  $('#nav-dashboard').classList.toggle('active', isDash);
  $('#nav-history').classList.toggle('active', isHist || isLog);
  $('#nav-settings').classList.toggle('active', isSett);
  if (isLog) {
    document.getElementById('screen-log').classList.add('active');
    const p = hashParams();
    openLog(parseInt(p.get('offset') || '0', 10), p.get('q') || '', parseInt(p.get('total') || '0', 10));
  } else if (isHist) {
    document.getElementById('screen-history').classList.add('active');
    const p = hashParams();
    histOffset = parseInt(p.get('offset') || '0', 10);
    histQ = p.get('q') || '';
    if ($('#q')) $('#q').value = histQ;
    loadHistory();
  } else if (isSett) {
    document.getElementById('screen-settings').classList.add('active');
  } else {
    document.getElementById('screen-dashboard').classList.add('active');
    loadDashboard();
  }
}
window.addEventListener('hashchange', route);
route();

function fmtSec(s) { return s >= 60 ? (s/60).toFixed(1)+' min' : s.toFixed(1)+' s'; }

// --- Live State Polling & Updates ---
let isRecording = false;

async function loadStatus() {
  const s = await api('/api/status');
  const pulse = $('#status-pulse');
  const text = $('#status-text');
  const logo = $('#header-logo');

  // Trigger immediate refresh on recording state transitions
  const currentlyRecording = !!s.recording;
  if (currentlyRecording !== isRecording) {
    isRecording = currentlyRecording;
    refreshCurrentScreen();
  }

  if (isRecording) {
    pulse.className = 'indicator pulse-active';
    text.innerHTML = '<span class="listening-text-glow">● LISTENING</span> - speak now...';
    logo.classList.add('listening-anim');
  } else {
    logo.classList.remove('listening-anim');
    if (s.model_loaded) {
      pulse.className = 'indicator pulse-loaded';
      text.textContent = `Model '${s.model}' ready in memory`;
    } else {
      pulse.className = 'indicator pulse-idle';
      text.textContent = `Idle · model '${s.model}' will load on first keypress`;
    }
  }

  $('#status-hotkey-badge').textContent = s.hotkey_display || keyDisplay(s.hotkey);
}

let histTotal = 0;
let histOffset = 0;
let histQ = '';
const HIST_PAGE = 20;

function refreshCurrentScreen() {
  const h = getHash();
  if (h === '#/' || h === '#') loadDashboard();
  else if (h.startsWith('#/history')) loadHistory();
}

async function loadDashboard() {
  const [st, rows] = await Promise.all([
    api('/api/stats'),
    api('/api/history?limit=10&offset=0')
  ]);
  const t = st.totals;
  histTotal = t.n;
  $('#tiles').innerHTML = [
    [t.n, 'transcriptions'],
    [t.words, 'words typed'],
    [fmtSec(t.audio_seconds), 'dictation time'],
    [Math.round(t.avg_transcribe_ms) + ' ms', 'avg latency'],
    [t.avg_cpu_percent ? t.avg_cpu_percent.toFixed(0) + '%' : '–', 'avg cpu'],
    [t.avg_memory_mb ? Math.round(t.avg_memory_mb) + ' MB' : '–', 'avg memory'],
  ].map(([v,l]) => `<div class="tile"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join('');
  drawChart(st.per_day);
  $('#dash-hist').innerHTML = rows.map((r, i) =>
    `<tr class="clickable" onclick="location.hash='#/log?offset=${i}&q=&total=${t.n}'">` +
    `<td style="white-space:nowrap;color:var(--text-muted);font-size:12px;">${esc(r.ts.replace('T',' '))}</td>` +
    `<td style="font-weight:600;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(r.text)}</td>` +
    `<td class="num">${r.audio_seconds ? r.audio_seconds.toFixed(1)+'s' : '–'}</td>` +
    `<td class="num">${r.transcribe_ms ? Math.round(r.transcribe_ms)+'ms' : '–'}</td>` +
    `</tr>`
  ).join('') || `<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--text-muted)">No transcriptions yet.</td></tr>`;
}

async function loadStats() { await loadDashboard(); }

function drawChart(days) {
  if (!days.length) { $('#chart').textContent = 'No dictation activity recorded.'; return; }
  const W = 860, H = 200, padL = 40, padB = 25, padT = 10;
  const max = Math.max(...days.map(d => d.words), 1);
  const bw = (W - padL) / days.length;
  
  // Custom premium gradient definition for standard SVG
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Words per day">` +
            `<defs>` +
            `<linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">` +
            `  <stop offset="0%" stop-color="#3b82f6" />` +
            `  <stop offset="100%" stop-color="#1d4ed8" />` +
            `</linearGradient>` +
            `<linearGradient id="barGradientHover" x1="0" y1="0" x2="0" y2="1">` +
            `  <stop offset="0%" stop-color="#60a5fa" />` +
            `  <stop offset="100%" stop-color="#3b82f6" />` +
            `</linearGradient>` +
            `</defs>`;
            
  // Recessive gridlines + y labels
  for (let i = 0; i <= 2; i++) {
    const val = Math.round(max * i / 2);
    const y = H - padB - (H - padB - padT) * i / 2;
    svg += `<line class="grid-line" x1="${padL}" x2="${W}" y1="${y}" y2="${y}"/>` +
           `<text class="axis" x="${padL-10}" y="${y+4}" text-anchor="end">${val}</text>`;
  }
  
  days.forEach((d, i) => {
    const h = Math.max(2, (H - padB - padT) * d.words / max);
    const x = padL + i * bw + 2, y = H - padB - h;
    const w = Math.max(2, bw - 4);
    
    // Rounded bar drawing via path
    svg += `<path class="bar" fill="url(#barGradient)" d="M${x},${y+4} q0,-4 4,-4 h${w-8} q4,0 4,4 v${h-4} h${-w} z">` +
           `<title>${esc(d.day)}: ${d.words} words, ${d.n} transcriptions</title></path>`;
           
    if (days.length <= 15 || i % Math.ceil(days.length/10) === 0)
      svg += `<text class="axis" x="${x + w/2}" y="${H-6}" text-anchor="middle">` +
             `${esc(d.day.slice(5))}</text>`;
  });
  $('#chart').innerHTML = svg + '</svg>';
}

async function loadHistory() {
  const rows = await api(`/api/history?limit=${HIST_PAGE}&offset=${histOffset}&q=${encodeURIComponent(histQ)}`);
  $('#hist').innerHTML = rows.map((r, i) => {
    const abs = histOffset + i;
    return `<tr class="clickable" onclick="location.hash='#/log?offset=${abs}&q=${encodeURIComponent(histQ)}&total=${histTotal}'">` +
    `<td style="white-space:nowrap;color:var(--text-muted);font-size:12px;">${esc(r.ts.replace('T',' '))}</td>` +
    `<td style="font-weight:600;">${esc(r.text)}</td>` +
    `<td class="num">${r.audio_seconds ? r.audio_seconds.toFixed(1)+'s' : '–'}</td>` +
    `<td class="num">${r.transcribe_ms ? Math.round(r.transcribe_ms)+'ms' : '–'}</td>` +
    `<td class="num">${r.cpu_percent != null ? r.cpu_percent.toFixed(0)+'%' : '–'}</td>` +
    `<td class="num">${r.memory_mb != null ? Math.round(r.memory_mb)+' MB' : '–'}</td>` +
    `</tr>`;
  }).join('') || `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-muted)">No transcriptions found.</td></tr>`;
  const hasPrev = histOffset > 0;
  const hasNext = rows.length === HIST_PAGE;
  const pg = Math.floor(histOffset / HIST_PAGE) + 1;
  $('#hist-pag').innerHTML =
    `<button class="pag-btn" onclick="histNav(-1)" ${hasPrev?'':'disabled'}>← Previous</button>` +
    `<span>Page ${pg}${histTotal ? ' of ' + Math.ceil(histTotal / HIST_PAGE) : ''}</span>` +
    `<button class="pag-btn" onclick="histNav(1)" ${hasNext?'':'disabled'}>Next →</button>`;
}

function histNav(dir) {
  histOffset = Math.max(0, histOffset + dir * HIST_PAGE);
  location.hash = `#/history?offset=${histOffset}&q=${encodeURIComponent(histQ)}`;
}

async function openLog(offset, q, total) {
  histTotal = total || histTotal;
  const rows = await api(`/api/history?limit=1&offset=${offset}&q=${encodeURIComponent(q)}`);
  const card = $('#log-detail-card');
  const pag = $('#log-pag');
  $('#back-btn').onclick = () => {
    location.hash = `#/history?offset=${Math.floor(offset / HIST_PAGE) * HIST_PAGE}&q=${encodeURIComponent(q)}`;
  };
  if (!rows.length) {
    card.innerHTML = `<p style="padding:20px;color:var(--text-muted)">Entry not found.</p>`;
    pag.innerHTML = '';
    return;
  }
  const r = rows[0];
  const fields = [
    ['Timestamp', r.ts ? r.ts.replace('T', ' ') : '–'],
    ['Transcription', r.text],
    ['Audio Duration', r.audio_seconds ? r.audio_seconds.toFixed(2) + ' s' : '–'],
    ['Transcribe Latency', r.transcribe_ms ? Math.round(r.transcribe_ms) + ' ms' : '–'],
    ['CPU Usage', r.cpu_percent != null ? r.cpu_percent.toFixed(1) + '%' : '–'],
    ['Memory Usage', r.memory_mb != null ? Math.round(r.memory_mb) + ' MB' : '–'],
    ['Model', r.model || '–'],
    ['Avg Log Probability', r.avg_logprob != null ? r.avg_logprob.toFixed(3) : '–'],
    ['No-Speech Probability', r.no_speech_prob != null ? r.no_speech_prob.toFixed(3) : '–'],
    ['Compression Ratio', r.compression_ratio != null ? r.compression_ratio.toFixed(3) : '–'],
  ];
  card.innerHTML = fields.map(([lbl, val], idx) =>
    `<div class="log-field">` +
    `<div class="log-field-label">${esc(lbl)}</div>` +
    `<div class="log-field-value${idx === 1 ? ' main-text' : ''}">${esc(String(val))}</div>` +
    `</div>`
  ).join('');
  const hasPrev = offset > 0;
  const hasNext = !histTotal || offset < histTotal - 1;
  const tot = histTotal ? ' / ' + histTotal : '';
  pag.innerHTML =
    `<button class="pag-btn" onclick="location.hash='#/log?offset=${offset-1}&q=${encodeURIComponent(q)}&total=${histTotal}'" ${hasPrev?'':'disabled'}>← Previous</button>` +
    `<span style="min-width:90px;text-align:center;">${offset + 1}${tot}</span>` +
    `<button class="pag-btn" onclick="location.hash='#/log?offset=${offset+1}&q=${encodeURIComponent(q)}&total=${histTotal}'" ${hasNext?'':'disabled'}>Next →</button>`;
}

// --- Configuration Form Construction ---
const KEY_NAMES = __KEY_NAMES__;
const MODELS = __MODELS__;
const LANGUAGE_NAMES = __LANGS__;
const LANGUAGES = [['auto','Auto-detect Language']].concat(
  Object.entries(LANGUAGE_NAMES).map(([c,n]) => [c, `${n} (${c})`]));
const COMPUTE_TYPES = ['int8','float16','int8_float16','float32'];
const BOOLS = ['dashboard','notify','beep','history','verbose','vad_filter',
  'condition_on_previous_text'];
const NUMBERS = {
  sample_rate: {min: 8000, step: 1000},
  beam_size: {min: 1, step: 1},
  min_duration: {min: 0, step: 0.1},
  dashboard_port: {min: 1, max: 65535, step: 1},
  idle_unload_minutes: {min: 0, step: 1},
  no_speech_threshold: {min: 0, max: 1, step: 0.05},
  log_prob_threshold: {min: -5, max: 0, step: 0.1},
  compression_ratio_threshold: {min: 1, max: 10, step: 0.1},
};
const SECTIONS = [
  ['Transcription Engine', ['model','language','device','compute_type','beam_size']],
  ['Input & Trigger', ['hotkey','sample_rate','min_duration','type_method']],
  ['Hallucination Filtering', ['vad_filter','no_speech_threshold',
    'log_prob_threshold','compression_ratio_threshold','condition_on_previous_text']],
  ['Dashboard & SQLite DB', ['dashboard','dashboard_port','history']],
  ['Optional Feedback Behaviors', ['notify','beep','idle_unload_minutes','verbose']],
];

const HELP = {
  model: 'faster-whisper model to load. Bigger = more accurate but slower and more memory.',
  language: 'Language spoken in the audio. Auto-detect adds latency; pick a fixed language if you know it.',
  device: 'Run inference on CPU or an NVIDIA GPU (cuda).',
  compute_type: 'Numeric precision for inference. int8 is fastest/smallest; float32 is most accurate.',
  beam_size: 'Search width for decoding. 1 = greedy (fastest); higher can improve accuracy at the cost of speed.',
  hotkey: 'Key (or +-combo) to hold down to record. Release to transcribe and type.',
  sample_rate: 'Microphone recording sample rate in Hz.',
  min_duration: 'Ignore recordings shorter than this many seconds (avoids accidental taps).',
  type_method: 'How transcribed text is typed into the focused field.',
  vad_filter: 'Trim silence/noise before transcription using Silero VAD. Reduces hallucinated text on quiet clips.',
  no_speech_threshold: 'Segments with a no-speech probability above this are treated as silence, not text.',
  log_prob_threshold: 'Segments whose average log-probability falls below this are considered low-confidence.',
  compression_ratio_threshold: 'Segments with a compression ratio above this look repetitive/looping and are flagged as likely hallucinations.',
  condition_on_previous_text: "Feed each segment's decoded text as context for the next. Can help long audio but often causes repeated-phrase hallucinations on short push-to-talk clips.",
  dashboard: 'Enable the local web dashboard (this page) at 127.0.0.1.',
  dashboard_port: 'Port the local dashboard listens on.',
  history: 'Save each transcription to the local SQLite history database.',
  notify: 'Show a desktop notification with the transcribed text.',
  beep: 'Play a short sound on transcription.',
  idle_unload_minutes: 'Unload the model from memory after this many minutes of inactivity (0 = never).',
  verbose: 'Print per-transcription logs to the terminal.',
};
const pretty = k => k.replace(/_/g, ' ');
const keyDisplay = hk => String(hk).split('+').filter(Boolean)
  .map(p => KEY_NAMES[p] || p.toUpperCase()).join(' + ');

const titleAttr = k => HELP[k] ? ` title="${esc(HELP[k])}"` : '';

const selectOf = (k, opts, v) => `<label${titleAttr(k)}>${pretty(k)}<select name="${k}">` +
  opts.map(o => `<option value="${esc(o)}"${o===v?' selected':''}>${esc(o)}</option>`)
      .join('') + `</select></label>`;

function customSelect(k, opts, v, placeholder) {
  const known = opts.some(o => o[0] === v);
  return `<label${titleAttr(k)}>${pretty(k)}<select name="${k}" id="${k}-sel" data-custom="1">` +
    opts.map(([val, lab]) =>
      `<option value="${esc(val)}"${val===v?' selected':''}>${esc(lab)}</option>`).join('') +
    `<option value="__custom__"${known?'':' selected'}>custom\u2026</option>` +
    `</select><input id="${k}-custom" placeholder="${placeholder}"` +
    ` value="${known?'':esc(v)}" style="margin-top:6px;` +
    `display:${known?'none':'block'}"></label>`;
}

function fieldHtml(k, v) {
  if (BOOLS.includes(k))
    return `<label class="check"${titleAttr(k)}><input type="checkbox" name="${k}"${v?' checked':''}>` +
           `<span>${pretty(k)}</span><div class="switch-slider"></div></label>`;
  if (k === 'device') return selectOf(k, ['cpu','cuda'], v);
  if (k === 'type_method') return selectOf(k, ['pynput','xdotool'], v);
  if (k === 'compute_type') return selectOf(k, COMPUTE_TYPES, v);
  if (k === 'model')
    return customSelect(k,
      MODELS.map(m => [m, m === 'base.en' ? 'base.en (default)' : m]),
      v, 'model name or HF repo id');
  if (k === 'language')
    return `<label${titleAttr(k)}>${pretty(k)}<select name="language">` +
      LANGUAGES.map(([c, lab]) =>
        `<option value="${c}"${c===v?' selected':''}>${esc(lab)}</option>`).join('') +
      `</select></label>`;
  if (k === 'hotkey')
    return `<label${titleAttr(k)}>hotkey (push to talk)` +
      `<button type="button" id="hotkey-capture" data-value="${esc(v)}">` +
      `${esc(keyDisplay(v))}</button></label>`;
  if (k in NUMBERS) {
    const n = NUMBERS[k];
    return `<label${titleAttr(k)}>${pretty(k)}<input type="number" name="${k}" value="${esc(v)}"` +
      ` min="${n.min}"${n.max?` max="${n.max}"`:''} step="${n.step}"></label>`;
  }
  return `<label${titleAttr(k)}>${pretty(k)}<input name="${k}" value="${esc(v)}"></label>`;
}

// --- Keyboard Hotkey Capturer ---
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

let capture = null;

function setupHotkeyCapture() {
  const btn = $('#hotkey-capture');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (capture) return;
    capture = {seen: new Set(), active: new Set(), prev: btn.dataset.value};
    btn.classList.add('capturing');
    btn.textContent = 'Press keys combo… (Esc to cancel)';
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
  if (ok) setTimeout(() => { m.style.opacity = 0; }, 3000);
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
  const res = await api('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  if (res.errors && res.errors.length)
    showMsg('Errors: ' + res.errors.join('; '), false);
  else
    showMsg('✓ ' + res.message, true);
}

$('#cfg').addEventListener('submit', e => { e.preventDefault(); saveConfig(); });
$('#save').addEventListener('click', e => { e.preventDefault(); saveConfig(); });

$('#restart').addEventListener('click', async () => {
  const res = await api('/api/restart', { method: 'POST' });
  showMsg(res.message, false);
});

let t;
$('#q').addEventListener('input', () => {
  clearTimeout(t);
  t = setTimeout(() => {
    histQ = $('#q').value;
    histOffset = 0;
    loadHistory();
  }, 300);
});

// --- Startup & Polling ---
loadStatus();
loadConfig();
// route() already called above and loaded the initial screen

setInterval(loadStatus, 1000);
setInterval(() => { if (!isRecording) refreshCurrentScreen(); }, 8000);
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
