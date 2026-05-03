"""Amiga prefs generation: IFF binary (wbpattern, locale, input) + Env-Archive text"""

import struct
from pathlib import Path


def make_iff_chunk(chunk_id: bytes, data: bytes) -> bytes:
    """create an IFF chunk"""
    if len(data) % 2:
        data += b"\x00"
    return chunk_id + struct.pack(">I", len(data)) + data


def make_iff_form(form_type: bytes, chunks: list[bytes]) -> bytes:
    """create an IFF FORM container"""
    content = form_type + b"".join(chunks)
    if len(content) % 2:
        content += b"\x00"
    return b"FORM" + struct.pack(">I", len(content)) + content


def generate_wbpattern_prefs(
    wb_pattern: int = 0,
    window_pattern: int = 0,
    backdrop: bool = True,
) -> bytes:
    """generate WBPattern.prefs file content"""
    prhd_chunk = make_iff_chunk(b"PRHD", b"\x00\x00\x00\x00")
    flags = 0x01 if backdrop else 0
    ptrn_data = struct.pack(">BB HH", wb_pattern, window_pattern, flags, 0)
    ptrn_chunk = make_iff_chunk(b"PTRN", ptrn_data)
    return make_iff_form(b"PREF", [prhd_chunk, ptrn_chunk])


def generate_locale_prefs(
    country: str,
    language: str,
    gmt_offset: int = 0,
) -> bytes:
    """generate Locale.prefs file content"""
    country_bytes = country.encode("ascii")[:31].ljust(32, b"\x00")
    language_bytes = language.encode("ascii")[:29].ljust(30, b"\x00")
    prhd_chunk = make_iff_chunk(b"PRHD", b"\x00\x00\x00\x00")
    lcle_data = country_bytes + language_bytes + struct.pack(">h", gmt_offset)
    lcle_chunk = make_iff_chunk(b"LCLE", lcle_data)
    return make_iff_form(b"PREF", [prhd_chunk, lcle_chunk])


def generate_input_prefs(
    keymap: str,
    key_repeat_delay: int,
    key_repeat_speed: int,
    mouse_acceleration: int = 2,
) -> bytes:
    """generate Input.prefs file content"""
    keymap_bytes = keymap.encode("ascii")[:29].ljust(30, b"\x00")
    prhd_chunk = make_iff_chunk(b"PRHD", b"\x00\x00\x00\x00")
    inpt_data = keymap_bytes + struct.pack(
        ">HHH", key_repeat_delay, key_repeat_speed, mouse_acceleration
    )
    inpt_chunk = make_iff_chunk(b"INPT", inpt_data)
    return make_iff_form(b"PREF", [prhd_chunk, inpt_chunk])


def write_env_var(env_archive_dir: Path, name: str, value: str) -> None:
    """write an environment variable to Env-Archive"""
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


def install_default_prefs(prefs_dir: Path) -> None:
    """install default preference files (locale, input, pattern) + env vars"""
    prefs_dir.mkdir(parents=True, exist_ok=True)
    env_archive = prefs_dir / "Env-Archive"
    env_archive.mkdir(exist_ok=True)

    (prefs_dir / "locale.prefs").write_bytes(
        generate_locale_prefs(country="united_kingdom", language="english")
    )
    (prefs_dir / "input.prefs").write_bytes(
        generate_input_prefs(keymap="usa", key_repeat_delay=50, key_repeat_speed=10)
    )
    (prefs_dir / "wbpattern.prefs").write_bytes(generate_wbpattern_prefs())

    generate_default_env_vars(env_archive)
