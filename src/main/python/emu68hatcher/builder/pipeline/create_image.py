"""create disk image stage"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.schema import Filesystem

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_create_image(workflow: BuildWorkflow) -> None:
    """create the disk image"""
    from emu68hatcher.builder.host.hst_commands import generate_disk_creation_script
    from emu68hatcher.builder.host.hst_runner import HSTRunner

    workflow._update_state(BuildStage.CREATE_IMAGE, 0.0)
    workflow._milestone("Creating disk image")

    if workflow.config.output is None or workflow.config.partitions is None:
        raise BuildError("Missing output or partition configuration")
    if not workflow.state.work_dir:
        raise BuildError("Work directory not set - setup stage may have failed")

    workflow.state.image_path = Path(workflow.config.output.path)

    # filesystem handler paths come from the DOWNLOAD stage
    fs_handler_paths: dict[Filesystem, Path] = {}
    if workflow.config.partitions.uses_pfs3:
        if not workflow.state.pfs3_handler_path:
            raise BuildError(
                "PFS3AIO filesystem handler not available. "
                "This should have been downloaded during the DOWNLOAD stage."
            )
        fs_handler_paths[Filesystem.PFS3] = workflow.state.pfs3_handler_path
    if workflow.config.partitions.uses_ffs:
        if not workflow.state.ffs_handler_path:
            raise BuildError(
                "FFS filesystem handler not available. L/FastFileSystem "
                "should have been extracted from Install3.x.adf during the "
                "DOWNLOAD stage."
            )
        fs_handler_paths[Filesystem.FFS] = workflow.state.ffs_handler_path

    script = generate_disk_creation_script(
        workflow.config,
        workflow.state.image_path,
        fs_handler_paths=fs_handler_paths,
    )

    runner = HSTRunner()

    def progress_cb(current: int, total: int, desc: str, status):
        progress = (current / total) * 100
        workflow._update_state(progress=progress, message=desc)

    result = runner.run_script(script, progress_callback=progress_cb)

    if not result.success:
        failed = result.failed_commands
        if failed:
            raise BuildError(f"Image creation failed: {failed[0].error}")
        raise BuildError("Image creation failed")

    workflow._update_state(progress=100.0)
    workflow._milestone("Disk image created")
