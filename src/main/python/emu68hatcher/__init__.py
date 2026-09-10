"""cross-platform (MacOS, Linux, Windows) app to build ready-to-run Amiga SD card images for Emu68/PiStorm"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _source_checkout_version() -> str | None:
    module_path = Path(__file__).resolve()
    try:
        root = module_path.parents[4]
    except IndexError:
        return None

    if module_path.parent != root / "src" / "main" / "python" / "emu68hatcher":
        return None

    pyproject = root / "pyproject.toml"
    try:
        lines = pyproject.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    in_project = False
    for line in lines:
        value = line.strip()
        if value == "[project]":
            in_project = True
            continue
        if value.startswith("["):
            if in_project:
                break
            continue
        key, separator, version = value.partition("=")
        if in_project and separator and key.strip() == "version":
            version = version.strip()
            if len(version) >= 2 and version[0] == version[-1] and version[0] in "\"'":
                return version[1:-1]
    return None


__version__ = _source_checkout_version()
if __version__ is None:
    try:
        __version__ = _pkg_version("emu68hatcher")
    except PackageNotFoundError:
        __version__ = "0.0.0+source"

__all__ = ["__version__"]
