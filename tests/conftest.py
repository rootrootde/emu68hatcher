"""pytest configuration and fixtures for Emu68 Hatcher tests"""

import sys
from pathlib import Path

import pytest

# add source directories to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "main" / "python"))
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _clear_package_cache():
    """clear the package loader cache before each test

    this prevents stale cached data when tests monkeypatch _PACKAGES_DIR.
    """
    from emu68hatcher.data.package_loader import invalidate_package_cache
    invalidate_package_cache()
    yield
    invalidate_package_cache()


@pytest.fixture
def temp_dir(tmp_path):
    """provide a temporary directory for tests"""
    return tmp_path


@pytest.fixture
def sample_config():
    """provide a sample BuildConfig for testing"""
    from emu68hatcher.config.defaults import create_default_config

    return create_default_config()


@pytest.fixture
def sample_config_dict():
    """provide a sample config as a dictionary"""
    return {
        "version": "1.0.0",
        "metadata": {
            "description": "Test configuration",
            "author": "Test",
        },
        "kickstart": {
            "version": "3.1",
            "rom_directory": "/path/to/roms",
        },
        "display": {
            "screen_mode": "PAL",
            "workbench": {
                "mode_type": "RTG",
                "screen_mode": "PAL:HighRes",
                "width": 640,
                "height": 480,
                "color_depth": 8,
                "backdrop": True,
            },
        },
        "packages": [
            {"name": "whdload", "enabled": True},
            {"name": "dopus", "enabled": False},
        ],
        "partitions": {
            "disk_size": 8589934592,
            "layout": [
                {"type": "fat32", "name": "EMU68BOOT", "size": 536870912},
                {
                    "type": "id76",
                    "name": "AMIGA",
                    "size": 8051964416,
                    "amiga_partitions": [
                        {
                            "device": "SDH0",
                            "volume": "System",
                            "filesystem": "PFS3",
                            "size": 2147483648,
                            "bootable": True,
                            "priority": 0,
                        },
                        {
                            "device": "SDH1",
                            "volume": "Work",
                            "filesystem": "PFS3",
                            "size": 5903481856,
                            "bootable": False,
                        },
                    ],
                },
            ],
        },
        "output": {
            "type": "img",
            "path": "/tmp/test.img",
        },
    }
