#!/bin/bash
# Package dist/omnihear.app into a drag-to-install DMG.
# Usage: ./macos/build-dmg.sh <version>
# Produces: omnihear-<version>-arm64.dmg (in the repo root).
set -e

VERSION="${1:?Usage: ./macos/build-dmg.sh <version, e.g. 1.4.0>}"
APP="dist/omnihear.app"
DMG="omnihear-${VERSION}-arm64.dmg"
STAGE="dist/dmg-stage"

[ -d "$APP" ] || { echo "missing $APP -- run pyinstaller macos/omnihear.spec first" >&2; exit 1; }

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
# Drag-to-install target.
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "Omnihear" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "Built $DMG"
