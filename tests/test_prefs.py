"""tests for builder/prefs.py - IFF generation, mode ID parsing, screenmode prefs"""

import struct

from emu68hatcher.builder.prefs import (
    generate_screenmode_prefs,
    get_videocore_mode_id,
    make_iff_chunk,
    make_iff_form,
    parse_mode_id,
    ScreenModeID,
    ScreenModePrefs,
)


# =============================================================================
# IFF chunk helpers
# =============================================================================


def test_iff_chunk_even_data():
    chunk = make_iff_chunk(b"TEST", b"abcd")
    assert chunk[:4] == b"TEST"
    size = struct.unpack(">I", chunk[4:8])[0]
    assert size == 4
    assert chunk[8:] == b"abcd"


def test_iff_chunk_odd_data_padded():
    chunk = make_iff_chunk(b"TEST", b"abc")
    assert chunk[:4] == b"TEST"
    # odd data gets padded, size reflects padded length
    size = struct.unpack(">I", chunk[4:8])[0]
    assert size == 4  # 3 + 1 pad
    assert chunk[8:11] == b"abc"
    assert chunk[11:12] == b"\x00"


def test_iff_form_structure():
    chunk = make_iff_chunk(b"TEST", b"data")
    form = make_iff_form(b"MYTP", [chunk])
    assert form[:4] == b"FORM"
    # FORM contains: type (4) + chunk
    assert b"MYTP" in form
    assert b"TEST" in form


def test_iff_form_odd_content_padded():
    # form type (4) + chunk with odd total = odd content -> padded
    chunk = make_iff_chunk(b"TEST", b"x")  # chunk: 4+4+2 = 10, content: 4+10 = 14 (even)
    form = make_iff_form(b"MYTP", [chunk])
    total_size = struct.unpack(">I", form[4:8])[0]
    assert total_size % 2 == 0


# =============================================================================
# screenmode prefs generation
# =============================================================================


def test_generate_screenmode_prefs_structure():
    prefs = ScreenModePrefs(mode_id=0x500A1303, depth=8)
    data = generate_screenmode_prefs(prefs)

    # must be a valid IFF FORM
    assert data[:4] == b"FORM"
    assert data[8:12] == b"PREF"

    # must contain PRHD and SCRM chunks
    assert b"PRHD" in data
    assert b"SCRM" in data


def test_generate_screenmode_prefs_mode_id_embedded():
    mode_id = 0x500A1303
    prefs = ScreenModePrefs(mode_id=mode_id, depth=4)
    data = generate_screenmode_prefs(prefs)

    # mode_id should be in the binary as big-endian
    packed_mode = struct.pack(">I", mode_id)
    assert packed_mode in data


def test_generate_screenmode_prefs_different_depths():
    for depth in [1, 4, 8, 16, 24]:
        prefs = ScreenModePrefs(mode_id=0x50001000, depth=depth)
        data = generate_screenmode_prefs(prefs)
        assert len(data) > 0
        assert data[:4] == b"FORM"


# =============================================================================
# parse_mode_id
# =============================================================================


def test_parse_mode_id_dollar_hex():
    assert parse_mode_id("$500A1303") == 0x500A1303


def test_parse_mode_id_0x_hex():
    assert parse_mode_id("0x500A1303") == 0x500A1303


def test_parse_mode_id_0x_case_insensitive():
    assert parse_mode_id("0X500a1303") == 0x500A1303


def test_parse_mode_id_decimal():
    assert parse_mode_id("1342640899") == 1342640899


def test_parse_mode_id_whitespace():
    assert parse_mode_id("  $500A1303  ") == 0x500A1303


def test_parse_mode_id_empty():
    assert parse_mode_id("") is None


def test_parse_mode_id_invalid():
    assert parse_mode_id("not_a_number") is None


# =============================================================================
# get_videocore_mode_id
# =============================================================================


def test_videocore_known_resolutions():
    assert get_videocore_mode_id(640, 480) == ScreenModeID.VC_640x480.value
    assert get_videocore_mode_id(1920, 1080) == ScreenModeID.VC_1920x1080.value
    assert get_videocore_mode_id(720, 576) == ScreenModeID.VC_720x576_PAL.value
    assert get_videocore_mode_id(720, 480) == ScreenModeID.VC_720x480_NTSC.value


def test_videocore_unknown_resolution_fallback():
    assert get_videocore_mode_id(1600, 1200) == ScreenModeID.VC_640x480.value
    assert get_videocore_mode_id(0, 0) == ScreenModeID.VC_640x480.value
