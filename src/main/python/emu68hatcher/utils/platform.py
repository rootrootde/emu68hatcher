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
    UNKNOWN = "unknown"


@dataclass
class PlatformInfo:
    """information about the current plattform"""

    os: OperatingSystem
    arch: Architecture
    os_version: str
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
        is_root=is_root(),
    )
