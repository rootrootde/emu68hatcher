"""
amiga file processing for Emu68 Hatcher

handles preparation of files for installation on Amiga partitions:
- file attribute preservation
- path conversion (Unix -> Amiga)
- file filtering and organization
- amiga .info file tooltype modification
"""

import logging
import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from emu68hatcher.utils.paths import ensure_dir

logger = logging.getLogger(__name__)


# --- Amiga .info file tooltype modification ---


def read_info_tooltypes(info_path: Path) -> list[str]:
    """read tooltypes from an Amiga .info file"""
    data = info_path.read_bytes()
    _, tooltypes, _ = _parse_info_to_tooltypes(data)
    return tooltypes


def write_info_tooltypes(info_path: Path, tooltypes: list[str]) -> None:
    """replace all tooltypes in an Amiga .info file"""
    data = info_path.read_bytes()
    tt_start, _, tt_end = _parse_info_to_tooltypes(data)

    # set the ToolTypes pointer in the header (non-zero = tooltypes present)
    # the actual pointer value doesn't matter on disk - just needs to be
    # non-zero to signal that the tooltype section exists
    header = bytearray(data[:78])
    if tooltypes:
        struct.pack_into(">I", header, 54, 1)
    else:
        struct.pack_into(">I", header, 54, 0)

    # build new tooltype section.  on-disk format:
    #   DWORD  pointer_array_size  =  (num_entries + 1) * 4
    #          (the in-memory size of the char** array incl. NULL terminator)
    #   for each entry:
    #     DWORD  string_length  (including null terminator)
    #     BYTE[] string_data    (null-terminated)
    ptr_array_size = (len(tooltypes) + 1) * 4
    new_tt = struct.pack(">I", ptr_array_size)
    for tt in tooltypes:
        tt_bytes = tt.encode("iso-8859-1") + b"\x00"
        new_tt += struct.pack(">I", len(tt_bytes)) + tt_bytes

    new_data = bytes(header) + data[78:tt_start] + new_tt + data[tt_end:]
    info_path.write_bytes(new_data)
    logger.info(f"Wrote {len(tooltypes)} tooltypes to {info_path.name}")


def _parse_info_to_tooltypes(data: bytes) -> tuple[int, list[str], int]:
    """parse an Amiga .info file to find the tooltypes section"""
    size = len(data)
    if size < 78:
        raise ValueError(f"File too small for .info header ({size} bytes)")

    magic = struct.unpack(">H", data[0:2])[0]
    if magic != 0xE310:
        raise ValueError(f"Not an Amiga .info file (magic=0x{magic:04X})")

    has_first_image = struct.unpack(">I", data[22:26])[0] != 0
    has_second_image = struct.unpack(">I", data[26:30])[0] != 0
    has_default_tool = struct.unpack(">I", data[50:54])[0] != 0
    has_tooltypes = struct.unpack(">I", data[54:58])[0] != 0

    offset = 78  # after DiskObject header

    # skip first image (struct Image = 20 bytes + pixel data)
    if has_first_image:
        offset = _skip_image(data, offset)

    # skip second image
    if has_second_image:
        offset = _skip_image(data, offset)

    # skip DefaultTool string
    if has_default_tool and offset + 4 <= size:
        dt_len = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4 + dt_len

    # read ToolTypes.  on-disk format:
    #   DWORD  pointer_array_size  =  (num_entries + 1) * 4
    #   for each entry: DWORD string_length + BYTE[] string_data
    tt_start = offset
    tooltypes: list[str] = []
    if has_tooltypes and offset + 4 <= size:
        ptr_array_size = struct.unpack(">I", data[offset : offset + 4])[0]
        num_entries = (ptr_array_size // 4) - 1 if ptr_array_size >= 4 else 0
        offset += 4
        for _ in range(num_entries):
            if offset + 4 > size:
                break
            tt_len = struct.unpack(">I", data[offset : offset + 4])[0]
            if offset + 4 + tt_len > size:
                break
            raw = data[offset + 4 : offset + 4 + tt_len]
            # strip null terminator
            tt_str = raw.rstrip(b"\x00").decode("iso-8859-1")
            tooltypes.append(tt_str)
            offset += 4 + tt_len

    return tt_start, tooltypes, offset


def _skip_image(data: bytes, offset: int) -> int:
    """skip an Amiga Image structure + pixel data, return new offset"""
    width = struct.unpack(">H", data[offset + 4 : offset + 6])[0]
    height = struct.unpack(">H", data[offset + 6 : offset + 8])[0]
    depth = struct.unpack(">H", data[offset + 8 : offset + 10])[0]
    offset += 20  # image struct size
    # pixel data: word-aligned width * height * depth
    word_width = (width + 15) // 16
    offset += word_width * 2 * height * depth
    return offset


@dataclass
class AmigaFile:
    """represents a file to be installed on Amiga"""

    source_path: Path
    dest_path: str  # amiga-style path (e.g., "C/Dir")
    device: str = "DH0"
    is_executable: bool = False
    icon_path: Optional[Path] = None
    comment: str = ""

    @property
    def full_dest(self) -> str:
        """get full Amiga destination path"""
        return f"{self.device}:{self.dest_path}"

    @property
    def has_icon(self) -> bool:
        """check if file has an associated icon"""
        return self.icon_path is not None and self.icon_path.exists()


def resolve_staging_path(base: Path, rel_path: str) -> Path:
    """resolve a relative path under base using case-insensitive matching

    amiga filesystems (PFS3, FFS) are case-insensitive. on a case-sensitive
    host filesystem, archives may use different casing for the same directory
    (e.g. ``Classes/Gadgets/`` vs ``Classes/gadgets/``). without resolution,
    these become separate directories on disk, and one set of files is lost
    when copied to the case-insensitive target partition.

    for each path component, if a case-insensitive match already exists on
    disk, the existing name is reused (first-writer-wins, matching PFS3).
    """
    result = base
    for part in Path(rel_path).parts:
        if not result.is_dir():
            result = result / part
            continue
        # fast path: exact match
        candidate = result / part
        if candidate.exists():
            result = candidate
            continue
        # case-insensitive scan
        part_lower = part.lower()
        matched = None
        try:
            for entry in result.iterdir():
                if entry.name.lower() == part_lower:
                    matched = entry.name
                    break
        except OSError:
            pass
        result = result / (matched if matched else part)
    return result


@dataclass
class FileMapping:
    """mapping of source files to Amiga destinations"""

    files: list[AmigaFile] = field(default_factory=list)

    def add(
        self,
        source: Path,
        dest: str,
        device: str = "DH0",
        executable: bool = False,
    ) -> None:
        """add a file mapping"""
        # check for associated icon
        icon_path = Path(str(source) + ".info")
        if not icon_path.exists():
            icon_path = None

        self.files.append(
            AmigaFile(
                source_path=source,
                dest_path=dest,
                device=device,
                is_executable=executable,
                icon_path=icon_path,
            )
        )

    def add_directory(
        self,
        source_dir: Path,
        dest_dir: str,
        device: str = "DH0",
        recursive: bool = True,
        filter_func: Optional[Callable[[Path], bool]] = None,
    ) -> None:
        """add all files from a directory"""
        if not source_dir.exists():
            return

        pattern = "**/*" if recursive else "*"

        for source in source_dir.glob(pattern):
            if source.is_file():
                # check if this is a .info file
                if source.suffix.lower() == ".info":
                    # check if there's a corresponding non-.info file (tool/program icon)
                    # if so, skip - it will be handled with its parent file
                    base_path = source.with_suffix("")
                    if base_path.exists() and base_path.is_file():
                        continue
                    # also check if this is a drawer icon (for a directory)
                    # these should be copied as standalone files
                    if base_path.exists() and base_path.is_dir():
                        # this is a drawer icon - copy it directly
                        pass
                    # if no matching file/dir exists, still copy the .info
                    # (might be orphaned or for something we didn't extract)

                # apply filter if provided
                if filter_func and not filter_func(source):
                    continue

                # calculate relative path
                rel_path = source.relative_to(source_dir)
                amiga_rel_path = unix_to_amiga_path(str(rel_path))
                # handle empty dest_dir (root of partition)
                if dest_dir:
                    dest_path = f"{dest_dir}/{amiga_rel_path}"
                else:
                    dest_path = amiga_rel_path

                self.add(source, dest_path, device)

    def get_by_device(self, device: str) -> list[AmigaFile]:
        """get files for a specific device"""
        return [f for f in self.files if f.device == device]

    def get_total_size(self) -> int:
        """get total size of all files in bytes"""
        total = 0
        for f in self.files:
            if f.source_path.exists():
                total += f.source_path.stat().st_size
                if f.has_icon:
                    total += f.icon_path.stat().st_size
        return total


def unix_to_amiga_path(path: str) -> str:
    """
    convert Unix-style path to Amiga-style

    - converts / to /
    - handles special Amiga directories
    """
    # already Amiga-style if contains :
    if ":" in path:
        return path

    # replace backslashes
    path = path.replace("\\", "/")

    # remove leading ./
    if path.startswith("./"):
        path = path[2:]

    # remove leading /
    path = path.lstrip("/")

    return path


def prepare_staging_directory(
    staging_dir: Path,
    devices: list[str],
) -> dict[str, Path]:
    """
    prepare staging directories for each device

    only creates standard Amiga subdirectories for Amiga devices,
    not for special partitions like EMU68BOOT (FAT32)."""
    device_dirs = {}

    # standard Amiga directories - only for Amiga partitions
    AMIGA_SUBDIRS = ["C", "S", "L", "Libs", "Devs", "Prefs", "Fonts", "T"]

    # devices that are NOT Amiga partitions (don't create Amiga subdirs)
    NON_AMIGA_DEVICES = {"EMU68BOOT", "BOOT", "FAT32"}

    for device in devices:
        device_dir = ensure_dir(staging_dir / device)
        device_dirs[device] = device_dir

        # only create standard Amiga directories for Amiga devices
        if device.upper() not in NON_AMIGA_DEVICES:
            for subdir in AMIGA_SUBDIRS:
                ensure_dir(device_dir / subdir)

    return device_dirs


def stage_files(
    mapping: FileMapping,
    staging_dir: Path,
) -> int:
    """
    copy files to staging directory structure"""
    count = 0

    for amiga_file in mapping.files:
        if not amiga_file.source_path.exists():
            continue

        # determine staging destination (case-insensitive to match PFS3)
        device_dir = staging_dir / amiga_file.device
        dest = resolve_staging_path(device_dir, amiga_file.dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # copy main file
        shutil.copy2(amiga_file.source_path, dest)
        count += 1

        # copy icon if present
        if amiga_file.has_icon:
            icon_dest = Path(str(dest) + ".info")
            shutil.copy2(amiga_file.icon_path, icon_dest)
            count += 1

    return count


