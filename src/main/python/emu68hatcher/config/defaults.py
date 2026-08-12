"""Configuration defaults and compatibility re-exports."""

from emu68hatcher.config.constants import (
    COMMON_DISK_SIZES,
    CYLINDER_SIZE,
    DEFAULT_BOOT_DEVICE,
    DEFAULT_WORK_DEVICE,
    EMU68_BOOT_PARTITION_NAME,
    FFS_MAX_PARTITION_SIZE,
    MAX_AMIGA_PARTITIONS,
    MBR_OVERHEAD,
    MBR_SECTOR_SIZE,
    MIN_AMIGA_PARTITION_SIZE,
    MIN_BOOT_PARTITION_SIZE,
    PFS3_MAX_PARTITION_SIZE,
    RDB_OVERHEAD,
)

__all__ = [
    "COMMON_DISK_SIZES",
    "CYLINDER_SIZE",
    "DEFAULT_BOOT_DEVICE",
    "DEFAULT_WORK_DEVICE",
    "EMU68_BOOT_PARTITION_NAME",
    "FFS_MAX_PARTITION_SIZE",
    "MAX_AMIGA_PARTITIONS",
    "MBR_OVERHEAD",
    "MBR_SECTOR_SIZE",
    "MIN_AMIGA_PARTITION_SIZE",
    "MIN_BOOT_PARTITION_SIZE",
    "PFS3_MAX_PARTITION_SIZE",
    "RDB_OVERHEAD",
    "create_default_config",
]


def create_default_config():
    from emu68hatcher.config.partition_helpers import create_default_partition_layout
    from emu68hatcher.config.schema import BuildConfig, KickstartConfig, KickstartVersion

    return BuildConfig(
        kickstart=KickstartConfig(version=KickstartVersion.V3_1),
        partitions=create_default_partition_layout(8),
    )
