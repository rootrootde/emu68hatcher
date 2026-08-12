"""local flash process control"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from emu68hatcher.utils.host_tools import get_hst_imager_env


@dataclass(frozen=True)
class FlashProcessResult:
    returncode: int
    cancelled: bool = False
    timed_out: bool = False
    stop_failed: bool = False


def _stop(proc: subprocess.Popen) -> bool:
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
        return True
    except (OSError, ProcessLookupError):
        return proc.poll() is not None
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
            return True
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            return proc.poll() is not None


def run_local_flash(
    cmd: list[str],
    *,
    timeout: float | None,
    cancel_check: Callable[[], bool] | None,
    on_line: Callable[[str], None],
) -> FlashProcessResult:
    """run a flash command while polling cancel and timeout"""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=get_hst_imager_env(),
        start_new_session=os.name != "nt",
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
    )
    assert proc.stdout is not None

    lines: queue.Queue[str | None] = queue.Queue()

    def _read() -> None:
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout if timeout else None
    eof = False

    while True:
        try:
            item = lines.get(timeout=0.1)
            if item is None:
                eof = True
            else:
                on_line(item)
        except queue.Empty:
            pass

        if cancel_check and cancel_check():
            stopped = _stop(proc)
            reader.join(timeout=1)
            return FlashProcessResult(
                proc.returncode if proc.returncode is not None else -1,
                cancelled=True,
                stop_failed=not stopped,
            )

        if deadline is not None and time.monotonic() >= deadline:
            stopped = _stop(proc)
            reader.join(timeout=1)
            return FlashProcessResult(
                proc.returncode if proc.returncode is not None else -1,
                timed_out=True,
                stop_failed=not stopped,
            )

        if proc.poll() is not None and eof and lines.empty():
            break

    reader.join(timeout=1)
    return FlashProcessResult(proc.returncode or 0)
