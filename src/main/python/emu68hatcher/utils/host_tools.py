"""host tool resolution - locates hst-imager / hst-amiga / 7z and builds their subprocess env"""

import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

from emu68hatcher.utils.paths import (
    DOTNET_BUNDLE_ENV_VAR,
    get_dotnet_bundle_dir,
    get_tools_dir,
)
from emu68hatcher.utils.platform import OperatingSystem, detect_os

logger = logging.getLogger(__name__)

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


_TOOL_NAMES: dict[str, tuple[list[str], list[str]]] = {
    "hst-imager": (
        ["hst-imager.exe", "hst.imager.exe", "Hst.Imager.Console.exe"],
        ["hst-imager", "hst.imager", "Hst.Imager.Console"],
    ),
    "hst-amiga": (
        ["hst-amiga.exe", "hst.amiga.exe", "Hst.Amiga.exe"],
        ["hst-amiga", "hst.amiga", "Hst.Amiga"],
    ),
    "7z": (
        ["7z.exe", "7za.exe"],
        ["7z", "7za", "7zz"],
    ),
}


def _find_named(tool: str) -> Path | None:
    """first resolvable binary from the tool's per-OS candidate names"""
    windows_names, posix_names = _TOOL_NAMES[tool]
    names = windows_names if detect_os() == OperatingSystem.WINDOWS else posix_names
    for name in names:
        path = find_tool(name)
        if path:
            return path
    return None


def find_hst_imager() -> Path | None:
    """find the HST Imager binary"""
    return _find_named("hst-imager")


def find_hst_amiga() -> Path | None:
    """find the HST Amiga binary"""
    return _find_named("hst-amiga")


def find_7z() -> Path | None:
    """find 7-Zip binary"""
    return _find_named("7z")


def get_hst_imager_env() -> dict[str, str]:
    """parent env + DOTNET_BUNDLE_EXTRACT_BASE_DIR; pass to subprocess.run(env=...) for direct hst-imager calls"""
    env = os.environ.copy()
    env[DOTNET_BUNDLE_ENV_VAR] = str(get_dotnet_bundle_dir())
    return env


def localize_for_hst(path: Path, local_dir: Path) -> Path:
    """return path, or a local copy when UNC-hosted - hst-imager resolves forward-slash UNC paths as 'Path not found'"""
    if not path.drive.startswith("\\\\"):
        return path
    return _copy_to_local(path, local_dir)


def _copy_to_local(path: Path, local_dir: Path) -> Path:
    """copy path into local_dir once, keyed by full source path; returns the copy"""
    # hash prefix keeps same-named files from different source dirs apart (ADFs all share one size)
    tag = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    dest = local_dir / f"{tag}-{path.name}"
    if not dest.exists():
        local_dir.mkdir(parents=True, exist_ok=True)
        # copy via .part so an interrupted copy is never mistaken for a finished one
        part = dest.with_name(dest.name + ".part")
        shutil.copy2(path, part)
        part.replace(dest)
        logger.info(f"Copied {path.name} to local storage for hst-imager (network path)")
    return dest


def run_hst_extract(
    hst_imager: str | Path,
    source: str,
    dest: str,
    *,
    uaemetadata: str = "UaeFsDb",
    recursive: bool = False,
    force: bool = True,
    timeout: int | None = 60,
) -> subprocess.CompletedProcess:
    """run `hst-imager fs extract`, always passing the DOTNET_BUNDLE env"""
    args = [str(hst_imager), "fs", "extract", source, dest]
    if recursive:
        args += ["--recursive", "TRUE"]
    if force:
        args += ["--force", "TRUE"]
    args += ["--uaemetadata", uaemetadata]
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=get_hst_imager_env(),
    )
