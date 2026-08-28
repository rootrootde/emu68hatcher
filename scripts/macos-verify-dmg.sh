#!/usr/bin/env bash
set -euo pipefail

DMG="${1:?path to .dmg required}"

if [[ ! -f "$DMG" ]]; then
    echo "disk image not found: $DMG" >&2
    exit 1
fi

MOUNT_DIR="$(mktemp -d)"
MOUNTED=false
APP_PID=""

cleanup() {
    if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
        kill -TERM "$APP_PID"
        wait "$APP_PID" || true
    fi
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

EXECUTABLE_NAME="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist")"
EXECUTABLE="$APP/Contents/MacOS/$EXECUTABLE_NAME"
if [[ ! -x "$EXECUTABLE" ]]; then
    echo "app executable not found: $EXECUTABLE" >&2
    exit 1
fi

RUN_DIR="$(mktemp -d)"
LAUNCH_LOG="$RUN_DIR/launch.log"
(
    cd "$RUN_DIR"
    exec env HATCHER_HOME="$RUN_DIR/data" QT_QPA_PLATFORM=offscreen "$EXECUTABLE"
) >"$LAUNCH_LOG" 2>&1 &
APP_PID=$!

for _ in {1..30}; do
    if ! kill -0 "$APP_PID" 2>/dev/null; then
        wait "$APP_PID" || true
        APP_PID=""
        cat "$LAUNCH_LOG"
        exit 1
    fi
    sleep 0.1
done

kill -TERM "$APP_PID"
wait "$APP_PID" || true
APP_PID=""
