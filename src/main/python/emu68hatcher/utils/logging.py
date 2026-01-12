"""
logging infrastructure for Emu68 Hatcher

provides structured logging with Rich console output and optional file logging.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# custom theme for Emu68 Hatcher
EMU68_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "progress": "blue",
        "dim": "dim",
    }
)

# global console instance
console = Console(theme=EMU68_THEME)


class Emu68Logger:
    """
    custom logger for Emu68 Hatcher

    wraps Python's logging with Rich formatting for console output.
    """

    def __init__(
        self,
        name: str = "emu68hatcher",
        level: int = logging.INFO,
        log_file: Optional[Path] = None,
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.handlers.clear()

        # rich console handler
        console_handler = RichHandler(
            console=console,
            show_time=False,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
        console_handler.setLevel(level)
        self.logger.addHandler(console_handler)

        # optional file handler
        if log_file:
            self._add_file_handler(log_file)

    def _add_file_handler(self, log_file: Path) -> None:
        """add a file handler for persistent logging"""
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def debug(self, message: str, **kwargs) -> None:
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        self.logger.error(message, **kwargs)

    def success(self, message: str) -> None:
        """log a success message with green formatting"""
        console.print(f"[success]✓[/success] {message}")

    def step(self, step_num: int, total: int, message: str) -> None:
        """log a numbered step in a multi-step process"""
        console.print(f"[progress][{step_num}/{total}][/progress] {message}")

    def section(self, title: str) -> None:
        """print a section header"""
        console.print()
        console.rule(f"[bold]{title}[/bold]")
        console.print()


# default logger instance
_logger: Optional[Emu68Logger] = None


def get_logger() -> Emu68Logger:
    """get or create the default logger"""
    global _logger
    if _logger is None:
        _logger = Emu68Logger()
    return _logger


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
    verbose: bool = False,
) -> Emu68Logger:
    """
    set up logging for the application"""
    global _logger

    if verbose:
        level = logging.DEBUG

    _logger = Emu68Logger(level=level, log_file=log_file)
    return _logger


def get_log_file_path() -> Path:
    """
    get the default log file path"""
    cache_dir = Path.home() / ".cache" / "emu68-hatcher"
    cache_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return cache_dir / f"emu68-hatcher_{timestamp}.log"


class BuildProgress:
    """
    track progress through the build process stages

    provides a high-level view of build progress with named stages.
    """

    STAGES = [
        "Validating configuration",
        "Downloading packages",
        "Extracting archives",
        "Creating disk image",
        "Setting up partitions",
        "Installing Workbench",
        "Installing packages",
        "Configuring system",
        "Finalizing image",
    ]

    def __init__(self):
        self.current_stage = 0
        self.total_stages = len(self.STAGES)
        self.logger = get_logger()

    def start(self) -> None:
        """start the build process"""
        self.logger.section("Build Process")
        console.print(f"Starting build with {self.total_stages} stages\n")

    def next_stage(self, custom_message: Optional[str] = None) -> None:
        """move to the next stage"""
        if self.current_stage < self.total_stages:
            stage_name = custom_message or self.STAGES[self.current_stage]
            self.logger.step(self.current_stage + 1, self.total_stages, stage_name)
            self.current_stage += 1

    def complete(self) -> None:
        """mark the build as complete"""
        console.print()
        self.logger.success("Build completed successfully!")

    def fail(self, error: str) -> None:
        """mark the build as failed"""
        console.print()
        self.logger.error(f"Build failed: {error}")
