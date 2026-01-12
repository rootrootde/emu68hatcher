"""create disk image stage"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.schema import OutputType

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_create_image(workflow: BuildWorkflow) -> None:
    """create the disk image"""
    from emu68hatcher.builder.hst_commands import generate_disk_creation_script, Filesystem
    from emu68hatcher.builder.hst_runner import HSTRunner

    workflow._update_state(BuildStage.CREATE_IMAGE, 0.0)
    workflow._log("Creating disk image")

    if workflow.config.output is None or workflow.config.partitions is None:
        raise BuildError("Missing output or partition configuration")
    if not workflow.state.work_dir:
        raise BuildError("Work directory not set - setup stage may have failed")

    # determine output path
    if workflow.config.output.type == OutputType.DISK:
        # for physical disk, create image in temp then write
        workflow.state.image_path = workflow.state.work_dir / "disk.img"
    else:
        workflow.state.image_path = Path(workflow.config.output.path)

    # use PFS3AIO handler downloaded during DOWNLOAD stage
    pfs3_handler_path: Optional[Path] = workflow.state.pfs3_handler_path
    uses_pfs3 = any(
        amiga_part.filesystem == Filesystem.PFS3
        for mbr_part in workflow.config.partitions.layout
        if mbr_part.amiga_partitions
        for amiga_part in mbr_part.amiga_partitions
    )

    if uses_pfs3 and not pfs3_handler_path:
        raise BuildError(
            "PFS3AIO filesystem handler not available. "
            "This should have been downloaded during the DOWNLOAD stage."
        )

    # generate and run HST commands
    script = generate_disk_creation_script(
        workflow.config,
        workflow.state.image_path,
        pfs3_handler_path=pfs3_handler_path,
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
    workflow._log("Disk image created")
