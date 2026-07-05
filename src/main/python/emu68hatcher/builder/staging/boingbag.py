"""install the AmigaOS 3.9 soft ROM update from the BoingBag 2 download"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from emu68hatcher.utils.host_tools import find_7z

logger = logging.getLogger(__name__)

# the AmigaOS-Update payload inside BoingBag 3.9-2 is a password-locked zip;
# the password is fixed and shipped with the original OS 3.9 update tooling
_INNER_ARCHIVE = "AmigaOS-Update"
_INNER_PASSWORD = "3FB6986B-B0AD6339-4FF3254B"
_ROM_UPDATE_MEMBER = "Devs/AmigaOS ROM Update.BB39-2"
_ROM_UPDATE_DEST = "Devs/AmigaOS ROM Update"


def install_rom_update(boingbag_dir: Path, boot_staging: Path) -> bool:
    """place the soft ROM update from an extracted BoingBag 2 tree under boot_staging/Devs"""
    seven_z = find_7z()
    if not seven_z:
        logger.error("7z not found; cannot open the BoingBag ROM update")
        return False

    inner = next((p for p in boingbag_dir.rglob(_INNER_ARCHIVE) if p.is_file()), None)
    if inner is None:
        logger.error(f"{_INNER_ARCHIVE} not found under {boingbag_dir}")
        return False

    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(
            [
                str(seven_z),
                "x",
                "-y",
                f"-p{_INNER_PASSWORD}",
                f"-o{td}",
                str(inner),
                _ROM_UPDATE_MEMBER,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        extracted = Path(td) / _ROM_UPDATE_MEMBER
        if r.returncode != 0 or not extracted.is_file():
            logger.error(f"failed to extract ROM update: {(r.stderr or r.stdout).strip()[:300]}")
            return False

        dest = boot_staging / _ROM_UPDATE_DEST
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extracted, dest)

    logger.info(f"installed soft ROM update -> {dest}")
    return True
