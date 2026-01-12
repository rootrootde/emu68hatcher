"""
HST Imager command generation for Emu68 Hatcher

generates HST Imager commands for:
- creating blank disk images
- partitioning (MBR + RDB)
- formatting filesystems
- copying files to/from images

based on the PowerShell implementation from the original Emu68 Hatcher.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from emu68hatcher.config.schema import (
    AmigaPartition,
    BuildConfig,
    Filesystem,
    MBRPartition,
    PartitionConfig,
)


class HSTCommand(str, Enum):
    """HST Imager command types"""

    # image operations
    BLANK = "blank"
    CONVERT = "convert"
    INFO = "info"
    READ = "read"
    WRITE = "write"
    OPTIMIZE = "optimize"

    # partition operations
    MBR_INIT = "mbr init"
    MBR_PART_ADD = "mbr part add"
    MBR_PART_FORMAT = "mbr part format"
    RDB_INIT = "rdb init"
    RDB_PART_ADD = "rdb part add"
    RDB_PART_FORMAT = "rdb part format"
    RDB_FS_ADD = "rdb fs add"
    RDB_FS_IMPORT = "rdb fs import"

    # filesystem operations
    FS_DIR = "fs dir"
    FS_COPY = "fs copy"
    FS_EXTRACT = "fs extract"


@dataclass
class HSTCommandLine:
    """represents a single HST Imager command"""

    command: HSTCommand
    args: list[str] = field(default_factory=list)
    description: str = ""

    def to_args(self) -> list[str]:
        """convert to command line arguments"""
        return self.command.value.split() + self.args

    def to_string(self) -> str:
        """convert to command string for display"""
        return f"hst-imager {self.command.value} {' '.join(self.args)}"


@dataclass
class HSTScript:
    """collection of HST commands to execute"""

    commands: list[HSTCommandLine] = field(default_factory=list)
    description: str = ""

    def add(self, command: HSTCommand, *args: str, description: str = "") -> None:
        """add a command to the script"""
        self.commands.append(
            HSTCommandLine(
                command=command,
                args=list(args),
                description=description,
            )
        )

    def to_script_file(self) -> str:
        """generate script content for batch execution"""
        lines = []
        for cmd in self.commands:
            if cmd.description:
                lines.append(f"# {cmd.description}")
            lines.append(cmd.to_string())
            lines.append("")
        return "\n".join(lines)


# =============================================================================
# filesystem handler paths (PFS3, FFS, etc.)
# =============================================================================

# DOS types must be 4 ASCII characters for hst-imager
# PFS3 AIO handler - commonly used for large partitions
PFS3_HANDLER_NAME = "pfs3aio"
PFS3_DOSTYPE = "PFS3"

# FFS handler - built into Kickstart
FFS_DOSTYPE = "DOS1"

# filesystem handlers bundled with the tool
FILESYSTEM_HANDLERS = {
    Filesystem.PFS3: {
        "name": "pfs3aio",
        "dostype": "PFS3",
        "handler_file": "pfs3aio",
    },
    Filesystem.FFS: {
        "name": "FastFileSystem",
        "dostype": "DOS1",
        "handler_file": None,  # built into Kickstart
    },
}


# =============================================================================
# command Generators
# =============================================================================


def generate_blank_image_command(
    output_path: Path,
    size_bytes: int,
) -> HSTCommandLine:
    """
    generate command to create a blank disk image"""
    return HSTCommandLine(
        command=HSTCommand.BLANK,
        args=[str(output_path), str(size_bytes)],
        description=f"Create blank {size_bytes // (1024**3)}GB image",
    )


def generate_mbr_init_command(image_path: Path) -> HSTCommandLine:
    """generate command to initialize MBR on image"""
    return HSTCommandLine(
        command=HSTCommand.MBR_INIT,
        args=[str(image_path)],
        description="Initialize MBR partition table",
    )


def generate_mbr_partition_commands(
    image_path: Path,
    partitions: list[MBRPartition],
) -> list[HSTCommandLine]:
    """
    generate commands to create MBR partitions"""
    commands = []

    # MBR first partition starts at sector 2048 (like original Emu68 Imager)
    MBR_FIRST_PARTITION_START_SECTOR = 2048
    current_sector = MBR_FIRST_PARTITION_START_SECTOR

    for i, part in enumerate(partitions):
        # determine partition type (matching original Emu68 Imager)
        if part.type == "fat32":
            part_type = "0xb"  # FAT32 (original uses 0xb, not 0x0C)
        else:
            part_type = "0x76"  # amiga RDB (ID76)

        # calculate size in sectors (512 bytes per sector)
        size_sectors = part.size // 512

        # add partition with explicit start sector
        commands.append(
            HSTCommandLine(
                command=HSTCommand.MBR_PART_ADD,
                args=[
                    str(image_path),
                    part_type,
                    str(part.size),
                    "--start-sector", str(current_sector),
                ],
                description=f"Add MBR partition {i+1}: {part.name} ({part.type})",
            )
        )

        # move to next partition start
        current_sector += size_sectors

        # format FAT32 partitions
        if part.type == "fat32":
            commands.append(
                HSTCommandLine(
                    command=HSTCommand.MBR_PART_FORMAT,
                    args=[
                        str(image_path),
                        str(i + 1),  # partition number (1-based)
                        part.name,
                    ],
                    description=f"Format {part.name} as FAT32",
                )
            )

    return commands


def generate_rdb_init_command(
    image_path: Path,
    partition_number: int,
) -> HSTCommandLine:
    """generate command to initialize RDB on an ID76 partition"""
    # use path notation: image_path/mbr/N (like original Emu68 Imager)
    rdb_path = f"{image_path}/mbr/{partition_number}"
    return HSTCommandLine(
        command=HSTCommand.RDB_INIT,
        args=[rdb_path],
        description=f"Initialize RDB in MBR partition {partition_number}",
    )


def generate_rdb_filesystem_command(
    image_path: Path,
    partition_number: int,
    filesystem: Filesystem,
    handler_path: Optional[Path] = None,
) -> HSTCommandLine:
    """
    generate command to add filesystem handler to RDB"""
    fs_info = FILESYSTEM_HANDLERS.get(filesystem, FILESYSTEM_HANDLERS[Filesystem.PFS3])

    # use path notation: image_path/mbr/N
    rdb_path = f"{image_path}/mbr/{partition_number}"

    # command format: rdb fs add "path" "handler_path" DOSTYPE
    if handler_path and fs_info["handler_file"]:
        args = [rdb_path, str(handler_path), fs_info["dostype"]]
    else:
        # for built-in filesystems, we still need a handler path
        # this should be provided by the caller
        args = [rdb_path, fs_info["name"], fs_info["dostype"]]

    return HSTCommandLine(
        command=HSTCommand.RDB_FS_ADD,
        args=args,
        description=f"Add {filesystem.value} filesystem handler",
    )


def generate_rdb_partition_commands(
    image_path: Path,
    mbr_partition_number: int,
    amiga_partitions: list[AmigaPartition],
) -> list[HSTCommandLine]:
    """
    generate commands to create Amiga RDB partitions"""
    commands = []

    # use path notation: image_path/mbr/N
    rdb_path = f"{image_path}/mbr/{mbr_partition_number}"

    for i, part in enumerate(amiga_partitions):
        fs_info = FILESYSTEM_HANDLERS.get(part.filesystem, FILESYSTEM_HANDLERS[Filesystem.PFS3])

        # command format from original:
        # rdb part add "path/mbr/N" DEVICE DOSTYPE SIZE --buffers X --max-transfer X --mask X
        #              --no-mount BOOL --bootable BOOL --boot-priority X
        args = [
            rdb_path,
            part.device,
            fs_info["dostype"],
            str(part.size),
            "--buffers", str(part.buffers),
            "--max-transfer", hex(part.max_transfer),
            "--mask", hex(part.mask),
        ]

        # add no-mount flag
        if part.no_mount:
            args.append("--no-mount")

        # add bootable flags
        if part.bootable:
            args.extend(["--bootable", "--boot-priority", str(part.priority)])

        commands.append(
            HSTCommandLine(
                command=HSTCommand.RDB_PART_ADD,
                args=args,
                description=f"Add Amiga partition {part.device}: {part.volume}",
            )
        )

        # format the partition (uses RDB partition number, 1-based)
        rdb_partition_number = i + 1
        commands.append(
            HSTCommandLine(
                command=HSTCommand.RDB_PART_FORMAT,
                args=[
                    rdb_path,
                    str(rdb_partition_number),
                    part.volume,
                ],
                description=f"Format {part.device} as {part.filesystem.value}",
            )
        )

    return commands


# =============================================================================
# full Build Script Generation
# =============================================================================


def generate_disk_creation_script(
    config: BuildConfig,
    output_path: Path,
    pfs3_handler_path: Optional[Path] = None,
) -> HSTScript:
    """
    generate complete HST script for disk image creation"""
    if config.partitions is None:
        raise ValueError("Partition configuration is required")

    script = HSTScript(description="Emu68 Hatcher - Disk Creation")

    # 1. create blank image
    script.commands.append(
        generate_blank_image_command(output_path, config.partitions.disk_size)
    )

    # 2. initialize MBR
    script.commands.append(generate_mbr_init_command(output_path))

    # 3. create MBR partitions
    script.commands.extend(
        generate_mbr_partition_commands(output_path, config.partitions.layout)
    )

    # 4. initialize RDB and create Amiga partitions for ID76 partitions
    for i, mbr_part in enumerate(config.partitions.layout):
        if mbr_part.type == "id76" and mbr_part.amiga_partitions:
            mbr_num = i + 1  # 1-based

            # initialize RDB
            script.commands.append(
                generate_rdb_init_command(output_path, mbr_num)
            )

            # add filesystem handlers (skip built-in FFS/OFS - ROM has them)
            filesystems_added = set()
            for amiga_part in mbr_part.amiga_partitions:
                fs = amiga_part.filesystem
                fs_info = FILESYSTEM_HANDLERS.get(fs)
                if fs not in filesystems_added and fs_info and fs_info["handler_file"]:
                    script.commands.append(
                        generate_rdb_filesystem_command(
                            output_path,
                            mbr_num,
                            fs,
                            pfs3_handler_path,
                        )
                    )
                    filesystems_added.add(fs)

            # create Amiga partitions
            script.commands.extend(
                generate_rdb_partition_commands(
                    output_path,
                    mbr_num,
                    mbr_part.amiga_partitions,
                )
            )

    return script


