"""elevated helper - one long-lived worker, file-based IPC for hst-imager calls (windows UAC, macOS osascript)"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from emu68hatcher.utils.platform import OperatingSystem, get_platform_info, is_root

logger = logging.getLogger(__name__)


# worker script gets written to a temp file at spawn time.
# Popen + poll so a cancel sentinel file can kill the in-flight subprocess.
# stdout/stderr stream through reader threads -> chunk files; consumer drains them live.
_WORKER_SCRIPT = '''
"""worker - reads cmd-N.json from ipc_dir, writes .result.json + chunked .out/.err files"""
import json, os, subprocess, sys, threading, time
from pathlib import Path


_trace_fp = None


def trace(msg):
    if _trace_fp is None:
        return
    try:
        _trace_fp.write(f"{time.time():.3f} {msg}\\n")
        _trace_fp.flush()
    except OSError:
        pass


def _grant_user_read(path):
    """windows-only: drop integrity to Medium so the non-elevated parent can read worker output"""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/q",
             "/grant", "*S-1-5-11:(R)",
             "/setintegritylevel", "Medium"],
            capture_output=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _stream_reader(pipe, ipc_dir, seq, stream, full_buf):
    """drain pipe in chunks; flush each complete-line batch as cmd-N.<stream>.NNNNNN; touch .done at EOF"""
    chunk_seq = 0
    buf = bytearray()

    def _flush(payload):
        nonlocal chunk_seq
        if not payload:
            return
        chunk_seq += 1
        name = f"cmd-{seq}.{stream}.{chunk_seq:06d}"
        tmp = ipc_dir / (name + ".tmp")
        final = ipc_dir / name
        try:
            tmp.write_bytes(payload)
            tmp.replace(final)
            _grant_user_read(final)
        except OSError as e:
            trace(f"seq={seq} chunk write failed {name}: {e}")

    try:
        while True:
            data = pipe.read(65536)
            if not data:
                break
            buf.extend(data)
            full_buf.extend(data)
            if b"\\n" not in buf:
                continue
            head, _sep, tail = buf.rpartition(b"\\n")
            _flush(bytes(head) + b"\\n")
            buf = bytearray(tail)
    except OSError as e:
        trace(f"seq={seq} stream {stream} read error: {e}")
    finally:
        if buf:
            _flush(bytes(buf))
        try:
            pipe.close()
        except OSError:
            pass
        done = ipc_dir / f"cmd-{seq}.{stream}.done"
        try:
            done.touch()
            _grant_user_read(done)
        except OSError as e:
            trace(f"seq={seq} done sentinel {stream} failed: {e}")


def run_one(argv, timeout, ipc_dir, cancel_file, seq):
    cancelled = False
    timed_out = False
    rc = -2
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    trace(f"seq={seq} run_one start argv0={argv[0] if argv else ''!r}")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # pin .NET single-file extraction inside ipc_dir; root context $HOME (/var/root) may be unwritable
    env = os.environ.copy()
    dotnet_dir = Path(ipc_dir) / "dotnet"
    try:
        dotnet_dir.mkdir(parents=True, exist_ok=True)
        env["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = str(dotnet_dir)
    except OSError as e:
        trace(f"seq={seq} dotnet dir setup failed: {e}")
    trace(f"seq={seq} popen begin")
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creation_flags,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as e:
        trace(f"seq={seq} popen failed: {e}")
        # still emit empty .done sentinels so the consumer can finalize
        for stream in ("out", "err"):
            try:
                (ipc_dir / f"cmd-{seq}.{stream}.done").touch()
                _grant_user_read(ipc_dir / f"cmd-{seq}.{stream}.done")
            except OSError:
                pass
        return -2, "", str(e), False
    trace(f"seq={seq} popen ok pid={proc.pid}")

    t_out = threading.Thread(
        target=_stream_reader,
        args=(proc.stdout, ipc_dir, seq, "out", stdout_buf),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_stream_reader,
        args=(proc.stderr, ipc_dir, seq, "err", stderr_buf),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    deadline = time.time() + timeout if timeout else None
    poll_count = 0
    while proc.poll() is None:
        poll_count += 1
        if cancel_file.exists():
            cancelled = True
            break
        if deadline and time.time() > deadline:
            timed_out = True
            break
        time.sleep(0.1)
    trace(f"seq={seq} poll loop done polls={poll_count} cancelled={cancelled} timed_out={timed_out}")
    if cancelled or timed_out:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        trace(f"seq={seq} kill+wait done")
    if cancelled:
        rc = -3
    elif timed_out:
        rc = -1
    else:
        rc = proc.returncode

    # let reader threads finish draining + write their .done sentinels
    t_out.join(timeout=10)
    t_err.join(timeout=10)
    out = stdout_buf.decode("utf-8", errors="replace")
    err = stderr_buf.decode("utf-8", errors="replace")
    trace(f"seq={seq} streams closed stdout={len(out)}b stderr={len(err)}b rc={rc}")
    if timed_out and not err:
        err = f"timeout after {timeout}s"
    if cancelled and not err:
        err = "cancelled by user"
    trace(f"seq={seq} run_one done")
    return rc, out, err, cancelled


def main(ipc_dir):
    global _trace_fp
    ipc_dir.mkdir(parents=True, exist_ok=True)
    try:
        _trace_fp = open(ipc_dir / "_trace.log", "w", encoding="utf-8")
        _grant_user_read(ipc_dir / "_trace.log")
    except OSError:
        _trace_fp = None
    trace(f"worker started pid={__import__('os').getpid()}")
    (ipc_dir / "ready").touch()
    _grant_user_read(ipc_dir / "ready")
    cancel_file = ipc_dir / "cancel"
    while True:
        if (ipc_dir / "quit").exists():
            break
        for cmd_file in sorted(ipc_dir.glob("cmd-*.json")):
            if cmd_file.name.endswith(".tmp") or cmd_file.name.endswith(".result.json"):
                continue
            try:
                spec = json.loads(cmd_file.read_text())
                argv = spec["argv"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
            timeout = spec.get("timeout")
            seq = cmd_file.stem.split("-", 1)[-1]
            trace(f"seq={seq} picked up cmd file")
            rc, out, err, cancelled = run_one(argv, timeout, ipc_dir, cancel_file, seq)
            if cancel_file.exists():
                try:
                    cancel_file.unlink()
                except OSError:
                    pass
            payload = {"rc": rc, "stdout": out, "stderr": err, "cancelled": cancelled}
            result = cmd_file.with_suffix(".result.json")
            tmp = result.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.rename(result)
            _grant_user_read(result)
            cmd_file.unlink(missing_ok=True)
            trace(f"seq={seq} result file written")
        time.sleep(0.1)
    trace("worker exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
'''


@dataclass
class HelperResult:
    """subprocess.CompletedProcess-shaped return"""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    cancelled: bool = False


class ElevatedHelper:
    """one elevated worker subprocess; commands go in/out via JSON files"""

    POLL = 0.2
    READY_TIMEOUT = 30.0
    HEARTBEAT_SECONDS = 10.0  # interval for "still running" log line

    def __init__(self) -> None:
        self.ipc_dir: Path | None = None
        self.worker_script: Path | None = None
        self._seq = 0

    def spawn(self) -> bool:
        """one auth prompt, start the worker; True when ready"""
        if is_root():
            return False  # already admin
        info = get_platform_info()
        if info.os == OperatingSystem.WINDOWS:
            return self._spawn_windows()
        if info.os == OperatingSystem.MACOS:
            return self._spawn_macos()
        return False

    def _spawn_windows(self) -> bool:
        self.ipc_dir = Path(tempfile.mkdtemp(prefix="emu68hatcher-helper-"))
        self.worker_script = Path(tempfile.mkstemp(prefix="emu68hatcher-worker-", suffix=".py")[1])
        self.worker_script.write_text(_WORKER_SCRIPT)

        from emu68hatcher.builder.host.elevation import _ps_quote

        ps_args = ", ".join(_ps_quote(str(p)) for p in (self.worker_script, self.ipc_dir))
        ps = (
            f"$p = Start-Process -FilePath {_ps_quote(sys.executable)} "
            f"-ArgumentList @({ps_args}) -Verb RunAs -PassThru -WindowStyle Hidden; "
            "if ($p) { exit 0 } else { exit 1 }"
        )
        try:
            # Start-Process blocks while the UAC prompt is open; windows auto-denies an
            # unanswered prompt after ~2 min, so 300s lets it resolve instead of killing
            # powershell mid-prompt
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            logger.warning("elevated helper UAC prompt was not answered")
            self._cleanup_files()
            return False
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"elevated helper Start-Process failed: {e}")
            self._cleanup_files()
            return False
        if r.returncode != 0:
            logger.warning(
                f"elevated helper spawn rc={r.returncode}: {r.stderr.strip() or r.stdout.strip()}"
            )
            self._cleanup_files()
            return False
        return self._wait_ready()

    def _spawn_macos(self) -> bool:
        import shlex

        self.ipc_dir = Path(tempfile.mkdtemp(prefix="emu68hatcher-helper-"))
        self.worker_script = Path(tempfile.mkstemp(prefix="emu68hatcher-worker-", suffix=".py")[1])
        self.worker_script.write_text(_WORKER_SCRIPT)

        spawn_log = self.ipc_dir / "_spawn.log"
        py = "/usr/bin/python3"
        logger.info(f"elevated helper using python: {py}")

        # no nohup - it chokes without a controlling tty inside osascripts shell context
        inner = (
            f"{shlex.quote(py)} {shlex.quote(str(self.worker_script))} "
            f"{shlex.quote(str(self.ipc_dir))} > {shlex.quote(str(spawn_log))} 2>&1 &"
        )
        inner_esc = inner.replace("\\", "\\\\").replace('"', '\\"')
        osa = f'do shell script "{inner_esc}" with administrator privileges'

        try:
            r = subprocess.run(
                ["osascript", "-e", osa],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"elevated helper osascript failed: {e}")
            self._cleanup_files()
            return False
        if r.returncode != 0:
            logger.warning(
                f"elevated helper spawn rc={r.returncode}: {r.stderr.strip() or r.stdout.strip()}"
            )
            self._cleanup_files()
            return False
        ok = self._wait_ready(cleanup_on_fail=False)
        if not ok:
            if spawn_log.exists():
                try:
                    tail = spawn_log.read_text(errors="replace").strip()
                    if tail:
                        logger.warning(f"elevated worker spawn log:\n{tail}")
                    else:
                        logger.warning("elevated worker spawn log is empty")
                except OSError as e:
                    logger.warning(f"could not read spawn log: {e}")
            else:
                logger.warning(f"spawn log not created at {spawn_log}")
            self._cleanup_files()
        return ok

    def _wait_ready(self, cleanup_on_fail: bool = True) -> bool:
        assert self.ipc_dir is not None
        ready_file = self.ipc_dir / "ready"
        deadline = time.time() + self.READY_TIMEOUT
        while time.time() < deadline:
            if ready_file.exists():
                logger.info(f"elevated helper ready at {self.ipc_dir}")
                return True
            time.sleep(self.POLL)
        logger.warning("elevated helper did not signal ready within 30s")
        if cleanup_on_fail:
            self._cleanup_files()
        return False

    def run(
        self,
        argv: list[str],
        timeout: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_line: Callable[[str, str], None] | None = None,
    ) -> HelperResult:
        """send cmd to worker; on_line(stream, line) fires per stdout/stderr line as the subprocess writes"""
        if self.ipc_dir is None:
            raise RuntimeError("ElevatedHelper.run called before spawn() succeeded")

        self._seq += 1
        cmd_seq = self._seq
        cmd_path = self.ipc_dir / f"cmd-{cmd_seq}.json"
        result_path = self.ipc_dir / f"cmd-{cmd_seq}.result.json"
        cancel_path = self.ipc_dir / "cancel"

        tmp = cmd_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"argv": argv, "timeout": timeout}))
        tmp.rename(cmd_path)

        # per-stream state: (last consumed chunk seq, .done sentinel observed)
        stream_state = {"out": [0, False], "err": [0, False]}

        # extra slack on top of per-command timeout to absorb IPC overhead
        wait_until = time.time() + (timeout or 600) + 30
        start = time.time()
        last_heartbeat = start
        cancel_signaled = False
        parse_failures = 0
        while time.time() < wait_until:
            if on_line:
                for stream, state in stream_state.items():
                    state[0], state[1] = self._drain_chunks(
                        cmd_seq, stream, state[0], state[1], on_line
                    )

            if result_path.exists():
                try:
                    data = json.loads(result_path.read_text())
                except (OSError, json.JSONDecodeError) as e:
                    parse_failures += 1
                    if parse_failures >= 5:
                        result_path.unlink(missing_ok=True)
                        self._cleanup_chunks(cmd_seq)
                        raise RuntimeError(
                            f"elevated worker wrote unreadable result file: {e}"
                        ) from e
                    time.sleep(self.POLL)
                    continue
                # drain any chunks the worker flushed after the .done sentinel
                if on_line:
                    for stream, state in stream_state.items():
                        state[0], state[1] = self._drain_chunks(
                            cmd_seq, stream, state[0], state[1], on_line
                        )
                result_path.unlink(missing_ok=True)
                self._cleanup_chunks(cmd_seq)
                return HelperResult(
                    args=argv,
                    returncode=data["rc"],
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    cancelled=data.get("cancelled", False),
                )

            if cancel_check and not cancel_signaled and cancel_check():
                logger.info("cancellation requested - signalling elevated worker")
                try:
                    cancel_path.touch()
                except OSError as e:
                    logger.warning(f"could not write cancel sentinel: {e}")
                cancel_signaled = True
                # bump the wait so the worker has time to kill its child + write result
                wait_until = max(wait_until, time.time() + 10)

            now = time.time()
            elapsed = now - start
            if (
                elapsed >= self.HEARTBEAT_SECONDS
                and (now - last_heartbeat) >= self.HEARTBEAT_SECONDS
            ):
                logger.info(f"hst-imager: still running... ({elapsed:.0f}s elapsed)")
                last_heartbeat = now

            time.sleep(self.POLL)

        self._cleanup_chunks(cmd_seq)
        raise subprocess.TimeoutExpired(argv, timeout or 600)

    def _drain_chunks(
        self,
        cmd_seq: int,
        stream: str,
        last_seq: int,
        done_seen: bool,
        on_line: Callable[[str, str], None],
    ) -> tuple[int, bool]:
        """consume cmd-N.<stream>.<NNN> in order, emit lines via on_line, unlink each chunk after read"""
        assert self.ipc_dir is not None
        while True:
            nxt = self.ipc_dir / f"cmd-{cmd_seq}.{stream}.{last_seq + 1:06d}"
            if not nxt.exists():
                break
            try:
                content = nxt.read_text(encoding="utf-8", errors="replace")
            except OSError:
                break
            for line in content.splitlines():
                try:
                    on_line(stream, line)
                except Exception:
                    pass  # one bad callback shouldnt break the stream
            nxt.unlink(missing_ok=True)
            last_seq += 1
        if not done_seen:
            done = self.ipc_dir / f"cmd-{cmd_seq}.{stream}.done"
            if done.exists():
                done.unlink(missing_ok=True)
                done_seen = True
        return last_seq, done_seen

    def _cleanup_chunks(self, cmd_seq: int) -> None:
        """drop any straggler chunk/sentinel files for cmd_seq; called after result is consumed"""
        if self.ipc_dir is None:
            return
        for pattern in (f"cmd-{cmd_seq}.out.*", f"cmd-{cmd_seq}.err.*"):
            for path in self.ipc_dir.glob(pattern):
                path.unlink(missing_ok=True)

    def shutdown(self) -> None:
        if self.ipc_dir is None:
            return
        try:
            (self.ipc_dir / "quit").touch()
            # let the worker notice and exit
            time.sleep(0.5)
        except OSError:
            pass
        # keep _trace.log around so a slow run can be diagnosed after the fact
        trace = self.ipc_dir / "_trace.log"
        if trace.exists():
            logger.info(f"elevated worker trace log: {trace}")
        self._cleanup_files(keep_ipc_dir=trace.exists())

    def _cleanup_files(self, keep_ipc_dir: bool = False) -> None:
        if self.ipc_dir is not None and not keep_ipc_dir:
            shutil.rmtree(self.ipc_dir, ignore_errors=True)
            self.ipc_dir = None
        if self.worker_script is not None:
            try:
                self.worker_script.unlink(missing_ok=True)
            except OSError:
                pass
            self.worker_script = None
