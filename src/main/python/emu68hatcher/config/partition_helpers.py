"""
partition layout helpers for validation, alignment, and auto-naming

shared by GUI and CLI to avoid duplicating partition logic.
"""

import re

from emu68hatcher.config.defaults import (
    CYLINDER_SIZE,
    FFS_MAX_PARTITION_SIZE,
    MAX_AMIGA_PARTITIONS,
    MBR_OVERHEAD,
    MBR_SECTOR_SIZE,
    MIN_AMIGA_PARTITION_SIZE,
    MIN_BOOT_PARTITION_SIZE,
    PFS3_MAX_PARTITION_SIZE,
    RDB_OVERHEAD,
)
from emu68hatcher.config.schema import (
    AmigaPartition,
    Filesystem,
    MBRPartition,
    PartitionConfig,
)

# OG tool uses 101 GB as PFS3 max in partition creation
PFS3_MAX_CREATE: int = 101 * 1024 * 1024 * 1024


def round_to_cylinder(size: int) -> int:
    """round down to cylinder boundary (516,096 bytes)"""
    return (size // CYLINDER_SIZE) * CYLINDER_SIZE


def round_to_mbr_sector(size: int) -> int:
    """round down to MBR sector boundary (512 bytes)"""
    return (size // MBR_SECTOR_SIZE) * MBR_SECTOR_SIZE


def disk_size_for_gb(gb: int) -> int:
    """convert GB to usable bytes (95% of decimal GB for SD card safety)"""
    return int(gb * 1_000_000_000 * 0.95)


def calculate_boot_default(disk_size: int) -> int:
    """calculate default boot partition size: min(disk/15, 1GB), MBR-aligned"""
    return round_to_mbr_sector(min(disk_size // 15, 1024 * 1024 * 1024))


def calculate_id76_size(disk_size: int, boot_size: int) -> int:
    """calculate ID76 (Amiga RDB container) size from remaining space"""
    return round_to_mbr_sector(disk_size - MBR_OVERHEAD - boot_size)


def calculate_usable_amiga_space(id76_size: int) -> int:
    """usable space for Amiga partitions within ID76 container"""
    return id76_size - RDB_OVERHEAD


def calculate_free_space(id76_size: int, amiga_partitions: list[AmigaPartition]) -> int:
    """free space remaining for new Amiga partitions"""
    usable = calculate_usable_amiga_space(id76_size)
    allocated = sum(p.size for p in amiga_partitions)
    return usable - allocated


def next_device_name(existing: list[str], prefix: str = "SDH") -> str:
    """find the lowest unused device name (e.g., SDH0, SDH1, ...)"""
    used = set()
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for name in existing:
        m = pattern.match(name)
        if m:
            used.add(int(m.group(1)))
    i = 0
    while i in used:
        i += 1
    return f"{prefix}{i}"


def next_volume_name(existing: list[str]) -> str:
    """find the next unused volume name: Work, Work_1, Work_2, ..."""
    used = {n.lower() for n in existing}
    if "work" not in used:
        return "Work"
    i = 1
    while f"work_{i}" in used:
        i += 1
    return f"Work_{i}"


def validate_partition_layout(
    disk_size: int,
    boot_size: int,
    amiga_partitions: list[AmigaPartition],
) -> list[str]:
    """validate a partition layout. returns list of error strings (empty = valid)"""
    errors = []

    # boot partition checks
    if boot_size < MIN_BOOT_PARTITION_SIZE:
        errors.append(f"Boot partition must be at least {MIN_BOOT_PARTITION_SIZE // (1024*1024)} MB")

    if boot_size % MBR_SECTOR_SIZE != 0:
        errors.append("Boot partition size must be MBR sector aligned (512 bytes)")

    # must have at least one Amiga partition
    if not amiga_partitions:
        errors.append("At least one Amiga partition is required")
        return errors

    # max partitions
    if len(amiga_partitions) > MAX_AMIGA_PARTITIONS:
        errors.append(f"Maximum {MAX_AMIGA_PARTITIONS} Amiga partitions allowed")

    # exactly one bootable
    bootable_count = sum(1 for p in amiga_partitions if p.bootable)
    if bootable_count == 0:
        errors.append("One Amiga partition must be bootable")
    elif bootable_count > 1:
        errors.append("Only one Amiga partition can be bootable")

    # unique device names
    devices = [p.device for p in amiga_partitions]
    if len(devices) != len(set(devices)):
        errors.append("Device names must be unique")

    # unique volume names
    volumes = [p.volume.lower() for p in amiga_partitions]
    if len(volumes) != len(set(volumes)):
        errors.append("Volume names must be unique")

    # per-partition checks
    for p in amiga_partitions:
        if p.size < MIN_AMIGA_PARTITION_SIZE:
            errors.append(f"{p.device}: size must be at least {MIN_AMIGA_PARTITION_SIZE // (1024*1024)} MB")

        if p.size % CYLINDER_SIZE != 0:
            errors.append(f"{p.device}: size must be cylinder aligned ({CYLINDER_SIZE} bytes)")

        if p.filesystem == Filesystem.PFS3 and p.size > PFS3_MAX_CREATE:
            errors.append(f"{p.device}: PFS3 partition cannot exceed {PFS3_MAX_CREATE // (1024**3)} GB")

        if p.filesystem == Filesystem.FFS and p.size > FFS_MAX_PARTITION_SIZE:
            errors.append(f"{p.device}: FFS partition cannot exceed {FFS_MAX_PARTITION_SIZE // (1024**3)} GB")

    # total size check
    id76_size = calculate_id76_size(disk_size, boot_size)
    usable = calculate_usable_amiga_space(id76_size)
    total_amiga = sum(p.size for p in amiga_partitions)
    if total_amiga > usable:
        over_mb = (total_amiga - usable) / (1024 * 1024)
        errors.append(f"Amiga partitions exceed available space by {over_mb:.0f} MB")

    return errors


def build_partition_config(
    disk_size_bytes: int,
    boot_size: int,
    amiga_partitions: list[AmigaPartition],
) -> PartitionConfig:
    """assemble a PartitionConfig from editor state"""
    id76_size = calculate_id76_size(disk_size_bytes, boot_size)

    return PartitionConfig(
        disk_size=disk_size_bytes,
        layout=[
            MBRPartition(type="fat32", name="EMU68BOOT", size=boot_size),
            MBRPartition(
                type="id76",
                name="AMIGA",
                size=id76_size,
                amiga_partitions=list(amiga_partitions),
            ),
        ],
    )


def parse_partition_spec(spec: str) -> list[tuple[str, int]]:
    """parse CLI partition spec like 'Workbench:500M,Work:4G,Games:8G'

    returns list of (volume_name, size_bytes) tuples.
    """
    parts = []
    for entry in spec.split(","):
        entry = entry.strip()
        if ":" not in entry:
            raise ValueError(f"Invalid partition spec '{entry}', expected 'name:size'")
        name, size_str = entry.split(":", 1)
        name = name.strip()
        size_str = size_str.strip().upper()

        if size_str.endswith("G"):
            size_bytes = int(float(size_str[:-1]) * 1024 * 1024 * 1024)
        elif size_str.endswith("M"):
            size_bytes = int(float(size_str[:-1]) * 1024 * 1024)
        else:
            raise ValueError(f"Invalid size '{size_str}', use M or G suffix (e.g., 500M, 4G)")

        size_bytes = round_to_cylinder(size_bytes)
        if size_bytes < MIN_AMIGA_PARTITION_SIZE:
            raise ValueError(f"Partition '{name}' too small (minimum {MIN_AMIGA_PARTITION_SIZE // (1024*1024)} MB)")

        parts.append((name, size_bytes))

    return parts
