"""build stages for Emu68 Hatcher workflow"""

from emu68hatcher.builder.pipeline.configure import stage_configure
from emu68hatcher.builder.pipeline.create_image import stage_create_image
from emu68hatcher.builder.pipeline.download import (
    stage_download,
    stage_extract,
    stage_setup_workspace,
)
from emu68hatcher.builder.pipeline.finalize import stage_finalize
from emu68hatcher.builder.pipeline.install_packages import stage_install_packages
from emu68hatcher.builder.pipeline.install_workbench import stage_install_workbench
from emu68hatcher.builder.pipeline.validate import stage_validate

__all__ = [
    "stage_validate",
    "stage_setup_workspace",
    "stage_download",
    "stage_extract",
    "stage_create_image",
    "stage_install_workbench",
    "stage_install_packages",
    "stage_configure",
    "stage_finalize",
]
