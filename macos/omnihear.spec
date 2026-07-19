# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the macOS Omnihear.app (Apple Silicon / arm64).

Build:  OMNIHEAR_VERSION=1.4.0 pyinstaller macos/omnihear.spec
Produces dist/omnihear.app. Run macos/make-icns.sh first so the icon exists.

Deps are frozen in at build time (no runtime pip / venv), mirroring the
Windows PyInstaller build. The Info.plist declares:
  * LSUIElement           -> menu-bar agent, no Dock icon
  * NSMicrophoneUsageDescription -> required or the mic access crashes on
    modern macOS; also drives the Privacy prompt.
"""

import os

from PyInstaller.utils.hooks import collect_all

# The ML native deps and their data files must be pulled in explicitly.
datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Tray menu-bar icon, loaded from sys._MEIPASS at runtime (see tray.py).
here = os.path.abspath(os.path.join(SPECPATH))
datas += [(os.path.join(here, "omnihear.png"), ".")]

version = os.environ.get("OMNIHEAR_VERSION", "0.0.0")

a = Analysis(
    [os.path.join(here, "entry.py")],
    pathex=[os.path.join(here, "..", "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="omnihear",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
    codesign_identity=None,   # macos/sign.sh handles signing post-build
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="omnihear",
)

app = BUNDLE(
    coll,
    name="omnihear.app",
    icon=os.path.join(here, "omnihear.icns"),
    bundle_identifier="com.omnihear.app",
    version=version,
    info_plist={
        "LSUIElement": True,
        "NSMicrophoneUsageDescription":
            "Omnihear records audio to transcribe your speech locally.",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    },
)
