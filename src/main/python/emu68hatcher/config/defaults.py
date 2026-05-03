"""default values + constraints"""

from typing import Final

# disk size

COMMON_DISK_SIZES: Final[list[int]] = [4, 8, 16, 32, 64, 128, 256, 512]

MIN_BOOT_PARTITION_SIZE: Final[int] = 128 * 1024 * 1024  # 128 MB

MBR_OVERHEAD: Final[int] = 1048576 + 50688  # ~1.05 MB (MBR + alignment)

# RDB header = Heads(16) * Sectors(63) * BlockSize(512) * Sides(2)
RDB_OVERHEAD: Final[int] = 16 * 63 * 512 * 2  # ~1 MB


# amiga partitions

# FFS > 4GB needs NSD/TD64 patches to mount reliably. PFS3 max (101GB) lives in partition_helpers.py
FFS_MAX_PARTITION_SIZE: Final[int] = 4 * 1024 * 1024 * 1024  # 4 GB

CYLINDER_SIZE: Final[int] = 16 * 63 * 512  # 516,096 bytes
MBR_SECTOR_SIZE: Final[int] = 512

MIN_AMIGA_PARTITION_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_AMIGA_PARTITIONS: Final[int] = 10  # per ID76 container

DEFAULT_BOOT_DEVICE: Final[str] = "SDH0"
DEFAULT_WORK_DEVICE: Final[str] = "SDH1"

# FAT32 boot partition name (also serves as MBR label and staging dir name)
EMU68_BOOT_PARTITION_NAME: Final[str] = "EMU68BOOT"


def create_default_config():
    """default BuildConfig"""
    from emu68hatcher.config.schema import (
        BuildConfig,
        KickstartConfig,
        KickstartVersion,
        create_default_partition_layout,
    )

    return BuildConfig(
        kickstart=KickstartConfig(version=KickstartVersion.V3_1),
        partitions=create_default_partition_layout(8),
    )
