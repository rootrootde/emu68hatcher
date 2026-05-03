"""JSON config file load/save"""

import json
from datetime import datetime
from pathlib import Path

from emu68hatcher.config.schema import BuildConfig


class ConfigurationError(Exception):
    """raised when configu loading or validation fails"""

    pass


def load_config(path: str | Path) -> BuildConfig:
    """load a build configuration from a JSON file"""
    path = Path(path)

    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    if not path.is_file():
        raise ConfigurationError(f"Path is not a file: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigurationError(f"Failed to read configuration file: {e}") from e

    try:
        # model_validate_json skips field validators, so loads() + model_validate
        return BuildConfig.model_validate(json.loads(content))
    except Exception as e:
        raise ConfigurationError(f"Invalid configuration: {e}") from e


def save_config(
    config: BuildConfig,
    path: str | Path,
    update_modified: bool = True,
) -> None:
    """save a build configuration to a JSON file"""
    path = Path(path)

    if update_modified:
        config.metadata.modified = datetime.now()

    try:
        # ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # write with pretty formatting
        content = config.model_dump_json(indent=2)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise ConfigurationError(f"Failed to save configuration: {e}") from e
