"""
archive extraction for Emu68 Hatcher

supports various archive formats commonly used in Amiga software:
- ZIP (via Python zipfile or 7z)
- 7z (via 7z command)
- LHA/LZH (via 7z or lha command)
- TAR/GZ/BZ2 (via Python tarfile)
"""

import gzip
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from emu68hatcher.utils.paths import get_extracted_dir, get_temp_dir
from emu68hatcher.utils.platform import find_7z, find_tool


class ArchiveFormat(str, Enum):
    """supported archive formats"""

    ZIP = "zip"
    SEVENZIP = "7z"
    LHA = "lha"
    TAR = "tar"
    TAR_GZ = "tar.gz"
    TAR_BZ2 = "tar.bz2"
    GZIP = "gz"
    UNKNOWN = "unknown"


@dataclass
class ExtractionResult:
    """result of an extraction operation"""

    archive_path: Path
    output_dir: Path
    format: ArchiveFormat
    success: bool
    files_extracted: int
    error: Optional[str] = None

    @property
    def extracted_files(self) -> list[Path]:
        """get list of extracted files"""
        if not self.success or not self.output_dir.exists():
            return []
        return list(self.output_dir.rglob("*"))


# progress callback type
ExtractProgressCallback = Callable[[str, int, int], None]

# extensions recognized as extractable archives
ARCHIVE_EXTENSIONS = {'.lha', '.lzh', '.zip', '.7z', '.tar', '.gz', '.tgz'}


def detect_format(path: Path) -> ArchiveFormat:
    """
    detect archive format from file extension and magic bytes"""
    suffix = path.suffix.lower()
    name = path.name.lower()

    # check compound extensions first
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return ArchiveFormat.TAR_GZ
    if name.endswith(".tar.bz2") or name.endswith(".tbz2"):
        return ArchiveFormat.TAR_BZ2

    # simple extension mapping
    ext_map = {
        ".zip": ArchiveFormat.ZIP,
        ".7z": ArchiveFormat.SEVENZIP,
        ".lha": ArchiveFormat.LHA,
        ".lzh": ArchiveFormat.LHA,
        ".tar": ArchiveFormat.TAR,
        ".gz": ArchiveFormat.GZIP,
    }

    if suffix in ext_map:
        return ext_map[suffix]

    # try magic bytes for common formats
    try:
        with open(path, "rb") as f:
            magic = f.read(8)

        if magic[:4] == b"PK\x03\x04":
            return ArchiveFormat.ZIP
        if magic[:6] == b"7z\xbc\xaf\x27\x1c":
            return ArchiveFormat.SEVENZIP
        if magic[2:5] == b"-lh":
            return ArchiveFormat.LHA
        if magic[:2] == b"\x1f\x8b":
            return ArchiveFormat.GZIP

    except Exception:
        pass

    return ArchiveFormat.UNKNOWN


def extract_archive(
    archive_path: Path,
    output_dir: Optional[Path] = None,
    progress_callback: Optional[ExtractProgressCallback] = None,
) -> ExtractionResult:
    """
    extract an archive to a directory

    automatically detects format and uses appropriate extractor."""
    archive_path = Path(archive_path)

    if not archive_path.exists():
        return ExtractionResult(
            archive_path=archive_path,
            output_dir=Path(),
            format=ArchiveFormat.UNKNOWN,
            success=False,
            files_extracted=0,
            error=f"Archive not found: {archive_path}",
        )

    # detect format
    fmt = detect_format(archive_path)

    # determine output directory
    if output_dir is None:
        base_name = archive_path.stem
        # handle .tar.gz etc
        if base_name.endswith(".tar"):
            base_name = base_name[:-4]
        output_dir = get_extracted_dir() / base_name

    output_dir.mkdir(parents=True, exist_ok=True)

    # extract based on format
    extractors = {
        ArchiveFormat.ZIP: _extract_zip,
        ArchiveFormat.SEVENZIP: _extract_7z,
        ArchiveFormat.LHA: _extract_lha,
        ArchiveFormat.TAR: _extract_tar,
        ArchiveFormat.TAR_GZ: _extract_tar,
        ArchiveFormat.TAR_BZ2: _extract_tar,
        ArchiveFormat.GZIP: _extract_gzip,
    }

    extractor = extractors.get(fmt)
    if extractor is None:
        return ExtractionResult(
            archive_path=archive_path,
            output_dir=output_dir,
            format=fmt,
            success=False,
            files_extracted=0,
            error=f"Unsupported archive format: {fmt.value}",
        )

    try:
        files_extracted = extractor(archive_path, output_dir, progress_callback)
        return ExtractionResult(
            archive_path=archive_path,
            output_dir=output_dir,
            format=fmt,
            success=True,
            files_extracted=files_extracted,
        )
    except Exception as e:
        return ExtractionResult(
            archive_path=archive_path,
            output_dir=output_dir,
            format=fmt,
            success=False,
            files_extracted=0,
            error=str(e),
        )


def _extract_zip(
    archive_path: Path,
    output_dir: Path,
    progress_callback: Optional[ExtractProgressCallback] = None,
) -> int:
    """extract ZIP archive using Python's zipfile module"""
    with zipfile.ZipFile(archive_path, "r") as zf:
        members = zf.namelist()
        total = len(members)

        for i, member in enumerate(members):
            zf.extract(member, output_dir)
            if progress_callback:
                progress_callback(member, i + 1, total)

        return total


def _extract_7z(
    archive_path: Path,
    output_dir: Path,
    progress_callback: Optional[ExtractProgressCallback] = None,
) -> int:
    """extract 7z archive using 7z command"""
    seven_z = find_7z()
    if not seven_z:
        raise RuntimeError("7z not found. Please install p7zip.")

    result = subprocess.run(
        [str(seven_z), "x", "-y", f"-o{output_dir}", str(archive_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"7z extraction failed: {result.stderr}")

    # count extracted files
    return sum(1 for _ in output_dir.rglob("*") if _.is_file())


def _extract_lha(
    archive_path: Path,
    output_dir: Path,
    progress_callback: Optional[ExtractProgressCallback] = None,
) -> int:
    """extract LHA/LZH archive using 7z or lha command"""
    # try 7z first (more commonly available)
    seven_z = find_7z()
    if seven_z:
        result = subprocess.run(
            [str(seven_z), "x", "-y", f"-o{output_dir}", str(archive_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return sum(1 for _ in output_dir.rglob("*") if _.is_file())

    # try lha command
    lha = find_tool("lha")
    if lha:
        # lha needs to be run from the output directory
        result = subprocess.run(
            [str(lha), "-xfq", str(archive_path)],
            cwd=output_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return sum(1 for _ in output_dir.rglob("*") if _.is_file())

    raise RuntimeError("No LHA extractor found. Install p7zip or lha.")



def _extract_tar(
    archive_path: Path,
    output_dir: Path,
    progress_callback: Optional[ExtractProgressCallback] = None,
) -> int:
    """extract TAR archive (including .tar.gz and .tar.bz2)"""
    mode = "r"
    name = archive_path.name.lower()

    if name.endswith(".gz") or name.endswith(".tgz"):
        mode = "r:gz"
    elif name.endswith(".bz2") or name.endswith(".tbz2"):
        mode = "r:bz2"

    with tarfile.open(archive_path, mode) as tf:
        members = tf.getmembers()
        total = len(members)

        for i, member in enumerate(members):
            tf.extract(member, output_dir)
            if progress_callback:
                progress_callback(member.name, i + 1, total)

        return total


def _extract_gzip(
    archive_path: Path,
    output_dir: Path,
    progress_callback: Optional[ExtractProgressCallback] = None,
) -> int:
    """extract gzip-compressed file"""
    # output filename without .gz
    output_name = archive_path.stem
    output_path = output_dir / output_name

    with gzip.open(archive_path, "rb") as gz:
        with open(output_path, "wb") as f:
            shutil.copyfileobj(gz, f)

    if progress_callback:
        progress_callback(output_name, 1, 1)

    return 1


