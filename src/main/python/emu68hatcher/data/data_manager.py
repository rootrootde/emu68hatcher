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


class InstallMediaHashDB:
    """install media hash database loaded from YAML"""

    def __init__(self):
        self._by_hash: dict[str, InstallMediaInfo] = {}
        self._loaded = False

    def load(self) -> int:
        """load install media hashes from YAML"""
        entries = load_yaml_data("install_media_hashes")
        self._by_hash.clear()

        for entry in entries:
            hash_val = (entry.get("hash") or "").lower()
            adf_name = entry.get("adf_name") or ""

            if not hash_val and not adf_name:
                continue

            info = InstallMediaInfo(
                workbench_version=str(entry.get("version") or ""),
                adf_name=adf_name,
                friendly_name=entry.get("friendly_name") or "",
            )

            if hash_val:
                self._by_hash[hash_val] = info

        self._loaded = True
        return len(self._by_hash)

    def lookup(self, md5_hash: str) -> InstallMediaInfo | None:
        """look up inatall media by hash"""
        if not self._loaded:
            self.load()
        return self._by_hash.get(md5_hash.lower())


# global instance
_media_db: InstallMediaHashDB | None = None


def get_install_media_db() -> InstallMediaHashDB:
    """get global install media database"""
    global _media_db
    if _media_db is None:
        _media_db = InstallMediaHashDB()
    return _media_db
