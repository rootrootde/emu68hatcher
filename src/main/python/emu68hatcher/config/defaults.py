"""
default values and constraints for Emu68 Hatcher configuration

centralizes all magic numbers and default settings for easy maintenance.
"""

from typing import Final

# =============================================================================
# disk Size Constraints
# =============================================================================

# minimum/maximum/default disk sizes in bytes
MIN_DISK_SIZE: Final[int] = 1 * 1024 * 1024 * 1024  # 1 GB
MAX_DISK_SIZE: Final[int] = 2 * 1024 * 1024 * 1024 * 1024  # 2 TB
DEFAULT_DISK_SIZE: Final[int] = 8 * 1024 * 1024 * 1024  # 8 GB

# common disk sizes for UI selection (in GB)
COMMON_DISK_SIZES: Final[list[int]] = [4, 8, 16, 32, 64, 128, 256, 512]

# boot partition size (EMU68BOOT FAT32)
DEFAULT_BOOT_PARTITION_SIZE: Final[int] = 512 * 1024 * 1024  # 512 MB
MIN_BOOT_PARTITION_SIZE: Final[int] = 128 * 1024 * 1024  # 128 MB

# MBR overhead (sectors reserved for MBR + alignment)
MBR_OVERHEAD: Final[int] = 1048576 + 50688  # ~1.05 MB

# RDB overhead (Rigid Disk Block header area)
# = Heads(16) * Sectors(63) * BlockSize(512) * Sides(2) = 1032192 bytes
RDB_OVERHEAD: Final[int] = 16 * 63 * 512 * 2  # ~1 MB


# =============================================================================
# amiga Partition Constraints
# =============================================================================

# PFS3 filesystem limits
PFS3_MAX_PARTITION_SIZE: Final[int] = 104 * 1024 * 1024 * 1024  # 104 GB
PFS3_RECOMMENDED_MAX: Final[int] = 2 * 1024 * 1024 * 1024  # 2 GB per partition

# FFS filesystem limits
FFS_MAX_PARTITION_SIZE: Final[int] = 4 * 1024 * 1024 * 1024  # 4 GB

# alignment
CYLINDER_SIZE: Final[int] = 16 * 63 * 512  # 516,096 bytes
MBR_SECTOR_SIZE: Final[int] = 512

# amiga partition limits
MIN_AMIGA_PARTITION_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_AMIGA_PARTITIONS: Final[int] = 10  # per ID76 container
DEFAULT_NEW_PARTITION_SIZE: Final[int] = 512 * 1024 * 1024  # 512 MB

# default partition settings
DEFAULT_BUFFERS: Final[int] = 30
DEFAULT_MAX_TRANSFER: Final[int] = 0x1FE00
DEFAULT_MASK: Final[int] = 0x7FFFFFFE
DEFAULT_PRIORITY: Final[int] = 0

# volume name constraints
MAX_VOLUME_NAME_LENGTH: Final[int] = 30


# =============================================================================
# display Defaults
# =============================================================================

# default screen modes
DEFAULT_SCREEN_MODE: Final[str] = "PAL:HighRes"
DEFAULT_COLOR_DEPTH: Final[int] = 8

# custom screen mode limits
MIN_SCREEN_WIDTH: Final[int] = 320
MAX_SCREEN_WIDTH: Final[int] = 1920
MIN_SCREEN_HEIGHT: Final[int] = 200
MAX_SCREEN_HEIGHT: Final[int] = 1200
MIN_FRAMERATE: Final[int] = 24
MAX_FRAMERATE: Final[int] = 75

# common screen mode presets
SCREEN_MODE_PRESETS: Final[dict[str, dict]] = {
    "PAL:HighRes": {
        "width": 640,
        "height": 256,
        "framerate": 50,
        "interlace": False,
    },
    "PAL:HighRes Laced": {
        "width": 640,
        "height": 512,
        "framerate": 50,
        "interlace": True,
    },
    "PAL:SuperHighRes": {
        "width": 1280,
        "height": 256,
        "framerate": 50,
        "interlace": False,
    },
    "NTSC:HighRes": {
        "width": 640,
        "height": 200,
        "framerate": 60,
        "interlace": False,
    },
    "NTSC:HighRes Laced": {
        "width": 640,
        "height": 400,
        "framerate": 60,
        "interlace": True,
    },
}


# =============================================================================
# emu68 Boot Configuration
# =============================================================================

# default boot command line
DEFAULT_EMU68_CMDLINE: Final[str] = "sd.unit0=rw emmc.unit0=rw"

# boot files required on EMU68BOOT partition
REQUIRED_BOOT_FILES: Final[list[str]] = [
    "Emu68.img",
    "config.txt",
    "cmdline.txt",
]


# =============================================================================
# package/Software Sources
# =============================================================================

# google Sheets CSV URLs for package definitions
# these are from the original PowerShell tool
PACKAGE_CSV_URL: Final[str] = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQTGDpVS9lxZ3-Z8lgdHDJqZHT1gGvVfHlIx4xYAMxwv7xFEHG7F2pVcJ8PKfX-pHjMxPLxoKDcxCdL"
    "/pub?gid=0&single=true&output=csv"
)

# known ROM checksums for validation
KNOWN_ROM_CHECKSUMS: Final[dict[str, list[str]]] = {
    "1.3": [
        "85ad74194e87c08904327de1a9443b7a",  # A500 Rev 34.5
    ],
    "3.1": [
        "e21545723fe8374e91342617604f1b3d",  # A1200 Rev 40.68
        "b7cc148386aa631136b510cd29e42fc3",  # A4000 Rev 40.70
    ],
    # add more as needed
}


# =============================================================================
# external Tool Versions
# =============================================================================

# expected versions of bundled tools
HST_IMAGER_VERSION: Final[str] = "4.1.1"
HST_AMIGA_VERSION: Final[str] = "1.0.30"


# =============================================================================
# default Configurations
# =============================================================================


def calculate_partition_layout(
    disk_size_gb: int,
    boot_size_mb: int = 512,
    num_amiga_partitions: int = 2,
) -> dict:
    """
    calculate a reasonable partition layout for a given disk size

    uses the same logic as the original Emu68 Imager tool with proper
    MBR sector and cylinder alignment."""
    disk_size = disk_size_gb * 1024 * 1024 * 1024

    # cylinder size for Amiga partition alignment
    cylinder_size = 16 * 63 * 512  # 516,096 bytes

    def round_to_mbr_sector(size: int) -> int:
        return (size // 512) * 512

    def round_to_cylinder(size: int) -> int:
        return (size // cylinder_size) * cylinder_size

    # EMU68BOOT: min(disk/15, 1GB)
    boot_size = round_to_mbr_sector(min(disk_size // 15, 1024 * 1024 * 1024))

    # ID76 MBR partition size (total for Amiga)
    id76_size = round_to_mbr_sector(disk_size - boot_size - MBR_OVERHEAD)

    # usable space for Amiga partitions (subtract RDB overhead)
    usable_amiga = id76_size - RDB_OVERHEAD

    # workbench: min(disk/15, 1GB), rounded to cylinder
    workbench_size = round_to_cylinder(min(disk_size // 15, 1024 * 1024 * 1024))

    # work gets the rest, rounded to cylinder
    work_size = round_to_cylinder(usable_amiga - workbench_size)

    return {
        "disk_size": disk_size,
        "boot_size": boot_size,
        "id76_size": id76_size,
        "amiga_total": usable_amiga,
        "partition_sizes": [workbench_size, work_size],
    }


def create_default_config():
    """
    create a default BuildConfig with sensible defaults

    uses create_default_partition_layout from schema.py to ensure
    partition calculations match the original Emu68 Imager."""
    from emu68hatcher.config.schema import (
        BuildConfig,
        create_default_partition_layout,
    )

    return BuildConfig(
        kickstart={"version": "3.1"},
        partitions=create_default_partition_layout(8),
        display={"workbench": {"screen_mode": "PAL:HighRes", "color_depth": 8, "backdrop": True}},
    )
