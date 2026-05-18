"""cross-platform (MacOS, Linux, Windows) app to build ready-to-run Amiga SD card images for Emu68/PiStorm"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("emu68hatcher")
except PackageNotFoundError:
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
