"""platform detection - OS + arch for binary selection"""

import os
import platform
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class OperatingSystem(str, Enum):
    """supported operating systems"""

    LINUX = "linux"
    MACOS = "darwin"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


class Architecture(str, Enum):
    """supported CPU architectures"""

    X64 = "x64"
    ARM64 = "arm64"
    ARM32 = "arm"
    X86 = "x86"
    UNKNOWN = "unknown"


@dataclass
class PlatformInfo:
    """information about the current plattform"""

    os: OperatingSystem
    arch: Architecture
    os_version: str
    hostname: str
    is_root: bool

    @property
    def platform_string(self) -> str:
        """return platform string for binary selection"""
        return f"{self.os.value}-{self.arch.value}"

    def __str__(self) -> str:
        root_status = "root" if self.is_root else "user"
        return f"{self.os.value}/{self.arch.value} ({self.os_version}) [{root_status}]"


def detect_os() -> OperatingSystem:
    """detect the current OS"""
    system = platform.system().lower()

    if system == "linux":
        return OperatingSystem.LINUX
    elif system == "darwin":
        return OperatingSystem.MACOS
    elif system == "windows":
        return OperatingSystem.WINDOWS
    else:
        return OperatingSystem.UNKNOWN


def detect_architecture() -> Architecture:
    """detect the CPU arch"""
    machine = platform.machine().lower()

    if machine in ("x86_64", "amd64"):
        return Architecture.X64
    elif machine in ("aarch64", "arm64"):
        return Architecture.ARM64
    elif machine in ("armv7l", "armv6l", "arm"):
        return Architecture.ARM32
    elif machine in ("i386", "i686", "x86"):
        return Architecture.X86
    else:
        return Architecture.UNKNOWN


def is_root() -> bool:
    """check if running with root/administrator privileges"""
    if platform.system() == "Windows":
        try:
            import ctypes

            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        return os.geteuid() == 0


def get_platform_info() -> PlatformInfo:
    """get platform information"""
    return PlatformInfo(
        os=detect_os(),
        arch=detect_architecture(),
        os_version=platform.version(),
        hostname=platform.node(),
        is_root=is_root(),
    )


########################
# tool path resolution #
########################


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
    from emu68hatcher.utils.paths import get_tools_dir

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


##############
# validation #
##############


def check_dependencies() -> dict[str, bool]:
    """check if all required external dependencies are available"""
    return {
        "hst-imager": find_hst_imager() is not None,
        "hst-amiga": find_hst_amiga() is not None,
        "7z": find_7z() is not None,
    }


if __name__ == "__main__":
    from emu68hatcher.utils.paths import get_tools_dir

    info = get_platform_info()
    print(f"Platform: {info}")
    print(f"Platform string: {info.platform_string}")
    print(f"Tools dir: {get_tools_dir()}")
    print("\nDependencies:")
    for name, available in check_dependencies().items():
        status = "OK" if available else "MISSING"
        print(f"  {name}: {status}")
