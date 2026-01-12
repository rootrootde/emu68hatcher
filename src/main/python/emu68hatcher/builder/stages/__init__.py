"""build stages for Emu68 Hatcher workflow"""

from emu68hatcher.builder.stages.validate import stage_validate
from emu68hatcher.builder.stages.download import stage_setup_workspace, stage_download, stage_extract
from emu68hatcher.builder.stages.create_image import stage_create_image
from emu68hatcher.builder.stages.install_workbench import stage_install_workbench
from emu68hatcher.builder.stages.install_packages import stage_install_packages
from emu68hatcher.builder.stages.configure import stage_configure
from emu68hatcher.builder.stages.finalize import stage_finalize

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
