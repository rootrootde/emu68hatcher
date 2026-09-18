"""Bundled Workbench theme definitions."""

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from emu68hatcher.config.display_models import WorkbenchTheme

# keep unfinished themes disabled, including saved config selections.
WORKBENCH_THEMES_ENABLED = False

THEME_COMPONENTS = {
    "palette": "Palette",
    "fonts": "Fonts",
    "mui": "MUI",
    "wallpaper": "Wallpaper",
}


class ThemeFile(BaseModel):
    source: str
    targets: list[str] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check_paths(self):
        for path in (self.source, *self.targets):
            if (
                "\\" in path
                or ":" in path
                or "\x00" in path
                or any(part in ("", ".", "..") for part in path.split("/"))
            ):
                raise ValueError(f"Theme paths must be relative file paths: {path!r}")
        return self


class ThemeDefinition(BaseModel):
    display_name: str = Field(min_length=1)
    required_packages: list[str] = Field(default_factory=list)
    components: dict[Literal["palette", "fonts", "mui", "wallpaper"], list[ThemeFile]]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check_targets(self):
        seen = set()
        for files in self.components.values():
            for file in files:
                for target in file.targets:
                    if target.lower() in seen:
                        raise ValueError(f"Theme writes the same file twice: {target}")
                    seen.add(target.lower())
        return self


@cache
def load_workbench_themes() -> dict[WorkbenchTheme, ThemeDefinition]:
    path = Path(__file__).parent / "reference" / "themes.yaml"
    themes = TypeAdapter(dict[WorkbenchTheme, ThemeDefinition]).validate_python(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    if set(themes) != set(WorkbenchTheme) - {WorkbenchTheme.DEFAULT}:
        raise ValueError("themes.yaml must define each non-default Workbench theme")
    return themes


def get_workbench_theme(theme: WorkbenchTheme) -> ThemeDefinition | None:
    if not WORKBENCH_THEMES_ENABLED or theme == WorkbenchTheme.DEFAULT:
        return None
    return load_workbench_themes()[theme]
