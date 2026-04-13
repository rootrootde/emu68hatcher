"""tests for config/partition_helpers.py."""

import pytest

from emu68hatcher.config.defaults import (
    CYLINDER_SIZE,
    FFS_MAX_PARTITION_SIZE,
    MBR_SECTOR_SIZE,
    MIN_AMIGA_PARTITION_SIZE,
    MIN_BOOT_PARTITION_SIZE,
)
from emu68hatcher.config.partition_helpers import (
    PFS3_MAX_CREATE,
    build_partition_config,
    calculate_boot_default,
    calculate_free_space,
    calculate_id76_size,
    calculate_usable_amiga_space,
    disk_size_for_gb,
    next_device_name,
    next_volume_name,
    parse_partition_spec,
    round_to_cylinder,
    round_to_mbr_sector,
    validate_partition_layout,
)
from emu68hatcher.config.schema import AmigaPartition, Filesystem


# ── Alignment ───────────────────────────────────────────────────────────


def test_round_to_cylinder():
    assert round_to_cylinder(0) == 0
    assert round_to_cylinder(CYLINDER_SIZE) == CYLINDER_SIZE
    assert round_to_cylinder(CYLINDER_SIZE + 100) == CYLINDER_SIZE
    assert round_to_cylinder(CYLINDER_SIZE * 3 - 1) == CYLINDER_SIZE * 2


def test_round_to_mbr_sector():
    assert round_to_mbr_sector(0) == 0
    assert round_to_mbr_sector(512) == 512
    assert round_to_mbr_sector(1000) == 512
    assert round_to_mbr_sector(1024) == 1024


# ── Size calculations ───────────────────────────────────────────────────


def test_disk_size_for_gb():
    result = disk_size_for_gb(8)
    assert result == int(8 * 1_000_000_000 * 0.95)


def test_calculate_boot_default():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    assert boot > 0
    assert boot % MBR_SECTOR_SIZE == 0
    assert boot == round_to_mbr_sector(disk // 15)


def test_calculate_boot_default_large_disk():
    # for very large disks, boot scales with disk size (no cap)
    disk = disk_size_for_gb(512)
    boot = calculate_boot_default(disk)
    assert boot == round_to_mbr_sector(disk // 15)
    assert boot > 1024 * 1024 * 1024  # exceeds 1 GB for 512 GB disk


def test_calculate_id76_size():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    id76 = calculate_id76_size(disk, boot)
    assert id76 > 0
    assert id76 % MBR_SECTOR_SIZE == 0


def test_calculate_free_space():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    id76 = calculate_id76_size(disk, boot)
    usable = calculate_usable_amiga_space(id76)
    parts = [
        AmigaPartition(device="SDH0", volume="Workbench", filesystem=Filesystem.PFS3,
                       size=round_to_cylinder(500 * 1024 * 1024), bootable=True),
    ]
    free = calculate_free_space(id76, parts)
    assert free == usable - parts[0].size


# ── Auto-naming ─────────────────────────────────────────────────────────


def test_next_device_name_empty():
    assert next_device_name([]) == "SDH0"


def test_next_device_name_gap():
    assert next_device_name(["SDH0", "SDH2"]) == "SDH1"


def test_next_device_name_sequential():
    assert next_device_name(["SDH0", "SDH1"]) == "SDH2"


def test_next_volume_name_empty():
    assert next_volume_name([]) == "Work"


def test_next_volume_name_work_taken():
    assert next_volume_name(["Work"]) == "Work_1"


def test_next_volume_name_gap():
    assert next_volume_name(["Work", "Work_1", "Work_3"]) == "Work_2"


# ── Validation ──────────────────────────────────────────────────────────


def _make_part(device="SDH0", volume="Workbench", size=None, bootable=True, fs=Filesystem.PFS3):
    if size is None:
        size = round_to_cylinder(500 * 1024 * 1024)
    return AmigaPartition(device=device, volume=volume, filesystem=fs, size=size, bootable=bootable)


def test_validate_valid_layout():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    parts = [
        _make_part("SDH0", "Workbench", bootable=True),
        _make_part("SDH1", "Work", bootable=False),
    ]
    errors = validate_partition_layout(disk, boot, parts)
    assert errors == []


def test_validate_no_partitions():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    errors = validate_partition_layout(disk, boot, [])
    assert any("at least one" in e.lower() for e in errors)


def test_validate_no_bootable():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    parts = [_make_part(bootable=False)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("bootable" in e.lower() for e in errors)


def test_validate_multiple_bootable():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    parts = [_make_part("SDH0", "WB", bootable=True), _make_part("SDH1", "Work", bootable=True)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("only one" in e.lower() for e in errors)


def test_validate_duplicate_devices():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    parts = [_make_part("SDH0", "WB", bootable=True), _make_part("SDH0", "Work", bootable=False)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("device" in e.lower() and "unique" in e.lower() for e in errors)


def test_validate_duplicate_volumes():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    parts = [_make_part("SDH0", "Work", bootable=True), _make_part("SDH1", "Work", bootable=False)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("volume" in e.lower() and "unique" in e.lower() for e in errors)


def test_validate_pfs3_too_large():
    disk = disk_size_for_gb(512)
    boot = calculate_boot_default(disk)
    huge = round_to_cylinder(PFS3_MAX_CREATE + CYLINDER_SIZE)
    parts = [_make_part("SDH0", "WB", size=huge, bootable=True, fs=Filesystem.PFS3)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("pfs3" in e.lower() for e in errors)


def test_validate_ffs_too_large():
    disk = disk_size_for_gb(16)
    boot = calculate_boot_default(disk)
    huge = round_to_cylinder(FFS_MAX_PARTITION_SIZE + CYLINDER_SIZE)
    parts = [_make_part("SDH0", "WB", size=huge, bootable=True, fs=Filesystem.FFS)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("ffs" in e.lower() for e in errors)


def test_validate_exceeds_disk():
    disk = disk_size_for_gb(4)
    boot = calculate_boot_default(disk)
    huge = round_to_cylinder(disk)  # way too big
    parts = [_make_part("SDH0", "WB", size=huge, bootable=True)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("exceed" in e.lower() for e in errors)


def test_validate_boot_too_small():
    disk = disk_size_for_gb(8)
    boot = 64 * 1024 * 1024  # 64 MB, below min
    parts = [_make_part(bootable=True)]
    errors = validate_partition_layout(disk, boot, parts)
    assert any("boot" in e.lower() for e in errors)


# ── build_partition_config ──────────────────────────────────────────────


def test_build_partition_config():
    disk = disk_size_for_gb(8)
    boot = calculate_boot_default(disk)
    parts = [
        _make_part("SDH0", "Workbench", bootable=True),
        _make_part("SDH1", "Work", bootable=False),
    ]
    config = build_partition_config(disk, boot, parts)
    assert config.disk_size == disk
    assert len(config.layout) == 2
    assert config.layout[0].type == "fat32"
    assert config.layout[0].size == boot
    assert config.layout[1].type == "id76"
    assert len(config.layout[1].amiga_partitions) == 2


# ── parse_partition_spec ────────────────────────────────────────────────


def test_parse_partition_spec():
    specs = parse_partition_spec("Workbench:500M,Work:4G")
    assert len(specs) == 2
    assert specs[0][0] == "Workbench"
    assert specs[0][1] == round_to_cylinder(500 * 1024 * 1024)
    assert specs[1][0] == "Work"
    assert specs[1][1] == round_to_cylinder(4 * 1024 * 1024 * 1024)


def test_parse_partition_spec_invalid():
    with pytest.raises(ValueError):
        parse_partition_spec("bad_entry")


def test_parse_partition_spec_no_suffix():
    with pytest.raises(ValueError):
        parse_partition_spec("Work:500")


def test_parse_partition_spec_too_small():
    with pytest.raises(ValueError):
        parse_partition_spec("Tiny:1M")
