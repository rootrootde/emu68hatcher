#!/usr/bin/env bash
# sign a .app bundle for Developer ID distribution (hardened runtime + notarizable)
#
# usage:
#   scripts/macos-sign.sh "target/Emu68 Hatcher.app"
#
# env:
#   MACOS_SIGN_IDENTITY = "Developer ID Application: Name (TEAMID)"
set -euo pipefail

BUNDLE="${1:?path to .app required}"
IDENTITY="${MACOS_SIGN_IDENTITY:?env var MACOS_SIGN_IDENTITY required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENT_FILE="$REPO_ROOT/src/build/settings/mac.entitlements"

if [[ ! -d "$BUNDLE" ]]; then
    echo "bundle not found: $BUNDLE" >&2
    exit 1
fi
if [[ ! -f "$ENT_FILE" ]]; then
    echo "entitlements not found: $ENT_FILE" >&2
    exit 1
fi

echo "[sign] bundle:       $BUNDLE"
echo "[sign] identity:     $IDENTITY"
echo "[sign] entitlements: $ENT_FILE"

# strip xattrs that interfere with signing (quarantine, FinderInfo, etc)
xattr -cr "$BUNDLE"

sign_one() {
    codesign --force \
             --sign "$IDENTITY" \
             --options runtime \
             --entitlements "$ENT_FILE" \
             --timestamp \
             "$1"
}

# phase 1: every Mach-O file (binaries + dylibs + framework-internal libs without extensions)
# -depth processes leaves before parents; file-magic check avoids signing shell scripts etc.
echo "[sign] phase 1: Mach-O files"
while IFS= read -r f; do
    if file -b "$f" 2>/dev/null | grep -q "Mach-O"; then
        echo "  $f"
        sign_one "$f"
    fi
done < <(find "$BUNDLE" -depth -type f)

# phase 2: framework bundles (dirs ending in .framework)
echo "[sign] phase 2: frameworks"
while IFS= read -r fw; do
    echo "  $fw"
    sign_one "$fw"
done < <(find "$BUNDLE" -depth -type d -name "*.framework")

# phase 3: the .app itself
echo "[sign] phase 3: app bundle"
sign_one "$BUNDLE"

echo "[sign] verifying signature..."
codesign --verify --deep --strict --verbose=2 "$BUNDLE"

echo "[sign] running Gatekeeper assessment..."
# spctl returns non-zero on a notarized-but-not-yet-stapled app; that's expected pre-notarization
spctl --assess --type execute --verbose=4 "$BUNDLE" || echo "[sign] spctl rejected (expected before notarization)"

echo "[sign] done: $BUNDLE"
