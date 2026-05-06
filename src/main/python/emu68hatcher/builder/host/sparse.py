"""sparse-file allocation for the build target (cross-platform)"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from emu68hatcher.utils.platform import OperatingSystem, get_platform_info

logger = logging.getLogger(__name__)


class SparseUnsupportedError(RuntimeError):
    """destination filesystem cant host a sparse file"""


def allocate_sparse(path: Path, size_bytes: int) -> None:
    """sparse file at path; raises SparseUnsupportedError on FAT32/exFAT/SMB"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.touch()

    info = get_platform_info()
    if info.os == OperatingSystem.WINDOWS:
        _set_windows_sparse_flag(path)

    os.truncate(str(path), size_bytes)
    logger.info(f"allocated sparse file: {path} ({size_bytes:,} bytes apparent)")


def _set_windows_sparse_flag(path: Path) -> None:
    try:
        result = subprocess.run(
            ["fsutil", "sparse", "setflag", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise SparseUnsupportedError(f"fsutil unavailable: {e}") from e
    if result.returncode != 0:
        # fsutil rejects sparse on FAT32, exFAT, and SMB/network shares
        msg = result.stderr.strip() or result.stdout.strip()
        raise SparseUnsupportedError(
            f"fsutil sparse setflag failed - destination must be NTFS "
            f"(not FAT32, exFAT, or a network share): {msg}"
        )


def actual_disk_usage(path: Path) -> int:
    """bytes actually on disk for path (vs apparent size); 0 if unknown"""
    try:
        st = os.stat(str(path))
    except OSError:
        return 0
    blocks = getattr(st, "st_blocks", None)
    if blocks is not None:
        return blocks * 512
    return st.st_size
