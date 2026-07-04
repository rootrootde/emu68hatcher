"""data management"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

_REFERENCE_DIR = Path(__file__).parent / "reference"


@cache
def load_yaml_data(name: str):
    """load a YAML data file from the data directory (result cached per name)"""
    path = _REFERENCE_DIR / f"{name}.yaml"
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    return yaml.safe_load(content) or []


@dataclass
class InstallMediaInfo:
    """information about install media"""

    workbench_version: str
    adf_name: str
    friendly_name: str


@cache
def _install_media_by_hash() -> dict[str, InstallMediaInfo]:
    """lowercased md5 hash -> InstallMediaInfo, loaded from install_media_hashes.yaml"""
    out: dict[str, InstallMediaInfo] = {}
    for entry in load_yaml_data("install_media_hashes"):
        hash_val = (entry.get("hash") or "").lower()
        if not hash_val:
            continue
        out[hash_val] = InstallMediaInfo(
            workbench_version=str(entry.get("version") or ""),
            adf_name=entry.get("adf_name") or "",
            friendly_name=entry.get("friendly_name") or "",
        )
    return out


def lookup_install_media(md5_hash: str) -> InstallMediaInfo | None:
    """look up install media by md5 hash"""
    return _install_media_by_hash().get(md5_hash.lower())
