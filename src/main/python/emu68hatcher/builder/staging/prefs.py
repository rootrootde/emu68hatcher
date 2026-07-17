"""Amiga prefs generation: wbpattern.prefs + Env-Archive defaults"""

from __future__ import annotations

import struct
from pathlib import Path

# AmigaOS IFF prefs PRHD: BYTE ph_Version + BYTE ph_Type + ULONG ph_Flags = 6 bytes.
_PRHD_BODY = b"\x00\x00\x00\x00\x00\x00"


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
    prhd_chunk = make_iff_chunk(b"PRHD", _PRHD_BODY)
    flags = 0x01 if backdrop else 0
    ptrn_data = struct.pack(">BB HH", wb_pattern, window_pattern, flags, 0)
    ptrn_chunk = make_iff_chunk(b"PTRN", ptrn_data)
    return make_iff_form(b"PREF", [prhd_chunk, ptrn_chunk])


def write_env_var(env_archive_dir: Path, name: str, value: str) -> None:
    """write an environment variable to Env-Archive"""
    var_path = env_archive_dir / name
    var_path.parent.mkdir(parents=True, exist_ok=True)
    var_path.write_text(value, encoding="iso-8859-1", newline="\n")


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
    """install default wbpattern.prefs + env vars (locale/input handled separately)"""
    prefs_dir.mkdir(parents=True, exist_ok=True)
    env_archive = prefs_dir / "Env-Archive"
    env_archive.mkdir(exist_ok=True)

    (prefs_dir / "wbpattern.prefs").write_bytes(generate_wbpattern_prefs())

    generate_default_env_vars(env_archive)
