"""macOS and Linux elevation acquisition."""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from emu68hatcher.builder.host._elevation_common import (
    ElevationDenied,
    ElevationToken,
    run_sudo_validate,
)
from emu68hatcher.utils.platform import OperatingSystem

logger = logging.getLogger(__name__)

_MACOS_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    "/usr/bin/osascript "
    '-e \'display dialog "Emu68 Hatcher needs admin access to write to the SD card." '
    'default answer "" with hidden answer with title "Emu68 Hatcher" with icon caution\' '
    "-e 'text returned of result' 2>/dev/null\n"
)
_LINUX_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    'PROMPT="${1:-Password:}"\n'
    'if [ -n "$WAYLAND_DISPLAY" ] || [ -n "$DISPLAY" ]; then\n'
    "  if command -v zenity >/dev/null 2>&1; then\n"
    '    exec zenity --password --title "Emu68 Hatcher" 2>/dev/null\n'
    "  elif command -v kdialog >/dev/null 2>&1; then\n"
    '    exec kdialog --password "$PROMPT" 2>/dev/null\n'
    "  elif [ -x /usr/lib/seahorse/ssh-askpass ]; then\n"
    '    exec /usr/lib/seahorse/ssh-askpass "$PROMPT"\n'
    "  elif [ -x /usr/bin/ksshaskpass ]; then\n"
    '    exec /usr/bin/ksshaskpass "$PROMPT"\n'
    "  elif command -v ssh-askpass >/dev/null 2>&1; then\n"
    '    exec ssh-askpass "$PROMPT"\n'
    "  fi\n"
    "fi\n"
    "exit 1\n"
)


def remove_askpass(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        logger.warning(f"could not remove askpass helper {path}: {error}")


def _write_askpass(script: str) -> Path:
    import tempfile

    descriptor, path = tempfile.mkstemp(prefix="emu68hatcher-askpass-", suffix=".sh")
    try:
        os.write(descriptor, script.encode())
    finally:
        os.close(descriptor)
    os.chmod(path, 0o700)
    return Path(path)


def acquire_macos() -> ElevationToken:
    have_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    if have_tty:
        askpass = _write_askpass(_MACOS_ASKPASS_SCRIPT)
        try:
            run_sudo_validate(askpass)
        except (subprocess.CalledProcessError, subprocess.SubprocessError, OSError) as error:
            remove_askpass(askpass)
            detail = getattr(error, "stderr", None) or getattr(error, "stdout", None) or error
            raise ElevationDenied(f"admin prompt cancelled or denied: {detail}") from error
        return ElevationToken(OperatingSystem.MACOS, "sudo", askpass_path=askpass)

    from emu68hatcher.builder.host.elevated_helper import ElevatedHelper

    helper = ElevatedHelper()
    if helper.spawn():
        return ElevationToken(OperatingSystem.MACOS, "osascript-helper", helper=helper)
    raise ElevationDenied(
        "macos admin prompt cancelled or osascript helper failed to start. "
        "launch the app from Terminal and try again."
    )


def acquire_linux() -> ElevationToken:
    have_gui = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    have_tty = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False
    if have_gui and shutil.which("sudo"):
        askpass = _write_askpass(_LINUX_ASKPASS_SCRIPT)
        try:
            run_sudo_validate(askpass)
            return ElevationToken(OperatingSystem.LINUX, "sudo", askpass_path=askpass)
        except (subprocess.CalledProcessError, subprocess.SubprocessError, OSError) as error:
            logger.info(f"sudo -A unavailable ({error}); trying pkexec")
            remove_askpass(askpass)
    if have_tty and shutil.which("sudo"):
        try:
            subprocess.run(["sudo", "-v"], check=True, timeout=120)
            return ElevationToken(OperatingSystem.LINUX, "sudo")
        except (subprocess.CalledProcessError, subprocess.SubprocessError, OSError) as error:
            logger.info(f"sudo unavailable ({error}); trying pkexec")
    if shutil.which("pkexec"):
        try:
            subprocess.run(
                ["pkexec", "true"],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return ElevationToken(OperatingSystem.LINUX, "pkexec")
        except subprocess.CalledProcessError as error:
            raise ElevationDenied(f"pkexec rejected (rc={error.returncode})") from error
        except (OSError, subprocess.SubprocessError) as error:
            raise ElevationDenied(f"pkexec failed: {error}") from error
    raise ElevationDenied(
        "no GUI askpass tool found and no terminal or pkexec available; "
        "install zenity or run from a terminal"
    )
