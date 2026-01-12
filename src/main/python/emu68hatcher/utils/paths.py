"""
path utilities for Emu68 Hatcher

handles application directories, cache management, and path resolution.

all runtime data (tools, downloads, cache, config) is stored in a single
directory chosen in this order:

1. `HATCHER_HOME` environment variable, if set.
2. OS-standard per-user data directory, when running as a frozen/bundled app:
   - macOS:   ~/Library/Application Support/Emu68 Hatcher/
   - windows: %LOCALAPPDATA%/Emu68 Hatcher/
   - linux:   $XDG_DATA_HOME/emu68-hatcher/ (or ~/.local/share/emu68-hatcher/)
3. repo-local `hatcher_data/` when running from a source checkout.
"""

import os
import sys
import tempfile
from pathlib import Path

from emu68hatcher.utils.platform import OperatingSystem, get_platform_info


def _user_data_dir() -> Path:
    """return the OS-standard per-user data directory for this app"""
    app_name = "Emu68 Hatcher"
    os_name = get_platform_info().os
    if os_name == OperatingSystem.MACOS:
        return Path.home() / "Library" / "Application Support" / app_name
    if os_name == OperatingSystem.WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / app_name
        return Path.home() / "AppData" / "Local" / app_name
    # linux / other Unix: XDG Base Directory Specification
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "emu68-hatcher"
    return Path.home() / ".local" / "share" / "emu68-hatcher"


def _get_home() -> Path:
    """
    get the base directory for all Emu68 Hatcher data

    see module docstring for the full resolution order.
    """
    home = os.environ.get("HATCHER_HOME")
    if home:
        p = Path(home).expanduser().resolve()
    elif getattr(sys, "frozen", False):
        # running as a PyInstaller-bundled app - use OS-standard user data dir
        p = _user_data_dir()
    else:
        # running from a source checkout - keep data in the repo for dev
        # convenience (parent of src/main/python/emu68hatcher/utils/)
        p = Path(__file__).parent.parent.parent.parent.parent.parent / "hatcher_data"

    p.mkdir(parents=True, exist_ok=True)
    return p


def get_app_data_dir() -> Path:
    """return `<home>/data` (see `_get_home()` for how `<home>` is chosen)"""
    app_dir = _get_home() / "data"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_config_dir() -> Path:
    """return `<home>/config` (see `_get_home()` for how `<home>` is chosen)"""
    config_dir = _get_home() / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_cache_dir() -> Path:
    """return `<home>/cache` (see `_get_home()` for how `<home>` is chosen)"""
    cache_dir = _get_home() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_downloads_dir() -> Path:
    """
    get the directory for downloaded packages"""
    downloads = get_cache_dir() / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


def get_extracted_dir() -> Path:
    """
    get the directory for extracted package contents"""
    extracted = get_cache_dir() / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    return extracted


def get_temp_dir() -> Path:
    """
    get a temporary directory for build operations

    this directory will be in the cache and can be safely cleaned."""
    temp_base = get_cache_dir() / "temp"
    temp_base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=temp_base))


def get_tools_dir() -> Path:
    """return `<home>/tools/<platform>` (see `_get_home()` for `<home>`)"""
    info = get_platform_info()
    tools_dir = _get_home() / "tools" / info.platform_string
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


def get_resources_dir() -> Path:
    """
    get the directory containing bundled resources"""
    # check relative to package first (development)
    pkg_dir = Path(__file__).parent.parent.parent.parent
    resources_dir = pkg_dir / "resources" / "base"
    if resources_dir.exists():
        return resources_dir

    # for installed package, check common locations
    import emu68hatcher

    pkg_path = Path(emu68hatcher.__file__).parent
    for relative in ["resources", "../resources/base", "../../resources/base"]:
        resources = pkg_path / relative
        if resources.exists():
            return resources

    # fallback to app data
    return get_app_data_dir() / "resources"


def ensure_dir(path: Path) -> Path:
    """
    ensure a directory exists, creating it if necessary"""
    path.mkdir(parents=True, exist_ok=True)
    return path


