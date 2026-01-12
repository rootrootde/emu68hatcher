"""tests for PiStorm hardware boot fixes

covers fixes discovered during first real Amiga 1200 + PiStorm boot:
- picasso96 version support for KS 3.2+
- failAt leak from OneTimeRun scripts via C:Execute
- HDToolbox IF EXISTS guards in Pi4vsPi3_Pistorm
- Startup-Sequence_UAEGFX persistent monitor swap (replaces OneTimeRun/UAEGFX_Setup)
- CheckScreenModeandChipset removed (we don't set screenmode.prefs.User)
- screenmode.prefs not forced (user picks on first boot)
- RexxMast injection fixes C:rx not found bug
"""

from pathlib import Path

import pytest


# --- Picasso96 version support ---

class TestPicasso96Versions:
    """picasso96 should be available for all Kickstart versions, not just 3.1."""

    def test_picasso96_available_for_31(self):
        from emu68hatcher.data.package_loader import get_packages_for_version
        names = [p.name for p in get_packages_for_version("3.1")]
        assert "picasso96" in names

    def test_picasso96_available_for_32(self):
        from emu68hatcher.data.package_loader import get_packages_for_version
        names = [p.name for p in get_packages_for_version("3.2")]
        assert "picasso96" in names

    def test_picasso96_available_for_3221(self):
        from emu68hatcher.data.package_loader import get_packages_for_version
        names = [p.name for p in get_packages_for_version("3.2.2.1")]
        assert "picasso96" in names

    def test_picasso96_available_for_323(self):
        from emu68hatcher.data.package_loader import get_packages_for_version
        names = [p.name for p in get_packages_for_version("3.2.3")]
        assert "picasso96" in names

    def test_picasso96_available_for_39(self):
        from emu68hatcher.data.package_loader import get_packages_for_version
        names = [p.name for p in get_packages_for_version("3.9")]
        assert "picasso96" in names

    def test_picasso96_is_default(self):
        from emu68hatcher.data.package_loader import get_default_packages
        names = [p.name for p in get_default_packages("3.2.3")]
        assert "picasso96" in names


# --- Picasso96Settings mandatory ---

class TestPicasso96SettingsMandatory:
    """picasso96Settings must be mandatory - without it, P96 has zero RTG mode definitions"""

    @pytest.mark.parametrize("ks_version", ["3.1", "3.2", "3.2.2.1", "3.2.3", "3.9"])
    def test_picasso96settings_is_mandatory(self, ks_version):
        from emu68hatcher.data.package_loader import get_mandatory_packages
        names = [p.name for p in get_mandatory_packages(ks_version)]
        assert "picasso96settings" in names, (
            f"picasso96settings must be mandatory for KS {ks_version} - "
            "without it, Picasso96 has no VideoCore RTG mode definitions"
        )


# --- FailAt leak fix ---

class TestFailAtLeak:
    """OneTimeRun scripts must not leak FailAt 10 via C:Execute"""

    def test_onetimerun_restores_failat_after_execute(self):
        """Startup-Sequence_OneTimeRun must restore FailAt 21 after C:Execute"""
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/S/Startup-Sequence_OneTimeRun"
        )
        content = script_path.read_text()
        lines = content.splitlines()

        # find the C:Execute T:RunTimeScript line
        execute_idx = None
        for i, line in enumerate(lines):
            if "C:Execute T:RunTimeScript" in line:
                execute_idx = i
                break

        assert execute_idx is not None, "Should have C:Execute T:RunTimeScript"

        # the very next non-empty line after Execute should restore FailAt 21
        for j in range(execute_idx + 1, min(execute_idx + 3, len(lines))):
            if lines[j].strip():
                assert "FailAt 21" in lines[j], (
                    f"FailAt 21 must be restored immediately after C:Execute "
                    f"(found '{lines[j].strip()}' instead)"
                )
                break

    def test_no_onetimerun_scripts_set_failat_10(self):
        """no OneTimeRun script should set FailAt 10 (it leaks via C:Execute)"""
        onetimerun_dir = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/OneTimeRun"
        )
        for script in onetimerun_dir.iterdir():
            if script.is_file() and not script.name.startswith("."):
                content = script.read_text()
                lines = [line.strip().lower() for line in content.splitlines()]
                assert "failat 10" not in lines, (
                    f"{script.name} must not set FailAt 10 - it leaks via C:Execute"
                )


# --- HDToolbox IF EXISTS guards ---

class TestPi4vsPi3Script:
    """pi4vsPi3_Pistorm should use IF EXISTS guards for optional files"""

    def _read_script(self):
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/OneTimeRun/Pi4vsPi3_Pistorm"
        )
        return script_path.read_text()

    def test_hdtoolbox_rename_guarded(self):
        """HDToolbox rename commands should be wrapped in IF EXISTS"""
        content = self._read_script()
        # every C:Rename for HDToolbox should be preceded by IF EXISTS
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "C:Rename" in line and "HDToolbox" in line:
                # check that there's an IF EXISTS guard above
                preceding = "\n".join(lines[max(0, i - 2) : i])
                assert "IF EXISTS" in preceding, (
                    f"HDToolbox Rename on line {i + 1} should be guarded by IF EXISTS"
                )

    def test_hdtoolbox_delete_guarded(self):
        """HDToolbox delete commands without >NIL: should be guarded"""
        content = self._read_script()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if (
                "C:Delete" in stripped
                and "HDToolbox" in stripped
                and ">NIL:" not in stripped
            ):
                # should be guarded by IF EXISTS
                preceding = "\n".join(lines[max(0, i - 2) : i])
                assert "IF EXISTS" in preceding, (
                    f"HDToolbox Delete on line {i + 1} should be guarded by IF EXISTS"
                )


# --- CheckScreenModeandChipset removed ---
# the screenmode chipset check required screenmode.prefs.User which we don't create
# the user picks their screenmode interactively on first boot instead


# --- ScreenModeSetup removed (deferred to second boot via OnetimeRunWB) ---

class TestScreenModeSetup:
    """ScreenModeSetup removed from OneTimeRunWB - logic moved to OnetimeRunWB sentinel"""

    def test_screenmode_setup_does_not_exist(self):
        """OneTimeRunWB/ScreenModeSetup should NOT exist (deferred to second boot)"""
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/OneTimeRunWB/ScreenModeSetup"
        )
        assert not script_path.exists(), (
            "ScreenModeSetup should be removed - ScreenMode prefs deferred to "
            "second boot via OnetimeRunWB SCREENMODESETUP sentinel"
        )

    def test_onetimerunwb_launches_screenmode_prefs(self):
        """onetimeRunWB should launch SYS:Prefs/ScreenMode on second boot"""
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/WBStartup/OnetimeRunWB"
        )
        content = script_path.read_text()
        assert "SYS:Prefs/ScreenMode" in content

    def test_onetimerun_package_installs_wb_scripts(self):
        """the onetimerun package should install OneTimeRunWB scripts"""
        from emu68hatcher.data.package_loader import get_package_by_name
        pkg = get_package_by_name("onetimerun")
        assert pkg is not None

        install_sources = [rule.source for rule in pkg.install]
        has_wb_scripts = any("OneTimeRunWB" in src for src in install_sources)
        assert has_wb_scripts, "onetimerun package should install OneTimeRunWB/* scripts"


class TestScreenModeDeferred:
    """ScreenMode prefs deferred to second boot via SCREENMODESETUP sentinel"""

    def _read_startup_onetimerun(self):
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/S/Startup-Sequence_OneTimeRun"
        )
        return script_path.read_text()

    def _read_onetimerunwb(self):
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/WBStartup/OnetimeRunWB"
        )
        return script_path.read_text()

    def test_sentinel_created_before_reboot(self):
        """Startup-Sequence_OneTimeRun should create SCREENMODESETUP sentinel before reboot"""
        content = self._read_startup_onetimerun()
        lines = content.splitlines()

        sentinel_idx = None
        reboot_idx = None
        for i, line in enumerate(lines):
            if "SCREENMODESETUP" in line and "TRUE" in line and "Echo" in line:
                sentinel_idx = i
            if "HARDRESET" in line or "C:Reboot" in line:
                reboot_idx = i

        assert sentinel_idx is not None, "Should write SCREENMODESETUP sentinel"
        assert reboot_idx is not None, "Should have reboot"
        assert sentinel_idx < reboot_idx, (
            "SCREENMODESETUP sentinel must be written before reboot"
        )

    def test_self_deletion_logic(self):
        """Startup-Sequence should schedule OnetimeRunWB deletion via OneTimeRun script"""
        content = self._read_startup_onetimerun()
        assert "DeleteOneTimeRunWB" in content, (
            "Should create a DeleteOneTimeRunWB script for self-cleanup"
        )

    def test_sentinel_checked_after_firstboot(self):
        """onetimeRunWB should check SCREENMODESETUP sentinel after FIRSTTIMEBOOTWB block"""
        content = self._read_onetimerunwb()
        assert "$SCREENMODESETUP" in content, "Should check SCREENMODESETUP sentinel"
        assert "SYS:Prefs/ScreenMode" in content, "Should launch ScreenMode prefs"

    def test_sentinel_cleared_before_screenmode(self):
        """sentinel should be set to FALSE before launching ScreenMode prefs"""
        content = self._read_onetimerunwb()
        lines = content.splitlines()

        clear_idx = None
        prefs_idx = None
        for i, line in enumerate(lines):
            if "SCREENMODESETUP" in line and "FALSE" in line:
                clear_idx = i
            if "SYS:Prefs/ScreenMode" in line:
                prefs_idx = i

        assert clear_idx is not None, "Should clear SCREENMODESETUP sentinel"
        assert prefs_idx is not None, "Should launch SYS:Prefs/ScreenMode"
        assert clear_idx < prefs_idx, (
            "Sentinel must be cleared before launching ScreenMode prefs"
        )


class TestCmdlineBAK:
    """cmdlineBAK.txt generation and Cmdline script IF EXISTS guard"""

    def test_cmdlinebak_generated_for_first_boot(self, tmp_path):
        """generate_boot_partition_files should create cmdlineBAK.txt when first_boot=True"""
        from emu68hatcher.builder.script_generator import generate_boot_partition_files

        generate_boot_partition_files(
            tmp_path, kickstart_version="3.2.3", first_boot=True,
        )

        bak = tmp_path / "EMU68BOOT" / "cmdlineBAK.txt"
        assert bak.exists(), "cmdlineBAK.txt should be generated for first boot"

        content = bak.read_text()
        assert "buptest" not in content, "cmdlineBAK.txt should NOT contain buptest"
        assert "bupiter" not in content, "cmdlineBAK.txt should NOT contain bupiter"
        assert "sd.low_speed" in content, "cmdlineBAK.txt should contain base params"

    def test_cmdlinebak_not_generated_for_normal_boot(self, tmp_path):
        """generate_boot_partition_files should NOT create cmdlineBAK.txt when first_boot=False"""
        from emu68hatcher.builder.script_generator import generate_boot_partition_files

        generate_boot_partition_files(
            tmp_path, kickstart_version="3.1", first_boot=False,
        )

        bak = tmp_path / "EMU68BOOT" / "cmdlineBAK.txt"
        assert not bak.exists(), "cmdlineBAK.txt should NOT exist for non-first-boot"

    def test_cmdline_script_has_if_exists_guard(self):
        """cmdline OneTimeRunWB script should guard rename with IF EXISTS"""
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/OneTimeRunWB/Cmdline"
        )
        content = script_path.read_text()
        assert "IF EXISTS EMU68BOOT:cmdlineBAK.txt" in content, (
            "Cmdline script should check IF EXISTS before renaming cmdlineBAK.txt"
        )


# --- SD0 mount before IF EXISTS ---

class TestSD0MountBeforeAccess:
    """SD0 must be explicitly mounted before IF EXISTS SD0: check"""

    def _read_script(self):
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/S/Startup-Sequence_OneTimeRun"
        )
        return script_path.read_text()

    def test_mount_sd0_exists(self):
        """SD0 is mounted by the stock Startup-Sequence Mount command, not our script.
        our script only assigns EMU68BOOT: to SD0: if SD0 exists"""
        content = self._read_script()
        assert "Assign" in content and "EXISTS SD0:" in content, (
            "Should check if SD0 is assigned before using it"
        )
        assert "EMU68BOOT:" in content and "SD0:" in content, (
            "Should assign EMU68BOOT: to SD0:"
        )

    def test_mount_sd0_checks_already_mounted(self):
        """SD0 assign check uses Assign EXISTS (silent) not IF EXISTS (triggers requester)"""
        content = self._read_script()
        assert "Assign >NIL: EXISTS SD0:" in content, (
            "SD0 check should use Assign EXISTS (silent)"
        )

    def test_mount_sd0_before_if_exists_sd0(self):
        """SD0 assign check must appear before EMU68BOOT assign"""
        content = self._read_script()
        lines = content.splitlines()

        check_idx = None
        assign_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(";"):
                continue
            if "Assign >NIL: EXISTS SD0:" in line and check_idx is None:
                check_idx = i
            if "EMU68BOOT:" in line and "SD0:" in line and assign_idx is None:
                assign_idx = i

        assert check_idx is not None, "Should have SD0 existence check"
        assert assign_idx is not None, "Should have EMU68BOOT: assign"
        assert check_idx < assign_idx, (
            "SD0 check must come before EMU68BOOT assign"
        )

    def test_mount_sd0_pistorm_only(self):
        """SD0/EMU68BOOT assign should be guarded by IF NOT $SYSTEM EQ UAE"""
        content = self._read_script()
        lines = content.splitlines()

        for i, line in enumerate(lines):
            if line.strip().startswith(";"):
                continue
            if "C:Assign" in line and "EMU68BOOT:" in line and "SD0:" in line:
                preceding = "\n".join(lines[max(0, i - 5) : i])
                assert 'NOT $SYSTEM EQ "UAE"' in preceding, (
                    "EMU68BOOT assign should only happen in PiStorm mode, not UAE"
                )
                break



# --- Picasso96 BOARDTYPE tooltypes ---

class TestInfoTooltypeParser:
    """amiga .info file tooltype parser/writer"""

    def _make_minimal_info(self, tooltypes=None):
        """create a minimal valid .info file with optional tooltypes"""
        import struct

        # DiskObject header (78 bytes)
        header = bytearray(78)
        struct.pack_into(">H", header, 0, 0xE310)  # magic
        struct.pack_into(">H", header, 2, 1)  # version
        # gadget: set Width=32, Height=16 (for a 32x16x1 icon)
        struct.pack_into(">h", header, 12, 32)  # width
        struct.pack_into(">h", header, 14, 16)  # height
        struct.pack_into(">I", header, 22, 1)  # GadgetRender (non-zero = image follows)
        header[48] = 3  # do_Type = TOOL

        # image struct (20 bytes) + pixel data
        image = bytearray(20)
        struct.pack_into(">H", image, 4, 32)  # width
        struct.pack_into(">H", image, 6, 16)  # height
        struct.pack_into(">H", image, 8, 1)   # depth
        struct.pack_into(">I", image, 10, 1)  # ImageData ptr (non-zero)
        pixel_data = bytes(((32 + 15) // 16) * 2 * 16 * 1)  # 64 bytes

        data = bytes(header) + bytes(image) + pixel_data

        if tooltypes:
            # set ToolTypes pointer to non-zero
            header_mut = bytearray(data[:78])
            struct.pack_into(">I", header_mut, 54, 1)
            data = bytes(header_mut) + data[78:]

            # append tooltype section: pointer array size + length-prefixed strings
            ptr_array_size = (len(tooltypes) + 1) * 4
            tt_section = struct.pack(">I", ptr_array_size)
            for tt in tooltypes:
                tt_bytes = tt.encode("iso-8859-1") + b"\x00"
                tt_section += struct.pack(">I", len(tt_bytes)) + tt_bytes
            data += tt_section

        return data

    def test_read_empty_tooltypes(self, tmp_path):
        """read .info with no tooltypes returns empty list"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes

        info_file = tmp_path / "test.info"
        info_file.write_bytes(self._make_minimal_info())
        assert read_info_tooltypes(info_file) == []

    def test_read_tooltypes(self, tmp_path):
        """read .info with tooltypes returns them correctly"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes

        original = ["BOARDTYPE=Videocore", "SOFTSPRITE=Yes"]
        info_file = tmp_path / "test.info"
        info_file.write_bytes(self._make_minimal_info(tooltypes=original))
        assert read_info_tooltypes(info_file) == original

    def test_write_tooltypes_roundtrip(self, tmp_path):
        """write tooltypes and read them back"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes, write_info_tooltypes

        info_file = tmp_path / "test.info"
        info_file.write_bytes(self._make_minimal_info())

        new_tt = ["BOARDTYPE=Videocore", "SETTINGSFILE=SYS:DEVS/Picasso96Settings"]
        write_info_tooltypes(info_file, new_tt)
        assert read_info_tooltypes(info_file) == new_tt

    def test_write_replaces_existing_tooltypes(self, tmp_path):
        """writing new tooltypes replaces old ones completely"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes, write_info_tooltypes

        original = ["OLD_KEY=old_value", "ANOTHER=thing"]
        info_file = tmp_path / "test.info"
        info_file.write_bytes(self._make_minimal_info(tooltypes=original))

        new_tt = ["BOARDTYPE=Videocore"]
        write_info_tooltypes(info_file, new_tt)
        result = read_info_tooltypes(info_file)
        assert result == new_tt
        assert "OLD_KEY=old_value" not in result

    def test_write_to_empty_info(self, tmp_path):
        """write tooltypes to .info that had none (ToolTypes pointer was 0)"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes, write_info_tooltypes

        info_file = tmp_path / "test.info"
        info_file.write_bytes(self._make_minimal_info())  # no tooltypes
        assert read_info_tooltypes(info_file) == []

        write_info_tooltypes(info_file, ["BOARDTYPE=Videocore"])
        assert read_info_tooltypes(info_file) == ["BOARDTYPE=Videocore"]

    def test_invalid_magic_raises(self, tmp_path):
        """non-.info file should raise ValueError"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes

        info_file = tmp_path / "test.info"
        info_file.write_bytes(b"\x00" * 100)

        import pytest
        with pytest.raises(ValueError, match="Not an Amiga .info file"):
            read_info_tooltypes(info_file)

    def test_file_too_small_raises(self, tmp_path):
        """file smaller than header should raise ValueError"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes

        info_file = tmp_path / "test.info"
        info_file.write_bytes(b"\xE3\x10" + b"\x00" * 10)

        import pytest
        with pytest.raises(ValueError, match="too small"):
            read_info_tooltypes(info_file)

    def test_reads_real_info_files(self):
        """parser should handle the bundled .info files without crashing"""
        from emu68hatcher.builder.amiga_files import read_info_tooltypes

        local_pkg = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages"
        )
        info_files = list(local_pkg.rglob("*.info"))
        assert len(info_files) > 0, "Should find bundled .info files"

        for info_file in info_files:
            # should not raise
            tooltypes = read_info_tooltypes(info_file)
            assert isinstance(tooltypes, list)


class TestInfoTooltypeBinaryFormat:
    """verify .info tooltype binary format matches Amiga DiskObject spec"""

    def test_pointer_array_size_dword(self, tmp_path):
        """first DWORD of tooltype section must be (num_entries + 1) * 4"""
        import struct
        from emu68hatcher.builder.amiga_files import write_info_tooltypes

        # create minimal .info
        header = bytearray(78)
        struct.pack_into(">H", header, 0, 0xE310)
        struct.pack_into(">H", header, 2, 1)
        struct.pack_into(">h", header, 12, 16)
        struct.pack_into(">h", header, 14, 8)
        struct.pack_into(">I", header, 22, 1)
        header[48] = 3
        image = bytearray(20)
        struct.pack_into(">H", image, 4, 16)
        struct.pack_into(">H", image, 6, 8)
        struct.pack_into(">H", image, 8, 1)
        struct.pack_into(">I", image, 10, 1)
        pixel_data = bytes(((16 + 15) // 16) * 2 * 8 * 1)

        info_file = tmp_path / "test.info"
        info_file.write_bytes(bytes(header) + bytes(image) + pixel_data)

        tooltypes = ["BOARDTYPE=Videocore", "SOFTSPRITE=Yes"]
        write_info_tooltypes(info_file, tooltypes)

        data = info_file.read_bytes()
        # tooltype section starts after header + image + pixel data
        tt_offset = 78 + 20 + len(pixel_data)
        ptr_array_size = struct.unpack(">I", data[tt_offset:tt_offset + 4])[0]
        expected = (len(tooltypes) + 1) * 4  # pointers + NULL terminator
        assert ptr_array_size == expected, (
            f"Pointer array size should be {expected}, got {ptr_array_size}"
        )


class TestVideocoreTooltypes:
    """configure stage must set BOARDTYPE on Videocore.info for P96 RTG"""

    def test_videocore_tooltypes_has_boardtype(self):
        """VIDEOCORE_TOOLTYPES must include BOARDTYPE=Videocore"""
        from emu68hatcher.builder.stages.configure import VIDEOCORE_TOOLTYPES
        assert "BOARDTYPE=Videocore" in VIDEOCORE_TOOLTYPES

    def test_videocore_tooltypes_has_settingsfile(self):
        """VIDEOCORE_TOOLTYPES must include SETTINGSFILE"""
        from emu68hatcher.builder.stages.configure import VIDEOCORE_TOOLTYPES
        assert any(tt.startswith("SETTINGSFILE=") for tt in VIDEOCORE_TOOLTYPES)

    def test_uaegfx_tooltypes_has_boardtype(self):
        """UAEGFX_TOOLTYPES must include BOARDTYPE=uaegfx"""
        from emu68hatcher.builder.stages.configure import UAEGFX_TOOLTYPES
        assert "BOARDTYPE=uaegfx" in UAEGFX_TOOLTYPES

    def test_configure_sets_videocore_tooltypes(self, tmp_path):
        """_configure_videocore_tooltypes should write BOARDTYPE to Videocore.info."""
        import struct
        from unittest.mock import MagicMock
        from emu68hatcher.builder.amiga_files import read_info_tooltypes
        from emu68hatcher.builder.stages.configure import _configure_videocore_tooltypes

        # create a minimal Videocore.info in the expected location
        monitors_dir = tmp_path / "Devs" / "Monitors"
        monitors_dir.mkdir(parents=True)
        info_file = monitors_dir / "Videocore.info"

        # minimal .info: header + image (no tooltypes, like the real Picasso96.info)
        header = bytearray(78)
        struct.pack_into(">H", header, 0, 0xE310)
        struct.pack_into(">H", header, 2, 1)
        struct.pack_into(">h", header, 12, 16)
        struct.pack_into(">h", header, 14, 8)
        struct.pack_into(">I", header, 22, 1)  # has image
        header[48] = 3
        image = bytearray(20)
        struct.pack_into(">H", image, 4, 16)
        struct.pack_into(">H", image, 6, 8)
        struct.pack_into(">H", image, 8, 1)
        struct.pack_into(">I", image, 10, 1)
        pixel_data = bytes(((16 + 15) // 16) * 2 * 8 * 1)
        info_file.write_bytes(bytes(header) + bytes(image) + pixel_data)

        # verify no tooltypes initially
        assert read_info_tooltypes(info_file) == []

        # run the configure function
        mock_workflow = MagicMock()
        _configure_videocore_tooltypes(mock_workflow, tmp_path)

        # verify BOARDTYPE is now set
        tooltypes = read_info_tooltypes(info_file)
        assert "BOARDTYPE=Videocore" in tooltypes
        assert any(tt.startswith("SETTINGSFILE=") for tt in tooltypes)


# --- Startup-Sequence_UAEGFX persistent injection ---

class TestStartupSequenceUAEGFX:
    """Startup-Sequence_UAEGFX persistent injection should swap monitors cleanly"""

    def _read_script(self):
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/S/Startup-Sequence_UAEGFX"
        )
        return script_path.read_text()

    def test_uaegfx_setup_no_longer_in_onetimerun(self):
        """UAEGFX_Setup should not exist in OneTimeRun (now a persistent S/ injection)"""
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/OneTimeRun/UAEGFX_Setup"
        )
        assert not script_path.exists(), (
            "UAEGFX_Setup should be removed from OneTimeRun - "
            "replaced by persistent Startup-Sequence_UAEGFX injection"
        )

    def test_no_screenmode_user_reference(self):
        """Startup-Sequence_UAEGFX should not reference screenmode.prefs.User."""
        content = self._read_script()
        assert "screenmode.prefs.user" not in content.lower(), (
            "Startup-Sequence_UAEGFX should not reference screenmode.prefs.User "
            "(file no longer created)"
        )

    def test_no_screenmode_native_reference(self):
        """Startup-Sequence_UAEGFX should not reference screenmode.prefs.Native"""
        content = self._read_script()
        assert "screenmode.prefs.native" not in content.lower(), (
            "Startup-Sequence_UAEGFX should not reference screenmode.prefs.Native "
            "(file no longer created)"
        )

    def test_no_screenmodeChipset_reference(self):
        """Startup-Sequence_UAEGFX should not reference ScreenModeChipset env var"""
        content = self._read_script()
        assert "ScreenModeChipset" not in content, (
            "Startup-Sequence_UAEGFX should not reference ScreenModeChipset "
            "(env var no longer created)"
        )

    def test_still_swaps_monitor_drivers(self):
        """Startup-Sequence_UAEGFX should swap Videocore/UAEGFX monitor drivers"""
        content = self._read_script()
        assert "Devs:Monitors/Videocore" in content
        assert "Devs:Monitors/Uaegfx" in content
        assert "Storage/Monitors/" in content

    def test_sets_failat_21(self):
        """Startup-Sequence_UAEGFX should set FailAt 21 at start (tolerant of warnings)"""
        content = self._read_script()
        first_line = content.strip().splitlines()[0].strip().lower()
        assert "failat 21" in first_line, (
            "Startup-Sequence_UAEGFX must set FailAt 21 at start "
            "(monitor copy commands can return non-zero)"
        )


# --- Configure stage: no screenmode.prefs override ---

class TestConfigureNoScreenmodeOverride:
    """configure stage should not generate screenmode.prefs (user picks on first boot)"""

    def test_install_default_prefs_no_screenmode(self, tmp_path):
        """install_default_prefs with screen_mode=None should not write screenmode.prefs"""
        from emu68hatcher.builder.prefs import (
            install_default_prefs,
            LocalePrefs,
            InputPrefs,
            WBPatternPrefs,
        )

        prefs_dir = tmp_path / "Prefs"
        prefs_dir.mkdir()

        install_default_prefs(
            prefs_dir,
            screen_mode=None,
            locale=LocalePrefs(country="united_kingdom", language="english"),
            input_prefs=InputPrefs(keymap="usa"),
            wb_pattern=WBPatternPrefs(backdrop=True),
        )

        # should NOT create screenmode.prefs
        assert not (prefs_dir / "screenmode.prefs").exists()
        assert not (prefs_dir / "Env-Archive" / "Sys" / "screenmode.prefs").exists()

    def test_no_screenmode_support_files(self, tmp_path):
        """configure should not create .User/.Native/ScreenModeChipset files"""
        from emu68hatcher.builder.prefs import (
            install_default_prefs,
            LocalePrefs,
            InputPrefs,
            WBPatternPrefs,
        )

        prefs_dir = tmp_path / "Prefs"
        prefs_dir.mkdir()

        install_default_prefs(
            prefs_dir,
            screen_mode=None,
            locale=LocalePrefs(country="united_kingdom", language="english"),
            input_prefs=InputPrefs(keymap="usa"),
            wb_pattern=WBPatternPrefs(backdrop=True),
        )

        env_sys = prefs_dir / "Env-Archive" / "Sys"
        env_archive = prefs_dir / "Env-Archive"

        # none of these should exist
        if env_sys.exists():
            assert not (env_sys / "screenmode.prefs.User").exists()
            assert not (env_sys / "screenmode.prefs.Native").exists()
        if env_archive.exists():
            assert not (env_archive / "ScreenModeChipset").exists()


# --- RexxMast injection ---

class TestRexxMastInjection:
    """RexxMast injection must exist to fix 'C:rx not found' bug"""

    def test_rexxmast_script_exists(self):
        """Startup-Sequence_REXXMAST should exist in S/"""
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/S/Startup-Sequence_REXXMAST"
        )
        assert script_path.exists()

    def test_rexxmast_starts_rexxmast(self):
        """Startup-Sequence_REXXMAST should start RexxMast"""
        script_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System/S/Startup-Sequence_REXXMAST"
        )
        content = script_path.read_text()
        assert "RexxMast" in content

    def test_rexxmast_in_injections(self):
        """STARTUP_SEQUENCE_INJECTIONS should include RexxMast"""
        from emu68hatcher.builder.script_injector import STARTUP_SEQUENCE_INJECTIONS
        names = [inj.name for inj in STARTUP_SEQUENCE_INJECTIONS]
        assert "RexxMast" in names

    def test_uaegfx_in_injections(self):
        """STARTUP_SEQUENCE_INJECTIONS should include UAEGFX Monitor Swap"""
        from emu68hatcher.builder.script_injector import STARTUP_SEQUENCE_INJECTIONS
        names = [inj.name for inj in STARTUP_SEQUENCE_INJECTIONS]
        assert "UAEGFX Monitor Swap" in names

    def test_progressbar_removed(self):
        """ProgressBar.rexx should be removed (was REXX, needed rexxtricks.library)"""
        for name in ("ProgressBar.rexx", "ProgressBar"):
            script_path = (
                Path(__file__).parent.parent
                / "src/main/python/emu68hatcher/data/local_packages/System/S"
                / name
            )
            assert not script_path.exists(), f"{name} should be removed"


# --- configure.py has_picasso96 fix ---

class TestHasPicasso96NoHack:
    """configure.py should not have 'or True' hack for has_picasso96"""

    def test_no_or_true_hack(self):
        """the 'or True' hack for has_picasso96 should be removed"""
        configure_path = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/builder/stages/configure.py"
        )
        content = configure_path.read_text()
        assert "or True" not in content, (
            "configure.py should not have 'or True' hack - "
            "picasso96 is now available for all KS versions"
        )


# --- Screen modes YAML ---

class TestScreenModesYAML:
    """screen mode definitions should include 1920x1200"""

    def test_1920x1200_mode_exists(self):
        from emu68hatcher.data.data_manager import load_yaml_data
        modes = load_yaml_data("screen_modes")
        names = [m["name"] for m in modes]
        assert "1920*1200-60" in names

    def test_1920x1200_hdmi_settings(self):
        from emu68hatcher.data.data_manager import load_yaml_data
        modes = load_yaml_data("screen_modes")
        mode = next(m for m in modes if m["name"] == "1920*1200-60")
        assert mode["hdmi_group"] == 2
        assert mode["hdmi_mode"] == 68
        assert mode["width"] == 1920
        assert mode["height"] == 1200


# --- Multi-variant PiStorm boot ---

class TestMultiVariantBoot:
    """all PiStorm variants (pistorm32lite, pistorm, pistorm16) should be downloaded"""

    def _mock_github_release(self, asset_names):
        """create a mock GitHub release response with the given asset filenames"""
        assets = []
        for name in asset_names:
            assets.append({
                "name": name,
                "browser_download_url": f"https://github.com/michalsc/Emu68/releases/download/v1.0/{name}",
            })
        return {"assets": assets}

    def test_get_emu68_boot_files_returns_all_variants(self):
        """get_emu68_boot_files should return items for all available variants"""
        import json
        from unittest.mock import patch, MagicMock
        from emu68hatcher.builder.downloads import get_emu68_boot_files

        release = self._mock_github_release([
            "Emu68-pistorm32lite.zip",
            "Emu68-pistorm.zip",
            "Emu68-pistorm16.zip",
            "other-file.txt",
        ])

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(release).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            items = get_emu68_boot_files()

        names = [i.name for i in items]
        assert "emu68_boot" in names
        assert "emu68_boot_pistorm" in names
        assert "emu68_boot_pistorm16" in names
        assert len(items) == 3

    def test_primary_variant_is_required(self):
        """the pistorm32lite variant should not be optional"""
        import json
        from unittest.mock import patch, MagicMock
        from emu68hatcher.builder.downloads import get_emu68_boot_files

        release = self._mock_github_release([
            "Emu68-pistorm32lite.zip",
            "Emu68-pistorm.zip",
        ])

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(release).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            items = get_emu68_boot_files()

        primary = next(i for i in items if i.name == "emu68_boot")
        assert not primary.optional

    def test_secondary_variants_are_optional(self):
        """the pistorm and pistorm16 variants should be optional"""
        import json
        from unittest.mock import patch, MagicMock
        from emu68hatcher.builder.downloads import get_emu68_boot_files

        release = self._mock_github_release([
            "Emu68-pistorm32lite.zip",
            "Emu68-pistorm.zip",
            "Emu68-pistorm16.zip",
        ])

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(release).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            items = get_emu68_boot_files()

        pistorm = next(i for i in items if i.name == "emu68_boot_pistorm")
        assert pistorm.optional
        pistorm16 = next(i for i in items if i.name == "emu68_boot_pistorm16")
        assert pistorm16.optional

    def test_missing_optional_variant_handled_gracefully(self):
        """missing pistorm16 should not prevent returning other items"""
        import json
        from unittest.mock import patch, MagicMock
        from emu68hatcher.builder.downloads import get_emu68_boot_files

        release = self._mock_github_release([
            "Emu68-pistorm32lite.zip",
            "Emu68-pistorm.zip",
            # no Emu68-pistorm16.zip
        ])

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(release).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            items = get_emu68_boot_files()

        names = [i.name for i in items]
        assert "emu68_boot" in names
        assert "emu68_boot_pistorm" in names
        assert "emu68_boot_pistorm16" not in names
        assert len(items) == 2

    def test_exact_filename_matching(self):
        """emu68-pistorm.zip must not match Emu68-pistorm32lite.zip."""
        import json
        from unittest.mock import patch, MagicMock
        from emu68hatcher.builder.downloads import get_emu68_boot_files

        release = self._mock_github_release([
            "Emu68-pistorm32lite.zip",
            # only pistorm32lite - pistorm.zip NOT present
        ])

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(release).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            items = get_emu68_boot_files()

        names = [i.name for i in items]
        assert "emu68_boot" in names
        # pistorm32lite.zip should NOT also match as emu68_boot_pistorm
        assert "emu68_boot_pistorm" not in names


class TestMultiVariantKernelMerge:
    """configure stage should merge kernels from multiple extracted variant dirs"""

    def test_kernels_copied_from_all_variants(self, tmp_path):
        """kernels from pistorm and pistorm16 variants should be copied"""
        from emu68hatcher.builder.stages.configure import _ensure_pistorm16_kernel

        boot_dir = tmp_path / "EMU68BOOT"
        boot_dir.mkdir()

        # simulate primary variant files
        (boot_dir / "bootcode.bin").write_bytes(b"boot")
        (boot_dir / "start.elf").write_bytes(b"start")
        (boot_dir / "Emu68-pistorm32lite.img").write_bytes(b"ps32lite")
        (boot_dir / "Emu68-pistorm.img").write_bytes(b"pistorm")

        # no pistorm16 kernel - should be copied from pistorm
        _ensure_pistorm16_kernel(boot_dir, _MockLogger())

        assert (boot_dir / "Emu68-pistorm16.img").exists()
        assert (boot_dir / "Emu68-pistorm16.img").read_bytes() == b"pistorm"

    def test_pistorm16_not_overwritten_if_exists(self, tmp_path):
        """if pistorm16 kernel already exists, it should not be overwritten"""
        from emu68hatcher.builder.stages.configure import _ensure_pistorm16_kernel

        boot_dir = tmp_path / "EMU68BOOT"
        boot_dir.mkdir()

        (boot_dir / "Emu68-pistorm.img").write_bytes(b"pistorm")
        (boot_dir / "Emu68-pistorm16.img").write_bytes(b"real_ps16")

        _ensure_pistorm16_kernel(boot_dir, _MockLogger())

        # should keep the real pistorm16, not overwrite with pistorm
        assert (boot_dir / "Emu68-pistorm16.img").read_bytes() == b"real_ps16"

    def test_no_pistorm_kernel_no_fallback(self, tmp_path):
        """if no pistorm kernel exists, pistorm16 fallback should not be created"""
        from emu68hatcher.builder.stages.configure import _ensure_pistorm16_kernel

        boot_dir = tmp_path / "EMU68BOOT"
        boot_dir.mkdir()

        (boot_dir / "Emu68-pistorm32lite.img").write_bytes(b"ps32lite")

        _ensure_pistorm16_kernel(boot_dir, _MockLogger())

        assert not (boot_dir / "Emu68-pistorm16.img").exists()

    def test_pistorm32lite_not_mistaken_for_pistorm(self, tmp_path):
        """emu68-pistorm32lite should NOT be used as pistorm fallback for pistorm16"""
        from emu68hatcher.builder.stages.configure import _ensure_pistorm16_kernel

        boot_dir = tmp_path / "EMU68BOOT"
        boot_dir.mkdir()

        # only pistorm32lite - no pistorm or pistorm16
        (boot_dir / "Emu68-pistorm32lite.img").write_bytes(b"ps32lite")

        _ensure_pistorm16_kernel(boot_dir, _MockLogger())

        assert not (boot_dir / "Emu68-pistorm16.img").exists()


class TestMountRedirectDoesNotEatScript:
    """mount redirect Remove must only remove the Mount line, not everything after it"""

    def test_single_line_remove_preserves_subsequent_lines(self):
        from emu68hatcher.builder.script_injector import _action_remove
        original = [
            "BindDrivers",
            "Mount DEVS:DOSDrivers/~(#?.info)",
            "LoadMonDrvs >NIL:",
            "IPrefs",
            "LoadWB",
        ]
        result = _action_remove(
            original,
            r"^Mount DEVS:DOSDrivers",
            r"^Mount DEVS:DOSDrivers",
            "Mount redirect",
        )
        # mount line should be removed (replaced by comment)
        assert any("Section Removed" in line for line in result)
        assert not any("Mount DEVS:DOSDrivers" in line for line in result
                       if "Removed" not in line)
        # lines after Mount must survive
        assert "LoadMonDrvs >NIL:" in result
        assert "IPrefs" in result
        assert "LoadWB" in result

    def test_full_injection_preserves_loadwb(self, tmp_path):
        """apply all Startup-Sequence injections and verify LoadWB survives"""
        from emu68hatcher.builder.script_injector import (
            apply_standard_injections,
            read_amiga_script,
        )
        from pathlib import Path

        # minimal WB 3.2.3-ish Startup-Sequence
        startup = tmp_path / "S" / "Startup-Sequence"
        startup.parent.mkdir(parents=True)
        startup.write_text(
            "FailAt 21\n"
            "SetPatch >NIL:\n"
            "BindDrivers\n"
            "Mount DEVS:DOSDrivers/~(#?.info)\n"
            "LoadMonDrvs >NIL:\n"
            "IPrefs\n"
            "LoadWB\n"
            "EndCLI >NIL:\n",
            encoding="iso-8859-1",
        )
        user_startup = tmp_path / "S" / "User-Startup"
        user_startup.write_text("", encoding="iso-8859-1")

        content_base = (
            Path(__file__).parent.parent
            / "src/main/python/emu68hatcher/data/local_packages/System"
        )
        apply_standard_injections(tmp_path, content_base, {"roadshow", "picasso96"})

        lines = read_amiga_script(startup)
        assert any("LoadWB" in line for line in lines), (
            "LoadWB must survive all injections"
        )
        assert any("LoadMonDrvs" in line for line in lines), (
            "LoadMonDrvs must survive all injections"
        )


class _MockLogger:
    """minimal mock logger for tests"""
    def info(self, msg): pass
    def debug(self, msg): pass
    def warning(self, msg): pass
