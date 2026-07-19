#!/bin/bash
# Build macos/omnihear.icns from the 1024x1024 source macos/omnihear.png,
# using the stock macOS tools (sips + iconutil). Run before pyinstaller.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/omnihear.png"
ICONSET="$DIR/omnihear.iconset"
OUT="$DIR/omnihear.icns"

[ -f "$SRC" ] || { echo "missing $SRC" >&2; exit 1; }

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# Apple's required iconset sizes (1x and 2x).
for size in 16 32 128 256 512; do
  sips -z "$size" "$size"       "$SRC" --out "$ICONSET/icon_${size}x${size}.png"      >/dev/null
  d=$((size * 2))
  sips -z "$d" "$d"             "$SRC" --out "$ICONSET/icon_${size}x${size}@2x.png"   >/dev/null
done

iconutil -c icns "$ICONSET" -o "$OUT"
rm -rf "$ICONSET"
echo "Built $OUT"
