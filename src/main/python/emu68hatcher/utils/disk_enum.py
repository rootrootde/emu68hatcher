"""removable-disk enumeration used by the gui picker and the pipeline"""

from __future__ import annotations

import json
import logging
import os
import plistlib
import subprocess
from dataclasses import dataclass, field

from emu68hatcher.utils.platform import OperatingSystem, get_platform_info

logger = logging.getLogger(__name__)


@dataclass
class DiskInfo:
    """one removable disk on the host"""

    device: str  # "/dev/disk4", "\\\\.\\PhysicalDrive2"
    name: str  # "SanDisk Ultra"
    size_bytes: int
    is_removable: bool
    is_system_disk: bool  # partition mounted at "/" or otherwise holds the OS
    mounted_partitions: list[str] = field(default_factory=list)

    @property
    def size_human(self) -> str:
        n = self.size_bytes
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
            n /= 1024
        return f"{n:.1f} PB"

    @property
    def display_label(self) -> str:
        return f"{self.name} ({self.size_human}) - {self.device}"


def list_removable_disks() -> list[DiskInfo]:
    """removable disks; no elevation needed"""
    info = get_platform_info()
    try:
        if info.os == OperatingSystem.LINUX:
            return _list_linux()
        if info.os == OperatingSystem.MACOS:
            return _list_macos()
        if info.os == OperatingSystem.WINDOWS:
            return _list_windows()
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        plistlib.InvalidFileException,
    ):
        logger.exception("disk enumeration failed")
    return []


def find_disk(device: str) -> DiskInfo | None:
    """look up a disk by device path; None if absent/non-removable"""
    for d in list_removable_disks():
        if d.device == device or _normalise_device(d.device) == _normalise_device(device):
            return d
    return None


def _normalise_device(s: str) -> str:
    return str(s).strip().lower().replace("/dev/r", "/dev/")


def unmount_disk(
    info: DiskInfo,
    logger: logging.Logger | None = None,
    elevation: object | None = None,
) -> None:
    """unmount any mounted partitions before raw write"""
    import shutil
    import subprocess

    log = logger or globals()["logger"]
    plat = get_platform_info().os
    log.info(f"unmounting {info.device}: {info.mounted_partitions}")

    if plat == OperatingSystem.MACOS:
        subprocess.run(
            ["diskutil", "unmountDisk", info.device],
            capture_output=True,
            text=True,
            timeout=30,
        )
    elif plat == OperatingSystem.LINUX:
        # udisksctl when present, umount-via-elevation fallback
        have_udisksctl = shutil.which("udisksctl") is not None
        for mp in info.mounted_partitions:
            ok = False
            if have_udisksctl:
                # findmnt resolves /media/me/X -> /dev/sdb1 for udisksctl -b
                find = subprocess.run(
                    ["findmnt", "-no", "SOURCE", mp],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                partdev = (find.stdout or "").strip()
                if partdev:
                    r = subprocess.run(
                        ["udisksctl", "unmount", "-b", partdev],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    ok = r.returncode == 0
                    if not ok:
                        log.info(
                            f"udisksctl unmount {partdev} failed (rc={r.returncode}): "
                            f"{r.stderr.strip() or r.stdout.strip()}"
                        )
            if not ok:
                cmd = ["umount", mp]
                if elevation is not None:
                    from emu68hatcher.builder.host.elevation import wrap_for_elevation

                    cmd = wrap_for_elevation(cmd, elevation)
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if r.returncode != 0:
                    log.warning(
                        f"umount {mp} failed (rc={r.returncode}): "
                        f"{r.stderr.strip() or r.stdout.strip()}"
                    )
    elif plat == OperatingSystem.WINDOWS:
        # offline stops explorer/shell from re-probing on every hst-imager call
        _set_windows_disk_offline(info, log, elevation, offline=True)


def online_disk(
    info: DiskInfo,
    logger: logging.Logger | None = None,
    elevation: object | None = None,
) -> None:
    """windows: bring a disk back online after the build; no-op on macos/linux"""
    log = logger or globals()["logger"]
    if get_platform_info().os == OperatingSystem.WINDOWS:
        _set_windows_disk_offline(info, log, elevation, offline=False)


def _set_windows_disk_offline(
    info: DiskInfo,
    log: logging.Logger,
    elevation: object | None,
    *,
    offline: bool,
) -> None:
    import re
    import subprocess

    m = re.search(r"PhysicalDrive(\d+)", info.device, re.IGNORECASE)
    if not m:
        return
    disk_num = m.group(1)
    flag = "$true" if offline else "$false"
    ps = f"Set-Disk -Number {disk_num} -IsOffline {flag}; Set-Disk -Number {disk_num} -IsReadOnly $false"
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]
    log.info(f"set-disk {disk_num} IsOffline={offline}")
    if elevation is not None:
        from emu68hatcher.builder.host.elevation import run_elevated

        try:
            run_elevated(cmd, elevation, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning(f"set-disk failed: {e}")
    else:
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)


# ----------------------------------------------------------------------------
# linux
# ----------------------------------------------------------------------------


def _list_linux() -> list[DiskInfo]:
    result = subprocess.run(
        [
            "lsblk",
            "-J",
            "-b",  # bytes
            "-o",
            "NAME,SIZE,TYPE,MOUNTPOINT,MOUNTPOINTS,RM,RO,MODEL,VENDOR",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    disks: list[DiskInfo] = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        if not dev.get("rm"):
            continue
        if dev.get("ro"):
            continue
        children = dev.get("children", []) or []
        mounted = [
            mp for c in children for mp in (c.get("mountpoints") or [c.get("mountpoint")]) if mp
        ]
        is_system = any(mp == "/" or mp == "/boot" or mp == "/boot/efi" for mp in mounted)
        name = (
            " ".join(filter(None, [dev.get("vendor", "").strip(), dev.get("model", "").strip()]))
            or dev["name"]
        )
        disks.append(
            DiskInfo(
                device=f"/dev/{dev['name']}",
                name=name,
                size_bytes=int(dev.get("size") or 0),
                is_removable=True,
                is_system_disk=is_system,
                mounted_partitions=mounted,
            )
        )
    return disks


# ----------------------------------------------------------------------------
# macOS
# ----------------------------------------------------------------------------


def _list_macos() -> list[DiskInfo]:
    listing = subprocess.run(
        ["diskutil", "list", "-plist", "physical"],
        capture_output=True,
        timeout=10,
    )
    if listing.returncode != 0:
        return []
    data = plistlib.loads(listing.stdout)
    disks: list[DiskInfo] = []
    for whole in data.get("AllDisksAndPartitions", []):
        device_id = whole.get("DeviceIdentifier")
        if not device_id:
            continue
        # one diskutil info per whole-disk for removable-ness; mounts via top-level listing
        info = _macos_disk_info(device_id)
        if info is None or not (info.get("RemovableMedia") or info.get("Ejectable")):
            continue
        mounted: list[str] = []
        is_system = bool(info.get("SystemImage"))
        for part in whole.get("Partitions", []) or []:
            mp = part.get("MountPoint")
            if mp:
                mounted.append(mp)
            if mp in ("/", "/System/Volumes/Data"):
                is_system = True
        size = int(info.get("TotalSize") or whole.get("Size") or 0)
        name = (
            info.get("MediaName") or info.get("IORegistryEntryName") or device_id
        ).strip() or device_id
        disks.append(
            DiskInfo(
                device=f"/dev/{device_id}",
                name=name,
                size_bytes=size,
                is_removable=True,
                is_system_disk=is_system,
                mounted_partitions=mounted,
            )
        )
    return disks


def _macos_disk_info(device_id: str) -> dict | None:
    r = subprocess.run(
        ["diskutil", "info", "-plist", device_id],
        capture_output=True,
        timeout=10,
    )
    if r.returncode != 0:
        return None
    return plistlib.loads(r.stdout)


# ----------------------------------------------------------------------------
# windows
# ----------------------------------------------------------------------------


_PS_GETDISK = r"""
$disks = Get-Disk | Where-Object { $_.BusType -in @('USB','SD','MMC') -or $_.IsBoot -eq $false } |
    Sort-Object Number
$out = @()
foreach ($d in $disks) {
    $partitions = Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue |
        ForEach-Object { @{
            DriveLetter = if ($_.DriveLetter) { "$($_.DriveLetter):\\" } else { $null }
            Type = $_.Type
        } }
    $out += @{
        Number = $d.Number
        FriendlyName = $d.FriendlyName
        Size = [int64]$d.Size
        BusType = "$($d.BusType)"
        IsBoot = [bool]$d.IsBoot
        IsSystem = [bool]$d.IsSystem
        Partitions = $partitions
    }
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


def _list_windows() -> list[DiskInfo]:
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _PS_GETDISK,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return []
    data = json.loads(r.stdout)
    if isinstance(data, dict):
        data = [data]
    sys_drive = os.environ.get("SystemDrive", "C:").rstrip("\\")
    disks: list[DiskInfo] = []
    for d in data:
        bus = (d.get("BusType") or "").upper()
        is_removable = bus in ("USB", "SD", "MMC")
        if not is_removable:
            continue
        if d.get("IsBoot") or d.get("IsSystem"):
            continue
        partitions = d.get("Partitions") or []
        if not isinstance(partitions, list):
            partitions = [partitions]
        mounted = [p.get("DriveLetter") for p in partitions if p and p.get("DriveLetter")]
        is_system = any(
            (mp or "").rstrip("\\").upper().rstrip(":") == sys_drive.rstrip(":").upper()
            for mp in mounted
        )
        disks.append(
            DiskInfo(
                device=f"\\\\.\\PhysicalDrive{d['Number']}",
                name=(d.get("FriendlyName") or f"Disk {d['Number']}").strip(),
                size_bytes=int(d.get("Size") or 0),
                is_removable=True,
                is_system_disk=is_system,
                mounted_partitions=mounted,
            )
        )
    return disks
