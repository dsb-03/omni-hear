#!/bin/bash
# Optional Developer-ID signing + notarization. NO-OP unless the signing
# environment is present, so the unsigned build path just works.
#
#   ./macos/sign.sh app              # codesign dist/omnihear.app  (before build-dmg.sh)
#   ./macos/sign.sh dmg <file.dmg>   # notarize + staple the DMG   (after  build-dmg.sh)
#
# Environment (set these — e.g. from CI secrets — to enable signing):
#   APPLE_SIGN_IDENTITY  "Developer ID Application: Name (TEAMID)"
#   APPLE_TEAM_ID        10-char team id
#   APPLE_ID             Apple account email        (notarization only)
#   APPLE_APP_PASSWORD   app-specific password      (notarization only)
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:?Usage: sign.sh app | sign.sh dmg <file.dmg>}"

if [ -z "$APPLE_SIGN_IDENTITY" ]; then
  echo "sign.sh: APPLE_SIGN_IDENTITY not set -- skipping ($MODE); build stays unsigned."
  exit 0
fi

case "$MODE" in
  app)
    APP="dist/omnihear.app"
    [ -d "$APP" ] || { echo "missing $APP" >&2; exit 1; }
    echo "sign.sh: codesigning $APP"
    codesign --force --deep --timestamp --options runtime \
      --entitlements "$DIR/entitlements.plist" \
      --sign "$APPLE_SIGN_IDENTITY" "$APP"
    codesign --verify --strict --verbose=2 "$APP"
    ;;
  dmg)
    DMG="${2:?Usage: sign.sh dmg <file.dmg>}"
    [ -f "$DMG" ] || { echo "missing $DMG" >&2; exit 1; }
    # Sign the DMG container itself, then notarize + staple.
    codesign --force --timestamp --sign "$APPLE_SIGN_IDENTITY" "$DMG"
    echo "sign.sh: submitting $DMG to notary service"
    xcrun notarytool submit "$DMG" \
      --apple-id "$APPLE_ID" \
      --team-id "$APPLE_TEAM_ID" \
      --password "$APPLE_APP_PASSWORD" \
      --wait
    xcrun stapler staple "$DMG"
    ;;
  *)
    echo "unknown mode: $MODE" >&2; exit 1 ;;
esac
