"""alphabetical icon grids for every drawer with icons, written via hst-amiga"""

import logging
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from emu68hatcher.utils.host_tools import find_hst_amiga, get_hst_imager_env

logger = logging.getLogger(__name__)

# package drawers are gridded too: install rules merge several archives into
# one drawer (hippoplayer + hipposupport), so even vendor layouts interleave.
# Env-Archive is runtime state, left alone.
_SKIP_SUBTREES = ("prefs/env-archive",)

_MARGIN_X = 10
_MARGIN_Y = 4
_CELL_PAD_X = 12
_ROW_PAD_Y = 18  # label line + gap below the image
_MIN_CELL_W = 70
_TOPAZ_CHAR_W = 8
_MAX_INNER_W = 520  # width budget for resizable drawer windows
# the SYS: window size lives in the volume disk.info (left alone), so the
# root grid has to fit the stock window
_ROOT_INNER_W = 420
_WINDOW_X = 80
_WINDOW_Y = 50
_EMBOSS = 3  # 3D frame workbench draws around the bitmap (IControl default)
_TARGET_ASPECT = 2.0  # preferred window shape, width:height (iTidy's default)

_CONTAINER_TYPES = (2, 5)  # WBDRAWER, WBGARBAGE


@dataclass
class _Icon:
    path: Path
    do_type: int
    width: int
    height: int


def _color_icon_size(data: bytes) -> tuple[int, int, bool] | None:
    """ColorIcon (FORM ICON, FACE chunk) real size + frameless flag"""
    pos = data.find(b"FORM")
    while pos != -1:
        if data[pos + 8 : pos + 12] == b"ICON":
            face = data.find(b"FACE", pos)
            # MagicWB-era icons (MUI 3.8, MagicMenu) end in a degenerate FACE
            # claiming 256x256 with no image data - only trust FACE when an
            # IMAG chunk backs it, otherwise the planar size is the real one
            if face != -1 and len(data) >= face + 11 and data.find(b"IMAG", face) != -1:
                return data[face + 8] + 1, data[face + 9] + 1, bool(data[face + 10] & 1)
            return None
        pos = data.find(b"FORM", pos + 4)
    return None


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
    framed = True
    # the gadget size can be a stub (seen: 8x8) - the rendered bitmap is in
    # the ColorIcon IFF tail or, for NewIcons, encoded in the first IM1=
    # tooltype (transparency char, then width/height as char - 0x21)
    color = _color_icon_size(data)
    if color:
        width, height = max(width, color[0]), max(height, color[1])
        framed = not color[2]
    else:
        im1 = data.find(b"IM1=")
        if im1 != -1 and len(data) > im1 + 7:
            width = max(width, data[im1 + 5] - 0x21)
            height = max(height, data[im1 + 6] - 0x21)
    # workbench adds the emboss frame once, plus a border when framed
    pad = _EMBOSS * 2 if framed else _EMBOSS
    return _Icon(path, data[48], width + pad, height + pad)


def _pick_columns(n: int, cell_w: int, row_h: int, max_cols: int) -> int:
    """column count whose grid shape lands closest to _TARGET_ASPECT"""
    max_cols = max(1, min(n, max_cols))
    best, best_diff = max_cols, None
    # min 2 columns - a 1xN tower is never the best-looking answer (iTidy)
    for cols in range(min(2, max_cols), max_cols + 1):
        rows = -(-n // cols)
        diff = abs((cols * cell_w) / (rows * row_h) - _TARGET_ASPECT)
        if best_diff is None or diff < best_diff:
            best, best_diff = cols, diff
    return best


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

    drawers = sorted(
        {p.parent for p in boot_staging.rglob("*") if p.is_file() and p.suffix.lower() == ".info"}
    )

    lines: list[str] = []
    count = 0
    for drawer in drawers:
        rel = drawer.relative_to(boot_staging).as_posix().lower()
        if any(rel == s or rel.startswith(s + "/") for s in _SKIP_SUBTREES):
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
        img_h = max(i.height for i in icons)
        row_h = img_h + _ROW_PAD_Y
        if rel == ".":
            # the stock SYS: window can't be resized - fill its width
            cols = max(1, min(len(icons), _ROOT_INNER_W // cell_w))
        else:
            cols = _pick_columns(len(icons), cell_w, row_h, _MAX_INNER_W // cell_w)

        for n, icon in enumerate(icons):
            x = _MARGIN_X + (n % cols) * cell_w + (cell_w - icon.width) // 2
            # bottom-aligned so the labels of a row share one baseline
            y = _MARGIN_Y + (n // cols) * row_h + (img_h - icon.height)
            lines.append(f'icon update "{icon.path}" -x {x} -y {y}')
        count += len(icons)

        # size the window to show the grid; the drawer's own icon holds it.
        # the SYS: window geometry lives in the volume disk.info, left alone.
        if rel != ".":
            own = drawer.parent / f"{drawer.name}.info"
            own_icon = _read_icon(own) if own.exists() else None
            if own_icon and own_icon.do_type in _CONTAINER_TYPES:
                rows = -(-len(icons) // cols)
                w = min(2 * _MARGIN_X + cols * cell_w + 24, 560)
                h = min(rows * row_h + _MARGIN_Y + 30, 200)
                lines.append(f'icon update "{own}" -dx {_WINDOW_X} -dy {_WINDOW_Y} -dw {w} -dh {h}')

    # package drawers holding only icon-less files (roadshow docs) open as an
    # empty window - flip their icon to show all files. Programs/ only, so
    # stock drawers like Storage/Keymaps keep the OS behaviour.
    gridded = set(drawers)
    for d in sorted({p.parent for p in boot_staging.rglob("*") if p.is_file()}):
        rel = d.relative_to(boot_staging).as_posix().lower()
        if d in gridded or not rel.startswith("programs/"):
            continue
        own = d.parent / f"{d.name}.info"
        own_icon = _read_icon(own) if own.exists() else None
        if own_icon and own_icon.do_type in _CONTAINER_TYPES:
            lines.append(f'icon update "{own}" -f AllFiles')

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
