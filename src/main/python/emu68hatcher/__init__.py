"""
emu68 Hatcher - Cross-platform tool for creating Emu68/PiStorm SD card images

this package provides the core functionality for:
- parsing and validating build configurations
- downloading packages from GitHub, Aminet, and web sources
- extracting archives (7z, lha, lzx, adf)
- generating and executing HST Imager commands
- creating disk images with MBR and Amiga RDB partitions
"""

__version__ = "0.1.0"
__author__ = "Chris"

from emu68hatcher.config.schema import BuildConfig

__all__ = [
    "__version__",
    "BuildConfig",
]
