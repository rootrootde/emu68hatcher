"""
data management for Emu68 Hatcher

config data is stored as YAML files alongside this module. the two hash
databases (ROM hashes, install media hashes) remain as CSV for tabular
lookups. edit data files directly to change URLs, add packages, update
hashes, etc.
"""

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


# =============================================================================
# data directories (in the package, committed to repo)
# =============================================================================

_REFERENCE_DIR = Path(__file__).parent / "reference"


def load_yaml_data(name: str):
    """
    load a YAML data file from the data directory"""
    path = _REFERENCE_DIR / f"{name}.yaml"
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    return yaml.safe_load(content) or []


def load_csv(name: str) -> list[dict]:
    """
    load a CSV file from the repo"""
    local_path = _REFERENCE_DIR / f"{name}.csv"

    if not local_path.exists():
        return []

    content = local_path.read_text(encoding="utf-8")

    # the CSV uses semicolons as delimiter (from Google Sheets)
    rows = []
    reader = csv.DictReader(io.StringIO(content), delimiter=";")

    for row in reader:
        # clean up row - remove empty keys and strip values
        cleaned = {}
        for key, value in row.items():
            if key and key.strip():
                cleaned[key.strip()] = value.strip() if value else ""
        if cleaned:
            rows.append(cleaned)

    return rows


# =============================================================================
# ROM Hash Database
# =============================================================================


@dataclass
class ROMInfo:
    """information about a Kickstart ROM"""

    hash: str
    kickstart_version: str
    friendly_name: str
    fat32_name: str
    sequence: int = 0
    include_or_exclude: str = "Include"
    exclude_message: str = ""

    @property
    def is_excluded(self) -> bool:
        """check if ROM is excluded (e.g., encrypted)"""
        return self.include_or_exclude.lower() == "exclude"


class ROMHashDB:
    """
    ROM hash database loaded from local CSV

    the CSV can be edited to add custom ROMs or change mappings.
    """

    def __init__(self):
        self._by_hash: dict[str, ROMInfo] = {}
        self._by_version: dict[str, list[ROMInfo]] = {}
        self._loaded = False

    def load(self) -> int:
        """load ROM hashes from CSV"""
        rows = load_csv("rom_hashes")

        self._by_hash.clear()
        self._by_version.clear()

        for row in rows:
            hash_val = row.get("Hash", "").lower()
            if not hash_val:
                continue

            try:
                seq = int(row.get("Sequence", "0") or "0")
            except ValueError:
                seq = 0

            info = ROMInfo(
                hash=hash_val,
                kickstart_version=row.get("Kickstart_Version", ""),
                friendly_name=row.get("FriendlyName", ""),
                fat32_name=row.get("FAT32Name", ""),
                sequence=seq,
                include_or_exclude=row.get("IncludeorExclude", "Include"),
                exclude_message=row.get("ExcludeMessage", ""),
            )

            self._by_hash[hash_val] = info

            version = info.kickstart_version
            if version not in self._by_version:
                self._by_version[version] = []
            self._by_version[version].append(info)

        # sort by sequence
        for version in self._by_version:
            self._by_version[version].sort(key=lambda x: x.sequence)

        self._loaded = True
        return len(self._by_hash)

    def lookup(self, md5_hash: str) -> Optional[ROMInfo]:
        """look up ROM by MD5 hash"""
        if not self._loaded:
            self.load()
        return self._by_hash.get(md5_hash.lower())

    def get_versions(self) -> list[str]:
        """get all known Kickstart versions"""
        if not self._loaded:
            self.load()
        return sorted(self._by_version.keys())

    def get_roms_for_version(self, version: str) -> list[ROMInfo]:
        """get all ROMs for a specific version"""
        if not self._loaded:
            self.load()
        return self._by_version.get(version, [])


# =============================================================================
# install Media Hash Database
# =============================================================================


@dataclass
class InstallMediaInfo:
    """information about install media (ADF, CD, etc.)"""

    hash: str
    workbench_version: str
    adf_name: str
    friendly_name: str
    install_media: str  # "Disk", "CD", "Archive"
    adf_source: str
    adf_description: str
    sequence: int = 0
    type_of_check: str = "Hash"


class InstallMediaHashDB:
    """
    install media hash database loaded from local CSV
    """

    def __init__(self):
        self._by_hash: dict[str, InstallMediaInfo] = {}
        self._by_version: dict[str, dict[str, list[InstallMediaInfo]]] = {}
        self._loaded = False

    def load(self) -> int:
        """load install media hashes from CSV"""
        rows = load_csv("install_media_hashes")

        self._by_hash.clear()
        self._by_version.clear()

        for row in rows:
            hash_val = row.get("Hash", "").lower()
            adf_name = row.get("ADF_Name", "")

            if not hash_val and not adf_name:
                continue

            try:
                seq = int(row.get("Sequence", "0") or "0")
            except ValueError:
                seq = 0

            info = InstallMediaInfo(
                hash=hash_val,
                workbench_version=row.get("WorkbenchVersion", ""),
                adf_name=adf_name,
                friendly_name=row.get("FriendlyName", ""),
                install_media=row.get("InstallMedia", "Disk"),
                adf_source=row.get("ADFSource", ""),
                adf_description=row.get("ADFDescription", ""),
                sequence=seq,
                type_of_check=row.get("TypeofCheck", "Hash"),
            )

            if hash_val:
                self._by_hash[hash_val] = info

            version = info.workbench_version
            if version not in self._by_version:
                self._by_version[version] = {}
            if adf_name not in self._by_version[version]:
                self._by_version[version][adf_name] = []
            self._by_version[version][adf_name].append(info)

        self._loaded = True
        return len(self._by_hash)

    def lookup(self, md5_hash: str) -> Optional[InstallMediaInfo]:
        """look up install media by MD5 hash"""
        if not self._loaded:
            self.load()
        return self._by_hash.get(md5_hash.lower())

    def get_versions(self) -> list[str]:
        """get all known Workbench versions"""
        if not self._loaded:
            self.load()
        return sorted(self._by_version.keys())

    def get_disks_for_version(self, version: str) -> dict[str, list[InstallMediaInfo]]:
        """get all required disks for a Workbench version"""
        if not self._loaded:
            self.load()
        return self._by_version.get(version, {})


# =============================================================================
# global Instances
# =============================================================================

_rom_db: Optional[ROMHashDB] = None
_media_db: Optional[InstallMediaHashDB] = None


def get_rom_db() -> ROMHashDB:
    """get the global ROM hash database"""
    global _rom_db
    if _rom_db is None:
        _rom_db = ROMHashDB()
    return _rom_db


def get_install_media_db() -> InstallMediaHashDB:
    """get the global install media database"""
    global _media_db
    if _media_db is None:
        _media_db = InstallMediaHashDB()
    return _media_db


# =============================================================================
# convenience Functions
# =============================================================================


def lookup_rom_by_hash(md5_hash: str) -> Optional[ROMInfo]:
    """look up a ROM by its MD5 hash"""
    return get_rom_db().lookup(md5_hash)


def lookup_install_media_by_hash(md5_hash: str) -> Optional[InstallMediaInfo]:
    """look up install media by its MD5 hash"""
    return get_install_media_db().lookup(md5_hash)
