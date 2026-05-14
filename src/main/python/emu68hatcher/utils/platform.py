"""platform detection - OS + arch for binary selection"""

import os
import platform
from dataclasses import dataclass
from enum import Enum


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


if __name__ == "__main__":
    from emu68hatcher.utils.host_tools import check_dependencies
    from emu68hatcher.utils.paths import get_tools_dir

    info = get_platform_info()
    print(f"Platform: {info}")
    print(f"Platform string: {info.platform_string}")
    print(f"Tools dir: {get_tools_dir()}")
    print("\nDependencies:")
    for name, available in check_dependencies().items():
        status = "OK" if available else "MISSING"
        print(f"  {name}: {status}")
