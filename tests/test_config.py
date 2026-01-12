"""tests for configuration schema and loader"""

import json
from pathlib import Path

import pytest


class TestConfigSchema:
    """tests for config schema validation"""

    def test_create_default_config(self, sample_config):
        """test that default config is created correctly"""
        assert sample_config is not None
        assert sample_config.version == "1.0.0"
        assert sample_config.kickstart.version == "3.1"

    def test_config_kickstart_version(self, sample_config):
        """test kickstart version handling"""
        sample_config.kickstart.version = "2.04"
        assert sample_config.kickstart.version == "2.04"

    def test_config_display_settings(self, sample_config):
        """test display configuration"""
        sample_config.display.workbench = {
            "width": 800,
            "height": 600,
            "color_depth": 16,
            "backdrop": False,
        }
        assert sample_config.display.workbench["width"] == 800
        assert sample_config.display.workbench["color_depth"] == 16

    def test_config_packages(self, sample_config):
        """test package configuration"""
        from emu68hatcher.config.schema import PackageConfig

        sample_config.packages = [
            PackageConfig(name="whdload", enabled=True),
            PackageConfig(name="dopus", enabled=False),
        ]
        assert len(sample_config.packages) == 2
        assert sample_config.packages[0].name == "whdload"
        assert sample_config.packages[0].enabled is True

    def test_config_partitions(self, sample_config):
        """test partition configuration"""
        assert sample_config.partitions is not None
        assert sample_config.partitions.disk_size > 0
        assert len(sample_config.partitions.layout) >= 1


class TestConfigLoader:
    """tests for config file loading and saving"""

    def test_save_and_load_config(self, sample_config, temp_dir):
        """test saving and loading config file"""
        from emu68hatcher.config.loader import save_config, load_config

        config_path = temp_dir / "test_config.json"

        # save
        save_config(sample_config, config_path)
        assert config_path.exists()

        # load
        loaded = load_config(config_path)
        assert loaded.version == sample_config.version
        assert loaded.kickstart.version == sample_config.kickstart.version

    def test_load_config_from_dict(self, sample_config_dict, temp_dir):
        """test loading config from dictionary format"""
        from emu68hatcher.config.loader import load_config

        config_path = temp_dir / "test_config.json"
        config_path.write_text(json.dumps(sample_config_dict, indent=2))

        loaded = load_config(config_path)
        assert loaded.kickstart.version == "3.1"
        assert str(loaded.kickstart.rom_directory) == "/path/to/roms"
        assert len(loaded.packages) == 2

    def test_config_json_roundtrip(self, sample_config, temp_dir):
        """test that config survives JSON serialization"""
        from emu68hatcher.config.loader import save_config, load_config

        config_path = temp_dir / "roundtrip.json"

        # modify config
        sample_config.metadata.description = "Roundtrip test"
        sample_config.kickstart.rom_directory = Path("/test/roms")

        # save and load
        save_config(sample_config, config_path)
        loaded = load_config(config_path)

        assert loaded.metadata.description == "Roundtrip test"
        assert str(loaded.kickstart.rom_directory) == "/test/roms"

    def test_merge_configs(self, sample_config):
        """test config merging"""
        from emu68hatcher.config.loader import merge_configs

        overlay = {
            "kickstart": {"version": "3.2"},
            "output": {"path": "/new/path.img"},
        }

        merged = merge_configs(sample_config, overlay)
        assert merged.kickstart.version == "3.2"
        assert str(merged.output.path) == "/new/path.img"


class TestConfigDefaults:
    """tests for configuration defaults"""

    def test_default_disk_size(self):
        """test default disk size constant"""
        from emu68hatcher.config.defaults import DEFAULT_DISK_SIZE

        assert DEFAULT_DISK_SIZE == 8 * 1024**3  # 8 GB

    def test_min_max_disk_size(self):
        """test disk size limits"""
        from emu68hatcher.config.defaults import MIN_DISK_SIZE, MAX_DISK_SIZE

        assert MIN_DISK_SIZE < MAX_DISK_SIZE
        assert MIN_DISK_SIZE >= 1 * 1024**3  # at least 1 GB
        assert MAX_DISK_SIZE <= 2 * 1024**4  # at most 2 TB

    def test_boot_partition_size(self):
        """test boot partition size"""
        from emu68hatcher.config.defaults import DEFAULT_BOOT_PARTITION_SIZE

        assert DEFAULT_BOOT_PARTITION_SIZE == 512 * 1024**2  # 512 MB

    def test_pfs3_max_partition(self):
        """test PFS3 partition size limit"""
        from emu68hatcher.config.defaults import PFS3_MAX_PARTITION_SIZE

        assert PFS3_MAX_PARTITION_SIZE == 104 * 1024**3  # 104 GB

    def test_screen_mode_presets(self):
        """test screen mode presets exist"""
        from emu68hatcher.config.defaults import SCREEN_MODE_PRESETS

        assert "PAL" in SCREEN_MODE_PRESETS or len(SCREEN_MODE_PRESETS) > 0
