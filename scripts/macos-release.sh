#!/usr/bin/env bash
# end-to-end signed + notarized .dmg build, for local testing
#
# usage:
#   export MACOS_SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"
#   export APPLE_ID="..."
#   export APPLE_TEAM_ID="..."
#   export APPLE_APP_PWD="..."
#   scripts/macos-release.sh
#
# produces a signed + notarized + stapled "target/Emu68 Hatcher.dmg"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

: "${MACOS_SIGN_IDENTITY:?env MACOS_SIGN_IDENTITY required}"
# notarize.sh accepts either APPLE_NOTARY_PROFILE or direct creds; let it validate
if [[ -z "${APPLE_NOTARY_PROFILE:-}" ]]; then
    : "${APPLE_ID:?set APPLE_NOTARY_PROFILE or APPLE_ID/APPLE_TEAM_ID/APPLE_APP_PWD}"
    : "${APPLE_TEAM_ID:?env APPLE_TEAM_ID required}"
    : "${APPLE_APP_PWD:?env APPLE_APP_PWD required}"
fi

APP="target/Emu68 Hatcher.app"
DMG="target/Emu68 Hatcher.dmg"

echo "=== fbs freeze ==="
fbs freeze

# fbs leaves CFBundleIdentifier empty - TCC needs a non-empty id to file FDA grants
echo "=== patch CFBundleIdentifier ==="
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.emu68hatcher.hatcher" "$APP/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.emu68hatcher.hatcher" "$APP/Contents/Info.plist"

echo "=== sign app ==="
"$SCRIPT_DIR/macos-sign.sh" "$APP"

echo "=== fbs installer (builds dmg from signed app) ==="
fbs installer

echo "=== sign dmg ==="
codesign --force --sign "$MACOS_SIGN_IDENTITY" --timestamp "$DMG"

echo "=== notarize + staple dmg ==="
"$SCRIPT_DIR/macos-notarize.sh" "$DMG"

echo
echo "=== done ==="
ls -lh "$DMG"
echo "Gatekeeper acceptance:"
spctl --assess --type open --context context:primary-signature -v "$DMG"
