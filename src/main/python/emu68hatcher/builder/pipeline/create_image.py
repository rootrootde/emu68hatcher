"""create-image stage"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.schema import Filesystem, OutputType

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_create_image(workflow: BuildWorkflow) -> None:
    """create .img file or init the target SD device"""
    from emu68hatcher.builder.host.hst_commands import (
        generate_disk_creation_script,
    )
    from emu68hatcher.builder.host.hst_runner import HSTRunner

    workflow._update_state(BuildStage.CREATE_IMAGE, 0.0)

    if workflow.config.output is None or workflow.config.partitions is None:
        raise BuildError("Missing output or partition configuration")
    if not workflow.state.work_dir:
        raise BuildError("Work directory not set - setup stage may have failed")

    output_type = workflow.config.output.type
    raw_target = workflow.config.output.path
    # device targets are strings on purpose (see OutputConfig.path); re-wrapping in Path
    # would corrupt \\.\PhysicalDriveN on windows 3.10/3.11
    target_path = raw_target if isinstance(raw_target, str) else Path(raw_target)
    # macOS: an elevated (root) helper cannot touch a .img inside a TCC-protected user folder
    # (~/Downloads, ~/Documents, ~/Desktop). when a flash target forces elevation, build the .img
    # in the non-protected work dir instead and move it to the user's path after flashing (done in
    # workflow._finalize_output_move). non-protected + external targets stay direct - they work as
    # is, and this avoids a cross-volume copy.
    if (
        output_type == OutputType.IMG
        and workflow.state.elevation is not None
        and workflow.state.work_dir is not None
        and _is_tcc_protected(target_path)
    ):
        workflow.state.final_output_path = target_path
        workflow.state.image_path = workflow.state.work_dir / target_path.name
        workflow.logger.info(
            f"building image in work dir (macOS TCC), will move to {target_path} after flashing"
        )
    else:
        workflow.state.image_path = target_path

    if output_type == OutputType.DEVICE:
        workflow._milestone(f"Initialising SD card on {workflow.state.image_path}")
        _prepare_device_target(workflow)
        skip_blank = True
    elif workflow.config.output.sparse:
        workflow._milestone(f"Allocating sparse image at {workflow.state.image_path}")
        _prepare_sparse_image(workflow)
        skip_blank = True
    else:
        workflow._milestone(f"Creating image file at {workflow.state.image_path}")
        skip_blank = False

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
        skip_blank=skip_blank,
    )

    runner = HSTRunner(cancel_check=lambda: workflow._cancelled)

    def progress_cb(current: int, total: int, desc: str, status):
        progress = (current / total) * 100
        workflow._update_state(progress=progress, message=desc)

    result = runner.run_script(
        script,
        progress_callback=progress_cb,
        elevation=workflow.state.elevation,
    )

    if not result.success:
        failed = result.failed_commands
        if failed:
            raise BuildError(f"Image creation failed: {failed[0].error}")
        raise BuildError("Image creation failed")

    workflow._update_state(progress=100.0)
    workflow._milestone(
        "Disk image created" if output_type == OutputType.IMG else "SD card initialised"
    )


def _prepare_sparse_image(workflow: BuildWorkflow) -> None:
    """sparse .img at target path, sized by disk_size"""
    from emu68hatcher.builder.host.sparse import (
        SparseUnsupportedError,
        allocate_sparse,
    )

    path = workflow.state.image_path
    size = workflow.config.partitions.disk_size
    try:
        allocate_sparse(path, size)
    except SparseUnsupportedError as e:
        workflow.logger.warning(
            f"Sparse allocation unsupported on this filesystem ({e}); "
            "disable 'Sparse' in the Output tab to silence this."
        )
        raise


def _prepare_device_target(workflow: BuildWorkflow) -> None:
    """sanity-check + unmount the SD before hst-imager touches it"""
    from emu68hatcher.builder.host.disk_enum import find_disk

    device = str(workflow.state.image_path)
    info = find_disk(device)
    if info is None:
        raise BuildError(
            f"Target device {device} is not present or not removable - was it ejected?"
        )
    if info.is_system_disk:
        raise BuildError(f"refusing to write to system disk {device}")
    required = workflow.config.partitions.disk_size
    if info.size_bytes < required:
        raise BuildError(
            f"target {device} is {info.size_bytes:,} bytes; configured disk_size is "
            f"{required:,} bytes (card too small)"
        )
    if info.mounted_partitions:
        from emu68hatcher.builder.host.disk_enum import unmount_disk

        unmount_disk(info, workflow.logger, elevation=workflow.state.elevation)


def _is_tcc_protected(path: Path) -> bool:
    """true if path is under a macOS TCC-protected user folder, denied even to a root helper"""
    from emu68hatcher.utils.platform import OperatingSystem, get_platform_info

    if get_platform_info().os != OperatingSystem.MACOS:
        return False
    try:
        rel = path.expanduser().resolve().relative_to(Path.home())
    except (ValueError, OSError, RuntimeError):
        return False
    return bool(rel.parts) and rel.parts[0] in ("Downloads", "Documents", "Desktop")
