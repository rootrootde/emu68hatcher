"""tests for HST Imager command generation"""

from pathlib import Path

import pytest


class TestBlankImageCommand:
    """tests for blank image creation commands"""

    def test_generate_blank_command(self):
        """test generating a blank image command"""
        from emu68hatcher.builder.hst_commands import (
            generate_blank_image_command,
            HSTCommand,
        )

        cmd = generate_blank_image_command(Path("/tmp/test.img"), 8 * 1024**3)

        assert cmd is not None
        assert cmd.command == HSTCommand.BLANK
        assert "/tmp/test.img" in cmd.args
        assert str(8 * 1024**3) in cmd.args

    def test_blank_command_format(self):
        """test blank command has correct format"""
        from emu68hatcher.builder.hst_commands import generate_blank_image_command

        cmd = generate_blank_image_command(Path("/output/amiga.img"), 4 * 1024**3)

        # convert to args list
        args = cmd.to_args()
        assert args[0] == "blank"


class TestMBRCommands:
    """tests for MBR partition commands"""

    def test_mbr_init_command(self):
        """test MBR initialization command"""
        from emu68hatcher.builder.hst_commands import (
            generate_mbr_init_command,
            HSTCommand,
        )

        cmd = generate_mbr_init_command(Path("/tmp/test.img"))

        assert cmd.command == HSTCommand.MBR_INIT
        assert "/tmp/test.img" in cmd.args

    def test_mbr_partition_commands(self):
        """test MBR partition add commands"""
        from emu68hatcher.builder.hst_commands import (
            generate_mbr_partition_commands,
            HSTCommand,
        )
        from emu68hatcher.config.schema import MBRPartition, AmigaPartition, Filesystem

        partitions = [
            MBRPartition(type="fat32", name="EMU68BOOT", size=512 * 1024**2, amiga_partitions=None),
            MBRPartition(
                type="id76",
                name="AMIGA",
                size=8 * 1024**3,
                amiga_partitions=[
                    AmigaPartition(
                        device="SDH0",
                        volume="Workbench",
                        filesystem=Filesystem.PFS3,
                        size=2 * 1024**3,
                        bootable=True,
                    )
                ],
            ),
        ]

        commands = generate_mbr_partition_commands(Path("/tmp/test.img"), partitions)

        assert len(commands) >= 2
        # at least one should be MBR_PART_ADD
        assert any(cmd.command == HSTCommand.MBR_PART_ADD for cmd in commands)


class TestRDBCommands:
    """tests for RDB (Rigid Disk Block) commands"""

    def test_rdb_init_command(self):
        """test RDB initialization command"""
        from emu68hatcher.builder.hst_commands import (
            generate_rdb_init_command,
            HSTCommand,
        )

        cmd = generate_rdb_init_command(Path("/tmp/test.img"), 2)

        assert cmd.command == HSTCommand.RDB_INIT
        # path should include mbr partition reference
        assert any("mbr" in arg.lower() or "/2" in arg for arg in cmd.args)

    def test_rdb_filesystem_command(self):
        """test adding filesystem to RDB"""
        from emu68hatcher.builder.hst_commands import (
            generate_rdb_filesystem_command,
            HSTCommand,
        )
        from emu68hatcher.config.schema import Filesystem

        cmd = generate_rdb_filesystem_command(
            Path("/tmp/test.img"),
            2,
            Filesystem.PFS3,
            Path("/path/to/pfs3aio"),
        )

        assert cmd.command == HSTCommand.RDB_FS_ADD

    def test_rdb_partition_commands(self):
        """test adding partitions to RDB"""
        from emu68hatcher.builder.hst_commands import (
            generate_rdb_partition_commands,
            HSTCommand,
        )
        from emu68hatcher.config.schema import AmigaPartition, Filesystem

        partitions = [
            AmigaPartition(
                device="SDH0",
                volume="Workbench",
                filesystem=Filesystem.PFS3,
                size=2 * 1024**3,
                bootable=True,
            ),
            AmigaPartition(
                device="SDH1",
                volume="Work",
                filesystem=Filesystem.PFS3,
                size=6 * 1024**3,
                bootable=False,
            ),
        ]

        commands = generate_rdb_partition_commands(Path("/tmp/test.img"), 2, partitions)

        # should have commands for each partition (add + format)
        assert len(commands) >= 2
        # at least some should be partition add commands
        assert any(cmd.command == HSTCommand.RDB_PART_ADD for cmd in commands)


class TestScriptGeneration:
    """tests for complete script generation"""

    def test_generate_full_script(self, sample_config, temp_dir):
        """test generating a complete build script"""
        from emu68hatcher.builder.hst_commands import generate_disk_creation_script

        output_path = temp_dir / "test.img"
        script = generate_disk_creation_script(sample_config, output_path)

        assert script is not None
        assert len(script.commands) > 0

        # should have at least: blank, mbr init, mbr part add (x2), rdb init
        assert len(script.commands) >= 5

    def test_script_has_comments(self, sample_config, temp_dir):
        """test that script includes comments"""
        from emu68hatcher.builder.hst_commands import generate_disk_creation_script

        output_path = temp_dir / "test.img"
        script = generate_disk_creation_script(sample_config, output_path)

        # check some commands have descriptions
        has_description = any(cmd.description for cmd in script.commands)
        assert has_description

    def test_script_to_string(self, sample_config, temp_dir):
        """test script can be converted to string for file output"""
        from emu68hatcher.builder.hst_commands import generate_disk_creation_script

        output_path = temp_dir / "test.img"
        script = generate_disk_creation_script(sample_config, output_path)

        script_text = script.to_script_file()

        assert isinstance(script_text, str)
        assert len(script_text) > 0
        assert "blank" in script_text


class TestCommandValidation:
    """tests for command validation"""

    def test_command_has_required_fields(self):
        """test that commands have required fields"""
        from emu68hatcher.builder.hst_commands import (
            HSTCommandLine,
            generate_blank_image_command,
        )

        cmd = generate_blank_image_command(Path("/tmp/test.img"), 1024**3)

        assert hasattr(cmd, "command")
        assert hasattr(cmd, "args")
        assert hasattr(cmd, "description")
        assert cmd.command is not None

    def test_command_to_string(self):
        """test command can be converted to string"""
        from emu68hatcher.builder.hst_commands import generate_blank_image_command

        cmd = generate_blank_image_command(Path("/tmp/test.img"), 1024**3)

        cmd_str = cmd.to_string()
        assert "hst-imager" in cmd_str
        assert "blank" in cmd_str
