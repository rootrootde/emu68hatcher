"""build config - pydantic models"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KickstartVersion(str, Enum):
    """kickstart versions the schema knows; 3.9 listed for forward-compat, not in SUPPORTED_KICKSTARTS"""

    V3_1 = "3.1"
    V3_2 = "3.2"
    V3_2_2_1 = "3.2.2.1"
    V3_2_3 = "3.2.3"
    V3_9 = "3.9"


class Filesystem(str, Enum):
    """supported amiga filesystems"""

    PFS3 = "PFS3"
    FFS = "FFS"


class OutputType(str, Enum):
    """output sink: file or device"""

    IMG = "img"
    DEVICE = "device"


_DEVICE_PATH_PREFIXES = ("/dev/disk", "/dev/sd", "/dev/mmcblk", "\\\\.\\PhysicalDrive")


def _is_device_path(p: str | Path) -> bool:
    return str(p).startswith(_DEVICE_PATH_PREFIXES)


class Emu68Version(str, Enum):
    """upstream Emu68 release to bundle on boot"""

    V1_0_7 = "1.0.7"
    V1_1_0_ALPHA_1 = "1.1.0-alpha.1"


######################
# sub-configurations #
######################


class ConfigMetadata(BaseModel):
    """config-file metadata"""

    created: datetime = Field(default_factory=datetime.now)
    modified: datetime | None = None
    description: str = ""
    author: str = ""


# versions the pipeline builds; adding here enables GUI + validator. needs adf_rules.yaml entry first
SUPPORTED_KICKSTARTS: tuple[KickstartVersion, ...] = (
    KickstartVersion.V3_1,
    KickstartVersion.V3_2,
    KickstartVersion.V3_2_2_1,
    KickstartVersion.V3_2_3,
)


def _check_supported_version(label: str, v: KickstartVersion) -> KickstartVersion:
    """raise unless v is in SUPPORTED_KICKSTARTS"""
    if v not in SUPPORTED_KICKSTARTS:
        supported = ", ".join(k.value for k in SUPPORTED_KICKSTARTS)
        raise ValueError(
            f"{label} {v.value} is not yet supported by the build pipeline. Supported: {supported}."
        )
    return v


def _coerce_optional_path(v):
    """'' / None -> None; str -> Path"""
    if v is None or v == "":
        return None
    return Path(v) if isinstance(v, str) else v


class KickstartConfig(BaseModel):
    """kickstart ROM config"""

    version: KickstartVersion = KickstartVersion.V3_1
    rom_directory: Path | None = Field(
        default=None,
        description="Directory containing Kickstart ROM files. The correct ROM will be auto-detected.",
    )

    @field_validator("version")
    @classmethod
    def _check_supported(cls, v: KickstartVersion) -> KickstartVersion:
        return _check_supported_version("Kickstart", v)

    @field_validator("rom_directory", mode="before")
    @classmethod
    def convert_path(cls, v):
        return _coerce_optional_path(v)


class InstallMediaConfig(BaseModel):
    """OS install media config"""

    version: KickstartVersion = KickstartVersion.V3_1
    directory: Path | None = Field(
        default=None,
        description="Directory containing installation media (ADFs, ISOs, etc.). Files are auto-detected.",
    )

    @field_validator("version")
    @classmethod
    def _check_supported(cls, v: KickstartVersion) -> KickstartVersion:
        return _check_supported_version("Workbench", v)

    @field_validator("directory", mode="before")
    @classmethod
    def convert_path(cls, v):
        return _coerce_optional_path(v)


class CustomScreenMode(BaseModel):
    """custom HDMI mode -> config.txt CVT line"""

    width: int = Field(ge=320, le=1920, default=640)
    height: int = Field(ge=200, le=1200, default=480)
    framerate: int = Field(ge=24, le=75, default=50)


class DisplayConfig(BaseModel):
    """display + screen mode"""

    # row in data/reference/screen_modes.yaml, or "Custom"
    hdmi_mode: str = "1280*720-50"
    custom: CustomScreenMode | None = None

    @model_validator(mode="after")
    def validate_custom_mode(self):
        # catches hand-edited JSON that picks "Custom" without supplying fields
        if self.hdmi_mode == "Custom" and self.custom is None:
            raise ValueError("Custom HDMI mode selected but no custom settings provided")
        return self


class PackageConfig(BaseModel):
    """one package toggle"""

    name: str
    enabled: bool = True


class AmigaPartition(BaseModel):
    """amiga RDB partition inside an ID76 MBR partition"""

    device: str = Field(pattern=r"^[A-Z]{2,3}\d+$", description="e.g., DH0, DH1, SDH0, SDH1")
    # AmigaDOS volume names: 1..31 chars
    volume: str = Field(min_length=1, max_length=31)
    filesystem: Filesystem = Filesystem.PFS3
    size: int = Field(gt=0, description="Size in bytes")
    bootable: bool = False
    priority: int = Field(ge=-128, le=127, default=0)
    buffers: int = Field(ge=1, le=600, default=30)
    max_transfer: int = Field(default=0x1FE00)
    mask: int = Field(default=0x7FFFFFFE)
    no_mount: bool = False


class MBRPartition(BaseModel):
    """MBR partition - FAT32 (boot) or ID76 (amiga)"""

    type: Literal["fat32", "id76"]
    name: str
    size: int = Field(gt=0, description="Size in bytes")
    # ID76 only
    amiga_partitions: list[AmigaPartition] | None = None

    @model_validator(mode="after")
    def validate_amiga_partitions(self):
        if self.type == "id76" and not self.amiga_partitions:
            raise ValueError("ID76 partition must have at least one Amiga partition")
        if self.type == "fat32" and self.amiga_partitions:
            raise ValueError("FAT32 partition cannot have Amiga partitions")
        return self


class PartitionConfig(BaseModel):
    """disk partition layout"""

    disk_size: int = Field(gt=0, description="Total disk size in bytes")
    layout: list[MBRPartition] = Field(min_length=1)

    def iter_amiga_partitions(self):
        """yield AmigaPartitions in declaration order"""
        for mbr_part in self.layout:
            if mbr_part.amiga_partitions:
                yield from mbr_part.amiga_partitions

    @property
    def bootable_device(self) -> str | None:
        """first bootable amiga partition's device, or None"""
        for amiga_part in self.iter_amiga_partitions():
            if amiga_part.bootable:
                return amiga_part.device
        return None

    @model_validator(mode="after")
    def validate_partition_sizes(self):
        from emu68hatcher.config.defaults import MBR_OVERHEAD, RDB_OVERHEAD

        total = sum(p.size for p in self.layout)
        if total + MBR_OVERHEAD > self.disk_size:
            raise ValueError(
                f"Total partition size ({total}) + overhead ({MBR_OVERHEAD}) "
                f"exceeds disk size ({self.disk_size})"
            )

        # cross-check amiga side here too - hand-edited JSON shouldnt bypass GUI pre-flight
        all_devices: list[str] = []
        all_volumes: list[str] = []
        bootable_count = 0
        for mbr in self.layout:
            if mbr.type != "id76" or not mbr.amiga_partitions:
                continue
            usable = mbr.size - RDB_OVERHEAD
            inner_total = sum(p.size for p in mbr.amiga_partitions)
            if inner_total > usable:
                over = inner_total - usable
                raise ValueError(
                    f"Amiga partitions in {mbr.name!r} exceed RDB usable space by {over} bytes"
                )
            for p in mbr.amiga_partitions:
                all_devices.append(p.device.upper())
                all_volumes.append(p.volume.lower())
                if p.bootable:
                    bootable_count += 1

        if len(all_devices) != len(set(all_devices)):
            raise ValueError("Amiga device names must be unique (case-insensitive)")
        if len(all_volumes) != len(set(all_volumes)):
            raise ValueError("Amiga volume names must be unique (case-insensitive)")
        if all_devices and bootable_count == 0:
            raise ValueError("Exactly one Amiga partition must be bootable")
        if bootable_count > 1:
            raise ValueError("Only one Amiga partition can be bootable")

        return self

    @property
    def uses_pfs3(self) -> bool:
        """any amiga partition on PFS3?"""
        return any(
            amiga_part.filesystem == Filesystem.PFS3
            for mbr_part in self.layout
            if mbr_part.amiga_partitions
            for amiga_part in mbr_part.amiga_partitions
        )

    @property
    def uses_ffs(self) -> bool:
        """any amiga partition on FFS?"""
        return any(
            amiga_part.filesystem == Filesystem.FFS
            for mbr_part in self.layout
            if mbr_part.amiga_partitions
            for amiga_part in mbr_part.amiga_partitions
        )


class OutputConfig(BaseModel):
    """output config for the built image"""

    type: OutputType = OutputType.IMG
    path: Path = Field(description="Output path: .img file or /dev/diskN device")
    sparse: bool = Field(
        default=True,
        description="Allocate the .img as a sparse file (IMG mode only); huge disk-space win",
    )
    flash_target: str | None = Field(
        default=None,
        description="If set (IMG mode only), flash the built .img to this physical disk",
    )

    @field_validator("path", mode="before")
    @classmethod
    def convert_path(cls, v):
        return Path(v) if isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_output(self):
        if self.type == OutputType.DEVICE:
            if not _is_device_path(self.path):
                raise ValueError(
                    f"DEVICE output requires a device path (e.g. /dev/disk4), got: {self.path}"
                )
            if self.flash_target:
                raise ValueError("flash_target is incompatible with DEVICE output")
        elif self.type == OutputType.IMG and _is_device_path(self.path):
            raise ValueError(
                f"IMG output rejects a device path (would overwrite the disk): {self.path}"
            )
        if self.flash_target and not _is_device_path(self.flash_target):
            raise ValueError(
                f"flash_target must be a physical disk device path, got: {self.flash_target}"
            )
        if self.flash_target and str(self.flash_target) == str(self.path):
            raise ValueError("flash_target cannot equal output path")
        return self


class NetworkStack(str, Enum):
    """TCP/IP stack picker"""

    ROADSHOW = "Roadshow"


class WifiConfig(BaseModel):
    """wifi creds - never written to disk"""

    ssid: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=63)


############################
# main Build Configuration #
############################


class BuildConfig(BaseModel):
    """full build config - JSON-serializable; drives the pipeline"""

    version: str = Field(default="1.0.0", description="Config schema version")
    metadata: ConfigMetadata = Field(default_factory=ConfigMetadata)

    # core settings
    kickstart: KickstartConfig = Field(default_factory=KickstartConfig)
    install_media: InstallMediaConfig = Field(default_factory=InstallMediaConfig)

    # directories scanned for both ROMs and ADFs/ISOs - the single source of truth
    asset_directories: list[Path] = Field(default_factory=list)

    # display settings
    display: DisplayConfig = Field(default_factory=DisplayConfig)

    # package selection
    packages: list[PackageConfig] = Field(default_factory=list)
    icon_set: str = "Default"

    # partition layout
    partitions: PartitionConfig | None = None

    # output settings
    output: OutputConfig | None = None

    # network stack (None = no network stack installed)
    network_stack: NetworkStack | None = NetworkStack.ROADSHOW

    # wifi creds - never serialized, never in repr
    wifi: WifiConfig | None = Field(default=None, exclude=True, repr=False)

    # boot
    emu68_version: Emu68Version = Field(
        default=Emu68Version.V1_0_7,
        description="upstream Emu68 release to bundle on the boot partition",
    )

    @field_validator("asset_directories", mode="before")
    @classmethod
    def _convert_asset_directories(cls, v):
        if v is None:
            return []
        return [Path(p) if isinstance(p, str) else p for p in v]

    @model_validator(mode="after")
    def _migrate_legacy_asset_paths(self):
        # fold the old single rom_directory + install_media.directory fields into the new list
        # so configs from 0.2.x keep loading; dedupe by string identity to preserve order
        if self.asset_directories:
            return self
        merged: list[Path] = []
        seen: set[str] = set()
        for legacy in (self.kickstart.rom_directory, self.install_media.directory):
            if legacy is None:
                continue
            key = str(legacy)
            if key in seen:
                continue
            seen.add(key)
            merged.append(legacy)
        if merged:
            self.asset_directories = merged
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "version": "1.0.0",
                "metadata": {
                    "description": "My Amiga 3.1 setup",
                    "author": "User",
                },
                "kickstart": {
                    "version": "3.1",
                    "rom_directory": "/path/to/roms/",
                },
                "install_media": {
                    "version": "3.1",
                    "directory": "/path/to/workbench/",
                },
                "display": {
                    "hdmi_mode": "1280*720-50",
                },
                "packages": [
                    {"name": "WHDLoad", "enabled": True},
                    {"name": "DirectoryOpus", "enabled": True},
                ],
                "icon_set": "GlowIcons",
                "partitions": {
                    "disk_size": 7600000000,
                    "layout": [
                        {"type": "fat32", "name": "EMU68BOOT", "size": 506000000},
                        {
                            "type": "id76",
                            "name": "AMIGA",
                            "size": 7093000000,
                            "amiga_partitions": [
                                {
                                    "device": "SDH0",
                                    "volume": "Workbench",
                                    "filesystem": "PFS3",
                                    "size": 506000000,
                                    "bootable": True,
                                    "priority": 0,
                                },
                                {
                                    "device": "SDH1",
                                    "volume": "Work",
                                    "filesystem": "PFS3",
                                    "size": 6586000000,
                                    "bootable": False,
                                },
                            ],
                        },
                    ],
                },
                "output": {"type": "img", "path": "/home/user/amiga.img"},
            }
        }
    )

    def to_json_file(self, path: Path) -> None:
        """write config to JSON"""
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def from_json_file(cls, path: Path) -> "BuildConfig":
        """read config from JSON"""
        import json

        # model_validate not model_validate_json - the former handles Path coercion
        return cls.model_validate(json.loads(path.read_text()))


##########################
# default configurations #
##########################


def create_default_partition_layout(
    disk_size_gb: int = 8, disk_size_bytes: int | None = None
) -> PartitionConfig:
    """default: SDH0=Workbench (disk/15, max 1GB), SDH1+=Work (split at PFS3's 101GB cap)"""
    from emu68hatcher.config.defaults import (
        DEFAULT_BOOT_DEVICE,
        DEFAULT_WORK_DEVICE,
        MBR_OVERHEAD,
        RDB_OVERHEAD,
    )
    from emu68hatcher.config.partition_helpers import (
        PFS3_MAX_CREATE,
        calculate_boot_default,
        disk_size_for_gb,
        round_to_cylinder,
        round_to_mbr_sector,
    )

    disk_size = disk_size_bytes if disk_size_bytes is not None else disk_size_for_gb(disk_size_gb)
    PFS3_MAX = PFS3_MAX_CREATE

    boot_size = calculate_boot_default(disk_size)

    remaining_for_id76 = disk_size - MBR_OVERHEAD - boot_size
    id76_size = round_to_mbr_sector(remaining_for_id76)

    workbench_default = min(disk_size // 15, 1024 * 1024 * 1024)
    workbench_size = round_to_cylinder(workbench_default)

    work_remaining = id76_size - RDB_OVERHEAD - workbench_size

    # split into multiple Work partitions if total exceeds PFS3_MAX (101GB)
    num_work_partitions = max(1, (work_remaining + PFS3_MAX - 1) // PFS3_MAX)

    if num_work_partitions == 1:
        work_size = round_to_cylinder(work_remaining)
        amiga_partitions = [
            AmigaPartition(
                device=DEFAULT_BOOT_DEVICE,
                volume="Workbench",
                filesystem=Filesystem.PFS3,
                size=workbench_size,
                bootable=True,
                priority=0,
            ),
            AmigaPartition(
                device=DEFAULT_WORK_DEVICE,
                volume="Work",
                filesystem=Filesystem.PFS3,
                size=work_size,
                bootable=False,
            ),
        ]
    else:
        # divide evenly, last partition gets remainder
        work_per_partition = round_to_cylinder(work_remaining // num_work_partitions)
        amiga_partitions = [
            AmigaPartition(
                device=DEFAULT_BOOT_DEVICE,
                volume="Workbench",
                filesystem=Filesystem.PFS3,
                size=workbench_size,
                bootable=True,
                priority=0,
            ),
        ]

        allocated = 0
        for i in range(num_work_partitions):
            if i == num_work_partitions - 1:
                size = round_to_cylinder(work_remaining - allocated)
            else:
                size = work_per_partition
                allocated += size

            volume = "Work" if i == 0 else f"Work_{i}"
            amiga_partitions.append(
                AmigaPartition(
                    device=f"SDH{i + 1}",
                    volume=volume,
                    filesystem=Filesystem.PFS3,
                    size=size,
                    bootable=False,
                ),
            )

    return PartitionConfig(
        disk_size=disk_size,
        layout=[
            MBRPartition(type="fat32", name="EMU68BOOT", size=boot_size),
            MBRPartition(
                type="id76",
                name="AMIGA",
                size=id76_size,
                amiga_partitions=amiga_partitions,
            ),
        ],
    )
