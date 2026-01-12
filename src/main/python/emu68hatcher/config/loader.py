"""
configuration file loading and saving utilities

handles JSON serialization with proper path handling and validation.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from emu68hatcher.config.schema import BuildConfig


class ConfigurationError(Exception):
    """raised when configuration loading or validation fails"""

    pass


def load_config(path: Union[str, Path]) -> BuildConfig:
    """
    load a build configuration from a JSON file"""
    path = Path(path)

    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    if not path.is_file():
        raise ConfigurationError(f"Path is not a file: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigurationError(f"Failed to read configuration file: {e}")

    try:
        # use model_validate with json.loads for proper Path handling
        # (model_validate_json doesn't properly invoke field validators)
        return BuildConfig.model_validate(json.loads(content))
    except Exception as e:
        raise ConfigurationError(f"Invalid configuration: {e}")


def save_config(
    config: BuildConfig,
    path: Union[str, Path],
    update_modified: bool = True,
) -> None:
    """
    save a build configuration to a JSON file"""
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
        raise ConfigurationError(f"Failed to save configuration: {e}")


def merge_configs(
    base: BuildConfig,
    overlay: dict,
) -> BuildConfig:
    """
    merge an overlay dictionary onto a base configuration

    useful for applying command-line overrides to a loaded config."""
    base_dict = base.model_dump()

    def deep_merge(target: dict, source: dict) -> dict:
        result = target.copy()
        for key, value in source.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            elif value is not None:
                result[key] = value
        return result

    merged = deep_merge(base_dict, overlay)
    return BuildConfig.model_validate(merged)


