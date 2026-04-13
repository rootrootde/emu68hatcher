"""tests for builder/script_injector.py - script injection and removal"""

from emu68hatcher.builder.script_injector import (
    _build_injection_block,
    write_amiga_script,
)
from pathlib import Path


# =============================================================================
# _build_injection_block
# =============================================================================


def test_injection_block_shell_markers():
    lines = ["Echo Hello"]
    block = _build_injection_block(lines, name="TestPkg", is_arexx=False)
    assert ";TestPkg - Added by Emu68 Hatcher - BEGIN" in block
    assert ";TestPkg - Added by Emu68 Hatcher - END" in block
    assert "Echo Hello" in block


def test_injection_block_arexx_markers():
    lines = ["say 'hello'"]
    block = _build_injection_block(lines, name="TestPkg", is_arexx=True)
    assert "TestPkg - Added by Emu68 Hatcher - BEGIN" in block
    assert "TestPkg - Added by Emu68 Hatcher - END" in block
    assert "/*" in block
    assert "*/" in block
    assert "say 'hello'" in block


def test_injection_block_no_name_no_markers():
    lines = ["Echo Hello"]
    block = _build_injection_block(lines, name="", is_arexx=False)
    # no markers, just the content
    assert block == ["Echo Hello"]


# =============================================================================
# write_amiga_script
# =============================================================================


def test_write_amiga_script_lf_only(tmp_path):
    dest = tmp_path / "test.script"
    write_amiga_script(dest, ["line1", "line2"])
    raw = dest.read_bytes()
    assert b"\r\n" not in raw
    assert b"\r" not in raw
    assert raw == b"line1\nline2\n"


def test_write_amiga_script_iso8859(tmp_path):
    dest = tmp_path / "test.script"
    # latin-1 char (umlaut)
    write_amiga_script(dest, ["Gr\u00fc\u00dfe"])
    raw = dest.read_bytes()
    assert raw == b"Gr\xfc\xdfe\n"
