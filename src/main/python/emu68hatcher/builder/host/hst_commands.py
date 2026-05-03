"""HST Imager command generation - create blank image, partition (MBR+RDB), format, copy files"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from emu68hatcher.config.schema import (
    AmigaPartition,
    BuildConfig,
    Filesystem,
    MBRPartition,
)


class HSTCommand(str, Enum):
    """HST Imager command types for the build pipeline"""

    # image + partition operations
    BLANK = "blank"
    MBR_INIT = "mbr init"
    MBR_PART_ADD = "mbr part add"
    MBR_PART_FORMAT = "mbr part format"
    RDB_INIT = "rdb init"
    RDB_PART_ADD = "rdb part add"
    RDB_PART_FORMAT = "rdb part format"
    RDB_FS_ADD = "rdb fs add"

    # filesystem operations
    FS_COPY = "fs copy"


@dataclass
class HSTCommandLine:
    """represents a singel HST Imager command"""

    command: HSTCommand
    args: list[str] = field(default_factory=list)
    description: str = ""

    def to_args(self) -> list[str]:
        """convert to command line argumets"""
        return self.command.value.split() + self.args

    def to_string(self) -> str:
        """convert to command string for display"""
        return f"hst-imager {self.command.value} {' '.join(self.args)}"


@dataclass
class HSTScript:
    """collection of HST commands to execute"""

    commands: list[HSTCommandLine] = field(default_factory=list)
    description: str = ""


##############################################
# filesystem handler paths (PFS3, FFS, etc.) #
##############################################

# dostype: 4 ASCII chars, last is interpreted as a hex digit ("PFS3" → PFS\x03)
FILESYSTEM_HANDLERS = {
    Filesystem.PFS3: {
        "name": "pfs3aio",
        "dostype": "PFS3",
        "handler_file": "pfs3aio",
    },
    Filesystem.FFS: {
        "name": "FastFileSystem",
        "dostype": "DOS3",
        "handler_file": "FastFileSystem",
    },
}


######################
# command Generators #
######################


def generate_blank_image_command(
    output_path: Path,
    size_bytes: int,
) -> HSTCommandLine:
    """generate command to create a blank disk image"""
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
    """generate commands to create MBR partitions"""
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
                    "--start-sector",
                    str(current_sector),
                ],
                description=f"Add MBR partition {i + 1}: {part.name} ({part.type})",
            )
        )

        # move to next partition start
        current_sector += size_sectors

        # format FAT32 partition
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
    """generate command to initialize RDB on ID76 partition"""
    # path notation: image_path/mbr/X
    rdb_path = f"{image_path.as_posix()}/mbr/{partition_number}"
    return HSTCommandLine(
        command=HSTCommand.RDB_INIT,
        args=[rdb_path],
        description=f"Initialize RDB in MBR partition {partition_number}",
    )


def generate_rdb_filesystem_command(
    image_path: Path,
    partition_number: int,
    filesystem: Filesystem,
    handler_path: Path | None = None,
) -> HSTCommandLine:
    """generate command to add filesystem handler to RDB"""
    fs_info = FILESYSTEM_HANDLERS.get(filesystem, FILESYSTEM_HANDLERS[Filesystem.PFS3])

    # path notation: image_path/mbr/X
    rdb_path = f"{image_path.as_posix()}/mbr/{partition_number}"

    # command format: rdb fs add "path" "handler_path" DOSTYPE
    if handler_path and fs_info["handler_file"]:
        args = [rdb_path, str(handler_path), fs_info["dostype"]]
    else:
        # built-in filesystems still need a handler path - caller must provide one
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
    """generate commands to create Amiga RDB partitions"""
    commands = []

    # path notation: image_path/mbr/X
    rdb_path = f"{image_path.as_posix()}/mbr/{mbr_partition_number}"

    for i, part in enumerate(amiga_partitions):
        fs_info = FILESYSTEM_HANDLERS.get(part.filesystem, FILESYSTEM_HANDLERS[Filesystem.PFS3])

        # rdb part add "path/mbr/N" DEVICE DOSTYPE SIZE --buffers --max-transfer --mask --no-mount --bootable --boot-priority
        args = [
            rdb_path,
            part.device,
            fs_info["dostype"],
            str(part.size),
            "--buffers",
            str(part.buffers),
            "--max-transfer",
            hex(part.max_transfer),
            "--mask",
            hex(part.mask),
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

        # format the partition
        rdb_partition_number = i + 1  # rdb partition numbers are 1 based
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


def generate_disk_creation_script(
    config: BuildConfig,
    output_path: Path,
    fs_handler_paths: dict[Filesystem, Path] | None = None,
) -> HSTScript:
    """complete HST script for disk image creation. fs_handler_paths: on-host handler file per non-ROM-resident FS"""
    if config.partitions is None:
        raise ValueError("Partition configuration is required")

    fs_handler_paths = fs_handler_paths or {}
    script = HSTScript(description="Emu68 Hatcher - Disk Creation")

    # 1. create blank image
    script.commands.append(generate_blank_image_command(output_path, config.partitions.disk_size))

    # 2. initialize MBR
    script.commands.append(generate_mbr_init_command(output_path))

    # 3. create MBR partitions
    script.commands.extend(generate_mbr_partition_commands(output_path, config.partitions.layout))

    # 4. initialize RDB and create Amiga partitions for ID76 partitions
    for i, mbr_part in enumerate(config.partitions.layout):
        if mbr_part.type == "id76" and mbr_part.amiga_partitions:
            mbr_num = i + 1  # 1 based

            # initialize RDB
            script.commands.append(generate_rdb_init_command(output_path, mbr_num))

            # register filesystem handlers in the RDB one per FS type
            filesystems_added = set()
            for amiga_part in mbr_part.amiga_partitions:
                fs = amiga_part.filesystem
                if fs in filesystems_added:
                    continue
                fs_info = FILESYSTEM_HANDLERS.get(fs)
                handler_path = fs_handler_paths.get(fs)
                if fs_info and fs_info.get("handler_file") and handler_path:
                    script.commands.append(
                        generate_rdb_filesystem_command(
                            output_path,
                            mbr_num,
                            fs,
                            handler_path,
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
