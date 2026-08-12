#!/usr/bin/env bash
set -euo pipefail

DMG="${1:?path to .dmg required}"

if [[ ! -f "$DMG" ]]; then
    echo "disk image not found: $DMG" >&2
    exit 1
fi

MOUNT_DIR="$(mktemp -d)"
MOUNTED=false

cleanup() {
    if [[ "$MOUNTED" == true ]]; then
        hdiutil detach "$MOUNT_DIR" >/dev/null
    fi
    rmdir "$MOUNT_DIR"
}
trap cleanup EXIT

hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT_DIR" "$DMG" >/dev/null
MOUNTED=true

APP="$(find "$MOUNT_DIR" -maxdepth 2 -type d -name '*.app' -print -quit)"
if [[ -z "$APP" ]]; then
    echo "app bundle not found in $DMG" >&2
    exit 1
fi

codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose=4 "$APP"
