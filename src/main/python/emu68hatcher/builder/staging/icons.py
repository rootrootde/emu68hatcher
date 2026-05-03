"""Amiga drawer-icon generation - ensure user-visible folders get a '.info' so Workbench shows them"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from emu68hatcher.data.package_loader import get_local_packages_dir
from emu68hatcher.utils.platform import find_hst_imager

logger = logging.getLogger(__name__)


# roots that get auto-generated drawer icons; system dirs (C/, S/, Libs/, Devs/) stay icon-less
_ICON_ROOTS: tuple[str, ...] = ("Programs", "Prefs")

# runtime-state subdirs to leave alone even when under an icon root
_ICON_SKIP: tuple[str, ...] = ("Prefs/Env-Archive",)


def _drawer_template() -> Path:
    """path to the bundled generic '_drawer.info' template"""
    return get_local_packages_dir() / "System" / "_drawer.info"


def _iter_drawer_dirs(boot_staging: Path):
    """yield every directory under the icon roots that should have an icon"""
    for root_name in _ICON_ROOTS:
        root = boot_staging / root_name
        if not root.exists():
            continue
        yield root
        for sub in root.rglob("*"):
            if not sub.is_dir():
                continue
            rel = sub.relative_to(boot_staging).as_posix()
            if any(rel == s or rel.startswith(s + "/") for s in _ICON_SKIP):
                continue
            yield sub


def ensure_drawer_icons(boot_staging: Path) -> int:
    """drop a '<name>.info' next to every folder under the icon roots that lacks one"""
    template = _drawer_template()
    if not template.exists():
        logger.warning("drawer template %s not found; skipping icon generation", template)
        return 0

    created = 0
    for d in _iter_drawer_dirs(boot_staging):
        info = d.with_name(d.name + ".info")
        if info.exists():
            continue
        shutil.copy2(template, info)
        created += 1
        logger.debug("created drawer icon %s", info.relative_to(boot_staging))
    return created


def extract_icon_from_adf(
    adf_path: Path,
    file_in_adf: str,
    dest: Path,
    hst_imager: Path | None = None,
) -> bool:
    """extract a single .info file from an ADF to 'dest' via hst-imager fs extract"""
    if hst_imager is None:
        hst_imager = find_hst_imager()
    if not hst_imager:
        logger.warning("hst-imager not found; cannot extract icon from ADF")
        return False
    if not adf_path.exists():
        logger.warning(f"ADF {adf_path} not found")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        args = [
            str(hst_imager),
            "fs",
            "extract",
            f"{adf_path.as_posix()}/{file_in_adf}",
            tmp_dir.as_posix() + "/",
            "--force",
            "TRUE",
            "--uaemetadata",
            "None",
        ]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                f"hst-imager failed to extract {adf_path.name}/{file_in_adf}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
            return False

        extracted = [p for p in tmp_dir.rglob("*.info") if p.is_file()]
        if not extracted:
            logger.warning(f"No .info file produced by extracting {file_in_adf}")
            return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extracted[0], dest)
        return True


def apply_icon_set_drawer(
    boot_staging: Path,
    adf_path: Path,
    file_in_adf: str,
    hst_imager: Path | None = None,
) -> int:
    """swap auto-generated drawer icons for the iconset version, matching by byte-equality against the bundled template (so tool icons are left alone)"""
    template = _drawer_template()
    if not template.exists():
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        iconset_drawer = Path(tmp) / "drawer.info"
        if not extract_icon_from_adf(adf_path, file_in_adf, iconset_drawer, hst_imager):
            return 0

        template_bytes = template.read_bytes()
        replaced = 0
        for d in _iter_drawer_dirs(boot_staging):
            info = d.with_name(d.name + ".info")
            if not info.exists() or not info.is_file():
                continue
            if info.read_bytes() != template_bytes:
                continue
            shutil.copy2(iconset_drawer, info)
            replaced += 1
        return replaced
