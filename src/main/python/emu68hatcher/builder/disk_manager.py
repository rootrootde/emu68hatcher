"""
disk management for Emu68 Hatcher

handles:
- physical disk detection and writing
- disk image creation and manipulation
- loop device mounting (Linux)
- disk utility operations (macOS)
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from emu68hatcher.utils.platform import (
    get_platform_info,
    OperatingSystem,
    list_removable_drives,
)


class DiskType(str, Enum):
    """type of disk target"""

    IMAGE_FILE = "image"
    PHYSICAL_DISK = "physical"
    LOOP_DEVICE = "loop"


@dataclass
class DiskInfo:
    """information about a disk or image"""

    path: Path
    disk_type: DiskType
    size_bytes: int
    model: str = ""
    is_removable: bool = False
    is_mounted: bool = False
    partitions: list[str] = None

    def __post_init__(self):
        if self.partitions is None:
            self.partitions = []

    @property
    def size_gb(self) -> float:
        """size in gigabytes"""
        return self.size_bytes / (1024**3)

    @property
    def size_human(self) -> str:
        """human-readable size"""
        if self.size_bytes >= 1024**4:
            return f"{self.size_bytes / (1024**4):.1f} TB"
        elif self.size_bytes >= 1024**3:
            return f"{self.size_bytes / (1024**3):.1f} GB"
        elif self.size_bytes >= 1024**2:
            return f"{self.size_bytes / (1024**2):.1f} MB"
        else:
            return f"{self.size_bytes / 1024:.1f} KB"


@dataclass
class WriteProgress:
    """progress information for disk write operation"""

    bytes_written: int
    total_bytes: int
    speed_bytes_per_sec: float
    eta_seconds: float

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return (self.bytes_written / self.total_bytes) * 100


# progress callback type
ProgressCallback = Callable[[WriteProgress], None]


class DiskManager:
    """
    manages disk operations for image creation and writing

    provides platform-specific implementations for Linux and macOS.
    """

    def __init__(self):
        """initialize disk manager"""
        import logging
        self.logger = logging.getLogger("emu68hatcher.disk_manager")
        self.platform_info = get_platform_info()

    def list_removable_disks(self) -> list[DiskInfo]:
        """
        list removable disks suitable for writing"""
        drives = list_removable_drives()
        disks = []

        for drive in drives:
            try:
                size = self._get_disk_size(Path(drive["path"]))
            except Exception:
                size = 0

            disks.append(
                DiskInfo(
                    path=Path(drive["path"]),
                    disk_type=DiskType.PHYSICAL_DISK,
                    size_bytes=size,
                    model=drive.get("name", ""),
                    is_removable=True,
                    is_mounted=drive.get("mounted", False),
                )
            )

        return disks

    def get_disk_info(self, path: Path) -> Optional[DiskInfo]:
        """
        get information about a disk or image file"""
        if not path.exists():
            return None

        if path.is_file():
            return DiskInfo(
                path=path,
                disk_type=DiskType.IMAGE_FILE,
                size_bytes=path.stat().st_size,
            )
        elif path.is_block_device() if hasattr(path, 'is_block_device') else str(path).startswith("/dev/"):
            size = self._get_disk_size(path)
            return DiskInfo(
                path=path,
                disk_type=DiskType.PHYSICAL_DISK,
                size_bytes=size,
                is_removable=self._is_removable(path),
            )

        return None

    def _get_disk_size(self, path: Path) -> int:
        """get size of a disk device"""
        if self.platform_info.os == OperatingSystem.LINUX:
            return self._get_linux_disk_size(path)
        elif self.platform_info.os == OperatingSystem.MACOS:
            return self._get_macos_disk_size(path)
        return 0

    def _get_linux_disk_size(self, path: Path) -> int:
        """get disk size on Linux"""
        try:
            # try blockdev
            result = subprocess.run(
                ["blockdev", "--getsize64", str(path)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())

            # try lsblk
            device_name = path.name
            result = subprocess.run(
                ["lsblk", "-b", "-n", "-o", "SIZE", f"/dev/{device_name}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception:
            pass
        return 0

    def _get_macos_disk_size(self, path: Path) -> int:
        """get disk size on macOS"""
        try:
            result = subprocess.run(
                ["diskutil", "info", str(path)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "Disk Size:" in line or "Total Size:" in line:
                        match = re.search(r"\((\d+) Bytes\)", line)
                        if match:
                            return int(match.group(1))
        except Exception:
            pass
        return 0

    def _is_removable(self, path: Path) -> bool:
        """check if a disk is removable"""
        if self.platform_info.os == OperatingSystem.LINUX:
            device_name = path.name
            removable_path = Path(f"/sys/block/{device_name}/removable")
            if removable_path.exists():
                return removable_path.read_text().strip() == "1"
        elif self.platform_info.os == OperatingSystem.MACOS:
            try:
                result = subprocess.run(
                    ["diskutil", "info", str(path)],
                    capture_output=True,
                    text=True,
                )
                return "Removable Media: Yes" in result.stdout
            except Exception:
                pass
        return False

    # =========================================================================
    # image File Operations
    # =========================================================================

    def create_blank_image(
        self,
        path: Path,
        size_bytes: int,
        sparse: bool = True,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> bool:
        """
        create a blank disk image file"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            if sparse:
                # create sparse file
                with open(path, "wb") as f:
                    f.seek(size_bytes - 1)
                    f.write(b"\x00")
            else:
                # create fully allocated file
                chunk_size = 1024 * 1024  # 1 MB chunks
                written = 0

                with open(path, "wb") as f:
                    while written < size_bytes:
                        chunk = min(chunk_size, size_bytes - written)
                        f.write(b"\x00" * chunk)
                        written += chunk

                        if progress_callback:
                            progress_callback(
                                WriteProgress(
                                    bytes_written=written,
                                    total_bytes=size_bytes,
                                    speed_bytes_per_sec=chunk_size,
                                    eta_seconds=(size_bytes - written) / chunk_size,
                                )
                            )

            return True
        except Exception as e:
            return False

    def write_image_to_disk(
        self,
        image_path: Path,
        disk_path: Path,
        progress_callback: Optional[ProgressCallback] = None,
        verify: bool = False,
        gui_mode: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        write an image file to a physical disk

        DANGEROUS: This will overwrite all data on the target disk!"""
        if not image_path.exists():
            return False, f"Image file not found: {image_path}"

        # unmount disk first (may need privileges on some systems)
        unmount_result = self.unmount_disk(disk_path)
        if not unmount_result[0]:
            return False, f"Failed to unmount disk: {unmount_result[1]}"

        # write using platform-specific method with privilege escalation
        if self.platform_info.os == OperatingSystem.LINUX:
            return self._write_image_linux(
                image_path, disk_path, progress_callback, verify, gui_mode
            )
        elif self.platform_info.os == OperatingSystem.MACOS:
            return self._write_image_macos(
                image_path, disk_path, progress_callback, verify, gui_mode
            )
        elif self.platform_info.os == OperatingSystem.WINDOWS:
            return self._write_image_windows(
                image_path, disk_path, progress_callback, verify
            )

        return False, f"Unsupported platform: {self.platform_info.os}"

    def _write_image_linux(
        self,
        image_path: Path,
        disk_path: Path,
        progress_callback: Optional[ProgressCallback],
        verify: bool,
        gui_mode: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """write image on Linux using dd with sudo/pkexec

        uses dd status=progress for real-time progress reporting.
        in gui_mode, uses pkexec (graphical PolicyKit dialog) instead of sudo.
        """
        import re
        import threading
        import time

        total_bytes = image_path.stat().st_size

        self.logger.info(f"Writing {image_path} ({total_bytes / (1024**2):.0f} MB) to {disk_path}")

        if progress_callback:
            progress_callback(WriteProgress(
                bytes_written=0, total_bytes=total_bytes,
                speed_bytes_per_sec=0, eta_seconds=0,
            ))

        dd_cmd = [
            "dd",
            f"if={image_path}",
            f"of={disk_path}",
            "bs=4M",
            "conv=fsync",
            "status=progress",
        ]

        if not self.platform_info.is_root:
            if gui_mode:
                # pkexec shows a graphical auth dialog
                cmd = ["pkexec"] + dd_cmd
            else:
                # cache sudo credentials before piping stderr
                self.logger.info("Requesting administrator privileges...")
                auth = subprocess.run(["sudo", "-v"], stdin=None)
                if auth.returncode != 0:
                    return False, "Authentication failed or cancelled"
                cmd = ["sudo"] + dd_cmd
        else:
            cmd = dd_cmd

        # linux dd progress format: "123456789 bytes (123 MB, 118 MiB) copied, 5.12 s, 24.1 MB/s"
        progress_pattern = re.compile(
            r'(\d+)\s+bytes.*copied,\s+[\d.]+\s*s,\s+([\d.]+)\s*([kMG]?)B/s'
        )

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            stderr_chunks = []
            while True:
                chunk = process.stderr.read(4096)
                if not chunk:
                    break
                stderr_chunks.append(chunk)
                text = chunk.decode("utf-8", errors="replace")

                # dd uses \r for progress line updates
                for line in text.replace('\r', '\n').split('\n'):
                    match = progress_pattern.search(line)
                    if match and progress_callback:
                        bytes_written = int(match.group(1))
                        speed_val = float(match.group(2))
                        speed_unit = match.group(3)
                        multiplier = {'': 1, 'k': 1024, 'M': 1024**2, 'G': 1024**3}
                        speed_bps = speed_val * multiplier.get(speed_unit, 1)
                        remaining = total_bytes - bytes_written
                        eta = remaining / speed_bps if speed_bps > 0 else 0

                        progress_callback(WriteProgress(
                            bytes_written=bytes_written,
                            total_bytes=total_bytes,
                            speed_bytes_per_sec=speed_bps,
                            eta_seconds=eta,
                        ))

            process.wait()
            full_stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")

            if process.returncode != 0:
                if "dismissed" in full_stderr.lower() or process.returncode == 126:
                    return False, "Authentication cancelled by user"
                return False, f"dd failed (exit {process.returncode}): {full_stderr}"

            if progress_callback:
                progress_callback(WriteProgress(
                    bytes_written=total_bytes, total_bytes=total_bytes,
                    speed_bytes_per_sec=0, eta_seconds=0,
                ))

            subprocess.run(["sync"])
            return True, None

        except Exception as e:
            try:
                process.kill()
            except Exception:
                pass
            return False, str(e)

    def _write_image_macos(
        self,
        image_path: Path,
        disk_path: Path,
        progress_callback: Optional[ProgressCallback],
        verify: bool,
        gui_mode: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """write image on macOS using dd with privilege escalation

        uses /dev/rdisk (raw device) for significantly faster writes.
        CLI mode: sudo dd via os.system (terminal handles password + output).
        GUI mode: osascript admin privileges (native password dialog).
        """
        import time

        total_bytes = image_path.stat().st_size
        raw_disk = str(disk_path).replace("/dev/disk", "/dev/rdisk")

        self.logger.info(f"Writing {image_path} ({total_bytes / (1024**2):.0f} MB) to {raw_disk}")

        if progress_callback:
            progress_callback(WriteProgress(
                bytes_written=0, total_bytes=total_bytes,
                speed_bytes_per_sec=0, eta_seconds=0,
            ))

        # unmount all volumes on the disk
        result = subprocess.run(
            ["diskutil", "unmountDisk", str(disk_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False, f"Failed to unmount {disk_path}: {result.stderr}"

        # GUI mode: use osascript for native macOS password dialog
        if gui_mode and not self.platform_info.is_root:
            return self._write_image_macos_gui(
                image_path, raw_disk, disk_path, total_bytes,
                progress_callback,
            )

        # CLI mode: sudo dd on the terminal
        dd_args = f'if="{image_path}" of="{raw_disk}" bs=4m'

        total_mb = total_bytes // (1024 * 1024)

        if not self.platform_info.is_root:
            # authenticate first with a clear message
            print(f"\nWriting {total_mb} MB to {raw_disk} requires administrator privileges.")
            auth_rc = os.system("sudo -v")
            if auth_rc != 0:
                return False, "Authentication failed or cancelled"
            print()

        # shell script: run dd, send SIGINFO for progress, parse output into MB/%
        shell_script = (
            f'/bin/dd {dd_args} 2>/tmp/_dd_progress &'
            f' DD_PID=$!;'
            f' TOTAL={total_bytes};'
            f' while kill -0 $DD_PID 2>/dev/null; do'
            f'   kill -INFO $DD_PID 2>/dev/null;'
            f'   sleep 2;'
            f'   LINE=$(tail -1 /tmp/_dd_progress 2>/dev/null);'
            f'   BYTES=$(echo "$LINE" | grep -o "^[0-9]*");'
            f'   if [ -n "$BYTES" ] && [ "$BYTES" -gt 0 ] 2>/dev/null; then'
            f'     MB=$((BYTES / 1048576));'
            f'     PCT=$((BYTES * 100 / TOTAL));'
            f'     SPEED=$(echo "$LINE" | grep -o "([0-9]* bytes" | grep -o "[0-9]*");'
            f'     SPEED_MB=$((SPEED / 1048576));'
            f'     printf "\\r  %d / {total_mb} MB  (%d%%)  %d MB/s   " $MB $PCT $SPEED_MB;'
            f'   fi;'
            f' done;'
            f' wait $DD_PID; EXIT=$?;'
            f' printf "\\r  {total_mb} / {total_mb} MB  (100%%)              \\n";'
            f' rm -f /tmp/_dd_progress;'
            f' /bin/sync; exit $EXIT'
        )

        if not self.platform_info.is_root:
            cmd = f"sudo /bin/sh -c '{shell_script}'"
        else:
            cmd = f"/bin/sh -c '{shell_script}'"

        try:
            returncode = os.system(cmd)

            # os.system returns the exit status in the format of wait()
            exit_code = os.waitstatus_to_exitcode(returncode) if hasattr(os, 'waitstatus_to_exitcode') else returncode >> 8

            if exit_code != 0:
                return False, f"dd failed (exit {exit_code})"

            if progress_callback:
                progress_callback(WriteProgress(
                    bytes_written=total_bytes, total_bytes=total_bytes,
                    speed_bytes_per_sec=0, eta_seconds=0,
                ))

            # eject
            subprocess.run(
                ["diskutil", "eject", str(disk_path)],
                capture_output=True,
            )

            return True, None

        except Exception as e:
            return False, str(e)

    def _write_image_macos_gui(
        self,
        image_path: Path,
        raw_disk: str,
        disk_path: Path,
        total_bytes: int,
        progress_callback: Optional[ProgressCallback],
    ) -> tuple[bool, Optional[str]]:
        """write image on macOS via osascript (native password dialog)

        osascript blocks until both auth and dd complete. we can't get
        real progress, so we just report the phase (authenticating vs writing).
        """
        import time

        # escape paths for AppleScript double-quoted string
        escaped_image = str(image_path).replace('\\', '\\\\').replace('"', '\\"')
        escaped_disk = raw_disk.replace('\\', '\\\\').replace('"', '\\"')
        dd_shell = f'/bin/dd if=\\"{escaped_image}\\" of=\\"{escaped_disk}\\" bs=4m 2>&1 && /bin/sync'

        cmd = [
            "osascript", "-e",
            f'do shell script "{dd_shell}" with administrator privileges',
        ]

        self.logger.info(f"Writing to {raw_disk} (GUI auth)...")

        # show "waiting for auth" - osascript blocks until password entered
        if progress_callback:
            progress_callback(WriteProgress(
                bytes_written=0, total_bytes=total_bytes,
                speed_bytes_per_sec=0, eta_seconds=0,
            ))

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )

            # wait for auth + dd to complete
            # we can't distinguish auth phase from write phase, so just
            # show indeterminate progress once enough time has passed
            # for the auth dialog to have been dismissed
            auth_likely_done = False
            start_time = time.time()

            while process.poll() is None:
                elapsed = time.time() - start_time
                # after ~10s, assume auth is done and dd is running
                if not auth_likely_done and elapsed > 10:
                    auth_likely_done = True
                if progress_callback:
                    if auth_likely_done:
                        # show that writing is in progress (no fake speed/ETA)
                        progress_callback(WriteProgress(
                            bytes_written=0, total_bytes=total_bytes,
                            speed_bytes_per_sec=0, eta_seconds=0,
                        ))
                time.sleep(2)

            stdout = process.stdout.read()
            stderr = process.stderr.read()
            output = stdout + stderr

            if process.returncode != 0:
                if "cancel" in output.lower() or "user canceled" in output.lower():
                    return False, "Authentication cancelled by user"
                if "operation not permitted" in output.lower():
                    return False, (
                        f"macOS blocked raw disk access to {raw_disk}. "
                        "Full Disk Access is required - see the dialog for "
                        "setup instructions."
                    )
                return False, f"Write failed: {output}"

            if progress_callback:
                progress_callback(WriteProgress(
                    bytes_written=total_bytes, total_bytes=total_bytes,
                    speed_bytes_per_sec=0, eta_seconds=0,
                ))

            # eject
            subprocess.run(
                ["diskutil", "eject", str(disk_path)],
                capture_output=True,
            )

            return True, None

        except Exception as e:
            try:
                process.kill()
            except Exception:
                pass
            return False, str(e)

    def _write_image_windows(
        self,
        image_path: Path,
        disk_path: Path,
        progress_callback: Optional[ProgressCallback],
        verify: bool,
    ) -> tuple[bool, Optional[str]]:
        """write image on Windows using PowerShell with raw disk access

        uses CreateFile with GENERIC_WRITE for raw disk access, run elevated
        via Start-Process -Verb RunAs. progress is written to a temp file
        that we poll from the main process.
        """
        import tempfile
        import threading
        import time

        total_bytes = image_path.stat().st_size

        self.logger.info(f"Writing {image_path} ({total_bytes / (1024**2):.0f} MB) to {disk_path}")

        if progress_callback:
            progress_callback(WriteProgress(
                bytes_written=0, total_bytes=total_bytes,
                speed_bytes_per_sec=0, eta_seconds=0,
            ))

        # progress file for communication between elevated and main process
        progress_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.progress', delete=False
        )
        progress_path = progress_file.name
        progress_file.close()

        # PowerShell script that writes image with progress reporting
        ps_script = f'''
$ErrorActionPreference = "Stop"
$progressFile = "{progress_path}"
$bufferSize = 4194304
$source = [System.IO.File]::OpenRead("{image_path}")
$sourceLength = $source.Length

# Open physical disk for raw write
$disk = [System.IO.File]::Open(
    "{disk_path}",
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Write,
    [System.IO.FileShare]::None
)

$buffer = New-Object byte[] $bufferSize
$totalRead = [long]0

try {{
    while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {{
        $disk.Write($buffer, 0, $read)
        $totalRead += $read
        # Write progress to file for the parent process to read
        "$totalRead" | Set-Content -Path $progressFile -NoNewline
    }}
    $disk.Flush()
}} finally {{
    $disk.Close()
    $source.Close()
}}
"DONE:$totalRead" | Set-Content -Path $progressFile -NoNewline
'''

        try:
            # write script to temp file
            script_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.ps1', delete=False, encoding='utf-8'
            )
            script_file.write(ps_script)
            script_path = script_file.name
            script_file.close()

            # poll progress file in background
            poll_active = True

            def poll_progress():
                last_bytes = 0
                last_time = time.time()
                while poll_active:
                    try:
                        content = Path(progress_path).read_text().strip()
                        if content.startswith("DONE:"):
                            break
                        bytes_written = int(content)
                        now = time.time()
                        elapsed = now - last_time
                        if elapsed > 0 and bytes_written > last_bytes:
                            speed = (bytes_written - last_bytes) / elapsed
                            remaining = total_bytes - bytes_written
                            eta = remaining / speed if speed > 0 else 0
                            if progress_callback:
                                progress_callback(WriteProgress(
                                    bytes_written=bytes_written,
                                    total_bytes=total_bytes,
                                    speed_bytes_per_sec=speed,
                                    eta_seconds=eta,
                                ))
                            last_bytes = bytes_written
                            last_time = now
                    except (ValueError, FileNotFoundError):
                        pass
                    time.sleep(0.5)

            poll_thread = threading.Thread(target=poll_progress, daemon=True)
            poll_thread.start()

            # run elevated
            cmd = [
                "powershell", "-Command",
                f"Start-Process powershell "
                f"-ArgumentList '-ExecutionPolicy Bypass -File \"{script_path}\"' "
                f"-Verb RunAs -Wait"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

            poll_active = False
            poll_thread.join(timeout=2)

            # clean up
            Path(script_path).unlink(missing_ok=True)
            Path(progress_path).unlink(missing_ok=True)

            if result.returncode != 0:
                return False, f"Write failed: {result.stderr}"

            if progress_callback:
                progress_callback(WriteProgress(
                    bytes_written=total_bytes, total_bytes=total_bytes,
                    speed_bytes_per_sec=0, eta_seconds=0,
                ))

            return True, None

        except subprocess.TimeoutExpired:
            return False, "Write operation timed out (>60 minutes)"
        except Exception as e:
            return False, str(e)

    # =========================================================================
    # mount/Unmount Operations
    # =========================================================================

    def unmount_disk(self, disk_path: Path) -> tuple[bool, Optional[str]]:
        """
        unmount all partitions on a disk"""
        if self.platform_info.os == OperatingSystem.LINUX:
            return self._unmount_linux(disk_path)
        elif self.platform_info.os == OperatingSystem.MACOS:
            return self._unmount_macos(disk_path)
        return False, "Unsupported platform"

    def _unmount_linux(self, disk_path: Path) -> tuple[bool, Optional[str]]:
        """unmount disk on Linux"""
        try:
            # find all mounted partitions
            device_name = disk_path.name
            result = subprocess.run(
                ["lsblk", "-n", "-o", "MOUNTPOINT", str(disk_path)],
                capture_output=True,
                text=True,
            )

            # unmount each partition
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    subprocess.run(["umount", line.strip()], capture_output=True)

            return True, None
        except Exception as e:
            return False, str(e)

    def _unmount_macos(self, disk_path: Path) -> tuple[bool, Optional[str]]:
        """unmount disk on macOS"""
        try:
            result = subprocess.run(
                ["diskutil", "unmountDisk", str(disk_path)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, result.stderr

            return True, None
        except Exception as e:
            return False, str(e)

    def mount_image(
        self,
        image_path: Path,
        mount_point: Optional[Path] = None,
    ) -> tuple[bool, Optional[Path], Optional[str]]:
        """
        mount a disk image"""
        if self.platform_info.os == OperatingSystem.LINUX:
            return self._mount_image_linux(image_path, mount_point)
        elif self.platform_info.os == OperatingSystem.MACOS:
            return self._mount_image_macos(image_path, mount_point)
        return False, None, "Unsupported platform"

    def _mount_image_linux(
        self,
        image_path: Path,
        mount_point: Optional[Path],
    ) -> tuple[bool, Optional[Path], Optional[str]]:
        """mount image on Linux using loop device"""
        try:
            # set up loop device
            result = subprocess.run(
                ["losetup", "-f", "--show", "-P", str(image_path)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, None, f"losetup failed: {result.stderr}"

            loop_device = result.stdout.strip()

            # create mount point
            if mount_point is None:
                mount_point = Path(f"/mnt/emu68-{image_path.stem}")

            mount_point.mkdir(parents=True, exist_ok=True)

            # mount first partition (FAT32 boot)
            part1 = f"{loop_device}p1"
            result = subprocess.run(
                ["mount", part1, str(mount_point)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # clean up loop device
                subprocess.run(["losetup", "-d", loop_device])
                return False, None, f"mount failed: {result.stderr}"

            return True, mount_point, None

        except Exception as e:
            return False, None, str(e)

    def _mount_image_macos(
        self,
        image_path: Path,
        mount_point: Optional[Path],
    ) -> tuple[bool, Optional[Path], Optional[str]]:
        """mount image on macOS using hdiutil"""
        try:
            result = subprocess.run(
                ["hdiutil", "attach", "-imagekey", "diskimage-class=CRawDiskImage",
                 str(image_path)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, None, f"hdiutil attach failed: {result.stderr}"

            # parse output to find mount point
            for line in result.stdout.split("\n"):
                parts = line.split("\t")
                if len(parts) >= 3 and parts[2].strip():
                    return True, Path(parts[2].strip()), None

            return False, None, "Could not determine mount point"

        except Exception as e:
            return False, None, str(e)

    def unmount_image(self, mount_point: Path) -> tuple[bool, Optional[str]]:
        """
        unmount a mounted disk image"""
        if self.platform_info.os == OperatingSystem.LINUX:
            return self._unmount_image_linux(mount_point)
        elif self.platform_info.os == OperatingSystem.MACOS:
            return self._unmount_image_macos(mount_point)
        return False, "Unsupported platform"

    def _unmount_image_linux(
        self,
        mount_point: Path,
    ) -> tuple[bool, Optional[str]]:
        """unmount image on Linux"""
        try:
            # find loop device
            result = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", str(mount_point)],
                capture_output=True,
                text=True,
            )

            loop_device = result.stdout.strip()

            # unmount
            subprocess.run(["umount", str(mount_point)], check=True)

            # detach loop device
            if loop_device.startswith("/dev/loop"):
                base_loop = loop_device.rstrip("0123456789").rstrip("p")
                subprocess.run(["losetup", "-d", base_loop], capture_output=True)

            return True, None

        except Exception as e:
            return False, str(e)

    def _unmount_image_macos(
        self,
        mount_point: Path,
    ) -> tuple[bool, Optional[str]]:
        """unmount image on macOS"""
        try:
            result = subprocess.run(
                ["hdiutil", "detach", str(mount_point)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, result.stderr

            return True, None

        except Exception as e:
            return False, str(e)


