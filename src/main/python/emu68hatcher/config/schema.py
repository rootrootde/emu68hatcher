"""
pydantic models for Emu68 Hatcher build configuration

these models define the JSON schema for build configs that can be:
- created by the GUI configurator
- shared between users
- executed by the builder to create disk images
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class KickstartVersion(str, Enum):
    """supported Amiga Kickstart versions"""

    V3_1 = "3.1"
    V3_2 = "3.2"
    V3_2_2_1 = "3.2.2.1"
    V3_2_3 = "3.2.3"
    V3_9 = "3.9"


class InstallMediaType(str, Enum):
    """type of OS installation media"""

    ADF = "ADF"
    CD = "CD"
    ISO = "ISO"


class Filesystem(str, Enum):
    """supported Amiga filesystems"""

    PFS3 = "PFS3"
    FFS = "FFS"


class OutputType(str, Enum):
    """output format for the created image"""

    IMG = "img"
    VHD = "vhd"
    DISK = "disk"


class ScreenModeType(str, Enum):
    """screen mode type"""

    PAL = "PAL"
    NTSC = "NTSC"
    CUSTOM = "Custom"


# =============================================================================
# sub-configurations
# =============================================================================


class ConfigMetadata(BaseModel):
    """metadata about the configuration file"""

    created: datetime = Field(default_factory=datetime.now)
    modified: Optional[datetime] = None
    description: str = ""
    author: str = ""


class KickstartConfig(BaseModel):
    """kickstart ROM configuration"""

    version: KickstartVersion = KickstartVersion.V3_1
    rom_directory: Optional[Path] = Field(
        default=None,
        description="Directory containing Kickstart ROM files. The correct ROM will be auto-detected.",
    )
    # resolved at build time - not stored in config
    _resolved_rom_path: Optional[Path] = None

    @field_validator("rom_directory", mode="before")
    @classmethod
    def convert_path(cls, v):
        if v is None or v == "":
            return None
        return Path(v) if isinstance(v, str) else v


class WorkbenchVersion(str, Enum):
    """supported Amiga Workbench versions"""

    V3_1 = "3.1"
    V3_2 = "3.2"
    V3_2_2_1 = "3.2.2.1"
    V3_2_3 = "3.2.3"
    V3_9 = "3.9"


class InstallMediaConfig(BaseModel):
    """OS installation media configuration"""

    type: InstallMediaType = InstallMediaType.ADF
    version: WorkbenchVersion = WorkbenchVersion.V3_1
    directory: Optional[Path] = Field(
        default=None,
        description="Directory containing installation media (ADFs, ISOs, etc.). Files are auto-detected.",
    )
    # resolved at build time - not stored in config
    _resolved_disk_paths: Optional[list[Path]] = None

    @field_validator("directory", mode="before")
    @classmethod
    def convert_path(cls, v):
        if v is None or v == "":
            return None
        return Path(v) if isinstance(v, str) else v


class CustomScreenMode(BaseModel):
    """custom screen mode parameters (CVT calculation)"""

    width: int = Field(ge=320, le=1920, default=640)
    height: int = Field(ge=200, le=1200, default=480)
    framerate: int = Field(ge=24, le=75, default=50)
    aspect: str = "4:3"
    margins: int = Field(ge=0, default=0)
    interlace: bool = False
    reduced_blanking: bool = False


class WorkbenchModeType(str, Enum):
    """workbench screen mode type"""

    NATIVE = "Native"
    RTG = "RTG"


class WorkbenchDisplayConfig(BaseModel):
    """workbench display settings"""

    mode_type: WorkbenchModeType = WorkbenchModeType.RTG
    screen_mode: str = "VideoCore:1280x720 32bit BGRA"
    mode_id: str = ""  # amiga ModeID (e.g., "$500A1303")
    width: int = 1280  # screen width from selected mode
    height: int = 720  # screen height from selected mode
    color_depth: Literal[2, 4, 8, 16, 24] = 24
    backdrop: bool = True


class UnicamConfig(BaseModel):
    """unicam scaler settings (for PiStorm with camera input)"""

    enabled: bool = False
    start_on_boot: bool = False
    scaling_type: Literal["Integer", "Smooth"] = "Smooth"
    phase: int = Field(ge=0, le=31, default=0)
    b_parameter: int = Field(ge=0, le=255, default=128)
    c_parameter: int = Field(ge=0, le=255, default=128)
    size_x: int = 0
    size_y: int = 0
    offset_x: int = 0
    offset_y: int = 0


class DisplayConfig(BaseModel):
    """display and screen mode configuration"""

    # HDMI output mode (Pi -> Monitor)
    screen_mode: ScreenModeType = ScreenModeType.PAL  # legacy: PAL/NTSC/Custom
    hdmi_mode: str = "1280*720-50"  # name from screen_modes.csv (e.g., "1280*720-50", "Auto")
    custom: Optional[CustomScreenMode] = None  # custom CVT settings if hdmi_mode is "Custom"

    # workbench display settings
    workbench: WorkbenchDisplayConfig = Field(default_factory=WorkbenchDisplayConfig)

    # optional: Unicam settings
    unicam: Optional[UnicamConfig] = None

    @model_validator(mode="after")
    def validate_custom_mode(self):
        if self.screen_mode == ScreenModeType.CUSTOM and self.custom is None:
            raise ValueError("Custom screen mode selected but no custom settings provided")
        return self


class PackageConfig(BaseModel):
    """individual package selection"""

    name: str
    enabled: bool = True
    # these are populated from CSV during build
    friendly_name: Optional[str] = None
    group: Optional[str] = None
    description: Optional[str] = None


class AmigaPartition(BaseModel):
    """amiga RDB partition within an ID76 MBR partition"""

    device: str = Field(pattern=r"^[A-Z]{2,3}\d+$", description="e.g., DH0, DH1, SDH0, SDH1")
    volume: str = Field(min_length=1, max_length=30)
    filesystem: Filesystem = Filesystem.PFS3
    size: int = Field(gt=0, description="Size in bytes")
    bootable: bool = False
    priority: int = Field(ge=-128, le=127, default=0)
    buffers: int = Field(ge=1, le=600, default=30)
    max_transfer: int = Field(default=0x1FE00)
    mask: int = Field(default=0x7FFFFFFE)
    no_mount: bool = False
    # for imported partitions
    imported: bool = False
    imported_files_path: Optional[Path] = None


class MBRPartition(BaseModel):
    """MBR partition (FAT32 for boot or ID76 for Amiga)"""

    type: Literal["fat32", "id76"]
    name: str
    size: int = Field(gt=0, description="Size in bytes")
    # only for ID76 partitions
    amiga_partitions: Optional[list[AmigaPartition]] = None

    @model_validator(mode="after")
    def validate_amiga_partitions(self):
        if self.type == "id76" and not self.amiga_partitions:
            raise ValueError("ID76 partition must have at least one Amiga partition")
        if self.type == "fat32" and self.amiga_partitions:
            raise ValueError("FAT32 partition cannot have Amiga partitions")
        return self


class PartitionConfig(BaseModel):
    """disk partition layout configuration"""

    disk_size: int = Field(gt=0, description="Total disk size in bytes")
    layout: list[MBRPartition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_partition_sizes(self):
        total = sum(p.size for p in self.layout)
        # allow for MBR overhead (about 1MB)
        overhead = 1048576 + 50688
        if total + overhead > self.disk_size:
            raise ValueError(
                f"Total partition size ({total}) + overhead ({overhead}) "
                f"exceeds disk size ({self.disk_size})"
            )
        return self


class OutputConfig(BaseModel):
    """output configuration for the created image"""

    type: OutputType = OutputType.IMG
    path: Path = Field(description="Output path for image file or physical disk device")

    @field_validator("path", mode="before")
    @classmethod
    def convert_path(cls, v):
        return Path(v) if isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_output(self):
        if self.type == OutputType.DISK:
            # physical disk should be a device path
            path_str = str(self.path)
            if not (
                path_str.startswith("/dev/")
                or path_str.startswith("\\\\.\\")  # linux/macOS
            ):  # windows
                raise ValueError(
                    f"Physical disk output must be a device path, got: {self.path}"
                )
        return self


class NetworkStack(str, Enum):
    """TCP/IP network stack selection"""

    ROADSHOW = "Roadshow"


class WifiConfig(BaseModel):
    """WiFi configuration for TCP/IP networking"""

    ssid: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=63)


# =============================================================================
# main Build Configuration
# =============================================================================


class BuildConfig(BaseModel):
    """
    complete build configuration for creating an Emu68/PiStorm disk image

    this is the main configuration object that gets serialized to/from JSON.
    it contains all settings needed to create a bootable Amiga disk image.
    """

    version: str = Field(default="1.0.0", description="Config schema version")
    metadata: ConfigMetadata = Field(default_factory=ConfigMetadata)

    # core settings
    kickstart: KickstartConfig = Field(default_factory=KickstartConfig)
    install_media: InstallMediaConfig = Field(default_factory=InstallMediaConfig)

    # display settings
    display: DisplayConfig = Field(default_factory=DisplayConfig)

    # package selection
    packages: list[PackageConfig] = Field(default_factory=list)
    icon_set: str = "Default"

    # partition layout
    partitions: Optional[PartitionConfig] = None

    # output settings
    output: Optional[OutputConfig] = None

    # network stack (None = no network stack installed)
    network_stack: Optional[NetworkStack] = NetworkStack.ROADSHOW

    # optional settings
    wifi: Optional[WifiConfig] = None

    # boot configuration
    emu68_boot_cmdline: str = Field(
        default="sd.unit0=rw emmc.unit0=rw",
        description="Emu68 boot command line parameters",
    )

    class Config:
        json_schema_extra = {
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
                    "type": "ADF",
                    "directory": "/path/to/workbench/",
                },
                "display": {
                    "screen_mode": "PAL",
                    "workbench": {
                        "screen_mode": "PAL:HighRes",
                        "color_depth": 8,
                        "backdrop": True,
                    },
                },
                "packages": [
                    {"name": "WHDLoad", "enabled": True},
                    {"name": "DirectoryOpus", "enabled": True},
                ],
                "icon_set": "GlowIcons",
                "partitions": {
                    "disk_size": 7600000000,  # 8GB SD card with 95% usable
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
                                    "size": 506000000,  # ~500MB
                                    "bootable": True,
                                    "priority": 0,
                                },
                                {
                                    "device": "SDH1",
                                    "volume": "Work",
                                    "filesystem": "PFS3",
                                    "size": 6586000000,  # remainder
                                    "bootable": False,
                                },
                            ],
                        },
                    ],
                },
                "output": {"type": "img", "path": "/home/user/amiga.img"},
            }
        }

    def to_json_file(self, path: Path) -> None:
        """save configuration to a JSON file"""
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def from_json_file(cls, path: Path) -> "BuildConfig":
        """load configuration from a JSON file"""
        import json
        # use model_validate instead of model_validate_json for proper Path handling
        return cls.model_validate(json.loads(path.read_text()))


# =============================================================================
# default configurations
# =============================================================================


def create_default_partition_layout(disk_size_gb: int = 8) -> PartitionConfig:
    """
    create a default partition layout for the given disk size

    matches the original Emu68 Imager partition calculation exactly:
    - uses MBR sector alignment (512 bytes) for FAT32 and ID76
    - uses cylinder alignment (516,096 bytes) for Amiga partitions
    - SDH0: Workbench (disk/15, max 1GB)
    - SDH1+: Work partitions (split if > PFS3 max of 101GB)

    note: SD cards use decimal GB (1 GB = 1,000,000,000 bytes), not GiB.
    A "32GB" card has ~29.8 GiB usable. we use 95% of decimal size for safety.
    """
    # SD cards use decimal GB, and often have slightly less than advertised
    # use 95% of decimal GB size to ensure image fits on real cards
    disk_size = int(disk_size_gb * 1_000_000_000 * 0.95)

    # constants from original tool (SetVariables.ps1)
    MBR_SECTOR_SIZE = 512
    MBR_OVERHEAD = 1048576 + 50688  # 1,099,264 bytes
    CYLINDER_SIZE = 16 * 63 * 512  # 516,096 bytes (Heads * Sectors * BlockSize)
    RDB_OVERHEAD = 1032192  # hardcoded in original (16 * 63 * 512 * 2)
    PFS3_MAX = 101 * 1024 * 1024 * 1024  # 101 GB

    def round_to_mbr_sector(size: int) -> int:
        """round down to MBR sector boundary (512 bytes)"""
        return (size // MBR_SECTOR_SIZE) * MBR_SECTOR_SIZE

    def round_to_cylinder(size: int) -> int:
        """round down to cylinder boundary (516,096 bytes)"""
        return (size // CYLINDER_SIZE) * CYLINDER_SIZE

    # EMU68BOOT default: min(disk/15, 1GB), rounded to MBR sector
    emu68boot_default = min(disk_size // 15, 1024 * 1024 * 1024)
    boot_size = round_to_mbr_sector(emu68boot_default)

    # ID76 size: remaining space after MBR overhead and boot, rounded to MBR sector
    remaining_for_id76 = disk_size - MBR_OVERHEAD - boot_size
    id76_size = round_to_mbr_sector(remaining_for_id76)

    # workbench default: min(disk/15, 1GB), rounded to cylinder
    workbench_default = min(disk_size // 15, 1024 * 1024 * 1024)
    workbench_size = round_to_cylinder(workbench_default)

    # remaining space for Work partitions (after RDB overhead and Workbench)
    work_remaining = id76_size - RDB_OVERHEAD - workbench_size

    # number of Work partitions needed (split if exceeds PFS3 max)
    num_work_partitions = max(1, (work_remaining + PFS3_MAX - 1) // PFS3_MAX)

    # calculate Work partition sizes
    if num_work_partitions == 1:
        # single work partition gets all remaining space (rounded to cylinder)
        work_size = round_to_cylinder(work_remaining)
        amiga_partitions = [
            AmigaPartition(
                device="SDH0",
                volume="Workbench",
                filesystem=Filesystem.PFS3,
                size=workbench_size,
                bootable=True,
                priority=0,
            ),
            AmigaPartition(
                device="SDH1",
                volume="Work",
                filesystem=Filesystem.PFS3,
                size=work_size,
                bootable=False,
            ),
        ]
    else:
        # multiple work partitions: divide evenly, last gets remainder
        work_per_partition = round_to_cylinder(work_remaining // num_work_partitions)
        amiga_partitions = [
            AmigaPartition(
                device="SDH0",
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
                # last partition gets remaining (rounded)
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


def create_minimal_config(
    kickstart_version: KickstartVersion = KickstartVersion.V3_1,
    disk_size_gb: int = 8,
) -> BuildConfig:
    """create a minimal build configuration with sensible defaults"""
    return BuildConfig(
        kickstart=KickstartConfig(version=kickstart_version),
        partitions=create_default_partition_layout(disk_size_gb),
    )
