"""Display configuration models."""

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


class DisplayConfig(BaseModel):
    hdmi_mode: str = "1280*720-50"
    custom: CustomScreenMode | None = None
    picasso96_archive: Path | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("picasso96_archive", mode="before")
    @classmethod
    def _convert_picasso96_archive(cls, value):
        return _optional_path(value)

    @model_validator(mode="after")
    def validate_custom_mode(self):
        if self.hdmi_mode == "Custom" and self.custom is None:
            raise ValueError("Custom HDMI mode selected but no custom settings provided")
        return self
