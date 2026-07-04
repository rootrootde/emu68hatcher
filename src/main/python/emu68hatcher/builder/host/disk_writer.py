"""flash an image to a physical disk via hst-imager write"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from emu68hatcher.builder.errors import BuildCancelledError, BuildError
from emu68hatcher.builder.host.elevation import ElevationToken, wrap_for_elevation
from emu68hatcher.utils.host_tools import find_hst_imager

logger = logging.getLogger(__name__)


# matches hst-imager 1.6.x lines like "[INF] Writing: 1234567 / 9876543 bytes (12.5 %)"
# plus "Writing: 1234 of 9876" / "Verifying: ..." in case the format drifts
_PROGRESS_RE = re.compile(
    r"(?P<phase>writing|verifying|reading)\s*[:\-]?\s*"
    r"(?P<done>\d[\d_,.]*)\s*(?:/|of)\s*(?P<total>\d[\d_,.]*)",
    re.IGNORECASE,
)


def _handle_progress_line(
    line: str,
    phase_seen: set[str],
    progress_callback: Callable[[float, str], None] | None,
    recent: deque[str],
) -> None:
    """emit progress on a hst-imager progress line, else buffer it and debug-log"""
    m = _PROGRESS_RE.search(line)
    if not m:
        recent.append(line)
        logger.debug(f"hst-imager: {line}")
        return
    phase = m.group("phase").lower()
    if phase not in phase_seen:
        phase_seen.add(phase)
        logger.info(f"flash: {phase} pass started")
    if progress_callback:
        total = _parse_int(m.group("total"))
        if total > 0:
            pct = max(0.0, min(100.0, 100.0 * _parse_int(m.group("done")) / total))
            progress_callback(pct, f"{phase.capitalize()}: {pct:.1f}%")


def _raise_flash_failure(rc: int, duration: float, recent: deque[str]) -> None:
    """log the tail buffer and raise BuildError with the most likely cause line"""
    for ln in recent:
        logger.error(f"hst-imager: {ln}")
    # first non-empty .NET-ish exception line is usually the human-readable cause
    cause = next(
        (ln for ln in recent if "Exception" in ln or "Error" in ln or "denied" in ln.lower()),
        recent[-1] if recent else "",
    )
    raise BuildError(f"hst-imager write failed (rc={rc}) after {duration:.1f}s: {cause}")


def flash_image_to_disk(
    image_path: Path,
    target_device: str,
    *,
    verify: bool = True,
    skip_unused_sectors: bool = True,
    force: bool = False,
    elevation: ElevationToken | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_predicate: Callable[[], bool] | None = None,
    timeout: float | None = None,
) -> None:
    """write image_path to target_device; BuildCancelledError on cancel, BuildError on failure"""
    image_path = Path(image_path)
    if not image_path.exists():
        raise BuildError(f"image not found: {image_path}")

    hst = find_hst_imager()
    if not hst:
        raise BuildError("hst-imager binary not found")

    args = [str(hst), "--verbose", "write", str(image_path), str(target_device)]
    if verify:
        args.append("--verify")
    if skip_unused_sectors:
        args.append("--skip-unused-sectors")
    if force:
        args.append("--force")

    # helper IPC streams stdout/stderr via on_line so the GUI progress bar moves while writing
    if (
        elevation is not None
        and elevation.method.endswith("-helper")
        and elevation.helper is not None
    ):
        logger.info(f"flash: $ {shlex.join(args)}")
        if progress_callback:
            progress_callback(0.0, f"Flashing to {target_device}, this can take a few minutes…")
        start = time.time()
        phase_seen: set[str] = set()
        recent: deque[str] = deque(maxlen=30)

        def on_line(stream: str, line: str) -> None:
            ln = line.rstrip()
            if not ln:
                return
            _handle_progress_line(ln, phase_seen, progress_callback, recent)

        result = elevation.helper.run(
            args, timeout=timeout, cancel_check=cancel_predicate, on_line=on_line
        )
        duration = time.time() - start
        if result.cancelled:
            raise BuildCancelledError("flash cancelled by user")
        if result.returncode != 0:
            _raise_flash_failure(result.returncode, duration, recent)
        logger.info(f"flash: done in {duration:.1f}s")
        if progress_callback:
            progress_callback(100.0, "Flash complete")
        return

    cmd = wrap_for_elevation(args, elevation)

    logger.info(f"flash: $ {shlex.join(cmd)}")
    if progress_callback:
        progress_callback(0.0, f"Flashing to {target_device}, this can take a few minutes…")

    start = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as e:
        raise BuildError(f"failed to launch hst-imager: {e}") from e

    cancelled = False
    deadline = (time.time() + timeout) if timeout else None
    phase_seen: set[str] = set()
    # tail buffer so a failure surfaces more than the outermost stack frame
    recent: deque[str] = deque(maxlen=30)

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue

            if cancel_predicate and cancel_predicate():
                cancelled = True
                logger.info("flash: cancel requested - killing subprocess")
                proc.kill()
                break

            if deadline and time.time() > deadline:
                logger.warning("flash: timeout exceeded - killing subprocess")
                proc.kill()
                raise BuildError(f"flash timed out after {timeout}s")

            _handle_progress_line(line, phase_seen, progress_callback, recent)

    finally:
        rc = proc.wait()

    duration = time.time() - start
    if cancelled:
        raise BuildCancelledError("flash cancelled by user")

    if rc != 0:
        _raise_flash_failure(rc, duration, recent)

    logger.info(f"flash: done in {duration:.1f}s")
    if progress_callback:
        progress_callback(100.0, "Flash complete")


def _parse_int(s: str) -> int:
    return int(s.replace("_", "").replace(",", "").replace(".", ""))
