"""ADF selection and name mapping."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.data.install_media import IdentifiedInstallMedia

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def filter_needed_media(
    media: Iterable[IdentifiedInstallMedia],
    kickstart_version: str,
) -> tuple[list[Path], list[str]]:
    from emu68hatcher.data.package_loader import get_adf_rules_for_version

    needed = {rule.adf for rule in get_adf_rules_for_version(kickstart_version)}
    picked: dict[str, IdentifiedInstallMedia] = {}
    for item in media:
        if item.adf_name in needed:
            picked.setdefault(item.adf_name, item)
    return (
        [item.path for item in picked.values()],
        sorted({item.friendly_name for item in picked.values()}),
    )


def build_adf_name_map(
    workflow: BuildWorkflow,
    adf_paths: list[Path],
    resolved_media: Iterable[IdentifiedInstallMedia],
) -> dict[str, Path]:
    kickstart_version = workflow.config.kickstart.version.value
    mapping: dict[str, Path] = {}
    for media in resolved_media:
        mapping[media.adf_name] = media.path
        match = re.match(r"^(.+\d+_\d+)_\d+$", media.adf_name)
        if match:
            mapping.setdefault(match.group(1), media.path)

    for adf_path in adf_paths:
        stem = adf_path.stem.lower()
        locale_match = re.match(r"^locale([a-z]{2}).*$", stem)
        if locale_match:
            code = locale_match.group(1).upper()
            version = _matching_adf_version(kickstart_version)
            if version:
                name = f"Locale{code}{version}"
                mapping.setdefault(name, adf_path)
                workflow.logger.debug(f"Mapped locale ADF: {name} -> {adf_path}")
            continue

        for fragment in (
            "workbench",
            "extras",
            "fonts",
            "storage",
            "locale",
            "install",
            "classes",
            "backdrops",
            "update",
            "diskdoctor",
        ):
            if fragment not in stem:
                continue
            version = _matching_adf_version(kickstart_version)
            if version:
                mapping.setdefault(f"{fragment.capitalize()}{version}", adf_path)
            break
    workflow.logger.debug(f"Mapped {len(mapping)} ADFs: {list(mapping)}")
    return mapping


def resolve_adf_path(mapping: dict[str, Path], source_name: str) -> Path | None:
    direct = mapping.get(source_name)
    if direct:
        return direct
    normalized = _normalized_name(source_name)
    return next(
        (path for name, path in mapping.items() if _normalized_name(name) == normalized),
        None,
    )


def _matching_adf_version(kickstart_version: str) -> str | None:
    for version in ("3_2_3", "3_2", "3_1"):
        if (
            version.replace("_", ".") in kickstart_version
            or version.replace("_", "") in kickstart_version
        ):
            return version
    return None


def _normalized_name(value: str) -> str:
    return value.lower().replace("_", "").replace(" ", "").replace(".", "")
