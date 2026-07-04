"""per-OS privilege escalation for raw-disk operations"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from emu68hatcher.utils.host_tools import get_hst_imager_env
from emu68hatcher.utils.paths import DOTNET_BUNDLE_ENV_VAR, get_dotnet_bundle_dir
from emu68hatcher.utils.platform import OperatingSystem, get_platform_info, is_root

logger = logging.getLogger(__name__)


class ElevationDenied(RuntimeError):
    """user cancelled the auth prompt or no method available"""


@dataclass
class ElevationToken:
    """marker that an interactive auth prompt succeeded"""

    os: OperatingSystem
    method: str  # "pkexec" | "sudo" | "runas" | "runas-helper" | "osascript-helper" | "noop"
    helper: object | None = None  # ElevatedHelper when method ends with "-helper"
    askpass_path: Path | None = None  # kept alive for sudo timestamp refresh on long builds


def acquire_elevation() -> ElevationToken:
    """one prompt; later run_elevated calls within the cache window dont re-prompt"""
    info = get_platform_info()
    if is_root():
        logger.info("already root - skipping interactive elevation")
        return ElevationToken(os=info.os, method="noop")

    if info.os == OperatingSystem.MACOS:
        return _acquire_macos()
    if info.os == OperatingSystem.LINUX:
        return _acquire_linux()
    if info.os == OperatingSystem.WINDOWS:
        return _acquire_windows()
    raise ElevationDenied(f"unsupported OS: {info.os}")


def _ps_quote(s: str) -> str:
    """powershell single-quoted literal (doubles internal ')"""
    return "'" + str(s).replace("'", "''") + "'"


def _dotnet_env_prefix() -> str:
    """shell fragment that pins .NET single-file extraction to a writable dir"""
    return f"{DOTNET_BUNDLE_ENV_VAR}={shlex.quote(str(get_dotnet_bundle_dir()))}"


def wrap_for_elevation(cmd: list[str], token: ElevationToken | None) -> list[str]:
    """rewrite argv so running it executes elevated under the given token"""
    if token is None or token.method == "noop":
        return cmd
    if token.method == "pkexec":
        # pkexec strips most env; bake the .NET var into the elevated shell
        inner = f"{_dotnet_env_prefix()} exec " + " ".join(shlex.quote(a) for a in cmd)
        return ["pkexec", "/bin/sh", "-c", inner]
    if token.method == "sudo":
        return _wrap_sudo(cmd)
    if token.method == "runas":
        ps_args = ", ".join(_ps_quote(a) for a in cmd[1:]) if len(cmd) > 1 else ""
        # RunAs cant pipe child stdout/stderr - dump to temp files and replay
        # $env: assignment propagates to Start-Process children (incl. -Verb RunAs)
        dotnet_path = _ps_quote(str(get_dotnet_bundle_dir()))
        ps = (
            f"$env:{DOTNET_BUNDLE_ENV_VAR} = {dotnet_path}; "
            "$o = [System.IO.Path]::GetTempFileName(); "
            "$e = [System.IO.Path]::GetTempFileName(); "
            f"$p = Start-Process -FilePath {_ps_quote(cmd[0])} "
            + (f"-ArgumentList @({ps_args}) " if ps_args else "")
            + "-Verb RunAs -Wait -PassThru "
            "-RedirectStandardOutput $o -RedirectStandardError $e; "
            "if (Test-Path $o) { Get-Content $o }; "
            "if (Test-Path $e) { Get-Content $e | Write-Host }; "
            "Remove-Item $o,$e -ErrorAction SilentlyContinue; "
            "exit $p.ExitCode"
        )
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]
    return cmd


def _wrap_sudo(cmd: list[str]) -> list[str]:
    """sudo -n cmd; macos chains diskutil unmountDisk for /dev/disk* args"""
    base_device = None
    for arg in cmd:
        m = _DEVICE_RE.match(arg)
        if m:
            base_device = m.group(1).replace("/dev/rdisk", "/dev/disk")
            break
    cmd_quoted = " ".join(shlex.quote(a) for a in cmd)
    if base_device and get_platform_info().os == OperatingSystem.MACOS:
        # chain unmount + cmd in one sudo bash -c so they share auth
        inner = (
            f"/usr/sbin/diskutil unmountDisk force {shlex.quote(base_device)} "
            f">/dev/null 2>&1 ; true ; "
            f"{_dotnet_env_prefix()} exec {cmd_quoted}"
        )
        return ["sudo", "-n", "/bin/bash", "-c", inner]
    # sudo strips env by default; set it inside the elevated shell
    inner = f"{_dotnet_env_prefix()} exec {cmd_quoted}"
    return ["sudo", "-n", "/bin/sh", "-c", inner]


_DEVICE_RE = re.compile(r"^(/dev/(?:r?disk|sd|mmcblk)\d+)")


def _run_sudo_validate(askpass: Path) -> None:
    """prime the sudo timestamp via the askpass helper (sudo -A -v)"""
    env = os.environ.copy()
    env["SUDO_ASKPASS"] = str(askpass)
    subprocess.run(
        ["sudo", "-A", "-v"],
        check=True,
        env=env,
        timeout=300,
        capture_output=True,
        text=True,
    )


def _refresh_sudo_timestamp(token: ElevationToken) -> None:
    """prime sudo timestamp before each call; long ops blow past the 5-min macos cache window"""
    if token.method != "sudo" or token.askpass_path is None:
        return
    try:
        _run_sudo_validate(token.askpass_path)
    except (subprocess.CalledProcessError, subprocess.SubprocessError, OSError) as e:
        # refresh failed -> let the wrapped sudo -n surface its own clearer error
        logger.warning(f"sudo timestamp refresh failed: {e}")


def run_elevated(
    cmd: list[str],
    token: ElevationToken | None,
    *,
    capture_output: bool = True,
    text: bool = True,
    timeout: float | None = None,
    encoding: str = "utf-8",
    errors: str = "replace",
    cancel_check: Callable[[], bool] | None = None,
    on_line: Callable[[str, str], None] | None = None,
) -> object:
    """run cmd elevated; *-helper methods stream stdout/stderr via on_line, else plain subprocess.run"""
    if token is not None and token.method.endswith("-helper") and token.helper is not None:
        return token.helper.run(cmd, timeout=timeout, cancel_check=cancel_check, on_line=on_line)
    if token is not None:
        _refresh_sudo_timestamp(token)
    wrapped = wrap_for_elevation(cmd, token)
    # noop/None path inherits this directly; wrapped paths re-set it inside the elevated shell
    result = subprocess.run(
        wrapped,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        encoding=encoding,
        errors=errors,
        env=get_hst_imager_env(),
    )
    # non-helper paths buffer the whole subprocess; replay lines so callers get the same contract
    if on_line is not None:
        for stream, blob in (("out", result.stdout or ""), ("err", result.stderr or "")):
            for ln in blob.splitlines():
                try:
                    on_line(stream, ln)
                except Exception:
                    pass
    return result


def _write_askpass(script: str) -> Path:
    """write an askpass helper script to a temp file (chmod 700); returns path"""
    import tempfile

    fd, path = tempfile.mkstemp(prefix="emu68hatcher-askpass-", suffix=".sh")
    try:
        os.write(fd, script.encode())
    finally:
        os.close(fd)
    os.chmod(path, 0o700)
    return Path(path)


# ----------------------------------------------------------------------------
# macOS
# ----------------------------------------------------------------------------


_MACOS_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    "# sudo -A invokes this for a GUI password prompt; stdout = password (sudo strips trailing \\n).\n"
    "/usr/bin/osascript "
    '-e \'display dialog "Emu68 Hatcher needs admin access to write to the SD card." '
    'default answer "" with hidden answer '
    'with title "Emu68 Hatcher" with icon caution\' '
    "-e 'text returned of result' "
    "2>/dev/null\n"
)


def _acquire_macos() -> ElevationToken:
    """tty: sudo+askpass; no-tty: osascript-spawned long-lived helper"""
    import sys

    have_tty = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False

    if have_tty:
        askpass = _write_askpass(_MACOS_ASKPASS_SCRIPT)
        try:
            _run_sudo_validate(askpass)
        except subprocess.CalledProcessError as e:
            try:
                askpass.unlink()
            except OSError:
                pass
            raise ElevationDenied(
                f"admin prompt cancelled or denied: {e.stderr or e.stdout or e}"
            ) from e
        return ElevationToken(os=OperatingSystem.MACOS, method="sudo", askpass_path=askpass)

    from emu68hatcher.builder.host.elevated_helper import ElevatedHelper

    helper = ElevatedHelper()
    if helper.spawn():
        return ElevationToken(os=OperatingSystem.MACOS, method="osascript-helper", helper=helper)
    raise ElevationDenied(
        "macos admin prompt cancelled or osascript helper failed to start. "
        "as a workaround, launch the .app from Terminal: "
        '"/Applications/Emu68 Hatcher.app/Contents/MacOS/Emu68 Hatcher"'
    )


# ----------------------------------------------------------------------------
# Linux
# ----------------------------------------------------------------------------


_LINUX_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    "# sudo -A invokes this for a GUI password prompt.\n"
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


def _acquire_linux() -> ElevationToken:
    import sys

    have_gui = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    have_tty = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False

    # gui session: askpass helper drives sudo so the prompt is visible.
    # terminal-sudo only when no display - prompt would land on a hidden tty otherwise.
    if have_gui and shutil.which("sudo"):
        askpass = _write_askpass(_LINUX_ASKPASS_SCRIPT)
        try:
            _run_sudo_validate(askpass)
            return ElevationToken(os=OperatingSystem.LINUX, method="sudo", askpass_path=askpass)
        except subprocess.CalledProcessError as e:
            logger.info(f"sudo -A rejected ({e.returncode}); trying pkexec")
        except (OSError, subprocess.SubprocessError) as e:
            logger.info(f"sudo -A unavailable ({e}); trying pkexec")

    if have_tty and shutil.which("sudo"):
        try:
            subprocess.run(["sudo", "-v"], check=True, timeout=120)
            return ElevationToken(os=OperatingSystem.LINUX, method="sudo")
        except subprocess.CalledProcessError as e:
            logger.info(f"sudo -v rejected ({e.returncode}); trying pkexec")
        except (OSError, subprocess.SubprocessError) as e:
            logger.info(f"sudo unavailable ({e}); trying pkexec")

    if shutil.which("pkexec"):
        try:
            subprocess.run(
                ["pkexec", "true"],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return ElevationToken(os=OperatingSystem.LINUX, method="pkexec")
        except subprocess.CalledProcessError as e:
            raise ElevationDenied(f"pkexec rejected (rc={e.returncode})") from e
        except (OSError, subprocess.SubprocessError) as e:
            raise ElevationDenied(f"pkexec failed: {e}") from e

    raise ElevationDenied(
        "no GUI askpass tool found (zenity/kdialog/ssh-askpass) and no terminal "
        "or pkexec available; install zenity or run from a terminal"
    )


# ----------------------------------------------------------------------------
# Windows
# ----------------------------------------------------------------------------


def _acquire_windows() -> ElevationToken:
    """long-lived elevated helper so per-call UAC doesnt storm the user"""
    if not shutil.which("powershell"):
        raise ElevationDenied("powershell not found on PATH")
    from emu68hatcher.builder.host.elevated_helper import ElevatedHelper

    helper = ElevatedHelper()
    if helper.spawn():
        return ElevationToken(os=OperatingSystem.WINDOWS, method="runas-helper", helper=helper)
    # helper spawn failed (UAC denied, missing python, etc.) - fall back to per-call
    # Start-Process; UAC prompts every elevated subprocess
    logger.warning("elevated helper unavailable; falling back to per-call UAC prompts")
    return ElevationToken(os=OperatingSystem.WINDOWS, method="runas")
