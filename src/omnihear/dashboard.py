"""Localhost web dashboard for omnihear (stdlib http.server only)."""

import json
import os
import subprocess
import sys
import threading
import time
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
<!-- No web fonts: the dashboard must work offline and never call out to a
     CDN, so the stacks below prefer locally installed Inter/Outfit and fall
     back to the platform UI font. -->
<style>
:root {
  --font-body: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --font-display: 'Outfit', 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --font-mono: ui-monospace, 'JetBrains Mono', SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace;
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
  --ok: #047857;
  --ok-soft: rgba(16, 185, 129, 0.13);
  --warn: #b45309;
  --warn-soft: rgba(245, 158, 11, 0.15);
  --fail: #dc2626;
  --fail-soft: rgba(239, 68, 68, 0.11);
  --code-bg: rgba(15, 23, 42, 0.045);
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
  --ok: #34d399;
  --ok-soft: rgba(52, 211, 153, 0.13);
  --warn: #fbbf24;
  --warn-soft: rgba(251, 191, 36, 0.13);
  --fail: #f87171;
  --fail-soft: rgba(248, 113, 113, 0.13);
  --code-bg: rgba(148, 163, 184, 0.1);
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
    --ok: #34d399;
    --ok-soft: rgba(52, 211, 153, 0.13);
    --warn: #fbbf24;
    --warn-soft: rgba(251, 191, 36, 0.13);
    --fail: #f87171;
    --fail-soft: rgba(248, 113, 113, 0.13);
    --code-bg: rgba(148, 163, 184, 0.1);
  }
}

* { box-sizing: border-box; margin: 0; padding: 0; }
[hidden] { display: none !important; }
body {
  background: var(--surface);
  color: var(--text);
  font-family: var(--font-body);
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
  font-family: var(--font-display);
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
.perm-banner {
  background: color-mix(in srgb, #f59e0b 14%, var(--card));
  border: 1px solid color-mix(in srgb, #f59e0b 55%, var(--border));
  border-radius: var(--radius);
  padding: 14px 20px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  font-size: 14px;
}
.perm-banner .perm-title { font-weight: 700; margin-bottom: 6px; }
.perm-banner .perm-sub { opacity: 0.85; margin-bottom: 12px; }
.perm-banner .perm-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.perm-banner button {
  background: #f59e0b;
  color: #1a1200;
  border: 0;
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.perm-banner button:hover { filter: brightness(1.06); }
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
  font-family: var(--font-mono);
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
  font-family: var(--font-display);
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
  font-family: var(--font-display);
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
  font-family: var(--font-body);
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

/* Recording overlay preview (Settings) */
.ov-preview {
  grid-column: 1 / -1;
  display: flex;
  gap: 20px;
  align-items: stretch;
  flex-wrap: wrap;
}
.ov-stage {
  flex: 1 1 300px;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid var(--border);
  padding: 16px;
  overflow: hidden;
  /* A checkerboard so overlay opacity is visible. */
  background-color: #8a94a6;
  background-image:
    linear-gradient(45deg, #7a8496 25%, transparent 25%, transparent 75%, #7a8496 75%),
    linear-gradient(45deg, #7a8496 25%, transparent 25%, transparent 75%, #7a8496 75%);
  background-size: 20px 20px;
  background-position: 0 0, 10px 10px;
}
.ov-stage canvas { max-width: 100%; height: auto; }
.ov-side {
  flex: 0 1 200px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
}
.ov-screen {
  position: relative;
  width: 192px;
  height: 108px;
  border-radius: 6px;
  border: 2px solid var(--text-muted);
  background: var(--code-bg);
}
.ov-screen span {
  position: absolute;
  border-radius: 3px;
  background: var(--accent);
}
.ov-modes { display: flex; gap: 6px; }
.ov-modes button {
  flex: 1;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card-solid);
  color: var(--text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.ov-modes button.on { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.cfg-grid label input[type=color] { padding: 2px 4px; height: 38px; cursor: pointer; }

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

/* Hotkey Capture buttons (any [data-capture-key]) */
.hk-row {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}
.hotkey-capture {
  flex: 1;
  min-width: 0;
  text-align: center;
  padding: 10px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  border: 1px dashed var(--border);
  background: var(--card-solid);
  color: var(--text);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  text-transform: none;
}
.hotkey-capture.empty {
  color: var(--text-muted);
  font-weight: 500;
}
.hotkey-capture:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}
.hotkey-capture.capturing {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
  animation: pulse-border 1.5s infinite;
}
.hk-clear {
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card-solid);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}
.hk-clear:hover:not(:disabled) { border-color: var(--fail); color: var(--fail); background: var(--fail-soft); }
.hk-clear:disabled { opacity: 0.45; cursor: default; }
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
#log-corr {
  display:block; width:100%; resize:vertical; padding:10px 12px;
  border-radius:8px; border:1px solid var(--border); background:var(--card-solid); color:var(--text);
  font-family:inherit; font-size:15px; line-height:1.5; transition:border-color 0.2s, box-shadow 0.2s;
}
#log-corr:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
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

.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.ico {
  width: 16px; height: 16px; flex: none;
  fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round;
}

/* Status bar: hands-free lock */
.status-bar.is-locked {
  border-color: color-mix(in srgb, #ef4444 45%, var(--border));
  background: color-mix(in srgb, #ef4444 7%, var(--card));
}
.locked-pill {
  display: inline-flex; align-items: center; gap: 6px;
  color: #ef4444; font-weight: 800; letter-spacing: 0.6px;
}
.locked-pill .ico { width: 15px; height: 15px; }

/* Copy buttons (history rows, log detail, doctor commands) */
.copy-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; cursor: pointer; }
.copy-btn .ico { width: 14px; height: 14px; }
.copy-btn .ic-check { display: none; }
.copy-btn.copied .ic-copy { display: none; }
.copy-btn.copied .ic-check { display: inline; }
.copy-btn.icon-only .cb-label { display: none; }
.copy-btn.icon-only.copied .cb-label,
.copy-btn.icon-only.manual .cb-label { display: inline; }
.copy-btn.copied { color: var(--ok) !important; border-color: color-mix(in srgb, var(--ok) 45%, var(--border)) !important; }
.copy-btn.manual { color: var(--warn) !important; border-color: color-mix(in srgb, var(--warn) 45%, var(--border)) !important; }
.mini {
  font-family: inherit; font-size: 12px; font-weight: 600; line-height: 1.2;
  padding: 5px 8px; border-radius: 7px; border: 1px solid var(--border);
  background: var(--card-solid); color: var(--text-muted);
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  white-space: nowrap;
}
.mini:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
td.copy-cell, th.copy-cell { width: 1%; white-space: nowrap; text-align: right; padding-left: 4px; padding-right: 8px; }
td.copy-cell { padding-top: 8px; padding-bottom: 8px; }
td.ts { white-space: nowrap; color: var(--text-muted); font-size: 12px; }
td.t-clip { font-weight: 600; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
td.t-text { font-weight: 600; }

/* Setup wizard (#/welcome) */
.wiz-intro { color: var(--text-muted); font-size: 14px; margin: -4px 0 16px; }
.wiz { padding: 24px; overflow: visible; }
.wiz-progress {
  list-style: none; display: flex; align-items: center;
  margin: 0 0 24px; padding: 0 0 20px; border-bottom: 1px solid var(--border);
}
.wiz-progress li { display: flex; align-items: center; flex: 1 1 auto; min-width: 0; }
.wiz-progress li:last-child { flex: 0 1 auto; }
.wiz-progress li:not(:last-child)::after {
  content: ""; flex: 1; height: 2px; min-width: 16px; margin: 0 14px;
  background: var(--border); border-radius: 2px; transition: background 0.3s;
}
.wiz-progress li.done:not(:last-child)::after { background: var(--ok); }
.wiz-progress a {
  display: flex; align-items: center; gap: 10px; min-width: 0;
  text-decoration: none; color: var(--text-muted);
  font-size: 13px; font-weight: 600; white-space: nowrap;
}
.wiz-progress li.active a { color: var(--text); }
.wiz-label { overflow: hidden; text-overflow: ellipsis; }
.wiz-dot {
  width: 30px; height: 30px; border-radius: 50%; flex: none;
  display: grid; place-items: center;
  border: 2px solid var(--border); background: var(--card-solid);
  font-size: 13px; font-weight: 700; transition: all 0.2s ease;
}
.wiz-dot .ico { display: none; width: 15px; height: 15px; stroke-width: 3; }
.wiz-progress li.active .wiz-dot { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); }
.wiz-progress li.done .wiz-dot { background: var(--ok); border-color: var(--ok); color: #fff; }
.wiz-progress li.done .wiz-dot .n { display: none; }
.wiz-progress li.done .wiz-dot .ico { display: block; }
.wiz-step:focus { outline: none; }
.wiz-step h3 {
  font-family: var(--font-display); font-size: 18px; font-weight: 700;
  letter-spacing: -0.2px; margin-bottom: 4px;
}
.wiz-sub { color: var(--text-muted); font-size: 14px; margin-bottom: 18px; }
.wiz-step-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.wiz-step-head .action { flex: none; white-space: nowrap; }
.wiz-nav {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border);
}
.wiz-nav .spacer { flex: 1; }
button.action:disabled { opacity: 0.45; cursor: default; transform: none; box-shadow: none; }
button.action.primary.pulse { animation: next-pulse 1.6s ease-in-out infinite; }
@keyframes next-pulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 45%, transparent); }
  50% { box-shadow: 0 0 0 7px color-mix(in srgb, var(--accent) 0%, transparent); }
}
.link-btn {
  font-family: inherit; font-size: 13px; font-weight: 600; color: var(--text-muted);
  background: none; border: 0; padding: 6px 2px; cursor: pointer;
  text-decoration: underline; text-underline-offset: 3px; text-decoration-color: var(--border);
}
.link-btn:hover { color: var(--accent); text-decoration-color: currentColor; }
.wiz a.inline-link { color: var(--accent); font-weight: 600; }

/* Step 1: doctor checklist */
.wiz-summary {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; margin-bottom: 14px; border-radius: 10px;
  font-weight: 600; font-size: 14px;
  background: var(--code-bg); border: 1px solid var(--border);
}
.wiz-summary .ico { width: 18px; height: 18px; }
.wiz-summary.ok { color: var(--ok); background: var(--ok-soft); border-color: color-mix(in srgb, var(--ok) 30%, transparent); }
.wiz-summary.warn { color: var(--warn); background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 30%, transparent); }
.wiz-summary.fail { color: var(--fail); background: var(--fail-soft); border-color: color-mix(in srgb, var(--fail) 30%, transparent); }
.wiz-summary .sum-sub { font-weight: 500; color: var(--text-muted); }
.checklist { list-style: none; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.check-row {
  display: grid; grid-template-columns: 66px minmax(110px, 190px) 1fr; gap: 12px;
  align-items: baseline; padding: 11px 14px; border-bottom: 1px solid var(--border); font-size: 14px;
}
.check-row:last-child { border-bottom: 0; }
.check-row.fail { background: color-mix(in srgb, var(--fail) 5%, transparent); }
.check-label { font-weight: 600; overflow-wrap: anywhere; }
.check-label::first-letter { text-transform: uppercase; }
.check-detail { color: var(--text-muted); font-size: 13px; overflow-wrap: anywhere; }
.chip {
  display: inline-flex; align-items: center; justify-content: center; gap: 4px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase;
  padding: 2px 8px; border-radius: 999px; line-height: 1.6; width: 58px;
}
.chip .ico { width: 11px; height: 11px; stroke-width: 3; }
.chip.ok { color: var(--ok); background: var(--ok-soft); }
.chip.warn { color: var(--warn); background: var(--warn-soft); }
.chip.fail { color: var(--fail); background: var(--fail-soft); }
.cmd {
  display: inline-flex; align-items: center; gap: 6px; max-width: 100%;
  margin: 3px 2px; padding: 3px 3px 3px 9px; vertical-align: middle;
  background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
}
.cmd code {
  font-family: var(--font-mono); font-size: 12.5px; color: var(--text);
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.cmd .mini { padding: 3px 7px; }
.skel { height: 14px; border-radius: 6px; background: var(--code-bg); animation: skel 1.2s ease-in-out infinite; }
@keyframes skel { 50% { opacity: 0.45; } }
.spinner {
  width: 16px; height: 16px; flex: none; border-radius: 50%;
  border: 2px solid var(--border); border-top-color: var(--accent);
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Step 2: hotkey + mic test */
.hk-stage { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; align-items: center; }
.orb-col { display: flex; flex-direction: column; align-items: center; gap: 16px; text-align: center; }
.wiz-keys { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 6px; min-height: 40px; }
kbd.keycap {
  display: inline-block; font-family: var(--font-mono); font-weight: 700; font-size: 14px;
  padding: 6px 12px; border-radius: 8px; color: var(--text);
  background: var(--card-solid); border: 1px solid var(--border); border-bottom-width: 3px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06); transition: transform 0.08s, border-color 0.08s, color 0.08s;
}
.wiz-keys.pressed kbd.keycap { transform: translateY(2px); border-bottom-width: 1px; border-color: #ef4444; color: #ef4444; }
.keycap-plus { color: var(--text-muted); font-weight: 600; }
.keys-inline kbd.keycap { font-size: 12px; padding: 1px 7px; border-bottom-width: 2px; }
.keys-inline .keycap-plus { margin: 0 3px; }
.rec-orb {
  position: relative; width: 132px; height: 132px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--accent-soft); color: var(--accent);
  border: 2px solid color-mix(in srgb, var(--accent) 25%, transparent);
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.rec-orb > .ico { width: 50px; height: 50px; stroke-width: 1.8; }
.rec-orb.on {
  background: radial-gradient(circle at 50% 38%, #f87171, #dc2626);
  color: #fff; border-color: transparent; animation: orb-pulse 1.3s ease-out infinite;
}
.rec-orb .lock-badge {
  display: none; position: absolute; right: 4px; bottom: 4px;
  width: 38px; height: 38px; border-radius: 50%; place-items: center;
  background: var(--card-solid); color: #ef4444; border: 2px solid #ef4444;
}
.rec-orb .lock-badge .ico { width: 18px; height: 18px; }
.rec-orb.locked .lock-badge { display: grid; }
@keyframes orb-pulse {
  0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5); }
  75% { box-shadow: 0 0 0 22px rgba(239, 68, 68, 0); }
  100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}
.orb-text { font-weight: 600; font-size: 14px; min-height: 44px; max-width: 320px; }
.orb-text.rec { color: #ef4444; }
.meter-label {
  display: flex; justify-content: space-between; margin-bottom: 8px;
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px;
}
.meter { display: flex; gap: 3px; height: 22px; }
.meter i { flex: 1; border-radius: 3px; background: var(--code-bg); border: 1px solid var(--border); transition: background 0.08s; }
.meter i.on { border-color: transparent; background: #10b981; }
.meter i.on.y { background: #f59e0b; }
.meter i.on.r { background: #ef4444; }
.mini-checks { list-style: none; margin-top: 20px; display: grid; gap: 10px; }
.mini-checks li { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 14px; color: var(--text-muted); }
.mini-checks .tick {
  width: 22px; height: 22px; border-radius: 50%; flex: none; display: grid; place-items: center;
  border: 2px solid var(--border); color: transparent; transition: all 0.2s ease;
}
.mini-checks .tick .ico { width: 13px; height: 13px; stroke-width: 3; }
.mini-checks li.done { color: var(--text); }
.mini-checks li.done .tick { background: var(--ok); border-color: var(--ok); color: #fff; }
.wiz-note {
  margin-top: 16px; padding: 10px 12px; border-radius: 10px; font-size: 13px;
  background: var(--accent-soft); border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
}
.wiz-note.warn { background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 30%, transparent); }
.wiz-help {
  margin-top: 22px; padding: 14px 16px; border-radius: 10px; font-size: 13px;
  background: var(--warn-soft); border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
}
.wiz-help b.h { display: block; font-size: 14px; margin-bottom: 6px; color: var(--warn); }
.wiz-help ul { margin: 0 0 8px 18px; display: grid; gap: 4px; }
.wiz-help code { font-family: var(--font-mono); font-size: 12px; }

/* Step 3: practice dictation */
#wiz-practice {
  width: 100%; min-height: 120px; resize: vertical;
  padding: 14px 16px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--card-solid); color: var(--text);
  font-family: inherit; font-size: 16px; line-height: 1.5;
  transition: border-color 0.2s, box-shadow 0.2s;
}
#wiz-practice:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
#wiz-practice.rec { border-color: #ef4444; box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15); }
.practice-state {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  min-height: 34px; margin-top: 10px; font-size: 13px; font-weight: 600; color: var(--text-muted);
}
.practice-state.rec { color: #ef4444; }
.practice-state.warn { color: var(--warn); }
.practice-state.ok { color: var(--ok); }
.practice-state .dot { width: 9px; height: 9px; border-radius: 50%; background: #ef4444; animation: text-blink 1s infinite; }
.wiz-success {
  position: relative; display: flex; gap: 14px; align-items: flex-start;
  margin-top: 8px; padding: 16px; border-radius: 12px;
  background: var(--ok-soft); border: 1px solid color-mix(in srgb, var(--ok) 35%, transparent);
  animation: pop-in 0.35s cubic-bezier(0.2, 0.9, 0.3, 1.3);
}
.succ-icon {
  width: 40px; height: 40px; border-radius: 50%; flex: none; display: grid; place-items: center;
  background: var(--ok); color: #fff;
}
.succ-icon .ico { width: 22px; height: 22px; stroke-width: 3; }
.succ-title { font-family: var(--font-display); font-weight: 700; font-size: 17px; color: var(--text); }
.succ-text { font-size: 14px; color: var(--text); margin-top: 2px; overflow-wrap: anywhere; }
.succ-text:empty { display: none; }
@keyframes pop-in { from { transform: scale(0.94); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.confetti { position: absolute; left: 34px; top: 34px; width: 0; height: 0; pointer-events: none; z-index: 2; }
.confetti i {
  position: absolute; width: 7px; height: 11px; border-radius: 2px; opacity: 0;
  animation: confetti-burst 1.1s cubic-bezier(0.15, 0.7, 0.35, 1) forwards;
}
@keyframes confetti-burst {
  0% { transform: translate(0, 0) rotate(0deg) scale(0.6); opacity: 1; }
  80% { opacity: 1; }
  100% { transform: translate(var(--x), var(--y)) rotate(var(--r)) scale(1); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .confetti { display: none; }
  .rec-orb.on, button.action.primary.pulse, .wiz-success { animation: none; }
}

/* Phone width */
@media (max-width: 720px) {
  .wrap { padding: 16px 16px 48px; }
  header { flex-wrap: wrap; gap: 10px 12px; padding: 12px 14px; margin-bottom: 16px; }
  /* All five tabs fit on a 360px+ phone; anything narrower wraps (never hides a tab). */
  nav { order: 3; width: 100%; margin: 0; gap: 2px; flex-wrap: wrap; justify-content: space-between; }
  nav a { padding: 6px 8px; font-size: 13px; white-space: nowrap; }
  .status-bar { flex-wrap: wrap; row-gap: 8px; padding: 12px 14px; margin-bottom: 16px; }
  #status-text { flex: 1 1 210px; min-width: 0; }
  .status-hotkey-container { margin-left: 22px; }
  .card { padding: 16px; }
  .wiz { padding: 18px 16px; }
  .wiz-progress { margin-bottom: 18px; padding-bottom: 16px; }
  .wiz-progress li:not(.active) .wiz-label { display: none; }
  .wiz-progress li:not(:last-child)::after { margin: 0 8px; }
  .wiz-step-head { flex-direction: column; gap: 4px; }
  .wiz-step-head .action { align-self: flex-start; margin-bottom: 14px; }
  .check-row { grid-template-columns: 66px minmax(0, 1fr); row-gap: 4px; }
  .check-row .check-detail { grid-column: 1 / -1; }
  .check-row .check-detail:empty { display: none; }
  .hk-stage { grid-template-columns: minmax(0, 1fr); gap: 20px; }
  .wiz-nav .action { padding: 10px 16px; }
  table .opt { display: none; }
  td.ts .ts-d { display: block; }
  td.t-clip { max-width: 0; width: 100%; }
  .log-field { grid-template-columns: 1fr; gap: 6px; }
}
@media (max-width: 400px) {
  header { padding: 12px 10px; }
  nav a { padding: 6px 6px; }
}
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
      <a href="#/beta" id="nav-beta">Beta</a>
      <a href="#/welcome" id="nav-welcome">Setup</a>
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
  <div class="status-bar" id="status-bar">
    <span class="indicator" id="status-pulse"></span>
    <span id="status-text">loading status…</span>
    <div class="status-hotkey-container">
      <span>Push-to-talk:</span>
      <span class="hotkey-badge" id="status-hotkey-badge">...</span>
    </div>
  </div>

  <!-- macOS permission banner (shown only when a grant is missing) -->
  <div class="perm-banner" id="perm-banner" style="display:none;"></div>

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
          <thead><tr><th>Time</th><th>Text</th><th class="num opt">Audio</th><th class="num opt">Latency</th><th class="copy-cell"><span class="sr-only">Copy</span></th></tr></thead>
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
          <thead><tr><th>Time</th><th>Text</th><th class="num opt">Audio</th><th class="num opt">Latency</th><th class="num opt">CPU</th><th class="num opt">Memory</th><th class="copy-cell"><span class="sr-only">Copy</span></th></tr></thead>
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
        <button class="action primary" id="save">Save &amp; apply</button>
        <button class="action" id="restart" type="button">Restart service</button>
        <span id="cfg-msg"></span>
      </div>
    </div>
    <p style="font-size:12px;color:var(--text-muted);margin-top:12px;padding-left:4px;">
      Configuration is saved to <code>~/.config/omnihear/config.toml</code>. Saving restarts omnihear so changes apply right away.
    </p>
  </section>

  <!-- Beta Screen -->
  <section class="screen" id="screen-beta">
    <h2>Omnihear Beta</h2>
    <div class="card" id="beta-auth" style="margin-bottom:24px;"></div>
    <div id="beta-locked-note" style="display:none;font-size:13px;color:var(--text-muted);margin:-12px 4px 16px;">
      Sign in (free) to unlock the Common Brain, experimental features and the feedback hub.
      Everything below runs 100% locally — audio, transcripts and learned data never leave this device.
    </div>
    <div id="beta-features">
      <h2>Common Brain</h2>
      <div class="card" style="margin-bottom:24px;">
        <div class="tiles" id="brain-tiles" style="margin-bottom:16px;"></div>
        <div style="display:flex;gap:8px;margin-bottom:12px;">
          <input id="brain-add-word" placeholder="Teach a word (name, product, jargon)…" style="flex:1;">
          <button class="action primary" id="brain-add-btn" type="button">Add word</button>
        </div>
        <div class="table-container" style="max-height:260px;overflow-y:auto;">
          <table><thead><tr><th>Learned word</th><th class="num">Seen</th><th></th></tr></thead>
          <tbody id="brain-words"></tbody></table>
        </div>
        <h3 style="margin-top:20px;">Learned corrections</h3>
        <div class="table-container" style="max-height:260px;overflow-y:auto;">
          <table><thead><tr><th>Heard</th><th>Corrected to</th><th class="num">Times</th><th></th></tr></thead>
          <tbody id="brain-corrs"></tbody></table>
        </div>
        <p style="font-size:12px;color:var(--text-muted);margin-top:12px;">
          Corrections are captured when you edit a transcription in History → detail view.
          After a correction repeats, it is auto-applied and its words are fed to Whisper as hotwords.
        </p>
      </div>
      <h2>Experimental</h2>
      <div class="card" style="margin-bottom:24px;">
        <form id="beta-cfg"></form>
        <div class="btn-group">
          <button class="action primary" id="beta-save" type="button">Save beta settings</button>
          <span id="beta-msg"></span>
        </div>
      </div>
      <h2>Feedback</h2>
      <div class="card">
        <div class="cfg-grid">
          <label>type<select id="fb-kind"><option value="bug">Bug report</option><option value="feature">Feature request</option></select></label>
          <label>title<input id="fb-title" placeholder="Short summary"></label>
        </div>
        <label style="display:block;margin-top:12px;">details
          <textarea id="fb-body" rows="4" style="width:100%;box-sizing:border-box;" placeholder="What happened / what would you like?"></textarea>
        </label>
        <label class="check" style="margin-top:8px;"><input type="checkbox" id="fb-diag">
          <span>Attach diagnostics (performance metrics only — never transcript text)</span><div class="switch-slider"></div></label>
        <div class="btn-group">
          <button class="action primary" id="fb-send" type="button">Send feedback</button>
          <span id="fb-msg"></span>
        </div>
      </div>
    </div>
  </section>

  <!-- First-run Setup Wizard -->
  <section class="screen" id="screen-welcome">
    <h2>Set up Omnihear</h2>
    <p class="wiz-intro">Three quick steps and you&rsquo;re dictating. Everything runs locally on this computer.</p>
    <div class="card wiz">
      <ol class="wiz-progress" id="wiz-progress">
        <li data-step="1"><a href="#/welcome?step=1"><span class="wiz-dot"><span class="n">1</span><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span><span class="wiz-label">Check your setup</span></a></li>
        <li data-step="2"><a href="#/welcome?step=2"><span class="wiz-dot"><span class="n">2</span><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span><span class="wiz-label">Try your hotkey</span></a></li>
        <li data-step="3"><a href="#/welcome?step=3"><span class="wiz-dot"><span class="n">3</span><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span><span class="wiz-label">Dictate something</span></a></li>
      </ol>

      <div class="wiz-step" id="wiz-step-1" tabindex="-1" aria-labelledby="wiz-h1">
        <div class="wiz-step-head">
          <div>
            <h3 id="wiz-h1">Check your setup</h3>
            <p class="wiz-sub">omnihear checked this computer for everything dictation needs. Fix anything marked <b>Fail</b>, then re-check. Warnings are optional.</p>
          </div>
          <button class="action" id="wiz-recheck" type="button">Re-check</button>
        </div>
        <div class="wiz-summary" id="wiz-summary" aria-live="polite"></div>
        <ul class="checklist" id="wiz-checks"></ul>
      </div>

      <div class="wiz-step" id="wiz-step-2" tabindex="-1" aria-labelledby="wiz-h2" hidden>
        <h3 id="wiz-h2">Try your hotkey</h3>
        <p class="wiz-sub">Hold your push-to-talk key and say a few words, then let go. Nothing is typed into this page on this step.</p>
        <div class="hk-stage">
          <div class="orb-col">
            <div class="wiz-keys" id="wiz-keys" data-hotkey-caps></div>
            <div class="rec-orb" id="wiz-orb">
              <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7"/></svg>
              <span class="lock-badge"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg></span>
            </div>
            <div class="orb-text" id="wiz-orb-text" aria-live="polite">Hold your hotkey and say something&hellip;</div>
          </div>
          <div>
            <div class="meter-label"><span>Microphone level</span><span id="wiz-level-txt">&ndash;</span></div>
            <div class="meter" id="wiz-meter" role="meter" aria-label="Microphone level" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"></div>
            <ul class="mini-checks">
              <li id="wiz-c-hotkey"><span class="tick"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>Hotkey works</li>
              <li id="wiz-c-mic"><span class="tick"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>Microphone works</li>
              <li id="wiz-c-lock" hidden><span class="tick"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>Hands-free lock works</li>
            </ul>
            <div class="wiz-note" id="wiz-handsfree" hidden><b>Hands-free is on.</b> Double-tap your hotkey to lock recording on, talk as long as you like, then tap it once more to stop and transcribe.</div>
          </div>
        </div>
        <div class="wiz-help" id="wiz-help" hidden>
          <b class="h">Nothing happening? Likely fixes:</b>
          <ul>
            <li>Hold exactly <span class="keys-inline" data-hotkey-caps></span> &mdash; some keyboards have no right-hand Ctrl or Alt. You can pick another key in <a class="inline-link" href="#/settings">Settings</a> (saving applies it).</li>
            <li data-os="linux">On Wayland, omnihear reads the keyboard directly and needs the <code>input</code> group &mdash; Step 1 shows the exact command.</li>
            <li data-os="darwin">Allow omnihear under <b>Input Monitoring</b> and <b>Accessibility</b> (System Settings &rarr; Privacy &amp; Security), then quit and reopen it.</li>
            <li>Another program (a game, remote-desktop or screen-sharing tool) may be grabbing that key.</li>
          </ul>
          <a class="inline-link" href="#/welcome?step=1">&larr; Back to Step 1: check your setup</a>
        </div>
        <div class="wiz-help" id="wiz-mic-help" hidden>
          <b class="h">Your hotkey works, but the microphone sounds silent</b>
          <ul>
            <li>Check the mic isn&rsquo;t muted and is the default input in your system sound settings.</li>
            <li>Several microphones? <code>omnihear --list-devices</code> lists them; set <code>input_device</code> in config.toml.</li>
            <li data-os="darwin">Allow omnihear under <b>Microphone</b> in System Settings &rarr; Privacy &amp; Security.</li>
          </ul>
          <a class="inline-link" href="#/welcome?step=1">&larr; Step 1 shows the microphones omnihear found</a>
        </div>
      </div>

      <div class="wiz-step" id="wiz-step-3" tabindex="-1" aria-labelledby="wiz-h3" hidden>
        <h3 id="wiz-h3">Dictate something</h3>
        <p class="wiz-sub">Click in the box, hold <span class="keys-inline" data-hotkey-caps></span> and say something like <i>&ldquo;Hello, this is my first dictation&rdquo;</i>. When you let go, omnihear types it wherever your cursor is.</p>
        <textarea id="wiz-practice" rows="4" placeholder="Your words will appear here&hellip;" aria-label="Practice dictation box"></textarea>
        <div class="practice-state" id="wiz3-state" aria-live="polite"></div>
        <div class="wiz-success" id="wiz3-success" hidden>
          <div class="succ-icon"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>
          <div style="flex:1;min-width:0;">
            <div class="succ-title" id="wiz3-title">It works &mdash; you&rsquo;re ready to dictate!</div>
            <div class="succ-text" id="wiz3-heard"></div>
            <div class="wiz-note warn" id="wiz3-nottyped" hidden>omnihear heard you, but the text didn&rsquo;t land in the box. Keep the box focused while you speak, or check the typing rows in <a class="inline-link" href="#/welcome?step=1">Step 1</a>.</div>
            <button class="link-btn" id="wiz3-again" type="button">Try again</button>
          </div>
        </div>
      </div>

      <div class="wiz-nav">
        <button class="link-btn" id="wiz-skip" type="button">Skip setup</button>
        <span class="spacer"></span>
        <button class="action" id="wiz-back" type="button">&larr; Back</button>
        <button class="action primary" id="wiz-next" type="button">Next &rarr;</button>
      </div>
    </div>
  </section>
</div>


<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api = (p, opts) => fetch(p, opts).then(r => r.json());
const PLATFORM = __PLATFORM__;  // sys.platform of the machine serving (and viewing) this page

// localStorage can throw (blocked site data, some private modes): never let
// that take the page down.
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
const ONBOARD_KEY = 'omnihear-onboarded';

// Inline icons (stroke = currentColor, sized by .ico)
const svgIco = (body, cls) => `<svg class="ico${cls ? ' ' + cls : ''}" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
const ICON = {
  copy: svgIco('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>', 'ic-copy'),
  copied: svgIco('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'ic-check'),
  check: svgIco('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
  warn: svgIco('<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.01"/>'),
  fail: svgIco('<path d="M6 6l12 12M18 6L6 18"/>'),
  lock: svgIco('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
};

// --- Theme Management ---
const effectiveTheme = () => document.documentElement.dataset.theme ||
  (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

function updateThemeIcon() {
  const dark = effectiveTheme() === 'dark';
  $('#icon-sun').style.display = dark ? 'block' : 'none';
  $('#icon-moon').style.display = dark ? 'none' : 'block';
}

const savedTheme = lsGet('omnihear-theme');
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
updateThemeIcon();

$('#theme-toggle').addEventListener('click', () => {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  lsSet('omnihear-theme', next);
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
  const isBeta = h === '#/beta';
  const isWelcome = h.startsWith('#/welcome');
  ['dashboard','history','log','settings','beta','welcome'].forEach(id => {
    const el = document.getElementById('screen-' + id);
    if (el) el.classList.remove('active');
  });
  $('#nav-dashboard').classList.toggle('active', isDash);
  $('#nav-history').classList.toggle('active', isHist || isLog);
  $('#nav-settings').classList.toggle('active', isSett);
  $('#nav-beta').classList.toggle('active', isBeta);
  $('#nav-welcome').classList.toggle('active', isWelcome);
  if (!isWelcome) { wizStop(); wiz.step = 0; }  // leaving the wizard stops its polling
  if (isWelcome) {
    document.getElementById('screen-welcome').classList.add('active');
    wizShow(parseInt(hashParams().get('step') || '1', 10));
  } else if (isBeta) {
    document.getElementById('screen-beta').classList.add('active');
    loadBeta();
  } else if (isLog) {
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
// The first route() runs from the startup section at the end of this script,
// once every top-level `let`/`const` it touches has been initialised.

function fmtSec(s) { return s >= 60 ? (s/60).toFixed(1)+' min' : s.toFixed(1)+' s'; }

// --- Live State Polling & Updates ---
let isRecording = false;
let lastStatus = null;

// Only touch the DOM when the markup changes, so polling (up to every
// 120 ms in the setup wizard) doesn't restart CSS animations or make
// screen readers re-announce live regions.
function setHTML(el, html) {
  if (el._html !== html) { el.innerHTML = html; el._html = html; }
}

async function loadStatus() {
  let s;
  try { s = await api('/api/status'); } catch (e) { return; }
  renderStatus(s);
}

function renderStatus(s) {
  lastStatus = s;
  const pulse = $('#status-pulse');
  const text = $('#status-text');
  const logo = $('#header-logo');

  // Trigger immediate refresh on recording state transitions
  const currentlyRecording = !!s.recording;
  if (currentlyRecording !== isRecording) {
    isRecording = currentlyRecording;
    refreshCurrentScreen();
  }

  $('#status-bar').classList.toggle('is-locked', !!s.locked);
  if (s.locked) {
    // Hands-free: recording continues without holding the key.
    pulse.className = 'indicator pulse-active';
    setHTML(text, `<span class="locked-pill">${ICON.lock}LOCKED</span> &mdash; tap your hotkey to stop` +
      (s.recording_mode === 'ask' ? ' &middot; listening for a question' : ''));
    logo.classList.add('listening-anim');
  } else if (isRecording) {
    pulse.className = 'indicator pulse-active';
    setHTML(text, s.recording_mode === 'ask'
      ? '<span class="listening-text-glow">● LISTENING</span> for a question - ask away...'
      : '<span class="listening-text-glow">● LISTENING</span> - speak now...');
    logo.classList.add('listening-anim');
  } else {
    text._html = null;
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
  renderPermBanner(s.permissions);
}

const PERM_LABELS = {
  accessibility: ['Accessibility', 'type transcribed text'],
  input_monitoring: ['Input Monitoring', 'detect the hotkey'],
  microphone: ['Microphone', 'record audio'],
};
async function openPermPane(name) {
  try { await api('/api/open-settings', { method: 'POST', body: JSON.stringify({ name }) }); }
  catch (e) {}
}
function renderPermBanner(perms) {
  const el = $('#perm-banner');
  if (!el) return;
  if (!perms) { el.style.display = 'none'; return; }
  const missing = Object.keys(PERM_LABELS)
    .filter(k => perms[k] && perms[k] !== 'authorized' && perms[k] !== 'unknown');
  if (!missing.length) { el.style.display = 'none'; return; }
  const btns = missing.map(k =>
    `<button data-perm="${k}">Open ${PERM_LABELS[k][0]} settings</button>`).join('');
  el.innerHTML =
    `<div class="perm-title">⚠️ omnihear needs permission to work</div>` +
    `<div class="perm-sub">Grant ${missing.map(k => PERM_LABELS[k][0]).join(', ')} in ` +
    `System&nbsp;Settings → Privacy&nbsp;&amp;&nbsp;Security, then quit and reopen omnihear.</div>` +
    `<div class="perm-actions">${btns}</div>`;
  el.querySelectorAll('button[data-perm]').forEach(b =>
    b.addEventListener('click', () => openPermPane(b.getAttribute('data-perm'))));
  el.style.display = 'block';
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
    `<tr class="clickable" data-nav="${esc(logHref(i, '', t.n))}">` +
    tsCell(r.ts) +
    `<td class="t-clip">${esc(r.text)}</td>` +
    `<td class="num opt">${r.audio_seconds ? r.audio_seconds.toFixed(1)+'s' : '–'}</td>` +
    `<td class="num opt">${r.transcribe_ms ? Math.round(r.transcribe_ms)+'ms' : '–'}</td>` +
    copyCell(r) +
    `</tr>`
  ).join('') || `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-muted)">No transcriptions yet.</td></tr>`;
}

// --- History rows: navigation + copy ---
const logHref = (offset, q, total) => `#/log?offset=${offset}&q=${encodeURIComponent(q)}&total=${total}`;
function tsCell(ts) {
  const [d, t] = String(ts || '').split('T');
  return `<td class="ts"><span class="ts-d">${esc(d)}</span> <span class="ts-t">${esc(t || '')}</span></td>`;
}
// What a row's Copy puts on the clipboard: the corrected text when there is one.
function copyCell(r) {
  const corrected = !!r.corrected_text;
  return `<td class="copy-cell">` + copyBtn(r.corrected_text || r.text, {
    iconOnly: true, title: corrected ? 'Copy corrected text' : 'Copy text', selectRow: !corrected,
  }) + `</td>`;
}
function copyBtn(text, {label = 'Copy', title = 'Copy to clipboard', iconOnly = false,
                        from = '', cls = 'mini', selectRow = false} = {}) {
  const src = from ? `data-copy-from="${esc(from)}"` : `data-copy="${esc(text)}"`;
  return `<button type="button" class="copy-btn ${cls}${iconOnly ? ' icon-only' : ''}" ${src}` +
    (selectRow ? ' data-select-row="1"' : '') +
    ` title="${esc(title)}" aria-label="${esc(title)}">` +
    `${ICON.copy}${ICON.copied}<span class="cb-label">${esc(label)}</span></button>`;
}

// Copy with graceful fallbacks: async clipboard API (127.0.0.1 is a secure
// context), then the legacy execCommand path, then select the text so the
// user can press Ctrl+C themselves.
async function copyText(text, btn, selectEl) {
  let ok = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch (e) {}
  if (!ok) ok = legacyCopy(text);
  if (ok) { flashCopy(btn, 'Copied', 'copied'); return true; }
  if (selectEl) {
    selectContents(selectEl);
    flashCopy(btn, (PLATFORM === 'darwin' ? '⌘C' : 'Ctrl+C') + ' to copy', 'manual', 4000);
  } else {
    flashCopy(btn, 'Copy failed', 'manual', 2500);
  }
  return false;
}
function legacyCopy(text) {
  const prev = document.activeElement;
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;';
  document.body.appendChild(ta);
  let ok = false;
  try { ta.select(); ok = document.execCommand('copy'); } catch (e) {}
  ta.remove();
  try { if (prev && prev.focus) prev.focus({preventScroll: true}); } catch (e) {}
  return !!ok;
}
function selectContents(el) {
  if (typeof el.select === 'function') { el.focus(); el.select(); return; }
  const r = document.createRange();
  r.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(r);
}
function flashCopy(btn, label, cls, ms = 1600) {
  const lab = btn.querySelector('.cb-label');
  if (btn.dataset.orig === undefined) btn.dataset.orig = lab ? lab.textContent : '';
  clearTimeout(btn._flash);
  btn.classList.remove('copied', 'manual');
  btn.classList.add(cls);
  if (lab) lab.textContent = label;
  btn._flash = setTimeout(() => {
    btn.classList.remove(cls);
    if (lab) lab.textContent = btn.dataset.orig;
    delete btn.dataset.orig;
  }, ms);
}

// Copy buttons sit inside clickable rows: handle them in the capture phase
// and stop the event there so the row never navigates.
document.addEventListener('click', e => {
  const btn = e.target.closest('.copy-btn');
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  const src = btn.dataset.copyFrom ? document.querySelector(btn.dataset.copyFrom) : null;
  const text = src ? (src.value != null ? src.value : src.textContent) : (btn.dataset.copy || '');
  const chip = btn.closest('.cmd');
  const row = btn.dataset.selectRow ? btn.closest('tr') : null;
  const sel = src || (chip && chip.querySelector('code')) ||
    (row && row.querySelector('.t-clip, .t-text')) || null;
  copyText(text, btn, sel);
}, true);

// Row / pager navigation (delegated; rows ignore clicks on controls and
// text selections). Hrefs live in data-nav so search text never ends up
// inside an inline JS string.
document.addEventListener('click', e => {
  const navBtn = e.target.closest('button[data-nav]');
  if (navBtn) { location.hash = navBtn.dataset.nav; return; }
  const row = e.target.closest('tr[data-nav]');
  if (!row || e.target.closest('a, button, input, textarea, select')) return;
  if (String(window.getSelection() || '').length) return;
  location.hash = row.dataset.nav;
});

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
    return `<tr class="clickable" data-nav="${esc(logHref(abs, histQ, histTotal))}">` +
    tsCell(r.ts) +
    `<td class="t-text">${esc(r.text)}</td>` +
    `<td class="num opt">${r.audio_seconds ? r.audio_seconds.toFixed(1)+'s' : '–'}</td>` +
    `<td class="num opt">${r.transcribe_ms ? Math.round(r.transcribe_ms)+'ms' : '–'}</td>` +
    `<td class="num opt">${r.cpu_percent != null ? r.cpu_percent.toFixed(0)+'%' : '–'}</td>` +
    `<td class="num opt">${r.memory_mb != null ? Math.round(r.memory_mb)+' MB' : '–'}</td>` +
    copyCell(r) +
    `</tr>`;
  }).join('') || `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-muted)">No transcriptions found.</td></tr>`;
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
    ['Audio Duration', r.audio_seconds ? r.audio_seconds.toFixed(2) + ' s' : '–'],
    ['Transcribe Latency', r.transcribe_ms ? Math.round(r.transcribe_ms) + ' ms' : '–'],
    ['CPU Usage', r.cpu_percent != null ? r.cpu_percent.toFixed(1) + '%' : '–'],
    ['Memory Usage', r.memory_mb != null ? Math.round(r.memory_mb) + ' MB' : '–'],
    ['Model', r.model || '–'],
    ['Avg Log Probability', r.avg_logprob != null ? r.avg_logprob.toFixed(3) : '–'],
    ['No-Speech Probability', r.no_speech_prob != null ? r.no_speech_prob.toFixed(3) : '–'],
    ['Compression Ratio', r.compression_ratio != null ? r.compression_ratio.toFixed(3) : '–'],
  ];
  const corrHtml =
    `<div class="log-field">` +
    `<div class="log-field-label">Transcription${r.corrected_text ? ' (corrected)' : ''}</div>` +
    `<div style="min-width:0;">` +
    `<textarea id="log-corr" rows="3">${esc(r.corrected_text || r.text)}</textarea>` +
    `<div class="btn-group" style="margin-top:10px;flex-wrap:wrap;">` +
    `<button class="action primary" id="log-corr-save" type="button">Save correction</button>` +
    copyBtn('', {from: '#log-corr', cls: 'action', title: 'Copy transcript'}) +
    `<span id="log-corr-msg" style="font-size:13px;"></span></div>` +
    (r.corrected_text ? `<div style="font-size:12px;color:var(--text-muted);margin-top:8px;">Original: ${esc(r.text)}</div>` : '') +
    `</div></div>`;
  card.innerHTML = corrHtml + fields.map(([lbl, val]) =>
    `<div class="log-field">` +
    `<div class="log-field-label">${esc(lbl)}</div>` +
    `<div class="log-field-value">${esc(String(val))}</div>` +
    `</div>`
  ).join('');
  $('#log-corr-save').onclick = async () => {
    const res = await api('/api/correction', { method: 'POST',
      body: JSON.stringify({ id: r.id, text: $('#log-corr').value }) });
    const m = $('#log-corr-msg');
    if (res.ok) {
      m.textContent = res.learned && res.learned.length
        ? '✓ Learned: ' + res.learned.map(p => `${p[0]} → ${p[1]}`).join(', ')
        : '✓ Saved' + (res.learned ? '' : '');
    } else m.textContent = res.error || 'Failed';
  };
  const hasPrev = offset > 0;
  const hasNext = !histTotal || offset < histTotal - 1;
  const tot = histTotal ? ' / ' + histTotal : '';
  pag.innerHTML =
    `<button class="pag-btn" type="button" data-nav="${esc(logHref(offset - 1, q, histTotal))}" ${hasPrev?'':'disabled'}>← Previous</button>` +
    `<span style="min-width:90px;text-align:center;">${offset + 1}${tot}</span>` +
    `<button class="pag-btn" type="button" data-nav="${esc(logHref(offset + 1, q, histTotal))}" ${hasNext?'':'disabled'}>Next →</button>`;
}

// --- Configuration Form Construction ---
const KEY_NAMES = __KEY_NAMES__;
const MODELS = __MODELS__;
const LANGUAGE_NAMES = __LANGS__;
const TYPE_METHODS = __TYPE_METHODS__;
const CLEANUP_LEVELS = __CLEANUP_LEVELS__;
// Overlay option lists, ranges and base geometry, from overlay_anim.py.
const OV = __OVERLAY__;
const LANGUAGES = [['auto','Auto-detect Language']].concat(
  Object.entries(LANGUAGE_NAMES).map(([c,n]) => [c, `${n} (${c})`]));
const COMPUTE_TYPES = ['int8','float16','int8_float16','float32'];
const BOOLS = ['dashboard','notify','beep','history','verbose','vad_filter',
  'condition_on_previous_text','brain','brain_autocorrect','brain_hotwords','analytics',
  'voice_commands','terminal_commands','rag_context','hands_free'];
const NUMBERS = {
  sample_rate: {min: 8000, step: 1000},
  beam_size: {min: 1, step: 1},
  min_duration: {min: 0, step: 0.1},
  dashboard_port: {min: 1, max: 65535, step: 1},
  idle_unload_minutes: {min: 0, step: 1},
  no_speech_threshold: {min: 0, max: 1, step: 0.05},
  log_prob_threshold: {min: -5, max: 0, step: 0.1},
  compression_ratio_threshold: {min: 1, max: 10, step: 0.1},
  brain_min_count: {min: 1, step: 1},
  rag_context_limit: {min: 1, max: 20, step: 1},
  ask_context_limit: {min: 1, max: 20, step: 1},
  max_recording_seconds: {min: 10, max: 3600, step: 10},
  overlay_scale: {step: 0.1},
  overlay_opacity: {step: 0.05},
  overlay_offset_x: {step: 10},
  overlay_offset_y: {step: 10},
  overlay_bar_count: {step: 1},
  overlay_bar_width: {step: 0.5},
  overlay_bar_gap: {step: 0.5},
  overlay_bar_height: {step: 1},
};
for (const [k, [lo, hi]] of Object.entries(OV.ranges)) Object.assign(NUMBERS[k], {min: lo, max: hi});
const OVERLAY_KEYS = ['overlay_scale','overlay_position','overlay_offset_x','overlay_offset_y',
  'overlay_shape','overlay_bg_color','overlay_opacity','overlay_dot_color',
  'overlay_bar_color','overlay_bar_count','overlay_bar_width','overlay_bar_gap',
  'overlay_bar_height','overlay_bar_shape'];
const OVERLAY_LABELS = {
  overlay_scale: 'Size (scale)', overlay_position: 'Screen position',
  overlay_offset_x: 'Nudge right (px)', overlay_offset_y: 'Nudge down (px)',
  overlay_shape: 'Container shape', overlay_bg_color: 'Container colour',
  overlay_opacity: 'Container opacity', overlay_dot_color: 'Recording dot colour',
  overlay_bar_color: 'Waveform colour', overlay_bar_count: 'Waveform bars',
  overlay_bar_width: 'Bar width (px)', overlay_bar_gap: 'Bar spacing (px)',
  overlay_bar_height: 'Bar max height (px)', overlay_bar_shape: 'Bar shape',
};
const OVERLAY_CHOICES = {
  overlay_position: OV.positions, overlay_shape: OV.shapes, overlay_bar_shape: OV.bar_shapes,
};
// Beta-only settings: rendered on #/beta, never in #/settings.
const BETA_KEYS = ['brain','brain_autocorrect','brain_hotwords','brain_min_count','analytics',
  'voice_commands','terminal_commands','rag_context','rag_context_limit',
  'ask_hotkey','ask_model','ask_context_limit'];
const SECTIONS = [
  ['Transcription Engine', ['model','language','device','compute_type','beam_size']],
  ['Input & Trigger', ['hotkey','sample_rate','min_duration','type_method']],
  ['Dictation (new)', ['hands_free','max_recording_seconds','paste_last_hotkey','cleanup']],
  ['Hallucination Filtering', ['vad_filter','no_speech_threshold',
    'log_prob_threshold','compression_ratio_threshold','condition_on_previous_text']],
  ['Dashboard & SQLite DB', ['dashboard','dashboard_port','history']],
  ['Optional Feedback Behaviors', ['notify','beep','idle_unload_minutes','verbose']],
  ['Recording Overlay', OVERLAY_KEYS],
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
  type_method: 'How transcribed text is typed into the focused field. auto picks pynput on X11/Windows/macOS; on Wayland the built-in uinput typer (any compositor), else ydotool, or wtype on wlroots. paste (beta) pastes through the clipboard: instant for long text and works with any keyboard layout; your previous clipboard is restored.',
  hands_free: 'Beta. Double-tap the hotkey to keep recording without holding it; tap once more to stop and transcribe.',
  max_recording_seconds: 'Safety cap: recording stops and is transcribed after this many seconds (hands-free or held).',
  paste_last_hotkey: 'Optional key/combo that puts your last transcript at the cursor again, for when it went to the wrong window. Empty disables it.',
  cleanup: 'Beta. light: remove filler words (um, uh), stutters ("the the") and spoken self-corrections ("at 2, actually 3" becomes "at 3") before typing.',
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
  brain: 'Common Brain: learn locally from your transcript corrections.',
  brain_autocorrect: 'Automatically apply learned corrections to new transcriptions.',
  brain_hotwords: 'Feed learned vocabulary to Whisper as hotwords / initial prompt.',
  brain_min_count: 'How many times a correction must repeat before it is auto-applied.',
  analytics: 'Opt-in anonymous usage pings (version and platform only — never audio or text).',
  voice_commands: 'Say punctuation words ("comma", "new line") to type symbols, and "scratch that" to undo the last thing typed.',
  terminal_commands: 'When a terminal is focused inside a git repo, translate phrases like "push to remote origin" into the real git command instead of typing them literally (Linux/X11 only).',
  rag_context: 'Retrieve relevant past transcriptions (keyword search over history.db) and feed them to Whisper as extra initial_prompt context, alongside Common Brain’s vocabulary.',
  rag_context_limit: 'Max past transcriptions to feed as RAG context.',
  ask_hotkey: 'Second push-to-talk key/combo (e.g. "ctrl_l+space"): hold, ask a question, release to get a locally-generated answer typed instead of the raw transcript. Empty disables it. Requires Ollama installed locally.',
  ask_model: 'Ollama model name used to generate voice Q&A answers (e.g. "llama3.2"). Ollama must be installed and the model pulled locally.',
  ask_context_limit: 'Max past transcriptions retrieved as context for voice Q&A.',
  overlay_scale: 'Overall size of the recording indicator. 1 is the original compact size.',
  overlay_position: 'Where on screen the indicator appears.',
  overlay_offset_x: 'Fine-tune the position: pixels to move right (negative moves left).',
  overlay_offset_y: 'Fine-tune the position: pixels to move down (negative moves up).',
  overlay_shape: 'Shape of the indicator container: pill (fully rounded ends), rounded corners, or square.',
  overlay_bg_color: 'Background colour of the indicator container.',
  overlay_opacity: 'How opaque the indicator is (0.2 to 1).',
  overlay_dot_color: 'Colour of the dot (and hands-free stop square) shown while recording.',
  overlay_bar_color: 'Colour of the waveform bars while recording.',
  overlay_bar_count: 'Number of waveform bars. Odd numbers keep a single centre bar.',
  overlay_bar_width: 'Thickness of each waveform bar, before scaling.',
  overlay_bar_gap: 'Space between waveform bars, before scaling.',
  overlay_bar_height: 'Height of the tallest waveform bar, before scaling. The container grows to fit.',
  overlay_bar_shape: 'Waveform bars with rounded ends, or square ends.',
};
const pretty = k => OVERLAY_LABELS[k] || k.replace(/_/g, ' ');
const prettyOpt = o => o.replace(/_/g, ' ');
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
  if (k === 'type_method') return selectOf(k, TYPE_METHODS, v);
  if (k === 'cleanup') return selectOf(k, CLEANUP_LEVELS, v);
  if (k === 'compute_type') return selectOf(k, COMPUTE_TYPES, v);
  if (k in OVERLAY_CHOICES)
    return `<label${titleAttr(k)}>${esc(pretty(k))}<select name="${k}">` +
      OVERLAY_CHOICES[k].map(o =>
        `<option value="${esc(o)}"${o===v?' selected':''}>${esc(prettyOpt(o))}</option>`).join('') +
      `</select></label>`;
  if (k.endsWith('_color'))
    return `<label${titleAttr(k)}>${esc(pretty(k))}<input type="color" name="${k}" value="${esc(v)}"></label>`;
  if (k === 'model')
    return customSelect(k,
      MODELS.map(m => [m, m === 'base.en' ? 'base.en (default)' : m]),
      v, 'model name or HF repo id');
  if (k === 'language')
    return `<label${titleAttr(k)}>${pretty(k)}<select name="language">` +
      LANGUAGES.map(([c, lab]) =>
        `<option value="${c}"${c===v?' selected':''}>${esc(lab)}</option>`).join('') +
      `</select></label>`;
  if (k in CAPTURE_KEYS) return captureField(k, v);
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
  MetaLeft:'cmd_l', MetaRight:'cmd_r',
};
for (let i = 1; i <= 12; i++) CODE_MAP['F'+i] = 'f'+i;
function codeToName(code, key) {
  if (CODE_MAP[code]) return CODE_MAP[code];
  let m = code.match(/^Key([A-Z])$/);   if (m) return m[1].toLowerCase();
  m = code.match(/^Digit([0-9])$/);     if (m) return m[1];
  // '+' joins combo parts in the config, so it can't be a key itself.
  if (key === '+') return null;
  // Punctuation / symbol keys (Backquote, Minus, BracketLeft, …)
  if (key && key.length === 1) return key.toLowerCase();
  return null;
}

// Every <button data-capture-key="..."> is a capture field; its value lives
// in data-value ('' = not set). Optional keys get a Clear button.
const CAPTURE_KEYS = {hotkey: false, paste_last_hotkey: true, ask_hotkey: true};  // key -> clearable
const hkLabel = v => v ? keyDisplay(v) : 'Not set — click to record';

function captureField(k, v) {
  v = v || '';
  const label = k === 'hotkey' ? 'hotkey (push to talk)' : pretty(k);
  return `<label${titleAttr(k)}>${label}<span class="hk-row">` +
    `<button type="button" class="hotkey-capture${v ? '' : ' empty'}" data-capture-key="${k}"` +
    ` data-value="${esc(v)}">${esc(hkLabel(v))}</button>` +
    (CAPTURE_KEYS[k]
      ? `<button type="button" class="hk-clear" data-clear-key="${k}" title="Clear (disables ${esc(pretty(k))})"` +
        `${v ? '' : ' disabled'}>Clear</button>`
      : '') +
    `</span></label>`;
}

// Value of a capture field inside `root`, or undefined if it isn't rendered.
function capturedValue(root, k) {
  const b = root.querySelector(`[data-capture-key="${k}"]`);
  return b ? (b.dataset.value || '') : undefined;
}

let capture = null;  // {btn, seen: Set(names, in press order), held: Set(codes), prev}

function syncCaptureBtn(btn) {
  const v = btn.dataset.value || '';
  btn.textContent = hkLabel(v);
  btn.classList.toggle('empty', !v);
  const clr = document.querySelector(`[data-clear-key="${btn.dataset.captureKey}"]`);
  if (clr) clr.disabled = !v;
}

function startCapture(btn) {
  if (capture) endCapture(true);
  capture = {btn, seen: new Set(), held: new Set(), prev: btn.dataset.value || ''};
  btn.classList.add('capturing');
  btn.textContent = 'Press keys combo… (Esc to cancel)';
}

function endCapture(canceled) {
  if (!capture) return;
  const {btn, seen, prev} = capture;
  capture = null;
  btn.dataset.value = (canceled || !seen.size) ? prev : [...seen].join('+');
  btn.classList.remove('capturing');
  syncCaptureBtn(btn);
}

document.addEventListener('click', e => {
  const cap = e.target.closest('[data-capture-key]');
  const clr = e.target.closest('[data-clear-key]');
  // A click anywhere else abandons an unfinished capture.
  if (capture && cap !== capture.btn) endCapture(true);
  if (cap) {
    e.preventDefault();
    if (capture && capture.btn === cap) endCapture(true);
    else startCapture(cap);
  } else if (clr) {
    e.preventDefault();
    const btn = document.querySelector(`[data-capture-key="${clr.dataset.clearKey}"]`);
    if (btn) { btn.dataset.value = ''; syncCaptureBtn(btn); }
  }
});

// Losing focus mid-combo (e.g. the combo switched windows) keeps what was seen.
window.addEventListener('blur', () => { if (capture) endCapture(!capture.seen.size); });

document.addEventListener('keydown', e => {
  if (!capture) return;
  e.preventDefault();
  if (e.key === 'Escape') { endCapture(true); return; }
  if (e.repeat) return;
  const name = codeToName(e.code, e.key);
  if (!name) {
    capture.btn.textContent = 'Key not supported';
    return;
  }
  capture.seen.add(name);
  capture.held.add(e.code);
  capture.btn.textContent = keyDisplay([...capture.seen].join('+'));
});

document.addEventListener('keyup', e => {
  if (!capture) return;
  e.preventDefault();
  // Track held keys by physical code: a symbol's e.key can change between
  // keydown and keyup (Shift released first: '?' down, '/' up).
  capture.held.delete(e.code);
  if (capture.seen.size && !capture.held.size) endCapture(false);
});

// --- Recording overlay live preview ---
// A JS port of overlay_anim.Style / place() and a trimmed-down version of
// its listening/transcribing animation; keep the layout maths in sync.
const OV_PREVIEW_HTML =
  `<div class="ov-preview"><div class="ov-stage"><canvas id="ov-canvas"></canvas></div>` +
  `<div class="ov-side"><div class="ov-modes">` +
  `<button type="button" class="on" data-ov-mode="listening">Listening</button>` +
  `<button type="button" data-ov-mode="transcribing">Transcribing</button></div>` +
  `<div>Position on a 1920×1080 screen</div><div class="ov-screen"><span id="ov-marker"></span></div>` +
  `</div></div>`;
const ovState = {mode: 'listening', raf: 0, since: 0, env: 0, hist: [], heights: [], n: 0};

function ovClamp(v, lo, hi, d) { v = parseFloat(v); return isNaN(v) ? d : Math.min(hi, Math.max(lo, v)); }
function ovHex(v, d) { return /^#[0-9a-f]{6}$/i.test(v || '') ? v : d; }
function ovRgb(h) { return [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); }
function ovMix(a, b, t) { return 'rgb(' + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',') + ')'; }
const ovCss = a => ovMix(a, a, 0);

function ovFormValues() {
  const f = $('#cfg'), c = {};
  for (const k of OVERLAY_KEYS) if (f.elements[k]) c[k] = f.elements[k].value;
  return c;
}

function ovStyle(c) {
  const B = OV.base, R = OV.ranges, D = OV.defaults;
  const st = {};
  const s = st.scale = ovClamp(c.overlay_scale, ...R.overlay_scale, 1);
  st.n = Math.trunc(ovClamp(c.overlay_bar_count, ...R.overlay_bar_count, B.n_bars));
  const bw = ovClamp(c.overlay_bar_width, ...R.overlay_bar_width, B.bar_w);
  const gap = ovClamp(c.overlay_bar_gap, ...R.overlay_bar_gap, B.bar_gap);
  const bmax = ovClamp(c.overlay_bar_height, ...R.overlay_bar_height, B.bar_max);
  st.shape = OV.shapes.includes(c.overlay_shape) ? c.overlay_shape : 'pill';
  st.roundBars = c.overlay_bar_shape !== 'square';
  st.opacity = ovClamp(c.overlay_opacity, ...R.overlay_opacity, 0.94);
  st.bg = ovRgb(ovHex(c.overlay_bg_color, D.overlay_bg_color));
  st.bar = ovRgb(ovHex(c.overlay_bar_color, D.overlay_bar_color));
  st.rec = ovRgb(ovHex(c.overlay_dot_color, D.overlay_dot_color));
  const h = Math.max(B.pill_h, bmax + 14);
  const left = st.shape === 'pill' ? h / 2 : B.dot_cx;
  const x0 = left + (B.bars_x0 - B.dot_cx);
  const right = st.shape === 'pill' ? Math.max(15, h / 2 - 4) : 15;
  const w = x0 + st.n * (bw + gap) - gap + right;
  const radius = {pill: h / 2, rounded: Math.min(10, h / 2), square: 0}[st.shape];
  Object.assign(st, {
    width: Math.max(1, Math.round(w * s)), height: Math.max(1, Math.round(h * s)),
    radius: radius * s, dotCx: left * s, dotR: B.dot_r * s,
    spinnerR: B.spinner_r * s, lineW: 2 * s, haloGrow: 6.5 * s,
    barW: bw * s, barGap: gap * s, x0: x0 * s, barMax: bmax * s,
  });
  st.barMin = Math.min(st.roundBars ? st.barW : 2 * s, st.barMax / 2);
  st.barX = i => st.x0 + i * (st.barW + st.barGap) + st.barW / 2;
  return st;
}

function ovPlace(st, c, sw, sh) {
  const M = OV.base;
  const pos = OV.positions.includes(c.overlay_position) ? c.overlay_position : 'bottom_center';
  let x = pos.endsWith('_left') ? M.margin_side
        : pos.endsWith('_right') ? sw - st.width - M.margin_side : (sw - st.width) / 2;
  let y = pos.startsWith('top') ? M.margin_top
        : pos.startsWith('bottom') ? sh - st.height - M.margin_bottom : (sh - st.height) / 2;
  x += ovClamp(c.overlay_offset_x, -10000, 10000, 0);
  y += ovClamp(c.overlay_offset_y, -10000, 10000, 0);
  return [Math.min(Math.max(0, x), Math.max(0, sw - st.width)),
          Math.min(Math.max(0, y), Math.max(0, sh - st.height))];
}

function ovRoundRect(ctx, x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function ovDraw(now) {
  const cv = document.getElementById('ov-canvas');
  if (!cv || !cv.offsetParent) { ovState.raf = 0; return; }   // left Settings
  const c = ovFormValues(), st = ovStyle(c);
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(st.width * dpr) || cv.height !== Math.round(st.height * dpr)) {
    cv.width = Math.round(st.width * dpr); cv.height = Math.round(st.height * dpr);
    cv.style.width = st.width + 'px';
  }
  if (ovState.n !== st.n) {
    ovState.n = st.n; ovState.heights = new Array(st.n).fill(0);
    ovState.hist = new Array(Math.floor(st.n / 2) + 1).fill(0);
  }
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, st.width, st.height);
  ctx.globalAlpha = st.opacity;
  const cy = st.height / 2, cx = st.dotCx, n = st.n, B = OV.base;
  const t = (now - ovState.since) / 1000, k = (B.n_bars - 1) / Math.max(1, n - 1);
  ovRoundRect(ctx, 0, 0, st.width, st.height, st.radius);
  ctx.fillStyle = ovCss(st.bg); ctx.fill();

  const targets = [], colors = [], busy = OV.busy;
  if (ovState.mode === 'transcribing') {
    const sweep = (t * 0.9) % 1.6 - 0.3;
    for (let i = 0; i < n; i++) {
      const x = i / (n - 1), wave = 0.5 + 0.5 * Math.sin(t * 5 - i * k * 0.62);
      const glow = Math.exp(-(((x - sweep) / 0.16) ** 2));
      targets.push(0.14 + 0.22 * wave + 0.44 * glow);
      colors.push(ovMix(busy, st.bg, 0.55 * (1 - glow)));
    }
    const sr = st.spinnerR, a = ((t * 400) % 360) * Math.PI / 180 - Math.PI / 2;
    ctx.lineWidth = st.lineW; ctx.lineCap = 'round';
    ctx.strokeStyle = ovMix(busy, st.bg, 0.75);
    ctx.beginPath(); ctx.arc(cx, cy, sr, 0, 2 * Math.PI); ctx.stroke();
    ctx.strokeStyle = ovCss(busy);
    ctx.beginPath(); ctx.arc(cx, cy, sr, a, a + 110 * Math.PI / 180); ctx.stroke();
  } else {
    // Simulated voice: syllable-like bursts.
    const level = Math.max(0, Math.sin(t * 2.1) * 0.5 + Math.sin(t * 5.3) * 0.35 + 0.15);
    ovState.env = level > ovState.env ? level : ovState.env * 0.86 + level * 0.14;
    ovState.hist.unshift(ovState.env); ovState.hist.length = Math.floor(n / 2) + 1;
    const centre = Math.floor(n / 2), nowS = now / 1000;
    for (let i = 0; i < n; i++) {
      const d = Math.abs(i - centre);
      let v = ovState.hist[d] * Math.max(0, 1 - 0.085 * d * k);
      v *= 0.74 + 0.26 * Math.sin(nowS * 11 + i * 1.9);
      const idle = 0.06 + 0.05 * (0.5 + 0.5 * Math.sin(nowS * 3.2 - d * k * 0.75));
      targets.push(Math.max(idle, v));
      colors.push(ovCss(st.bar));
    }
    const phase = (t % 1.3) / 1.3, hr = st.dotR + st.scale + phase * st.haloGrow;
    ctx.fillStyle = ovMix(st.rec, st.bg, 1 - 0.45 * (1 - phase));
    ctx.beginPath(); ctx.arc(cx, cy, hr, 0, 2 * Math.PI); ctx.fill();
    ctx.fillStyle = ovCss(st.rec);
    ctx.beginPath(); ctx.arc(cx, cy, st.dotR, 0, 2 * Math.PI); ctx.fill();
  }
  const ease = ovState.mode === 'transcribing' ? 0.25 : 0.5;
  for (let i = 0; i < n; i++) {
    ovState.heights[i] += (targets[i] - ovState.heights[i]) * ease;
    const bh = st.barMin + ovState.heights[i] * (st.barMax - st.barMin);
    ovRoundRect(ctx, st.barX(i) - st.barW / 2, cy - bh / 2, st.barW, bh,
                st.roundBars ? st.barW / 2 : 0);
    ctx.fillStyle = colors[i]; ctx.fill();
  }
  ctx.globalAlpha = 1;

  // Where it lands on a 1920x1080 screen, drawn at 1/10 scale.
  const [px, py] = ovPlace(st, c, 1920, 1080), m = $('#ov-marker');
  if (m) Object.assign(m.style, {left: px / 10 + 'px', top: py / 10 + 'px',
    width: Math.max(3, st.width / 10) + 'px', height: Math.max(2, st.height / 10) + 'px'});
  ovState.raf = requestAnimationFrame(ovDraw);
}

function ovStart() {
  ovState.since = performance.now();
  if (!ovState.raf) ovState.raf = requestAnimationFrame(ovDraw);
}

document.addEventListener('click', e => {
  const b = e.target.closest('[data-ov-mode]');
  if (!b) return;
  e.preventDefault();
  ovState.mode = b.dataset.ovMode;
  ovState.since = performance.now();
  document.querySelectorAll('[data-ov-mode]').forEach(x => x.classList.toggle('on', x === b));
});

async function loadConfig() {
  const cfg = await api('/api/config');
  $('#cfg').innerHTML = SECTIONS.map(([title, keys]) =>
    `<div class="cfg-section"><h3>${title}</h3><div class="cfg-grid">` +
    (keys === OVERLAY_KEYS ? OV_PREVIEW_HTML : '') +
    keys.filter(k => k in cfg).map(k => fieldHtml(k, cfg[k])).join('') +
    `</div></div>`).join('');
  ovStart();
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

// Save settings and, if anything changed, restart omnihear so they apply
// right away. `say(text, ok)` shows progress. Waits for the new process
// (its /api/status "boot" id differs), following a changed dashboard port.
async function saveAndRestart(data, say) {
  let res;
  try {
    res = await api('/api/config', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  } catch (e) { say('Could not reach omnihear to save.', false); return; }
  const errs = res.errors && res.errors.length ? 'Errors: ' + res.errors.join('; ') : '';
  if (!res.changed || !res.changed.length) { say(errs || '✓ No changes to save.', !errs); return; }
  if (!res.can_restart) {
    say((errs ? errs + ' — other changes saved' : '✓ Saved') +
        '. Not running under systemd: restart omnihear manually to apply.', !errs);
    return;
  }
  let before = null;
  try { before = (await api('/api/status')).boot; } catch (e) {}
  say((errs ? errs + ' — ' : '') + 'Saved. Restarting omnihear…', false);
  try { await api('/api/restart', {method: 'POST'}); } catch (e) {}
  if (res.changed.includes('dashboard') && data.dashboard === false) {
    say('✓ Saved and restarting. The dashboard is now turned off.', true);
    return;
  }
  const port = res.changed.includes('dashboard_port') ? String(data.dashboard_port) : '';
  const base = port && port !== location.port ? `http://127.0.0.1:${port}` : '';
  const deadline = Date.now() + 30000;
  await new Promise(r => setTimeout(r, 1200));
  while (Date.now() < deadline) {
    try {
      const st = await fetch(base + '/api/status').then(r => r.json());
      if (st.boot && st.boot !== before) {
        if (base) { location.href = base + '/' + location.hash; return; }
        say((errs ? errs + ' — other changes' : '✓ Saved and') + ' applied (omnihear restarted).', !errs);
        return;
      }
    } catch (e) {}   // down while it restarts
    await new Promise(r => setTimeout(r, 600));
  }
  say('Saved, but omnihear has not come back yet. Check: systemctl --user status omnihear', false);
}

async function saveConfig() {
  if (capture) endCapture(true);
  const form = $('#cfg');
  const data = {};
  for (const [, keys] of SECTIONS) for (const k of keys) {
    const hk = capturedValue(form, k);
    if (hk !== undefined) { data[k] = hk; continue; }
    const el = form.elements[k];
    if (!el) continue;
    if (BOOLS.includes(k)) data[k] = el.checked;
    else if (el.dataset && el.dataset.custom)
      data[k] = el.value === '__custom__' ? $('#' + k + '-custom').value : el.value;
    else data[k] = el.value;
  }
  $('#save').disabled = true;
  try { await saveAndRestart(data, showMsg); }
  finally { $('#save').disabled = false; }
}

$('#cfg').addEventListener('submit', e => { e.preventDefault(); saveConfig(); });
$('#save').addEventListener('click', e => { e.preventDefault(); saveConfig(); });

$('#restart').addEventListener('click', async () => {
  const res = await api('/api/restart', { method: 'POST' });
  showMsg(res.message, false);
});

// --- Beta Screen ---
async function loadBeta() {
  const [b, cfg] = await Promise.all([api('/api/brain'), api('/api/config')]);
  const st = b.beta || {};
  const auth = $('#beta-auth');
  if (st.signed_in) {
    auth.innerHTML =
      `<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">` +
      `<span style="font-weight:600;">${esc(st.email || '')}</span>` +
      `<span class="hotkey-badge">${st.beta_access ? 'BETA ACTIVE' : 'NO BETA ACCESS'}</span>` +
      `<span style="flex:1"></span>` +
      `<button class="action" id="beta-logout" type="button">Sign out</button></div>`;
    $('#beta-logout').onclick = async () => { await api('/api/auth/logout', {method:'POST'}); loadBeta(); };
  } else {
    auth.innerHTML =
      `<div class="cfg-grid">` +
      `<label>email<input id="auth-email" type="email" placeholder="you@example.com"></label>` +
      `<label>password<input id="auth-pw" type="password" placeholder="••••••••"></label></div>` +
      `<div class="btn-group"><button class="action primary" id="auth-login" type="button">Sign in</button>` +
      `<button class="action" id="auth-signup" type="button">Create free account</button>` +
      `<span id="auth-msg" style="font-size:13px;"></span></div>`;
    const doAuth = async path => {
      $('#auth-msg').textContent = '…';
      const res = await api(path, { method: 'POST', body: JSON.stringify(
        { email: $('#auth-email').value.trim(), password: $('#auth-pw').value }) });
      if (res.error) $('#auth-msg').textContent = res.error;
      else if (res.confirm_email) $('#auth-msg').textContent = 'Check your email to confirm, then sign in.';
      else loadBeta();
    };
    $('#auth-login').onclick = () => doAuth('/api/auth/login');
    $('#auth-signup').onclick = () => doAuth('/api/auth/signup');
  }
  const unlocked = !!st.beta_access;
  const feats = $('#beta-features');
  feats.style.opacity = unlocked ? '' : '0.45';
  feats.style.pointerEvents = unlocked ? '' : 'none';
  $('#beta-locked-note').style.display = unlocked ? 'none' : 'block';

  const s = b.stats || {corrections: 0, words: 0, reinforced: 0};
  $('#brain-tiles').innerHTML = [
    [s.words, 'learned words'], [s.corrections, 'corrections'],
    [s.reinforced, 'times reinforced'],
  ].map(([v,l]) => `<div class="tile"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join('');
  $('#brain-words').innerHTML = (b.words || []).map(w =>
    `<tr><td>${esc(w.word)}${w.manual ? ' <span style="font-size:11px;color:var(--text-muted)">(manual)</span>' : ''}</td>` +
    `<td class="num">${w.count}</td>` +
    `<td class="num"><button class="pag-btn" onclick="betaDelWord('${esc(w.word).replace(/'/g, "\\'")}')">✕</button></td></tr>`
  ).join('') || `<tr><td colspan="3" style="text-align:center;padding:16px;color:var(--text-muted)">Nothing learned yet.</td></tr>`;
  $('#brain-corrs').innerHTML = (b.corrections || []).map(c =>
    `<tr><td>${esc(c.original)}</td><td style="font-weight:600;">${esc(c.corrected)}</td>` +
    `<td class="num">${c.count}</td>` +
    `<td class="num"><button class="pag-btn" onclick="betaDelCorr(${c.id})">✕</button></td></tr>`
  ).join('') || `<tr><td colspan="4" style="text-align:center;padding:16px;color:var(--text-muted)">No corrections yet — edit a transcription in History.</td></tr>`;

  $('#beta-cfg').innerHTML = `<div class="cfg-grid">` +
    BETA_KEYS.filter(k => k in cfg).map(k => fieldHtml(k, cfg[k])).join('') + `</div>`;
}

const betaMsgTimers = {};
function betaMsg(sel, text) {
  const m = $(sel); m.textContent = text;
  clearTimeout(betaMsgTimers[sel]);
  betaMsgTimers[sel] = setTimeout(() => { m.textContent = ''; }, 6000);
}

async function betaDelWord(w) { await api('/api/brain/word', {method:'POST', body: JSON.stringify({word: w, delete: true})}); loadBeta(); }
async function betaDelCorr(id) { await api('/api/brain/correction-delete', {method:'POST', body: JSON.stringify({id})}); loadBeta(); }

$('#brain-add-btn').addEventListener('click', async () => {
  const w = $('#brain-add-word').value.trim();
  if (!w) return;
  await api('/api/brain/word', {method:'POST', body: JSON.stringify({word: w})});
  $('#brain-add-word').value = '';
  loadBeta();
});

$('#beta-save').addEventListener('click', async () => {
  if (capture) endCapture(true);
  const form = $('#beta-cfg');
  const data = {};
  for (const k of BETA_KEYS) {
    const hk = capturedValue(form, k);
    if (hk !== undefined) { data[k] = hk; continue; }
    const el = form.elements[k];
    if (!el) continue;
    data[k] = BOOLS.includes(k) ? el.checked : el.value;
  }
  await saveAndRestart(data, text => betaMsg('#beta-msg', text));
});

$('#fb-send').addEventListener('click', async () => {
  const title = $('#fb-title').value.trim(), body = $('#fb-body').value.trim();
  if (!title || !body) { betaMsg('#fb-msg', 'Title and details are required.'); return; }
  const res = await api('/api/feedback', {method:'POST', body: JSON.stringify({
    kind: $('#fb-kind').value, title, body,
    include_diagnostics: $('#fb-diag').checked})});
  if (res.ok) { betaMsg('#fb-msg', '✓ Thanks — feedback sent!'); $('#fb-title').value = ''; $('#fb-body').value = ''; }
  else betaMsg('#fb-msg', res.error || 'Failed to send.');
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

// --- First-run setup wizard (#/welcome) ---
// The step lives in the hash (#/welcome?step=N) so Back/Next, the browser's
// back button and "back to step 1" links all go through route().
const LEVEL_OK = 0.15;   // live mic level (0..1) that counts as "we can hear you"
const METER_SEGS = 24;
const wiz = {
  step: 0, gen: 0, timer: null, helpTimer: null, fast: false, docReq: 0,
  doctorOk: false, hk: null,
  sawRec: false, sawVoice: false, sawLock: false, meter: 0, quietMs: 0, lastTick: 0,
  baseId: 0, done3: false, rec3: false, stoppedAt: 0,
};

$('#wiz-meter').innerHTML = Array.from({length: METER_SEGS}, (_, i) =>
  `<i class="${i >= METER_SEGS * 0.85 ? 'r' : i >= METER_SEGS * 0.65 ? 'y' : ''}"></i>`).join('');

// Stops the wizard's pollers/timers. The generation counter makes any
// request already in flight drop its result.
function wizStop() {
  wiz.gen++;
  clearTimeout(wiz.timer);
  clearTimeout(wiz.helpTimer);
  wiz.timer = wiz.helpTimer = null;
  wiz.fast = false;
}
// Self-scheduling poll (never overlaps a slow request), bound to this generation.
function wizLoop(ms, fn) {
  const gen = wiz.gen;
  const tick = async () => {
    if (gen !== wiz.gen) return;
    try { await fn(gen); } catch (e) {}
    if (gen === wiz.gen) wiz.timer = setTimeout(tick, ms);
  };
  tick();
}

function wizShow(n) {
  n = Math.min(3, Math.max(1, n || 1));
  wizStop();
  wiz.step = n;
  for (let k = 1; k <= 3; k++) $('#wiz-step-' + k).hidden = k !== n;
  $('#wiz-back').disabled = n === 1;
  const next = $('#wiz-next');
  next.innerHTML = n === 3 ? 'Finish' : 'Next &rarr;';
  next.classList.remove('pulse');
  $('#wiz-skip').textContent = lsGet(ONBOARD_KEY) ? 'Close setup' : 'Skip setup';
  wizRenderProgress();
  // Park focus on the step: omnihear types into whatever has focus, and a
  // transcribed space/Enter must not press a button here.
  if (n !== 3) $('#wiz-step-' + n).focus({preventScroll: true});
  if (n === 1) wizStep1();
  else if (n === 2) wizStep2();
  else wizStep3();
}

function wizRenderProgress() {
  const done = {1: wiz.doctorOk, 2: wiz.sawRec && wiz.sawVoice, 3: wiz.done3};
  document.querySelectorAll('#wiz-progress li').forEach(li => {
    const k = +li.dataset.step;
    li.classList.toggle('active', k === wiz.step);
    li.classList.toggle('done', !!done[k]);
    if (k === wiz.step) li.setAttribute('aria-current', 'step');
    else li.removeAttribute('aria-current');
  });
}

function wizGo(n) { location.hash = '#/welcome?step=' + n; }
function wizFinish() { lsSet(ONBOARD_KEY, '1'); location.hash = '#/'; }

function keycaps(hk, display) {
  const parts = String(hk || '').split('+').filter(Boolean);
  if (!parts.length) return `<kbd class="keycap">${esc(display || 'your hotkey')}</kbd>`;
  return parts.map(p => `<kbd class="keycap">${esc(KEY_NAMES[p] || p.toUpperCase())}</kbd>`)
    .join('<span class="keycap-plus">+</span>');
}
function wizDrawKeys(s) {
  const hk = (s && s.hotkey) || '';
  if (hk === wiz.hk) return;
  wiz.hk = hk;
  const html = keycaps(hk, s && s.hotkey_display);
  document.querySelectorAll('[data-hotkey-caps]').forEach(el => { el.innerHTML = html; });
}

// Step 1: doctor checklist
function chipHtml(st) {
  const [icon, label] = st === 'ok' ? [ICON.check, 'OK'] : st === 'warn' ? [ICON.warn, 'Warn'] : [ICON.fail, 'Fail'];
  return `<span class="chip ${st}">${icon}${label}</span>`;
}
// Doctor details carry their fix commands in backticks: render each one as a
// code chip with its own Copy button.
function detailHtml(detail) {
  return String(detail || '').split('`').map((part, i) => (i % 2 && part.trim())
    ? `<span class="cmd"><code>${esc(part)}</code>${copyBtn(part, {title: 'Copy command'})}</span>`
    : esc(part)).join('');
}
async function wizStep1() {
  const req = ++wiz.docReq;
  const list = $('#wiz-checks'), sum = $('#wiz-summary'), btn = $('#wiz-recheck');
  btn.disabled = true;
  sum.className = 'wiz-summary';
  sum.innerHTML = '<span class="spinner"></span>Checking your setup&hellip;';
  if (!list.children.length)
    list.innerHTML = [62, 48, 74, 55].map(w =>
      `<li class="check-row"><span class="skel" style="width:58px"></span>` +
      `<span class="skel" style="width:${w}%"></span><span class="skel" style="width:${w + 20}%"></span></li>`).join('');
  let res;
  try { res = await api('/api/doctor'); }
  catch (e) {
    res = {rows: [{status: 'FAIL', label: 'setup check',
                   detail: 'could not reach omnihear — is it still running?'}]};
  }
  if (req !== wiz.docReq) return;  // a newer Re-check owns the screen
  btn.disabled = false;
  const rank = {FAIL: 0, warn: 1};
  const rows = (Array.isArray(res.rows) ? res.rows : [])
    .map((r, i) => [r, i])
    .sort((a, b) => ((rank[a[0].status] ?? 2) - (rank[b[0].status] ?? 2)) || a[1] - b[1])
    .map(x => x[0]);
  const fails = rows.filter(r => r.status === 'FAIL').length;
  const warns = rows.filter(r => r.status === 'warn').length;
  wiz.doctorOk = !fails;
  wizRenderProgress();
  list.innerHTML = rows.map(r => {
    const st = r.status === 'FAIL' ? 'fail' : r.status === 'warn' ? 'warn' : 'ok';
    return `<li class="check-row ${st}">${chipHtml(st)}<span class="check-label">${esc(r.label)}</span>` +
      `<span class="check-detail">${detailHtml(r.detail)}</span></li>`;
  }).join('');
  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  sum.className = 'wiz-summary ' + (fails ? 'fail' : warns ? 'warn' : 'ok');
  sum.innerHTML = fails
    ? `${ICON.fail}<span>${plural(fails, 'thing')} to fix <span class="sum-sub">&middot; run the fixes below, then Re-check</span></span>`
    : warns
      ? `${ICON.check}<span>All good <span class="sum-sub">&middot; ${plural(warns, 'optional suggestion')}</span></span>`
      : `${ICON.check}<span>All good <span class="sum-sub">&middot; omnihear has everything it needs</span></span>`;
}

// Step 2: live hotkey + microphone test
function wizStep2() {
  wiz.fast = true;  // the wizard polls status itself while this step is open
  wiz.meter = 0;
  wiz.lastTick = 0;
  wizUpdate2(Object.assign({}, lastStatus || {}, {recording: false, locked: false, level: 0}));
  wiz.helpTimer = setTimeout(() => { if (!wiz.sawRec) $('#wiz-help').hidden = false; }, 15000);
  wizLoop(120, async gen => {
    const s = await api('/api/status');
    if (gen !== wiz.gen) return;
    renderStatus(s);
    wizUpdate2(s);
  });
}
function wizUpdate2(s) {
  wizDrawKeys(s);
  const now = performance.now();
  const rec = !!s.recording, locked = !!s.locked, hf = !!s.hands_free;
  const lvl = Math.max(0, Math.min(1, Number(s.level) || 0));
  if (rec) {
    wiz.sawRec = true;
    if (lvl > LEVEL_OK) wiz.sawVoice = true;
    else if (!wiz.sawVoice && wiz.lastTick) wiz.quietMs += now - wiz.lastTick;
  }
  if (locked) wiz.sawLock = true;
  wiz.lastTick = rec ? now : 0;
  // Fast attack, slower release, so short syllables stay visible.
  wiz.meter = rec ? Math.max(lvl, wiz.meter * 0.72) : 0;
  const lit = Math.round(wiz.meter * METER_SEGS);
  const meter = $('#wiz-meter');
  meter.querySelectorAll('i').forEach((el, i) => el.classList.toggle('on', i < lit));
  meter.setAttribute('aria-valuenow', String(Math.round(wiz.meter * 100)));
  $('#wiz-level-txt').textContent = rec ? Math.round(lvl * 100) + '%' : '–';
  $('#wiz-keys').classList.toggle('pressed', rec && !locked);
  const orb = $('#wiz-orb');
  orb.classList.toggle('on', rec);
  orb.classList.toggle('locked', locked);
  $('#wiz-handsfree').hidden = !hf;
  $('#wiz-c-lock').hidden = !hf;
  $('#wiz-c-hotkey').classList.toggle('done', wiz.sawRec);
  $('#wiz-c-mic').classList.toggle('done', wiz.sawVoice);
  $('#wiz-c-lock').classList.toggle('done', wiz.sawLock);
  const txt = $('#wiz-orb-text');
  txt.classList.toggle('rec', rec);
  const msg = locked ? 'Locked — recording hands-free. Tap your hotkey once to stop.'
    : rec ? (lvl > LEVEL_OK ? 'Listening… we can hear you.' : 'Listening… say something.')
    : (wiz.sawRec && wiz.sawVoice) ? 'Your hotkey and microphone work. On to the next step!'
    : wiz.sawRec ? 'We saw your hotkey but heard nothing. Hold it again and speak up.'
    : hf ? 'Hold your hotkey (or double-tap it to lock) and say something…'
    : 'Hold your hotkey and say something…';
  if (txt.textContent !== msg) txt.textContent = msg;  // aria-live: announce changes only
  if (wiz.sawRec) $('#wiz-help').hidden = true;
  $('#wiz-mic-help').hidden = !(wiz.sawRec && !wiz.sawVoice && wiz.quietMs > 2500);
  $('#wiz-next').classList.toggle('pulse', wiz.step === 2 && wiz.sawRec && wiz.sawVoice);
  wizRenderProgress();
}

// Step 3: dictate into a practice box; success = text arrives in the box or
// a new history row appears (newest id beyond the one seen on entry).
function wizState3(cls, html) {
  const el = $('#wiz3-state');
  el.className = 'practice-state' + (cls ? ' ' + cls : '');
  setHTML(el, html);  // unchanged markup keeps its spinner spinning
}
async function wizStep3() {
  const gen = wiz.gen;
  const ta = $('#wiz-practice');
  if (lastStatus) wizDrawKeys(lastStatus);
  ta.classList.remove('rec');
  ta.focus({preventScroll: true});
  if (wiz.done3) { wizPaint3Done(); return; }
  wiz.rec3 = false;
  wiz.stoppedAt = 0;
  wizState3('', 'Waiting for you to dictate&hellip;');
  try {
    const rows = await api('/api/history?limit=1');
    if (gen !== wiz.gen) return;
    wiz.baseId = rows.length ? rows[0].id : 0;
  } catch (e) {
    if (gen !== wiz.gen) return;
    wiz.baseId = 0;
  }
  if (wiz.done3) return;  // text was typed while we fetched the baseline
  wiz.fast = true;
  let n = 0;
  wizLoop(250, async g => {
    const s = await api('/api/status');
    if (g !== wiz.gen) return;
    renderStatus(s);
    wizUpdate3(s);
    if (++n % 3 === 0 && !wiz.done3) {
      const rows = await api('/api/history?limit=1');
      if (g !== wiz.gen) return;
      if (rows.length && rows[0].id > wiz.baseId) wizSuccess3(rows[0]);
    }
  });
}
function wizUpdate3(s) {
  if (wiz.done3) return;
  const ta = $('#wiz-practice');
  const rec = !!s.recording;
  ta.classList.toggle('rec', rec);
  if (rec) {
    wiz.rec3 = true;
    wiz.stoppedAt = 0;
    // omnihear types into whatever has focus: make that the practice box.
    if (document.activeElement !== ta) ta.focus({preventScroll: true});
    wizState3('rec', `<span class="dot"></span>${s.locked ? 'Locked — tap your hotkey to stop' : 'Listening… let go when you’re done'}`);
  } else if (wiz.rec3) {
    if (!wiz.stoppedAt) wiz.stoppedAt = Date.now();
    const waited = Date.now() - wiz.stoppedAt;
    if (waited < 90000 && !s.model_loaded)
      wizState3('busy', '<span class="spinner"></span>Loading the speech model&hellip; the first time can take a minute.');
    else if (waited < 12000)
      wizState3('busy', '<span class="spinner"></span>Transcribing&hellip;');
    else
      wizState3('warn', 'Nothing came through. Hold the hotkey a little longer and speak clearly, ' +
        'or check <a class="inline-link" href="#/welcome?step=2">Step 2</a>.');
  } else {
    wizState3('', 'Waiting for you to dictate&hellip;');
  }
}
function wizSuccess3(row) {
  if (wiz.done3) return;
  wiz.done3 = true;
  wizStop();  // done polling; the 1 s status poll takes over
  const ta = $('#wiz-practice');
  ta.classList.remove('rec');
  const heard = row ? (row.corrected_text || row.text || '') : '';
  $('#wiz3-heard').textContent = heard ? `omnihear heard: “${heard}”` : '';
  wizPaint3Done();
  confetti($('#wiz3-success'));
  // Typing happens before the history insert, so an empty box by now means
  // the text went somewhere else.
  if (row && !ta.value.trim())
    wiz.helpTimer = setTimeout(() => {
      if (ta.value.trim()) return;
      // Transcription works but insertion didn't reach the box: don't claim
      // full success next to the "didn't land" hint.
      $('#wiz3-title').textContent = WIZ3_TITLE_PARTIAL;
      $('#wiz3-nottyped').hidden = false;
    }, 2000);
}
const WIZ3_TITLE_OK = 'It works — you’re ready to dictate!';
const WIZ3_TITLE_PARTIAL = 'Almost there: omnihear heard you';
function wizPaint3Done() {
  wizState3('ok', `${ICON.check}Dictation works!`);
  $('#wiz3-success').hidden = false;
  $('#wiz-next').classList.add('pulse');
  wizRenderProgress();
}
function confetti(host) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];
  const box = document.createElement('div');
  box.className = 'confetti';
  box.setAttribute('aria-hidden', 'true');
  for (let i = 0; i < 28; i++) {
    const p = document.createElement('i');
    const a = (i / 28) * Math.PI * 2 + Math.random() * 0.4;
    const d = 45 + Math.random() * 85;
    p.style.setProperty('--x', (Math.cos(a) * d).toFixed(1) + 'px');
    p.style.setProperty('--y', (Math.sin(a) * d * 0.75 + 28).toFixed(1) + 'px');
    p.style.setProperty('--r', Math.round(Math.random() * 720 - 360) + 'deg');
    p.style.background = colors[i % colors.length];
    p.style.animationDelay = Math.round(Math.random() * 90) + 'ms';
    box.appendChild(p);
  }
  host.appendChild(box);
  setTimeout(() => box.remove(), 1500);
}

$('#wiz-back').addEventListener('click', () => wizGo(Math.max(1, wiz.step - 1)));
$('#wiz-next').addEventListener('click', () => wiz.step >= 3 ? wizFinish() : wizGo(wiz.step + 1));
$('#wiz-skip').addEventListener('click', wizFinish);
$('#wiz-recheck').addEventListener('click', wizStep1);
$('#wiz-practice').addEventListener('input', () => {
  const has = !!$('#wiz-practice').value.trim();
  if (has) { $('#wiz3-nottyped').hidden = true; $('#wiz3-title').textContent = WIZ3_TITLE_OK; }
  if (has && wiz.step === 3 && !wiz.done3) wizSuccess3(null);
});
$('#wiz3-again').addEventListener('click', () => {
  wiz.done3 = false;
  $('#wiz-practice').value = '';
  $('#wiz3-heard').textContent = '';
  $('#wiz3-success').hidden = true;
  $('#wiz3-nottyped').hidden = true;
  $('#wiz3-title').textContent = WIZ3_TITLE_OK;
  wizShow(3);
});
// Step 2 has nothing to type into, but omnihear still "types" the transcript
// into this window. Swallow plain printable keys aimed at the page itself so
// a space can't scroll and a ' or / can't open Firefox's quick-find bar.
// Shortcuts, Tab, and keys aimed at controls pass through.
document.addEventListener('keydown', e => {
  if (capture || wiz.step !== 2 || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.target !== document.body && e.target !== $('#wiz-step-2')) return;
  if (e.key.length === 1 || e.key === 'Enter') e.preventDefault();
});
document.querySelectorAll('[data-os]').forEach(el => { el.hidden = el.dataset.os !== PLATFORM; });

// --- Startup & Polling ---
// First visit with no history yet: open the setup wizard instead of an empty
// dashboard (once the user finishes or skips, the flag keeps it closed).
async function boot() {
  const h = getHash();
  if (!lsGet(ONBOARD_KEY) && (h === '#/' || h === '#')) {
    try {
      const rows = await api('/api/history?limit=1');
      if (Array.isArray(rows) && !rows.length && getHash() === h)
        history.replaceState(null, '', '#/welcome');
    } catch (e) {}
  }
  route();
}
window.addEventListener('hashchange', route);
loadStatus();
loadConfig();
boot();

setInterval(() => { if (!wiz.fast) loadStatus(); }, 1000);
setInterval(() => { if (!isRecording) refreshCurrentScreen(); }, 8000);
</script>
</body>
</html>
"""


def _auth_error(e: Exception) -> str:
    """Human-readable message from a Supabase/urllib failure."""
    try:
        import urllib.error
        if isinstance(e, urllib.error.HTTPError):
            body = json.loads(e.read() or b"{}")
            return (body.get("msg") or body.get("error_description")
                    or body.get("message") or f"HTTP {e.code}")
    except Exception:
        pass
    return str(e) or "network error"


def _doctor_report(cfg: dict | None) -> dict:
    """`omnihear --doctor` rows for the setup wizard (read-only).

    Checks the running process's effective config when there is one. Never
    raises: a crashing check becomes a FAIL row instead of an HTTP 500, so
    the page can still say something useful.
    """
    try:
        from . import doctor
        rows = [{"status": status, "label": label, "detail": detail}
                for status, label, detail in doctor.checks(cfg or config_mod.load_config())]
    except Exception as e:
        rows = [{"status": "FAIL", "label": "setup check",
                 "detail": f"could not run the setup checks: {e}"}]
    return {"rows": rows, "ok": not any(r["status"] == "FAIL" for r in rows)}


# Identifies this process to the page, so after a restart it can tell the
# new omnihear is up (GET /api/status returns it as "boot").
_BOOT_ID = f"{os.getpid()}-{time.time():.0f}"


def _can_restart() -> bool:
    """Whether POST /api/restart can bring omnihear back by itself: Windows
    and macOS re-exec in place; Linux only under systemd (a terminal run
    would just exit)."""
    return sys.platform in ("win32", "darwin") or bool(os.environ.get("INVOCATION_ID"))


def _overlay_js_consts() -> dict:
    """Overlay option lists, ranges and base geometry for the Settings
    preview, so the page never duplicates overlay_anim.py / config.py."""
    from . import overlay_anim as oa
    keys = ("overlay_bg_color", "overlay_bar_color", "overlay_dot_color")
    return {
        "positions": list(oa.POSITIONS), "shapes": list(oa.SHAPES),
        "bar_shapes": list(oa.BAR_SHAPES),
        "ranges": {k: list(v) for k, v in config_mod.OVERLAY_RANGES.items()},
        "defaults": {k: config_mod.DEFAULTS[k] for k in keys},
        "busy": [round(c * 255) for c in oa.BUSY],
        "base": {
            "pill_h": oa.PILL_H, "dot_cx": oa.DOT_CX, "dot_r": oa.DOT_R,
            "spinner_r": oa.SPINNER_R, "bars_x0": oa.BARS_X0,
            "n_bars": oa.N_BARS, "bar_w": oa.BAR_W, "bar_gap": oa.BAR_GAP,
            "bar_max": oa.BAR_MAX, "margin_bottom": oa.MARGIN_BOTTOM,
            "margin_top": oa.MARGIN_TOP, "margin_side": oa.MARGIN_SIDE,
        },
    }


class DashboardHandler(BaseHTTPRequestHandler):
    # set on the server: server.db, server.status_fn, server.brain, server.cfg

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json", headers=()):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
            return body
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "invalid JSON body"})
            return None

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
                             json.dumps(config_mod.LANGUAGE_NAMES))
                    .replace("__CLEANUP_LEVELS__",
                             json.dumps(list(config_mod.CLEANUP_LEVELS)))
                    .replace("__PLATFORM__", json.dumps(sys.platform))
                    .replace("__OVERLAY__", json.dumps(_overlay_js_consts()))
                    .replace("__TYPE_METHODS__",
                             json.dumps(["auto", "pynput", "paste"]
                                        if sys.platform in ("win32", "darwin")
                                        else list(config_mod.TYPE_METHODS))))
            # Anti-clickjacking: refuse to be framed by any page. The
            # _request_allowed() CSRF guard can't help here, since requests
            # made by a framed dashboard are same-origin. Only
            # frame-ancestors -- a fuller CSP would block PAGE's inline
            # <script>/<style>. Nothing legitimately frames the dashboard
            # (tray.py opens it top-level).
            self._send(200, page.encode(), "text/html; charset=utf-8",
                       headers=(("X-Frame-Options", "DENY"),
                                ("Content-Security-Policy",
                                 "frame-ancestors 'none'")))
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
        elif url.path == "/api/brain":
            brain = getattr(self.server, "brain", None)
            from . import cloud
            out = {"beta": cloud.status(), "enabled": brain is not None}
            if brain is not None:
                out.update(stats=brain.stats(), words=brain.list_words(),
                           corrections=brain.list_corrections())
            self._send(200, out)
        elif url.path == "/api/auth/status":
            from . import cloud
            self._send(200, cloud.status())
        elif url.path == "/api/doctor":
            self._send(200, _doctor_report(getattr(self.server, "cfg", None)))
        elif url.path == "/api/status":
            st = dict(self.server.status_fn())
            st["boot"] = _BOOT_ID   # changes when omnihear restarts
            if sys.platform == "darwin":
                try:
                    from . import macos_permissions as macperm
                    st["permissions"] = macperm.check()
                except Exception:
                    pass
            self._send(200, st)
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
            changed = []
            if clean:
                cfg = config_mod.load_config()
                changed = sorted(k for k, v in clean.items() if cfg.get(k) != v)
                cfg.update(clean)
                config_mod.save_config(cfg)
            msg = ("Saved." if changed else
                   "No changes." if clean else "Nothing saved.")
            # The page restarts omnihear itself when `changed` is non-empty.
            self._send(200, {"saved": sorted(clean), "changed": changed,
                             "errors": errors, "message": msg,
                             "can_restart": _can_restart()})
        elif url.path == "/api/restart":
            if not _can_restart():
                self._send(200, {"restarting": False, "message":
                                 "Not running under systemd; restart omnihear manually."})
            elif sys.platform in ("win32", "darwin"):
                # Frozen (PyInstaller) argv[0] is the exe itself; drop it so
                # the relaunch doesn't get its own path as a positional arg.
                threading.Timer(0.5, lambda: os.execv(
                    sys.executable, [sys.executable] + sys.argv[1:]
                )).start()
                self._send(200, {"restarting": True, "message": "Restarting…"})
            else:
                # Running under systemd: ask it to restart us.
                threading.Timer(0.5, lambda: subprocess.Popen(
                    ["systemctl", "--user", "restart", "omnihear"]
                )).start()
                self._send(200, {"restarting": True,
                                 "message": "Restarting via systemd…"})
        elif url.path == "/api/correction":
            body = self._json_body()
            if body is None:
                return
            db, brain = self.server.db, getattr(self.server, "brain", None)
            row_id, text = body.get("id"), (body.get("text") or "").strip()
            if db is None or not isinstance(row_id, int) or not text:
                self._send(400, {"error": "need id and text"})
                return
            row = db.get(row_id)
            if row is None:
                self._send(404, {"error": "not found"})
                return
            db.set_corrected(row_id, text)
            learned = []
            from . import cloud
            if brain is not None and cloud.beta_active():
                learned = brain.learn_correction(row["text"], text, row_id)
            self._send(200, {"ok": True, "learned": learned})
        elif url.path in ("/api/auth/login", "/api/auth/signup"):
            body = self._json_body()
            if body is None:
                return
            from . import cloud
            try:
                fn = cloud.sign_in if url.path.endswith("login") else cloud.sign_up
                self._send(200, fn(body.get("email", ""), body.get("password", "")))
            except Exception as e:
                self._send(200, {"error": _auth_error(e)})
        elif url.path == "/api/auth/logout":
            from . import cloud
            cloud.sign_out()
            self._send(200, {"ok": True})
        elif url.path == "/api/brain/word":
            body = self._json_body()
            if body is None:
                return
            brain = getattr(self.server, "brain", None)
            word = (body.get("word") or "").strip()
            if brain is None or not word:
                self._send(400, {"error": "brain disabled or empty word"})
                return
            if body.get("delete"):
                brain.delete_word(word)
            else:
                brain.add_word(word)
            self._send(200, {"ok": True})
        elif url.path == "/api/brain/correction-delete":
            body = self._json_body()
            if body is None:
                return
            brain = getattr(self.server, "brain", None)
            if brain is None or not isinstance(body.get("id"), int):
                self._send(400, {"error": "brain disabled or bad id"})
                return
            brain.delete_correction(body["id"])
            self._send(200, {"ok": True})
        elif url.path == "/api/feedback":
            body = self._json_body()
            if body is None:
                return
            from . import cloud
            diagnostics = None
            if body.get("include_diagnostics") and self.server.db is not None:
                # metrics only — never transcript text
                rows = self.server.db.search(limit=50)
                diagnostics = json.dumps([
                    {k: r.get(k) for k in ("ts", "audio_seconds", "transcribe_ms",
                                           "model", "cpu_percent", "memory_mb",
                                           "avg_logprob", "no_speech_prob",
                                           "compression_ratio")}
                    for r in rows])
            try:
                self._send(200, cloud.submit_feedback(
                    body.get("kind", ""), (body.get("title") or "").strip(),
                    (body.get("body") or "").strip(), diagnostics))
            except Exception as e:
                self._send(200, {"error": _auth_error(e)})
        elif url.path == "/api/open-settings":
            name = ""
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                name = body.get("name", "") if isinstance(body, dict) else ""
            except (ValueError, json.JSONDecodeError):
                self._send(400, {"error": "invalid JSON body"})
                return
            opened = False
            if sys.platform == "darwin":
                try:
                    from . import macos_permissions as macperm
                    opened = macperm.open_settings_pane(name)
                except Exception:
                    pass
            self._send(200, {"opened": opened})
        else:
            self._send(404, {"error": "not found"})


def start_dashboard(db, status_fn, port: int = 4738, brain=None, cfg=None):
    """Start the dashboard server on 127.0.0.1 in a daemon thread.

    cfg is the running process's effective config (CLI flags applied), for
    endpoints that report on the live setup; None falls back to the file.
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
    server.brain = brain
    server.cfg = cfg
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"omnihear: dashboard at http://127.0.0.1:{port}")
    return server
