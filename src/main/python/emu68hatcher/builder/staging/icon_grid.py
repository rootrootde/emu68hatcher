"""alphabetical icon grids for mixed-source drawers, written via hst-amiga"""

import logging
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from emu68hatcher.utils.host_tools import find_hst_amiga, get_hst_imager_env

logger = logging.getLogger(__name__)

# drawers whose icons come from several sources (OS install + packages + local
# files); "" is the SYS: root window. package-internal drawers keep their
# vendor layout, which is consistent within one archive.
_GRID_DRAWERS: tuple[str, ...] = (
    "",
    "Programs",
    "Utilities",
    "WBStartup",
    "Prefs",
    "Devs",
    "Devs/DataTypes",
    "Devs/DOSDrivers",
    "Devs/Monitors",
    "Devs/NetInterfaces",
    "Storage",
    "Storage/DataTypes",
    "Storage/DOSDrivers",
    "Storage/Monitors",
    "Storage/NetInterfaces",
)

_MARGIN_X = 10
_MARGIN_Y = 4
_CELL_PAD_X = 12
_ROW_PAD_Y = 18  # label line + gap below the image
_MIN_CELL_W = 70
_TOPAZ_CHAR_W = 8
_MAX_INNER_W = 520  # icons wrap to the next row beyond this width
_WINDOW_X = 80
_WINDOW_Y = 50

_CONTAINER_TYPES = (2, 5)  # WBDRAWER, WBGARBAGE


@dataclass
class _Icon:
    path: Path
    do_type: int
    width: int
    height: int


def _read_icon(path: Path) -> _Icon | None:
    """parse the DiskObject header; None for anything that isn't an icon"""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    # magic 0xE310, Gadget width/height at 12/14, do_Type at 48
    if len(data) < 78 or data[0:2] != b"\xe3\x10":
        return None
    width, height = struct.unpack(">HH", data[12:16])
    return _Icon(path, data[48], width, height)


def _resolve_dir(root: Path, rel: str) -> Path | None:
    """case-insensitive lookup - staged dirs keep whatever casing came first"""
    cur = root
    for part in filter(None, rel.split("/")):
        match = next(
            (c for c in cur.iterdir() if c.is_dir() and c.name.lower() == part.lower()),
            None,
        )
        if match is None:
            return None
        cur = match
    return cur


def _drawer_icons(drawer: Path) -> list[_Icon]:
    """visible icons of a drawer, containers first, each group alphabetical"""
    icons = []
    for child in drawer.iterdir():
        # disk.info is the volume icon on the backdrop, not part of the window
        if not child.is_file() or child.suffix.lower() != ".info":
            continue
        if child.name.lower() == "disk.info":
            continue
        icon = _read_icon(child)
        if icon:
            icons.append(icon)
    icons.sort(key=lambda i: (i.do_type not in _CONTAINER_TYPES, i.path.stem.lower()))
    return icons


def arrange_icons(boot_staging: Path) -> int:
    """grid-position every icon in the shared drawers; returns icons placed"""
    hst_amiga = find_hst_amiga()
    if not hst_amiga:
        logger.warning("hst-amiga not found; icons keep their archive positions")
        return 0

    lines: list[str] = []
    count = 0
    for rel in _GRID_DRAWERS:
        drawer = _resolve_dir(boot_staging, rel)
        if drawer is None:
            continue
        icons = _drawer_icons(drawer)
        if not icons:
            continue

        # one cell size per drawer so the columns line up; the label can be
        # wider than the image (topaz 8 is 8px per char)
        cell_w = max(
            _MIN_CELL_W,
            max(max(i.width, len(i.path.stem) * _TOPAZ_CHAR_W) for i in icons) + _CELL_PAD_X,
        )
        row_h = max(i.height for i in icons) + _ROW_PAD_Y
        cols = max(1, min(len(icons), _MAX_INNER_W // cell_w))

        for n, icon in enumerate(icons):
            x = _MARGIN_X + (n % cols) * cell_w + (cell_w - icon.width) // 2
            y = _MARGIN_Y + (n // cols) * row_h
            lines.append(f'icon update "{icon.path}" -x {x} -y {y}')
        count += len(icons)

        # size the window to show the grid; the drawer's own icon holds it.
        # the SYS: window geometry lives in the volume disk.info, left alone.
        if rel:
            own = drawer.parent / f"{drawer.name}.info"
            own_icon = _read_icon(own) if own.exists() else None
            if own_icon and own_icon.do_type in _CONTAINER_TYPES:
                rows = -(-len(icons) // cols)
                w = min(2 * _MARGIN_X + cols * cell_w + 24, 560)
                h = min(rows * row_h + _MARGIN_Y + 30, 200)
                lines.append(f'icon update "{own}" -dx {_WINDOW_X} -dy {_WINDOW_Y} -dw {w} -dh {h}')

    if not lines:
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as script:
        script.write("\n".join(lines) + "\n")
        script_path = script.name
    try:
        result = subprocess.run(
            [str(hst_amiga), "script", script_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=get_hst_imager_env(),
        )
    finally:
        Path(script_path).unlink(missing_ok=True)

    # hst tools log per-line errors at ERR level and can still exit 0
    output = result.stdout + result.stderr
    if result.returncode != 0 or " ERR]" in output:
        errs = [ln for ln in output.splitlines() if " ERR]" in ln]
        logger.warning(
            f"hst-amiga icon script reported errors ({result.returncode}): "
            f"{'; '.join(errs[:3]) or output.strip()[:300]}"
        )
        return 0
    return count
