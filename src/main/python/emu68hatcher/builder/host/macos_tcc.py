"""trigger tccd to file hst-imager so it appears in full disk access"""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def register_hst_imager_with_tcc(hst_imager: Path) -> bool:
    """one osascript prompt + a deliberate eperm probe files the binary with tccd"""
    if not hst_imager.is_file():
        return False
    # probe /dev/disk0 (always present); root + tcc denial registers the subject
    inner = f"{shlex.quote(str(hst_imager))} info /dev/disk0 >/dev/null 2>&1 ; true"
    escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
    prompt = (
        "Emu68 Hatcher needs to register hst-imager with macOS "
        "so it appears in Full Disk Access.\n\n"
        "Enter your password once, then enable hst-imager "
        "in the settings pane that opens next."
    )
    prompt_esc = prompt.replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "{escaped}" with administrator privileges with prompt "{prompt_esc}"'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=120,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"tcc registration probe failed: {e}")
        return False
    # rc != 0 = user cancelled the prompt; nothing was registered
    return result.returncode == 0


def open_full_disk_access_pane() -> bool:
    """open system settings -> privacy & security -> full disk access"""
    url = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    try:
        subprocess.run(["open", url], check=False, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"failed to open FDA settings: {e}")
        return False
