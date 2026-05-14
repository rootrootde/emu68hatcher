"""host tool resolution - locates hst-imager / hst-amiga / 7z and builds their subprocess env"""

import os
import shutil
from pathlib import Path

from emu68hatcher.utils.paths import (
    DOTNET_BUNDLE_ENV_VAR,
    get_dotnet_bundle_dir,
    get_tools_dir,
)
from emu68hatcher.utils.platform import OperatingSystem, detect_os, get_platform_info

_WINDOWS_EXE_EXTS = (".exe", ".cmd", ".bat", ".com")


def _is_runnable(path: Path) -> bool:
    """true if path is runnable on this OS"""
    if not path.exists() or not path.is_file():
        return False
    if detect_os() == OperatingSystem.WINDOWS:
        return path.suffix.lower() in _WINDOWS_EXE_EXTS or os.access(path, os.X_OK)
    return os.access(path, os.X_OK)


def find_tool(name: str) -> Path | None:
    """find tool binary - platform tools dir first, then system PATH"""
    platform_dir = get_tools_dir()
    if platform_dir.exists():
        tool_path = platform_dir / name
        if _is_runnable(tool_path):
            return tool_path

        if detect_os() == OperatingSystem.WINDOWS:
            for ext in _WINDOWS_EXE_EXTS:
                tool_path = platform_dir / f"{name}{ext}"
                if tool_path.exists():
                    return tool_path

    system_path = shutil.which(name)
    if system_path:
        return Path(system_path)

    return None


def find_hst_imager() -> Path | None:
    """find the HST Imager binary"""
    info = get_platform_info()

    if info.os == OperatingSystem.WINDOWS:
        names = ["hst-imager.exe", "hst.imager.exe", "Hst.Imager.Console.exe"]
    else:
        names = ["hst-imager", "hst.imager", "Hst.Imager.Console"]

    for name in names:
        path = find_tool(name)
        if path:
            return path

    return None


def find_hst_amiga() -> Path | None:
    """find the HST Amiga binary"""
    info = get_platform_info()

    if info.os == OperatingSystem.WINDOWS:
        names = ["hst-amiga.exe", "hst.amiga.exe", "Hst.Amiga.exe"]
    else:
        names = ["hst-amiga", "hst.amiga", "Hst.Amiga"]

    for name in names:
        path = find_tool(name)
        if path:
            return path

    return None


def find_7z() -> Path | None:
    """find 7-Zip binary"""
    info = get_platform_info()

    if info.os == OperatingSystem.WINDOWS:
        names = ["7z.exe", "7za.exe"]
    else:
        names = ["7z", "7za", "7zz"]

    for name in names:
        path = find_tool(name)
        if path:
            return path

    return None


def check_dependencies() -> dict[str, bool]:
    """check if all required external dependencies are available"""
    return {
        "hst-imager": find_hst_imager() is not None,
        "hst-amiga": find_hst_amiga() is not None,
        "7z": find_7z() is not None,
    }


def get_hst_imager_env() -> dict[str, str]:
    """parent env + DOTNET_BUNDLE_EXTRACT_BASE_DIR; pass to subprocess.run(env=...) for direct hst-imager calls"""
    env = os.environ.copy()
    env[DOTNET_BUNDLE_ENV_VAR] = str(get_dotnet_bundle_dir())
    return env
