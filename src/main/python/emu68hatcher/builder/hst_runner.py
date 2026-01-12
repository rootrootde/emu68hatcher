"""
HST Imager command execution for Emu68 Hatcher

runs HST Imager commands with:
- progress monitoring
- output capture
- error handling
- timeout support
"""

import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from emu68hatcher.builder.hst_commands import (
    HSTCommand,
    HSTCommandLine,
    HSTScript,
)
from emu68hatcher.utils.platform import find_hst_imager


class CommandStatus(str, Enum):
    """status of a command execution"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class CommandResult:
    """result of executing a single HST command"""

    command: HSTCommandLine
    status: CommandStatus
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status == CommandStatus.COMPLETED and self.return_code == 0


@dataclass
class ScriptResult:
    """result of executing an HST script"""

    script: HSTScript
    results: list[CommandResult] = field(default_factory=list)
    total_duration: float = 0.0

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def failed_commands(self) -> list[CommandResult]:
        return [r for r in self.results if not r.success]

    @property
    def completed_count(self) -> int:
        return sum(1 for r in self.results if r.success)


# progress callback type
ProgressCallback = Callable[[int, int, str, CommandStatus], None]


class HSTRunner:
    """
    executes HST Imager commands

    provides both synchronous and asynchronous execution with
    progress monitoring.
    """

    def __init__(
        self,
        hst_imager_path: Optional[Path] = None,
        timeout: float = 300.0,
        dry_run: bool = False,
    ):
        """
        initialize HST Runner"""
        self._hst_imager = hst_imager_path
        self.timeout = timeout
        self.dry_run = dry_run

    @property
    def hst_imager(self) -> Path:
        """get path to HST Imager binary"""
        if self._hst_imager is None:
            self._hst_imager = find_hst_imager()
        if self._hst_imager is None:
            raise RuntimeError(
                "HST Imager not found. Run 'emu68-hatcher setup' to download it."
            )
        return self._hst_imager

    def is_available(self) -> bool:
        """check if HST Imager is available"""
        try:
            return self.hst_imager.exists()
        except RuntimeError:
            return False

    def run_command(
        self,
        command: HSTCommandLine,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """
        execute a single HST command synchronously"""
        if self.dry_run:
            return CommandResult(
                command=command,
                status=CommandStatus.COMPLETED,
                stdout=f"[DRY RUN] Would execute: {command.to_string()}",
            )

        cmd_timeout = timeout or self.timeout
        start_time = time.time()

        try:
            args = [str(self.hst_imager)] + command.to_args()

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=cmd_timeout,
            )

            duration = time.time() - start_time

            if result.returncode == 0:
                return CommandResult(
                    command=command,
                    status=CommandStatus.COMPLETED,
                    return_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    duration=duration,
                )
            else:
                # hst-imager outputs errors to stdout with format "[timestamp ERR] message"
                # extract error message from stdout or fallback to stderr
                error_detail = None
                if result.stdout:
                    for line in result.stdout.split("\n"):
                        if " ERR]" in line:
                            # extract message after "ERR] "
                            error_detail = line.split(" ERR]", 1)[-1].strip()
                            break
                if not error_detail:
                    error_detail = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
                return CommandResult(
                    command=command,
                    status=CommandStatus.FAILED,
                    return_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    duration=duration,
                    error=error_detail,
                )

        except subprocess.TimeoutExpired:
            return CommandResult(
                command=command,
                status=CommandStatus.TIMEOUT,
                duration=cmd_timeout,
                error=f"Command timed out after {cmd_timeout}s",
            )
        except Exception as e:
            return CommandResult(
                command=command,
                status=CommandStatus.FAILED,
                duration=time.time() - start_time,
                error=str(e),
            )

    def run_script(
        self,
        script: HSTScript,
        progress_callback: Optional[ProgressCallback] = None,
        stop_on_error: bool = True,
    ) -> ScriptResult:
        """
        execute an HST script synchronously"""
        result = ScriptResult(script=script)
        total = len(script.commands)
        start_time = time.time()

        for i, command in enumerate(script.commands):
            # report progress
            if progress_callback:
                progress_callback(
                    i + 1,
                    total,
                    command.description or command.to_string(),
                    CommandStatus.RUNNING,
                )

            # execute command
            cmd_result = self.run_command(command)
            result.results.append(cmd_result)

            # report completion
            if progress_callback:
                progress_callback(
                    i + 1,
                    total,
                    command.description or command.to_string(),
                    cmd_result.status,
                )

            # stop on error if configured
            if not cmd_result.success and stop_on_error:
                # mark remaining commands as skipped
                for remaining in script.commands[i + 1:]:
                    result.results.append(
                        CommandResult(
                            command=remaining,
                            status=CommandStatus.SKIPPED,
                        )
                    )
                break

        result.total_duration = time.time() - start_time
        return result

