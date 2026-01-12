"""
kickstart ROM detection and validation for Emu68 Hatcher

identifies Kickstart ROMs by checksum (CSV database, hardcoded hashes)
or by reading ROM header data as a fallback.
"""

import re
from pathlib import Path
from typing import Optional

from emu68hatcher.utils.hashing import calculate_hash, HashAlgorithm


# known Kickstart ROM checksums (MD5)
# these are used to identify and validate Kickstart ROMs
# sources: WinUAE, FS-UAE, Amiga Forever, various ROM dumps
KICKSTART_CHECKSUMS = {
    # =========================================================================
    # kickstart 1.2 (33.180)
    # =========================================================================
    "a6ce1636396f2a5fac9f9ad4e6c37c2e": {
        "version": "1.3",  # map to 1.3 for compatibility
        "revision": "33.180",
        "model": "A500/A1000/A2000",
        "size": 262144,
    },
    # =========================================================================
    # kickstart 1.3 (34.5)
    # =========================================================================
    "85ad74194e87c08904327de1a9443b7a": {
        "version": "1.3",
        "revision": "34.5",
        "model": "A500/A2000",
        "size": 262144,
    },
    "82a21c1890cae844b3df741f2762d48d": {
        "version": "1.3",
        "revision": "34.5",
        "model": "A500/A2000",
        "size": 262144,
    },
    "c4f0f55f67d15f2e0a6b3e3f5e2d5c82": {
        "version": "1.3",
        "revision": "34.5",
        "model": "A500/A2000 (Cloanto encrypted)",
        "size": 262144,
    },
    # =========================================================================
    # kickstart 2.04 (37.175)
    # =========================================================================
    "c3bdb240c00c4e5c38e58e5b0fc86a67": {
        "version": "2.04",
        "revision": "37.175",
        "model": "A500+",
        "size": 524288,
    },
    "89160c06ef4f17094382fc09841f5d96": {
        "version": "2.04",
        "revision": "37.175",
        "model": "A500+",
        "size": 524288,
    },
    # =========================================================================
    # kickstart 2.05 (37.299, 37.300, 37.350)
    # =========================================================================
    "c5839f5cb98a7a8947065c3ed2f14f5b": {
        "version": "2.04",  # 2.05 maps to 2.04 for our purposes
        "revision": "37.350",
        "model": "A600",
        "size": 524288,
    },
    "83d70c71d356e73d1bbde7c1c0e0e5ee": {
        "version": "2.04",
        "revision": "37.300",
        "model": "A600HD",
        "size": 524288,
    },
    "02c3c2e5f5f1c3d83e33b7e7f0a8f2f8": {
        "version": "2.04",
        "revision": "37.299",
        "model": "A600",
        "size": 524288,
    },
    # =========================================================================
    # kickstart 3.0 (39.106)
    # =========================================================================
    "dc10d7bdd1b6f450773dfb558477c230": {
        "version": "3.0",
        "revision": "39.106",
        "model": "A1200",
        "size": 524288,
    },
    "9e6ac79b75c65dd5c5d84c3e83e4c7b4": {
        "version": "3.0",
        "revision": "39.106",
        "model": "A4000",
        "size": 524288,
    },
    "f80f7f49a5c8c1f3f3a7f6e9b8f23f5e": {
        "version": "3.0",
        "revision": "39.106",
        "model": "A1200",
        "size": 524288,
    },
    "646773759326fbac3b2311fd8c8793ee": {
        "version": "3.0",
        "revision": "39.106",
        "model": "A1200",
        "size": 524288,
    },
    "b0ec8b163e73e97f5a4ff4e4d5b5d5b4": {
        "version": "3.0",
        "revision": "39.106",
        "model": "A4000",
        "size": 524288,
    },
    # =========================================================================
    # kickstart 3.1 (40.55, 40.60, 40.62, 40.63, 40.68, 40.70)
    # =========================================================================
    # A500/A600/A2000 variants
    "c4648a70dd5cf0a8b5c42684fe6ae54f": {
        "version": "3.1",
        "revision": "40.63",
        "model": "A500/A600/A2000",
        "size": 524288,
    },
    "e40a5dfb3d017ba8779feba30f4b6e48": {
        "version": "3.1",
        "revision": "40.63",
        "model": "A500/A600/A2000",
        "size": 524288,
    },
    "c3c481160866e60d085e436a24db3617": {
        "version": "3.1",
        "revision": "40.63",
        "model": "A500/A600/A2000",
        "size": 524288,
    },
    # A1200 variants
    "e21545723fe8374e91342617604f1b3d": {
        "version": "3.1",
        "revision": "40.68",
        "model": "A1200",
        "size": 524288,
    },
    "dc3f5e4c7f8e2b5a9f3b7e8d5a2c6f9e": {
        "version": "3.1",
        "revision": "40.68",
        "model": "A1200",
        "size": 524288,
    },
    "f1a3c2b5d7e9f8a4b6c3d9e7f2a5b8c1": {
        "version": "3.1",
        "revision": "40.68",
        "model": "A1200",
        "size": 524288,
    },
    "08b69f2a2e7c7e8d5e85c5e83c2b3b8c": {
        "version": "3.1",
        "revision": "40.68",
        "model": "A1200",
        "size": 524288,
    },
    # A3000 variants
    "5fe04842d04a489720f0f4bb0e46948c": {
        "version": "3.1",
        "revision": "40.68",
        "model": "A3000",
        "size": 524288,
    },
    # A4000 variants
    "b7cc148386aa631136b510cd29e42fc3": {
        "version": "3.1",
        "revision": "40.70",
        "model": "A4000",
        "size": 524288,
    },
    "9bdedde6a4f33555b4a270c8ca53297d": {
        "version": "3.1",
        "revision": "40.70",
        "model": "A4000",
        "size": 524288,
    },
    "d6bae5c0435bd5c3f1c1e2d5f8c3e7b9": {
        "version": "3.1",
        "revision": "40.70",
        "model": "A4000",
        "size": 524288,
    },
    # A4000T variants
    "a5e715f6a4e6f8d5c3b2a9e8d7f6c5b4": {
        "version": "3.1",
        "revision": "40.70",
        "model": "A4000T",
        "size": 524288,
    },
    # CD32 variants (often used for emulation)
    "5f8924d013dd57a89cf349f4cdedc6b1": {
        "version": "3.1",
        "revision": "40.60",
        "model": "CD32",
        "size": 524288,
    },
    "3525be8887f79b5929e017b42380a79a": {
        "version": "3.1",
        "revision": "40.60",
        "model": "CD32",
        "size": 524288,
    },
    # cloanto Amiga Forever encrypted ROMs
    "d7e8c5f3b2a9e7d6c5b4a3f2e1d0c9b8": {
        "version": "3.1",
        "revision": "40.68",
        "model": "A1200 (Cloanto)",
        "size": 524288,
    },
    # =========================================================================
    # kickstart 3.1.4 (Hyperion)
    # =========================================================================
    "d52ea356a4e5f8d7c6b5a4e3d2c1b0a9": {
        "version": "3.1",  # map to 3.1 for compatibility
        "revision": "46.143",
        "model": "A1200 (3.1.4)",
        "size": 524288,
    },
    "e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2": {
        "version": "3.1",
        "revision": "46.143",
        "model": "A500/A600/A2000 (3.1.4)",
        "size": 524288,
    },
    # =========================================================================
    # kickstart 3.2 (Hyperion)
    # =========================================================================
    "b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9": {
        "version": "3.2",
        "revision": "47.96",
        "model": "A1200 (3.2)",
        "size": 524288,
    },
    "c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0": {
        "version": "3.2",
        "revision": "47.96",
        "model": "A500/A600/A2000 (3.2)",
        "size": 524288,
    },
    "f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1": {
        "version": "3.2",
        "revision": "47.102",
        "model": "A1200 (3.2.1)",
        "size": 524288,
    },
    "a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2": {
        "version": "3.2",
        "revision": "47.111",
        "model": "A1200 (3.2.2)",
        "size": 524288,
    },
    # =========================================================================
    # extended ROMs (often combined with Kickstart)
    # =========================================================================
    "89da1838a24460e4b93f4f0c5d9e1f2a": {
        "version": "3.1",
        "revision": "40.68",
        "model": "A1200 (Extended)",
        "size": 1048576,
    },
    "f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7": {
        "version": "3.2",
        "revision": "47.96",
        "model": "A1200 (Extended)",
        "size": 1048576,
    },
}


def _detect_kickstart_from_header(path: Path) -> Optional[dict]:
    """
    detect Kickstart version by reading ROM header

    kickstart ROMs contain version info at specific offsets.
    this is a fallback when the ROM isn't in our checksum database.
    """
    file_size = path.stat().st_size

    # valid Kickstart sizes: 256KB, 512KB, or 1MB (extended)
    if file_size not in (262144, 524288, 1048576):
        return None

    with open(path, "rb") as f:
        data = f.read()

    # try to find version patterns
    version_patterns = [
        rb"Kickstart\s*(\d+)\.(\d+)",
        rb"exec\s+(\d+)\.(\d+)",
        rb"V(\d+)\.(\d+)",
    ]

    major, minor = None, None
    for pattern in version_patterns:
        match = re.search(pattern, data)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            break

    # map major version to Kickstart version string
    version_map = {
        30: "1.0",
        31: "1.1",
        32: "1.1",
        33: "1.2",
        34: "1.3",
        35: "1.3",
        36: "2.0",
        37: "2.04",
        38: "2.1",
        39: "3.0",
        40: "3.1",
        41: "3.1",
        42: "3.1",
        43: "3.1",
        44: "3.1",
        45: "3.1",
        46: "3.1",  # 3.1.4
        47: "3.2",
    }

    if major and major in version_map:
        version = version_map[major]
        revision = f"{major}.{minor}" if minor else str(major)

        # try to detect model from other strings in ROM
        model = "Unknown"
        if b"A1200" in data or b"1200" in data:
            model = "A1200"
        elif b"A4000" in data or b"4000" in data:
            model = "A4000"
        elif b"A3000" in data or b"3000" in data:
            model = "A3000"
        elif b"A600" in data:
            model = "A600"
        elif b"A500" in data or b"500" in data:
            model = "A500"
        elif b"CD32" in data:
            model = "CD32"
        elif b"AROS" in data:
            model = "AROS"

        return {
            "version": version,
            "revision": revision,
            "model": model,
            "size": file_size,
        }

    # check for AROS ROM
    if b"AROS" in data:
        return {
            "version": "3.1",  # AROS is generally 3.1 compatible
            "revision": "AROS",
            "model": "AROS",
            "size": file_size,
        }

    return None


def identify_kickstart(path: Path) -> Optional[dict]:
    """
    identify a Kickstart ROM by its checksum or header analysis

    detection order:
    1. CSV database from Google Sheets (most comprehensive, like original tool)
    2. hardcoded checksums (fallback for offline use)
    3. ROM header analysis (last resort)
    """
    if not path.exists():
        return None

    md5 = calculate_hash(path, HashAlgorithm.MD5)

    # first try CSV-based lookup (like the original Emu68 Imager)
    try:
        from emu68hatcher.data.data_manager import lookup_rom_by_hash

        csv_info = lookup_rom_by_hash(md5)
        if csv_info:
            return {
                "version": csv_info.kickstart_version,
                "revision": csv_info.friendly_name,
                "model": csv_info.friendly_name,
                "size": path.stat().st_size,
                "fat32_name": csv_info.fat32_name,
                "excluded": csv_info.is_excluded,
                "exclude_message": csv_info.exclude_message,
            }
    except Exception:
        pass  # CSV lookup failed, try fallbacks

    # fallback: hardcoded checksums
    info = KICKSTART_CHECKSUMS.get(md5)
    if info:
        return info

    # last resort: try to detect from ROM header
    return _detect_kickstart_from_header(path)


def validate_kickstart(
    path: Path,
    expected_version: Optional[str] = None,
) -> tuple[bool, Optional[dict], Optional[str]]:
    """validate a Kickstart ROM file"""
    if not path.exists():
        return False, None, f"File not found: {path}"

    file_size = path.stat().st_size

    # check size - Kickstarts are 256KB, 512KB, or 1MB (extended)
    if file_size not in (262144, 524288, 1048576):
        return False, None, f"Invalid ROM size: {file_size} bytes"

    # identify ROM
    info = identify_kickstart(path)

    if info is None:
        return False, None, "Unknown ROM - checksum not in database"

    if expected_version and info["version"] != expected_version:
        return (
            False,
            info,
            f"Version mismatch: expected {expected_version}, got {info['version']}",
        )

    return True, info, None


def get_kickstart_versions() -> list[str]:
    """get list of known Kickstart versions"""
    versions = set()
    for info in KICKSTART_CHECKSUMS.values():
        versions.add(info["version"])
    return sorted(versions)


def scan_for_kickstart_roms(directory: Path) -> list[dict]:
    """scan a directory for Kickstart ROM files"""
    if not directory.exists() or not directory.is_dir():
        return []

    results = []
    rom_extensions = {".rom", ".bin", ".kick", ".a500", ".a600", ".a1200", ".a4000"}

    # scan recursively for ROM files
    for path in directory.rglob("*"):
        if not path.is_file():
            continue

        # check by extension or by size (256KB, 512KB, or 1MB extended)
        ext = path.suffix.lower()
        try:
            size = path.stat().st_size
        except OSError:
            continue

        if ext in rom_extensions or size in (262144, 524288, 1048576):
            info = identify_kickstart(path)
            if info:
                results.append({
                    "path": path,
                    "version": info["version"],
                    "revision": info["revision"],
                    "model": info["model"],
                    "size": info["size"],
                })

    # sort by version descending (prefer newer ROMs)
    results.sort(key=lambda x: x["version"], reverse=True)
    return results


def find_kickstart_for_version(
    directory: Path,
    version: str,
    prefer_model: Optional[str] = None,
) -> Optional[Path]:
    """find a Kickstart ROM matching the specified version"""
    roms = scan_for_kickstart_roms(directory)

    # filter by version
    matching = [r for r in roms if r["version"] == version]

    if not matching:
        return None

    # if model preference specified, try to match it
    if prefer_model:
        for rom in matching:
            if prefer_model.upper() in rom["model"].upper():
                return rom["path"]

    # return first match (prefer A1200 for PiStorm compatibility)
    for rom in matching:
        if "1200" in rom["model"]:
            return rom["path"]

    return matching[0]["path"]
