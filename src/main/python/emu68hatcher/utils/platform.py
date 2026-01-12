"""
platform detection utilities for Emu68 Hatcher

detects OS and architecture to locate correct HST binaries and
determine which disk operations commands to use.
"""

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


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
    """information about the current platform"""

    os: OperatingSystem
    arch: Architecture
    os_version: str
    hostname: str
    is_root: bool

    @property
    def platform_string(self) -> str:
        """return platform string for binary selection (e.g., 'linux-x64')"""
        return f"{self.os.value}-{self.arch.value}"

    @property
    def can_write_disks(self) -> bool:
        """check if we can write to physical disks (requires root/admin)"""
        return self.is_root

    def __str__(self) -> str:
        root_status = "root" if self.is_root else "user"
        return f"{self.os.value}/{self.arch.value} ({self.os_version}) [{root_status}]"


def detect_os() -> OperatingSystem:
    """detect the current operating system"""
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
    """detect the CPU architecture"""
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
    """get comprehensive platform information"""
    return PlatformInfo(
        os=detect_os(),
        arch=detect_architecture(),
        os_version=platform.version(),
        hostname=platform.node(),
        is_root=is_root(),
    )


# =============================================================================
# tool path resolution
# =============================================================================


def get_tools_dir() -> Path:
    """get the tools directory for the current platform

    delegates to paths.get_tools_dir() which handles all path resolution
    including HATCHER_HOME env var, .app bundle detection, and development mode.
    """
    from emu68hatcher.utils.paths import get_tools_dir as _get_tools_dir
    return _get_tools_dir().parent  # paths.get_tools_dir() returns platform-specific subdir


def get_platform_tools_dir() -> Path:
    """get the tools directory for the current platform"""
    info = get_platform_info()
    return get_tools_dir() / info.platform_string


def find_tool(name: str) -> Optional[Path]:
    """
    find a tool binary by name

    searches in order:
    1. platform-specific tools directory
    2. system PATH
    """
    # check platform tools directory
    platform_dir = get_platform_tools_dir()
    if platform_dir.exists():
        tool_path = platform_dir / name
        if tool_path.exists() and os.access(tool_path, os.X_OK):
            return tool_path

        # try with common extensions on Windows
        if detect_os() == OperatingSystem.WINDOWS:
            for ext in [".exe", ".cmd", ".bat"]:
                tool_path = platform_dir / f"{name}{ext}"
                if tool_path.exists():
                    return tool_path

    # check system PATH
    system_path = shutil.which(name)
    if system_path:
        return Path(system_path)

    return None


def find_hst_imager() -> Optional[Path]:
    """find the HST Imager binary"""
    # try platform-specific name first
    info = get_platform_info()

    if info.os == OperatingSystem.WINDOWS:
        names = ["hst.imager.exe", "Hst.Imager.Console.exe"]
    else:
        names = ["hst-imager", "hst.imager", "Hst.Imager.Console"]

    for name in names:
        path = find_tool(name)
        if path:
            return path

    return None


def find_hst_amiga() -> Optional[Path]:
    """find the HST Amiga binary"""
    info = get_platform_info()

    if info.os == OperatingSystem.WINDOWS:
        names = ["hst.amiga.exe", "Hst.Amiga.exe"]
    else:
        names = ["hst-amiga", "hst.amiga", "Hst.Amiga"]

    for name in names:
        path = find_tool(name)
        if path:
            return path

    return None


def find_7z() -> Optional[Path]:
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



# =============================================================================
# disk operations helpers
# =============================================================================


def list_removable_drives() -> list[dict]:
    """list removable drives (SD cards, USB drives)"""
    info = get_platform_info()
    drives = []

    if info.os == OperatingSystem.LINUX:
        drives = _list_linux_removable_drives()
    elif info.os == OperatingSystem.MACOS:
        drives = _list_macos_removable_drives()
    elif info.os == OperatingSystem.WINDOWS:
        drives = _list_windows_removable_drives()

    return drives


def _list_linux_removable_drives() -> list[dict]:
    """list removable drives on Linux using lsblk"""
    drives = []
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,RM,MODEL"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            import json

            data = json.loads(result.stdout)
            for device in data.get("blockdevices", []):
                if device.get("type") == "disk" and device.get("rm"):
                    drives.append(
                        {
                            "path": f"/dev/{device['name']}",
                            "name": device.get("model", device["name"]),
                            "size": device.get("size", "Unknown"),
                            "mounted": device.get("mountpoint") is not None,
                        }
                    )
    except Exception:
        pass
    return drives


def _list_macos_removable_drives() -> list[dict]:
    """list removable drives on macOS using diskutil

    checks for removable media (SD cards, USB drives) including those
    in built-in card readers which macOS marks as 'internal'.
    """
    drives = []
    try:
        # get list of all physical disks
        result = subprocess.run(
            ["diskutil", "list", "-plist", "physical"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return drives

        import plistlib
        data = plistlib.loads(result.stdout.encode())

        # check each disk for removable media
        for disk in data.get("AllDisksAndPartitions", []):
            device_id = disk.get("DeviceIdentifier", "")
            if not device_id:
                continue

            # get detailed info to check if removable
            info_result = subprocess.run(
                ["diskutil", "info", "-plist", device_id],
                capture_output=True,
                text=True,
            )
            if info_result.returncode != 0:
                continue

            info = plistlib.loads(info_result.stdout.encode())

            # check for removable media (includes built-in SD readers)
            is_removable = info.get("RemovableMedia", False)
            is_ejectable = info.get("Ejectable", False)
            is_internal = info.get("Internal", True)

            # include if removable OR ejectable, but not the main system disk
            if (is_removable or is_ejectable) and not info.get("SystemImage", False):
                media_name = info.get("MediaName", device_id)
                size_bytes = info.get("TotalSize", 0)

                # format size
                if size_bytes >= 1024**3:
                    size_str = f"{size_bytes / (1024**3):.1f} GB"
                elif size_bytes >= 1024**2:
                    size_str = f"{size_bytes / (1024**2):.1f} MB"
                else:
                    size_str = f"{size_bytes} bytes"

                drives.append({
                    "path": f"/dev/{device_id}",
                    "name": media_name,
                    "size": size_str,
                    "mounted": info.get("MountPoint") is not None,
                })
    except Exception:
        pass
    return drives


def _list_windows_removable_drives() -> list[dict]:
    """list removable drives on Windows"""
    drives = []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        drives_bitmask = kernel32.GetLogicalDrives()

        for i in range(26):
            if drives_bitmask & (1 << i):
                drive_letter = f"{chr(65 + i)}:\\"
                drive_type = kernel32.GetDriveTypeW(drive_letter)
                # 2 = DRIVE_REMOVABLE
                if drive_type == 2:
                    drives.append(
                        {
                            "path": f"\\\\.\\{chr(65 + i)}:",
                            "name": f"Removable Disk ({chr(65 + i)}:)",
                            "size": "Unknown",
                            "mounted": True,
                        }
                    )
    except Exception:
        pass
    return drives


# =============================================================================
# validation
# =============================================================================


def check_dependencies() -> dict[str, bool]:
    """check if all required external dependencies are available"""
    return {
        "hst-imager": find_hst_imager() is not None,
        "hst-amiga": find_hst_amiga() is not None,
        "7z": find_7z() is not None,
    }


def check_optional_dependencies() -> dict[str, bool]:
    """check optional dependencies"""
    return {}


if __name__ == "__main__":
    # quick test
    info = get_platform_info()
    print(f"Platform: {info}")
    print(f"Platform string: {info.platform_string}")
    print(f"Tools dir: {get_platform_tools_dir()}")
    print(f"\nDependencies:")
    for name, available in check_dependencies().items():
        status = "OK" if available else "MISSING"
        print(f"  {name}: {status}")
