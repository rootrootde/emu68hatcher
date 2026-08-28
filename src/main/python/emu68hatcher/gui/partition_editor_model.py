"""Mutable partition editor state independent of Qt widgets."""

from pathlib import Path

from emu68hatcher.config.constants import MAX_AMIGA_PARTITIONS, MIN_AMIGA_PARTITION_SIZE
from emu68hatcher.config.partition_helpers import (
    build_partition_config,
    calculate_boot_default,
    calculate_free_space,
    calculate_id76_size,
    calculate_usable_amiga_space,
    create_default_partition_layout,
    next_device_name,
    next_volume_name,
    round_to_cylinder,
    round_to_mbr_sector,
    validate_partition_layout,
)
from emu68hatcher.config.partition_models import AmigaPartition, Filesystem, PartitionConfig


class PartitionEditorModel:
    def __init__(self, disk_size_gb: int = 64):
        self.disk_size = 0
        self.boot_size = 0
        self.partitions: list[AmigaPartition] = []
        self.reset(disk_size_gb=disk_size_gb)

    def load(self, config: PartitionConfig) -> None:
        self.disk_size = config.disk_size
        self.boot_size = 0
        self.partitions = []
        for mbr in config.layout:
            if mbr.type == "fat32":
                self.boot_size = mbr.size
            elif mbr.type == "id76" and mbr.amiga_partitions:
                self.partitions = [part.model_copy(deep=True) for part in mbr.amiga_partitions]

    def reset(
        self,
        *,
        disk_size_gb: int | None = None,
        disk_size_bytes: int | None = None,
        preserve_extra_directories: bool = False,
    ) -> None:
        extras = (
            {part.device: part.extra_content_directory for part in self.partitions}
            if preserve_extra_directories
            else {}
        )
        layout = create_default_partition_layout(
            disk_size_gb=disk_size_gb or 8,
            disk_size_bytes=disk_size_bytes,
        )
        self.load(layout)
        for part in self.partitions:
            if extras.get(part.device):
                part.extra_content_directory = extras[part.device]

    def change_disk_size(self, disk_size: int) -> bool:
        self.disk_size = disk_size
        self.boot_size = calculate_boot_default(disk_size)
        if self.free_space < 0:
            self.reset(disk_size_bytes=disk_size)
            return True
        return False

    def set_boot_size_mb(self, size_mb: int) -> None:
        self.boot_size = round_to_mbr_sector(size_mb * 1024 * 1024)

    @property
    def id76_size(self) -> int:
        return calculate_id76_size(self.disk_size, self.boot_size)

    @property
    def usable_space(self) -> int:
        return calculate_usable_amiga_space(self.id76_size)

    @property
    def allocated_space(self) -> int:
        return sum(part.size for part in self.partitions)

    @property
    def free_space(self) -> int:
        return calculate_free_space(self.id76_size, self.partitions)

    @property
    def can_add(self) -> bool:
        return (
            len(self.partitions) < MAX_AMIGA_PARTITIONS
            and self.free_space >= MIN_AMIGA_PARTITION_SIZE
        )

    def add_partition(self) -> bool:
        if not self.can_add:
            return False
        size = round_to_cylinder(self.free_space)
        if size < MIN_AMIGA_PARTITION_SIZE:
            return False
        self.partitions.append(
            AmigaPartition(
                device=next_device_name([part.device for part in self.partitions]),
                volume=next_volume_name([part.volume for part in self.partitions]),
                filesystem=Filesystem.PFS3,
                size=size,
            )
        )
        return True

    def remove_partition(self, row: int) -> bool:
        if not 0 <= row < len(self.partitions) or len(self.partitions) <= 1:
            return False
        self.partitions.pop(row)
        return True

    def set_partition_size_mb(self, row: int, size_mb: int) -> None:
        part = self.partitions[row]
        new_size = max(
            round_to_cylinder(size_mb * 1024 * 1024),
            round_to_cylinder(MIN_AMIGA_PARTITION_SIZE),
        )
        maximum = round_to_cylinder(self.free_space + part.size)
        part.size = min(new_size, maximum)

    def set_device(self, row: int, value: str) -> None:
        device = value.strip().upper()
        if device:
            self.partitions[row].device = device

    def set_volume(self, row: int, value: str) -> None:
        volume = value.strip()
        if volume:
            self.partitions[row].volume = volume

    def set_filesystem(self, row: int, value: str) -> None:
        self.partitions[row].filesystem = Filesystem(value)

    def resize_pair(self, left: int, left_size: int, right: int, right_size: int) -> None:
        if 0 <= left < len(self.partitions):
            self.partitions[left].size = left_size
        if 0 <= right < len(self.partitions):
            self.partitions[right].size = right_size

    def set_bootable(self, row: int, bootable: bool) -> None:
        if bootable:
            for index, part in enumerate(self.partitions):
                part.bootable = index == row
        else:
            self.partitions[row].bootable = False

    def set_extra_directory(self, row: int, path: Path | None) -> None:
        self.partitions[row].extra_content_directory = path

    @property
    def errors(self) -> list[str]:
        return validate_partition_layout(self.disk_size, self.boot_size, self.partitions)

    def to_config(self) -> PartitionConfig:
        return build_partition_config(self.disk_size, self.boot_size, self.partitions)
