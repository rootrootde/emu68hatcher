"""logging - Rich console + shared file handler helper"""

import logging
import threading
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

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

console = Console(theme=EMU68_THEME)


def attach_file_handler(
    logger: logging.Logger,
    path: Path,
    mode: str = "a",
    level: int = logging.DEBUG,
    fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt: str | None = None,
) -> logging.FileHandler | None:
    """attach a FileHandler to logger;return None if open failed"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, mode=mode, encoding="utf-8")
    except OSError:
        return None
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(handler)
    return handler


class Emu68Logger:
    """wraps logging for rich formatting"""

    def __init__(
        self,
        name: str = "emu68hatcher",
        level: int = logging.INFO,
        log_file: Path | None = None,
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.handlers.clear()

        console_handler = RichHandler(
            console=console,
            show_time=False,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
        console_handler.setLevel(level)
        self.logger.addHandler(console_handler)

        if log_file:
            attach_file_handler(self.logger, log_file)

    def debug(self, message: str, **kwargs) -> None:
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        self.logger.error(message, **kwargs)

    def exception(self, message: str, **kwargs) -> None:
        """log at ERROR wiht the active traceback attached"""
        self.logger.exception(message, **kwargs)

    def success(self, message: str) -> None:
        self.logger.info(f"[success][OK][/success] {message}")


_logger: Emu68Logger | None = None
_logger_lock = threading.Lock()


def get_logger() -> Emu68Logger:
    """get or create the default logger (thread-safe)"""
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = Emu68Logger()
    return _logger
