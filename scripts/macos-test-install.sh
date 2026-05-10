#!/usr/bin/env bash
# build + sign + notarize, fake quarantine xattr, mount dmg
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

source .venv/bin/activate
source .env-mac.sh

"$SCRIPT_DIR/macos-release.sh"

DMG="target/Emu68 Hatcher.dmg"
xattr -w com.apple.quarantine "0083;$(printf %x "$(date +%s)");Safari;0" "$DMG"
open "$DMG"
