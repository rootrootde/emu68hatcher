"""tests for config/schema.py - model validators and properties"""

import pytest
from pathlib import Path

from emu68hatcher.config.schema import (
    AmigaPartition,
    BuildConfig,
    Filesystem,
    MBRPartition,
    OutputConfig,
    OutputType,
    PartitionConfig,
    create_default_partition_layout,
)
from emu68hatcher.config.defaults import MBR_OVERHEAD
from emu68hatcher.config.partition_helpers import PFS3_MAX_CREATE


# =============================================================================
# MBRPartition validators
# =============================================================================


def test_id76_without_amiga_partitions_rejected():
    with pytest.raises(ValueError, match="Amiga partition"):
        MBRPartition(type="id76", name="AMIGA", size=1_000_000_000)


def test_id76_with_amiga_partitions_accepted():
    p = MBRPartition(
        type="id76",
        name="AMIGA",
        size=1_000_000_000,
        amiga_partitions=[
            AmigaPartition(
                device="SDH0", volume="Workbench",
                filesystem=Filesystem.PFS3, size=500_000_000,
                bootable=True,
            ),
        ],
    )
    assert p.type == "id76"


def test_fat32_with_amiga_partitions_rejected():
    with pytest.raises(ValueError):
        MBRPartition(
            type="fat32",
            name="EMU68BOOT",
            size=500_000_000,
            amiga_partitions=[
                AmigaPartition(
                    device="SDH0", volume="Workbench",
                    filesystem=Filesystem.PFS3, size=400_000_000,
                    bootable=True,
                ),
            ],
        )


def test_fat32_without_amiga_partitions_accepted():
    p = MBRPartition(type="fat32", name="EMU68BOOT", size=500_000_000)
    assert p.type == "fat32"


# =============================================================================
# PartitionConfig validators
# =============================================================================


def test_partition_sizes_exceed_disk_rejected():
    with pytest.raises(ValueError, match="exceeds disk size"):
        PartitionConfig(
            disk_size=1_000_000_000,
            layout=[
                MBRPartition(type="fat32", name="EMU68BOOT", size=500_000_000),
                MBRPartition(
                    type="id76", name="AMIGA", size=600_000_000,
                    amiga_partitions=[
                        AmigaPartition(
                            device="SDH0", volume="Workbench",
                            filesystem=Filesystem.PFS3, size=500_000_000,
                            bootable=True,
                        ),
                    ],
                ),
            ],
        )


def test_uses_pfs3_true():
    config = PartitionConfig(
        disk_size=8_000_000_000,
        layout=[
            MBRPartition(type="fat32", name="EMU68BOOT", size=500_000_000),
            MBRPartition(
                type="id76", name="AMIGA", size=6_000_000_000,
                amiga_partitions=[
                    AmigaPartition(
                        device="SDH0", volume="Workbench",
                        filesystem=Filesystem.PFS3, size=500_000_000,
                        bootable=True,
                    ),
                ],
            ),
        ],
    )
    assert config.uses_pfs3 is True


def test_uses_pfs3_false():
    config = PartitionConfig(
        disk_size=8_000_000_000,
        layout=[
            MBRPartition(type="fat32", name="EMU68BOOT", size=500_000_000),
            MBRPartition(
                type="id76", name="AMIGA", size=6_000_000_000,
                amiga_partitions=[
                    AmigaPartition(
                        device="SDH0", volume="Workbench",
                        filesystem=Filesystem.FFS, size=500_000_000,
                        bootable=True,
                    ),
                ],
            ),
        ],
    )
    assert config.uses_pfs3 is False


# =============================================================================
# OutputConfig validators
# =============================================================================


def test_output_disk_type_requires_device_path():
    with pytest.raises(ValueError, match="device path"):
        OutputConfig(type=OutputType.DISK, path=Path("/home/user/image.img"))


def test_output_disk_type_accepts_dev_path():
    config = OutputConfig(type=OutputType.DISK, path=Path("/dev/disk4"))
    assert config.type == OutputType.DISK


def test_output_img_type_accepts_any_path():
    config = OutputConfig(type=OutputType.IMG, path=Path("/home/user/amiga.img"))
    assert config.type == OutputType.IMG


# =============================================================================
# create_default_partition_layout
# =============================================================================


def test_default_layout_small_disk():
    layout = create_default_partition_layout(8)
    assert layout.disk_size > 0
    assert len(layout.layout) == 2
    assert layout.layout[0].type == "fat32"
    assert layout.layout[1].type == "id76"

    amiga = layout.layout[1].amiga_partitions
    assert len(amiga) >= 2
    assert amiga[0].volume == "Workbench"
    assert amiga[0].bootable is True


def test_default_layout_large_disk_splits_work():
    # 256 GB should need multiple work partitions due to PFS3 max
    layout = create_default_partition_layout(256)
    amiga = layout.layout[1].amiga_partitions

    # workbench + at least 2 work partitions
    assert len(amiga) >= 3
    for part in amiga[1:]:
        assert part.size <= PFS3_MAX_CREATE


def test_default_layout_partitions_fit():
    for gb in [4, 8, 16, 32, 64, 128, 256]:
        layout = create_default_partition_layout(gb)
        total = sum(p.size for p in layout.layout)
        assert total + MBR_OVERHEAD <= layout.disk_size
