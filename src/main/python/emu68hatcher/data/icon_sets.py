"""Icon set catalog."""

import re

from emu68hatcher.data.data_manager import load_yaml_data
from emu68hatcher.data.install_media import get_required_install_media


def get_icon_sets_for_version(workbench_version: str) -> list[dict]:
    return [
        row for row in load_yaml_data("icon_sets") if workbench_version in row.get("versions", [])
    ]


def get_icon_set_extra_adf(icon_set: str, workbench_version: str) -> str | None:
    row = next(
        (
            item
            for item in get_icon_sets_for_version(workbench_version)
            if item.get("name") == icon_set
        ),
        None,
    )
    if row is None:
        return None
    source = (row.get("new_folder_icon") or {}).get("source")
    if not source or source in get_required_install_media(workbench_version):
        return None
    return str(source)


def format_adf_name(adf_name: str) -> str:
    match = re.match(r"^(.*?)(\d+(?:_\d+)+)$", adf_name)
    if not match:
        return adf_name
    name, version = match.groups()
    return f"{name} {version.replace('_', '.')}"
