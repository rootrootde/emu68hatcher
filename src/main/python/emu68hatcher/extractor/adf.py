"""
ADF (Amiga Disk File) extraction for Emu68 Hatcher

uses HST Imager to extract files from ADF disk images.
supports both single ADF files and multi-disk sets.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from emu68hatcher.utils.paths import get_extracted_dir, get_temp_dir
from emu68hatcher.utils.platform import find_hst_imager


@dataclass
class ADFInfo:
    """information about an ADF disk image"""

    path: Path
    label: str
    filesystem: str
    size: int
    used: int
    free: int
    files: list[str] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)

    @property
    def is_bootable(self) -> bool:
        """check if disk appears to be bootable"""
        return any(
            f.lower() in ("s", "s/startup-sequence", "startup-sequence")
            for f in self.files + self.directories
        )


@dataclass
class ADFExtractionResult:
    """result of ADF extraction operation"""

    adf_path: Path
    output_dir: Path
    success: bool
    files_extracted: int
    error: Optional[str] = None


class ADFExtractor:
    """
    extracts files from ADF disk images using HST Imager

    HST Imager provides cross-platform ADF handling with support
    for various Amiga filesystems (OFS, FFS, etc.).
    """

    def __init__(self, hst_imager_path: Optional[Path] = None):
        """
        initialize ADF extractor"""
        self.hst_imager = hst_imager_path or find_hst_imager()

    def is_available(self) -> bool:
        """check if HST Imager is available"""
        return self.hst_imager is not None and self.hst_imager.exists()

    def _run_hst(self, *args: str) -> subprocess.CompletedProcess:
        """run HST Imager command"""
        if not self.is_available():
            raise RuntimeError(
                "HST Imager not found. Run 'emu68-hatcher setup' to download it."
            )

        return subprocess.run(
            [str(self.hst_imager)] + list(args),
            capture_output=True,
            text=True,
        )

    def get_info(self, adf_path: Path) -> Optional[ADFInfo]:
        """
        get information about an ADF file"""
        if not adf_path.exists():
            return None

        # use HST Imager to list contents
        result = self._run_hst("fs", "dir", str(adf_path))

        if result.returncode != 0:
            return None

        # parse output
        files = []
        directories = []
        label = adf_path.stem
        filesystem = "Unknown"

        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line:
                continue

            # HST outputs info lines and file listings
            if line.startswith("Volume:"):
                label = line.split(":", 1)[1].strip()
            elif line.startswith("Filesystem:"):
                filesystem = line.split(":", 1)[1].strip()
            elif "<DIR>" in line:
                # directory entry
                name = line.split()[0]
                directories.append(name)
            elif line and not line.startswith("-"):
                # file entry (has size, date, etc.)
                parts = line.split()
                if parts:
                    files.append(parts[0])

        return ADFInfo(
            path=adf_path,
            label=label,
            filesystem=filesystem,
            size=adf_path.stat().st_size,
            used=0,  # would need to parse from HST output
            free=0,
            files=files,
            directories=directories,
        )

    def extract(
        self,
        adf_path: Path,
        output_dir: Optional[Path] = None,
        preserve_structure: bool = True,
    ) -> ADFExtractionResult:
        """
        extract all files from an ADF"""
        adf_path = Path(adf_path)

        if not adf_path.exists():
            return ADFExtractionResult(
                adf_path=adf_path,
                output_dir=Path(),
                success=False,
                files_extracted=0,
                error=f"ADF not found: {adf_path}",
            )

        if output_dir is None:
            output_dir = get_extracted_dir() / adf_path.stem

        output_dir.mkdir(parents=True, exist_ok=True)

        # use HST Imager to extract
        # hst-imager fs extract <source> <dest>/ -r -f
        result = self._run_hst(
            "fs", "extract",
            str(adf_path),
            str(output_dir) + "/",
            "-r",  # recursive
            "-f",  # force overwrite existing files
        )

        if result.returncode != 0:
            # HST Imager outputs errors to stdout, not stderr
            error_output = result.stderr or result.stdout or "Unknown error"
            return ADFExtractionResult(
                adf_path=adf_path,
                output_dir=output_dir,
                success=False,
                files_extracted=0,
                error=f"HST Imager failed: {error_output}",
            )

        # count extracted files
        files_extracted = sum(1 for _ in output_dir.rglob("*") if _.is_file())

        return ADFExtractionResult(
            adf_path=adf_path,
            output_dir=output_dir,
            success=True,
            files_extracted=files_extracted,
        )

    def extract_file(
        self,
        adf_path: Path,
        file_path: str,
        output_path: Path,
    ) -> bool:
        """
        extract a single file from an ADF"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = self._run_hst(
            "fs", "copy",
            f"{adf_path}/{file_path}",
            str(output_path),
        )

        return result.returncode == 0

    def list_files(self, adf_path: Path, path: str = "") -> list[str]:
        """
        list files in an ADF directory"""
        source = str(adf_path)
        if path:
            source = f"{adf_path}/{path}"

        result = self._run_hst("fs", "dir", source)

        if result.returncode != 0:
            return []

        files = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line and not line.startswith("-") and ":" not in line:
                parts = line.split()
                if parts:
                    files.append(parts[0])

        return files


class MultiDiskExtractor:
    """
    handles extraction from multi-disk ADF sets

    used for Workbench installation disks that span multiple floppies.
    """

    def __init__(self, hst_imager_path: Optional[Path] = None):
        """initialize multi-disk extractor"""
        self.extractor = ADFExtractor(hst_imager_path)

    def find_disk_set(self, directory: Path, pattern: str = "*.adf") -> list[Path]:
        """
        find ADF files that form a disk set"""
        adfs = list(directory.glob(pattern))

        # sort by disk number if present in filename
        def disk_number(path: Path) -> int:
            name = path.stem.lower()
            # look for patterns like "disk1", "disk_2", "workbench1"
            match = re.search(r"(\d+)", name)
            return int(match.group(1)) if match else 0

        adfs.sort(key=disk_number)
        return adfs

    def extract_disk_set(
        self,
        adf_paths: list[Path],
        output_dir: Optional[Path] = None,
    ) -> ADFExtractionResult:
        """
        extract files from a set of ADFs, merging contents"""
        if not adf_paths:
            return ADFExtractionResult(
                adf_path=Path(),
                output_dir=Path(),
                success=False,
                files_extracted=0,
                error="No ADF files provided",
            )

        if output_dir is None:
            # use name of first disk
            output_dir = get_extracted_dir() / adf_paths[0].stem

        output_dir.mkdir(parents=True, exist_ok=True)

        total_files = 0
        errors = []

        for adf_path in adf_paths:
            result = self.extractor.extract(adf_path, output_dir)
            if result.success:
                total_files += result.files_extracted
            else:
                errors.append(f"{adf_path.name}: {result.error}")

        success = len(errors) == 0
        error = "; ".join(errors) if errors else None

        return ADFExtractionResult(
            adf_path=adf_paths[0],
            output_dir=output_dir,
            success=success,
            files_extracted=total_files,
            error=error,
        )


# convenience functions


def extract_adf(
    adf_path: Path,
    output_dir: Optional[Path] = None,
) -> ADFExtractionResult:
    """
    extract files from an ADF"""
    extractor = ADFExtractor()
    return extractor.extract(adf_path, output_dir)


def extract_workbench_disks(
    disk_directory: Path,
    output_dir: Optional[Path] = None,
) -> ADFExtractionResult:
    """
    extract Workbench installation disks"""
    extractor = MultiDiskExtractor()

    # find Workbench disks
    adfs = extractor.find_disk_set(disk_directory, "*ench*.adf")
    if not adfs:
        adfs = extractor.find_disk_set(disk_directory, "*.adf")

    return extractor.extract_disk_set(adfs, output_dir)


# =============================================================================
# workbench ADF Detection
# =============================================================================

# known Workbench disk labels and patterns by version
WORKBENCH_PATTERNS = {
    "3.2": {
        "labels": ["Workbench3.2", "Workbench 3.2", "WB3.2"],
        "files": ["Workbench3.2"],
        "required_disks": ["Workbench", "Locale", "Extras", "Storage", "Fonts"],
    },
    "3.1": {
        "labels": ["Workbench3.1", "Workbench 3.1", "WB3.1", "Workbench31"],
        "files": ["Workbench3.1"],
        "required_disks": ["Workbench", "Locale", "Extras", "Storage", "Fonts"],
    },
    "3.0": {
        "labels": ["Workbench3.0", "Workbench 3.0", "WB3.0"],
        "files": ["Workbench3.0"],
        "required_disks": ["Workbench", "Extras", "Fonts"],
    },
    "2.1": {
        "labels": ["Workbench2.1", "Workbench 2.1", "WB2.1"],
        "files": [],
        "required_disks": ["Workbench", "Extras"],
    },
    "2.04": {
        "labels": ["Workbench2.04", "Workbench 2.04", "WB2.04"],
        "files": [],
        "required_disks": ["Workbench"],
    },
    "1.3": {
        "labels": ["Workbench1.3", "Workbench 1.3", "WB1.3"],
        "files": [],
        "required_disks": ["Workbench"],
    },
}


@dataclass
class WorkbenchDiskSet:
    """information about a detected Workbench disk set"""

    version: str
    directory: Path
    disks: dict[str, Path]  # disk_type -> path (e.g., "Workbench" -> path/to/wb.adf)
    complete: bool
    missing_disks: list[str]

    @property
    def workbench_disk(self) -> Optional[Path]:
        """get the main Workbench disk"""
        return self.disks.get("Workbench")


def detect_workbench_version_from_adf(adf_path: Path) -> Optional[str]:
    """
    detect Workbench version from an ADF file"""
    extractor = ADFExtractor()

    if not extractor.is_available():
        # fall back to filename-based detection
        return _detect_version_from_filename(adf_path)

    info = extractor.get_info(adf_path)
    if not info:
        return _detect_version_from_filename(adf_path)

    # check label against known patterns
    label = info.label.lower().replace(" ", "").replace("_", "")

    for version, patterns in WORKBENCH_PATTERNS.items():
        for pattern in patterns["labels"]:
            if pattern.lower().replace(" ", "") in label:
                return version

    # check for version-specific files
    files_lower = [f.lower() for f in info.files]
    for version, patterns in WORKBENCH_PATTERNS.items():
        for vfile in patterns["files"]:
            if vfile.lower() in files_lower:
                return version

    return _detect_version_from_filename(adf_path)


def _detect_version_from_filename(adf_path: Path) -> Optional[str]:
    """detect version from filename patterns"""
    name = adf_path.stem.lower()

    version_patterns = [
        ("3.2", ["3.2", "32", "3_2"]),
        ("3.1", ["3.1", "31", "3_1"]),
        ("3.0", ["3.0", "30", "3_0"]),
        ("2.1", ["2.1", "21", "2_1"]),
        ("2.04", ["2.04", "204", "2_04"]),
        ("2.0", ["2.0", "20", "2_0"]),
        ("1.3", ["1.3", "13", "1_3"]),
    ]

    for version, patterns in version_patterns:
        for pattern in patterns:
            if pattern in name:
                return version

    return None


def _identify_disk_type(adf_path: Path) -> Optional[str]:
    """identify what type of Workbench disk this is"""
    name = adf_path.stem.lower()

    disk_types = [
        ("Workbench", ["workbench", "wb", "install"]),
        ("Locale", ["locale"]),
        ("Extras", ["extras", "extra"]),
        ("Storage", ["storage"]),
        ("Fonts", ["fonts", "font"]),
    ]

    for disk_type, patterns in disk_types:
        for pattern in patterns:
            if pattern in name:
                return disk_type

    return None


def scan_for_workbench_disks(directory: Path) -> list[WorkbenchDiskSet]:
    """
    scan a directory for Workbench ADF disk sets"""
    if not directory.exists() or not directory.is_dir():
        return []

    # find all ADF files
    adf_files = list(directory.glob("*.adf")) + list(directory.glob("*.ADF"))

    if not adf_files:
        return []

    # group ADFs by detected version
    version_disks: dict[str, dict[str, Path]] = {}

    for adf_path in adf_files:
        version = detect_workbench_version_from_adf(adf_path)
        if not version:
            continue

        disk_type = _identify_disk_type(adf_path)
        if not disk_type:
            disk_type = "Workbench"  # default assumption

        if version not in version_disks:
            version_disks[version] = {}

        # don't overwrite if we already have this disk type
        if disk_type not in version_disks[version]:
            version_disks[version][disk_type] = adf_path

    # build WorkbenchDiskSet objects
    results = []
    for version, disks in version_disks.items():
        patterns = WORKBENCH_PATTERNS.get(version, {"required_disks": ["Workbench"]})
        required = patterns["required_disks"]

        missing = [d for d in required if d not in disks]
        complete = len(missing) == 0

        results.append(WorkbenchDiskSet(
            version=version,
            directory=directory,
            disks=disks,
            complete=complete,
            missing_disks=missing,
        ))

    # sort by version descending
    results.sort(key=lambda x: x.version, reverse=True)
    return results


def find_workbench_for_version(
    directory: Path,
    version: str,
) -> Optional[WorkbenchDiskSet]:
    """
    find Workbench disks matching the specified version"""
    disk_sets = scan_for_workbench_disks(directory)

    # exact match first
    for disk_set in disk_sets:
        if disk_set.version == version:
            return disk_set

    # try partial match (e.g., "3.1" matches "3.1.4")
    for disk_set in disk_sets:
        if disk_set.version.startswith(version) or version.startswith(disk_set.version):
            return disk_set

    return None


# =============================================================================
# hash-based Install Media Detection (like original Emu68 Imager)
# =============================================================================

@dataclass
class IdentifiedInstallMedia:
    """an install media file identified by hash"""
    path: Path
    md5_hash: str
    friendly_name: str
    adf_name: str  # internal name from CSV
    workbench_version: str  # e.g., "3.1", "3.2"
    install_media: str  # e.g., "Disk", "CD"
    source: str  # e.g., "Commodore", "Cloanto"


def scan_install_media_by_hash(
    directory: Path,
    max_files: int = 500,
) -> list[IdentifiedInstallMedia]:
    """
    scan a directory for install media (ADFs, ISOs) and identify by MD5 hash

    this matches the behavior of the original Emu68 Imager which uses
    the install_media_hashes.csv database."""
    from emu68hatcher.utils.hashing import calculate_hash, HashAlgorithm
    from emu68hatcher.data.data_manager import lookup_install_media_by_hash

    if not directory.exists() or not directory.is_dir():
        return []

    # find ADF files (standard 880KB = 901120 bytes)
    # also find ISOs/LHAs for CD-based installs
    candidates = []

    for pattern in ["*.adf", "*.ADF", "*.iso", "*.ISO", "*.lha", "*.LHA"]:
        candidates.extend(directory.rglob(pattern))

    # filter ADFs by size (standard floppy = 901120 bytes)
    adf_candidates = []
    other_candidates = []
    for path in candidates:
        if path.suffix.lower() == ".adf":
            if path.stat().st_size == 901120:
                adf_candidates.append(path)
        else:
            other_candidates.append(path)

    candidates = adf_candidates + other_candidates

    if len(candidates) > max_files:
        # limit to max_files, preferring files in the root directory
        root_files = [f for f in candidates if f.parent == directory]
        sub_files = [f for f in candidates if f.parent != directory]
        candidates = root_files[:max_files] or sub_files[:max_files]

    # hash and lookup each file
    identified = []
    for path in candidates:
        try:
            md5 = calculate_hash(path, HashAlgorithm.MD5)
            info = lookup_install_media_by_hash(md5)

            if info:
                identified.append(IdentifiedInstallMedia(
                    path=path,
                    md5_hash=md5,
                    friendly_name=info.friendly_name,
                    adf_name=info.adf_name,
                    workbench_version=info.workbench_version,
                    install_media=info.install_media,
                    source=info.adf_source,
                ))
        except Exception:
            continue

    return identified


def get_required_install_media(workbench_version: str) -> list[str]:
    """
    get list of required install media ADF_Names for a Workbench version"""
    # ADF_Name values from install_media_hashes.csv
    # based on original Emu68 Imager requirements
    # note: Locale disks are optional (user selects language)
    requirements = {
        "3.1": [
            "Workbench3_1", "Extras3_1", "Storage3_1", "Fonts3_1", "Install3_1",
        ],
        "3.2": [
            "Workbench3_2", "Extras3_2", "Storage3_2", "Fonts3_2", "Install3_2",
            "Classes3_2", "DiskDoctor3_2", "Backdrops3_2",
        ],
        "3.2.2.1": [
            # base 3.2 disks
            "Workbench3_2", "Extras3_2", "Storage3_2", "Fonts3_2", "Install3_2",
            "Classes3_2", "Backdrops3_2",
            # 3.2.2.x update disks
            "Update3_2_2", "Update3_2_2_1", "Classes3_2_2", "DiskDoctor3_2_2",
        ],
        "3.2.3": [
            # base 3.2 disks
            "Workbench3_2", "Extras3_2", "Storage3_2", "Fonts3_2", "Install3_2",
            "Classes3_2", "Backdrops3_2",
            # 3.2.3 update disks
            "Update3_2_3", "Extras3_2_3", "Classes3_2_3", "DiskDoctor3_2_3",
        ],
        "3.9": [
            "AmigaOS3_9", "AmigaOS3_9BB1", "AmigaOS3_9BB2",
        ],
    }
    return requirements.get(workbench_version, ["Workbench3_1"])


def check_install_media_complete(
    found_media: list[IdentifiedInstallMedia],
    workbench_version: str,
) -> tuple[bool, list[str]]:
    """
    check if all required install media for a version is present"""
    required = get_required_install_media(workbench_version)

    # get ALL adf_names from found media (don't filter by version!)
    # this is important because e.g. 3.2.3 requires base 3.2 disks
    # which are tagged with version "3.2", not "3.2.3"
    found_adf_names = {m.adf_name for m in found_media}

    # check which required disks are missing
    missing = [r for r in required if r not in found_adf_names]

    return len(missing) == 0, missing
