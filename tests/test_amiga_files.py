"""tests for builder/amiga_files.py - path conversion and file mapping"""

from emu68hatcher.builder.amiga_files import unix_to_amiga_path


# =============================================================================
# unix_to_amiga_path
# =============================================================================


def test_already_amiga_path_unchanged():
    assert unix_to_amiga_path("DH0:C/Dir") == "DH0:C/Dir"


def test_strip_leading_dot_slash():
    assert unix_to_amiga_path("./C/Dir") == "C/Dir"


def test_strip_leading_slash():
    assert unix_to_amiga_path("/C/Dir") == "C/Dir"


def test_strip_multiple_leading_slashes():
    assert unix_to_amiga_path("///C/Dir") == "C/Dir"


def test_backslash_to_forward_slash():
    assert unix_to_amiga_path("C\\Libs\\test") == "C/Libs/test"


def test_plain_path_unchanged():
    assert unix_to_amiga_path("C/Dir") == "C/Dir"


def test_single_filename():
    assert unix_to_amiga_path("file.txt") == "file.txt"


def test_empty_path():
    assert unix_to_amiga_path("") == ""


def test_colon_in_path_keeps_original():
    # even with backslashes, colon means it's already Amiga-style
    assert unix_to_amiga_path("DH0:C\\Dir") == "DH0:C\\Dir"
