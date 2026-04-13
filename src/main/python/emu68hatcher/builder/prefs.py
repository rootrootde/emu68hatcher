"""
amiga preferences file generation for Emu68 Hatcher

generates various Amiga preference files:
- workbench prefs (ScreenMode, Palette, etc.)
- locale settings
- input preferences
- environment variables
"""

import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class ScreenModeID(Enum):
    """common Amiga screen mode IDs"""

    PAL_LORES = 0x00000000
    PAL_HIRES = 0x00008000
    PAL_SUPERHIRES = 0x00008020
    PAL_LORES_LACE = 0x00000004
    PAL_HIRES_LACE = 0x00008004
    PAL_SUPERHIRES_LACE = 0x00008024

    NTSC_LORES = 0x00010000
    NTSC_HIRES = 0x00018000
    NTSC_SUPERHIRES = 0x00018020
    NTSC_LORES_LACE = 0x00010004
    NTSC_HIRES_LACE = 0x00018004
    NTSC_SUPERHIRES_LACE = 0x00018024

    # RTG modes (P96/CGX) - legacy, not used by Emu68
    P96_640x480 = 0x50001000
    P96_800x600 = 0x50001001
    P96_1024x768 = 0x50001002
    P96_1280x1024 = 0x50001003

    # videocore/Emu68 RTG modes (UAEGFX) - mode IDs from screen_modes_wb.csv
    # format: $50XX1303 where XX varies by resolution
    VC_640x480 = 0x50051303   # not in CSV, estimated from pattern
    VC_800x600 = 0x50061303   # VideoCore:800x600 32bit BGRA
    VC_1024x768 = 0x50071303  # VideoCore:1024x768 32bit BGRA
    VC_1280x720 = 0x500A1303  # VideoCore:1280x720 32bit BGRA (DEFAULT)
    VC_1280x1024 = 0x50321303 # VideoCore:1280x1024 32bit BGRA
    VC_1920x1080 = 0x50311303 # VideoCore:1920x1080 32bit BGRA
    VC_720x576_PAL = 0x50001303  # estimated PAL resolution
    VC_720x480_NTSC = 0x50001303 # estimated NTSC resolution


@dataclass
class ScreenModePrefs:
    """screen mode preference settings"""

    mode_id: int = ScreenModeID.PAL_HIRES.value
    width: int = 640
    height: int = 256
    depth: int = 4  # bits per pixel (2^4 = 16 colors)
    overscan: int = 0
    auto_scroll: bool = False


@dataclass
class WBPatternPrefs:
    """workbench pattern/backdrop settings"""

    wb_pattern: int = 0  # workbench pattern
    window_pattern: int = 0  # window pattern
    backdrop: bool = True
    # pattern data would go here for custom patterns


@dataclass
class LocalePrefs:
    """locale preference settings"""

    country: str = "united_kingdom"
    language: str = "english"
    gmt_offset: int = 0  # minutes from GMT


@dataclass
class InputPrefs:
    """input (keyboard/mouse) preference settings"""

    keymap: str = "usa"  # keymap name
    key_repeat_delay: int = 50  # milliseconds
    key_repeat_speed: int = 10  # characters per second
    mouse_acceleration: int = 2


# =============================================================================
# IFF Chunk Writing Helpers
# =============================================================================


def make_iff_chunk(chunk_id: bytes, data: bytes) -> bytes:
    """create an IFF chunk"""
    # pad to even length
    if len(data) % 2:
        data += b"\x00"

    return chunk_id + struct.pack(">I", len(data)) + data


def make_iff_form(form_type: bytes, chunks: list[bytes]) -> bytes:
    """create an IFF FORM container"""
    content = form_type + b"".join(chunks)
    if len(content) % 2:
        content += b"\x00"

    return b"FORM" + struct.pack(">I", len(content)) + content


# =============================================================================
# preference File Generation
# =============================================================================


def generate_screenmode_prefs(prefs: ScreenModePrefs) -> bytes:
    """
    generate ScreenMode.prefs as an IFF FORM/PREF file

    structure: FORM PREF { PRHD, SCRM }
    - PRHD: 6 bytes (version header, all zeros)
    - SCRM: 28 bytes (screen mode data with mode_id and depth)
    """
    # PRHD chunk - 6 bytes of zeros (version header)
    prhd_data = b"\x00" * 6
    prhd_chunk = make_iff_chunk(b"PRHD", prhd_data)

    # SCRM chunk - 28 bytes:
    #   offset 0-15:  reserved (zeros)
    #   offset 16-19: mode_id (big-endian uint32)
    #   offset 20-23: 0xFFFFFFFF (auto width/height)
    #   offset 24:    reserved (0x00)
    #   offset 25:    depth
    #   offset 26-27: 0x0001 (reserved)
    scrm_data = struct.pack(
        ">16x I I B B H",
        prefs.mode_id,   # mode ID
        0xFFFFFFFF,      # auto width/height
        0x00,            # reserved
        prefs.depth,     # color depth
        0x0001,          # reserved
    )
    scrm_chunk = make_iff_chunk(b"SCRM", scrm_data)

    return make_iff_form(b"PREF", [prhd_chunk, scrm_chunk])


def generate_wbpattern_prefs(prefs: WBPatternPrefs) -> bytes:
    """generate WBPattern.prefs file content"""
    # PRHD chunk
    prhd_data = struct.pack(">BBBB", 0, 0, 0, 0)
    prhd_chunk = make_iff_chunk(b"PRHD", prhd_data)

    # PTRN chunk - pattern data
    flags = 0
    if prefs.backdrop:
        flags |= 0x01

    ptrn_data = struct.pack(
        ">BB HH",
        prefs.wb_pattern,
        prefs.window_pattern,
        flags,
        0,  # reserved
    )
    ptrn_chunk = make_iff_chunk(b"PTRN", ptrn_data)

    return make_iff_form(b"PREF", [prhd_chunk, ptrn_chunk])


def generate_locale_prefs(prefs: LocalePrefs) -> bytes:
    """generate Locale.prefs file content"""
    # country name (32 bytes, null-padded)
    country_bytes = prefs.country.encode("ascii")[:31].ljust(32, b"\x00")

    # language name
    language_bytes = prefs.language.encode("ascii")[:29].ljust(30, b"\x00")

    # PRHD chunk
    prhd_data = struct.pack(">BBBB", 0, 0, 0, 0)
    prhd_chunk = make_iff_chunk(b"PRHD", prhd_data)

    # LCLE chunk - locale data
    lcle_data = country_bytes + language_bytes + struct.pack(">h", prefs.gmt_offset)
    lcle_chunk = make_iff_chunk(b"LCLE", lcle_data)

    return make_iff_form(b"PREF", [prhd_chunk, lcle_chunk])


def generate_input_prefs(prefs: InputPrefs) -> bytes:
    """generate Input.prefs file content"""
    # keymap name (30 bytes)
    keymap_bytes = prefs.keymap.encode("ascii")[:29].ljust(30, b"\x00")

    # PRHD chunk
    prhd_data = struct.pack(">BBBB", 0, 0, 0, 0)
    prhd_chunk = make_iff_chunk(b"PRHD", prhd_data)

    # INPT chunk
    inpt_data = keymap_bytes + struct.pack(
        ">HHH",
        prefs.key_repeat_delay,
        prefs.key_repeat_speed,
        prefs.mouse_acceleration,
    )
    inpt_chunk = make_iff_chunk(b"INPT", inpt_data)

    return make_iff_form(b"PREF", [prhd_chunk, inpt_chunk])


# =============================================================================
# environment Variables
# =============================================================================


def write_env_var(
    env_archive_dir: Path,
    name: str,
    value: str,
) -> None:
    """
    write an environment variable to Env-Archive"""
    var_path = env_archive_dir / name
    var_path.parent.mkdir(parents=True, exist_ok=True)
    var_path.write_text(value, encoding="iso-8859-1")


def generate_default_env_vars(env_archive_dir: Path) -> None:
    """generate default environment variables"""
    defaults = {
        "Workbench": "Workbench:",
        "Sys/def_shell": "CON:0/50//150/Shell/CLOSE",
        "Sys/def_editor": "C:Ed",
        "Sys/def_cli": "NewShell",
        "Sys/def_width": "640",
        "Sys/def_height": "256",
    }

    for name, value in defaults.items():
        write_env_var(env_archive_dir, name, value)


# =============================================================================
# complete Preference Installation
# =============================================================================


def install_default_prefs(
    prefs_dir: Path,
    screen_mode: Optional[ScreenModePrefs] = None,
    locale: Optional[LocalePrefs] = None,
    input_prefs: Optional[InputPrefs] = None,
    wb_pattern: Optional[WBPatternPrefs] = None,
) -> None:
    """
    install default preference files"""
    prefs_dir.mkdir(parents=True, exist_ok=True)
    env_archive = prefs_dir / "Env-Archive"
    env_archive.mkdir(exist_ok=True)

    # screen mode
    if screen_mode:
        import logging
        logger = logging.getLogger("emu68hatcher")
        data = generate_screenmode_prefs(screen_mode)
        logger.info(f"Writing screenmode.prefs ({len(data)} bytes) with mode_id={hex(screen_mode.mode_id)}")
        logger.debug(f"ScreenMode prefs hex: {data.hex()}")

        def _write_prefs(directory: Path) -> None:
            for variant in ["screenmode.prefs", "ScreenMode.prefs", "Screenmode.prefs"]:
                variant_path = directory / variant
                if variant_path.exists():
                    variant_path.unlink()
                    logger.debug(f"Removed existing {variant_path}")
            dest = directory / "screenmode.prefs"
            dest.write_bytes(data)
            logger.info(f"Wrote {dest}")

        _write_prefs(prefs_dir)

        sys_dir = env_archive / "Sys"
        sys_dir.mkdir(parents=True, exist_ok=True)
        _write_prefs(sys_dir)
        logger.info(f"Wrote {env_prefs_file}")

    # locale
    if locale:
        data = generate_locale_prefs(locale)
        (prefs_dir / "locale.prefs").write_bytes(data)

    # input
    if input_prefs:
        data = generate_input_prefs(input_prefs)
        (prefs_dir / "input.prefs").write_bytes(data)

    # WB Pattern
    if wb_pattern:
        data = generate_wbpattern_prefs(wb_pattern)
        (prefs_dir / "wbpattern.prefs").write_bytes(data)

    # default environment variables
    generate_default_env_vars(env_archive)


def parse_mode_id(mode_id_str: str) -> Optional[int]:
    """
    parse a mode ID string (like "$500A1303" or "0x500A1303") to an integer"""
    if not mode_id_str:
        return None
    mode_id_str = mode_id_str.strip()
    try:
        if mode_id_str.startswith("$"):
            return int(mode_id_str[1:], 16)
        elif mode_id_str.lower().startswith("0x"):
            return int(mode_id_str, 16)
        else:
            return int(mode_id_str)
    except ValueError:
        return None


def get_videocore_mode_id(width: int, height: int) -> int:
    """get the appropriate Videocore mode ID for a resolution"""
    mode_map = {
        (640, 480): ScreenModeID.VC_640x480.value,
        (800, 600): ScreenModeID.VC_800x600.value,
        (1024, 768): ScreenModeID.VC_1024x768.value,
        (1280, 720): ScreenModeID.VC_1280x720.value,
        (1920, 1080): ScreenModeID.VC_1920x1080.value,
        (720, 576): ScreenModeID.VC_720x576_PAL.value,
        (720, 480): ScreenModeID.VC_720x480_NTSC.value,
    }
    return mode_map.get((width, height), ScreenModeID.VC_640x480.value)


