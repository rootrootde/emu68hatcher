"""Display configuration models."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _optional_path(value):
    if value is None or value == "":
        return None
    return Path(value) if isinstance(value, str) else value


class CustomScreenMode(BaseModel):
    width: int = Field(ge=320, le=1920, default=640)
    height: int = Field(ge=200, le=1200, default=480)
    framerate: int = Field(ge=24, le=75, default=50)
    aspect_ratio: int = Field(ge=1, le=6, default=3)
    margins: bool = False
    interlace: bool = False
    reduced_blanking: bool = False

    model_config = ConfigDict(extra="forbid")

    def to_cvt_string(self) -> str:
        return (
            f"{self.width} {self.height} {self.framerate} "
            f"{self.aspect_ratio} {int(self.margins)} "
            f"{int(self.interlace)} {int(self.reduced_blanking)}"
        )


class WorkbenchScreenMode(str, Enum):
    NATIVE = "native"
    VIDEOCORE_800X600 = "videocore_800x600"
    VIDEOCORE_960X540 = "videocore_960x540"
    VIDEOCORE_1024X768 = "videocore_1024x768"
    VIDEOCORE_1280X720 = "videocore_1280x720"
    VIDEOCORE_1280X1024 = "videocore_1280x1024"
    VIDEOCORE_1366X768 = "videocore_1366x768"
    VIDEOCORE_1600X900 = "videocore_1600x900"
    VIDEOCORE_1920X1080 = "videocore_1920x1080"


@dataclass(frozen=True)
class WorkbenchScreenModeInfo:
    mode: WorkbenchScreenMode
    width: int
    height: int
    mode_id: int
    depth: int = 24

    @property
    def label(self) -> str:
        return f"VideoCore {self.width}x{self.height}, 32-bit BGRA"


WORKBENCH_RTG_MODES = (
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_800X600, 800, 600, 0x50061303),
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_960X540, 960, 540, 0x50171303),
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_1024X768, 1024, 768, 0x50071303),
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_1280X720, 1280, 720, 0x500A1303),
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_1280X1024, 1280, 1024, 0x50321303),
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_1366X768, 1366, 768, 0x501B1303),
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_1600X900, 1600, 900, 0x50341303),
    WorkbenchScreenModeInfo(WorkbenchScreenMode.VIDEOCORE_1920X1080, 1920, 1080, 0x50311303),
)

WORKBENCH_RTG_MODE_BY_NAME = {item.mode: item for item in WORKBENCH_RTG_MODES}


def _display_bounds(
    hdmi_mode: str,
    custom: CustomScreenMode | dict | None,
) -> tuple[int, int] | None:
    if hdmi_mode == "Custom" and custom:
        if isinstance(custom, dict):
            return int(custom["width"]), int(custom["height"])
        return custom.width, custom.height
    size = hdmi_mode.split("-", 1)[0]
    try:
        width, height = size.split("*", 1)
        return int(width), int(height)
    except ValueError:
        return None


class DisplayConfig(BaseModel):
    hdmi_mode: str = "1280*720-50"
    custom: CustomScreenMode | None = None
    workbench_mode: WorkbenchScreenMode = WorkbenchScreenMode.VIDEOCORE_1280X720
    picasso96_archive: Path | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("picasso96_archive", mode="before")
    @classmethod
    def _convert_picasso96_archive(cls, value):
        return _optional_path(value)

    @model_validator(mode="before")
    @classmethod
    def _default_workbench_mode(cls, value):
        if not isinstance(value, dict) or "workbench_mode" in value:
            return value
        value = dict(value)
        bounds = _display_bounds(
            value.get("hdmi_mode", "1280*720-50"),
            value.get("custom"),
        )
        if bounds is None:
            value["workbench_mode"] = WorkbenchScreenMode.VIDEOCORE_1280X720
            return value
        compatible = [
            mode
            for mode in WORKBENCH_RTG_MODES
            if mode.width <= bounds[0] and mode.height <= bounds[1]
        ]
        value["workbench_mode"] = compatible[-1].mode if compatible else WorkbenchScreenMode.NATIVE
        return value

    @model_validator(mode="after")
    def validate_custom_mode(self):
        if self.hdmi_mode == "Custom" and self.custom is None:
            raise ValueError("Custom HDMI mode selected but no custom settings provided")
        if self.workbench_mode == WorkbenchScreenMode.NATIVE:
            return self
        mode = WORKBENCH_RTG_MODE_BY_NAME[self.workbench_mode]
        bounds = _display_bounds(self.hdmi_mode, self.custom)
        if bounds and (mode.width > bounds[0] or mode.height > bounds[1]):
            raise ValueError(
                f"Workbench mode {mode.width}x{mode.height} exceeds HDMI output "
                f"{bounds[0]}x{bounds[1]}"
            )
        return self
