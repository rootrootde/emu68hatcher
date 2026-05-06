"""finalize stage - copy staged files into the image"""

from __future__ import annotations

import shutil
import time
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.defaults import EMU68_BOOT_PARTITION_NAME

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_finalize(workflow: BuildWorkflow) -> None:
    """copy staged files into the image"""
    from emu68hatcher.config.schema import OutputType

    workflow._update_state(BuildStage.FINALIZE, 0.0)
    workflow._milestone("Finalizing")

    if workflow.config.output is None:
        raise BuildError("Missing output configuration")
    if not workflow.state.image_path:
        raise BuildError("Disk image not found - create_image stage may have failed")
    # windows physical-drive paths lie in exists() once the disk is offline; in DEVICE mode
    # the path is meaningful regardless of fs state
    if workflow.config.output.type != OutputType.DEVICE and not workflow.state.image_path.exists():
        raise BuildError("Disk image not found - create_image stage may have failed")
    if not workflow.state.staging_dir:
        raise BuildError("Staging directory not set - setup stage may have failed")

    workflow._update_state(progress=10.0)
    workflow._milestone("Copying staged files to image")
    _copy_staged_files_to_image(workflow)

    workflow._update_state(progress=90.0)
    workflow._milestone("Cleaning up")
    if workflow.state.work_dir and workflow.state.work_dir.exists():
        # keep the image file, clean up work dirs
        for subdir in ["staging", "downloads", "extracted", "workbench"]:
            cleanup_path = workflow.state.work_dir / subdir
            if cleanup_path.exists():
                shutil.rmtree(cleanup_path, ignore_errors=True)

    workflow._update_state(progress=100.0)
    workflow._milestone("Build complete")


def _ensure_device_unmounted(workflow: BuildWorkflow) -> None:
    """re-unmount before fs copy - windows auto-mounts the new fat32 and locks the raw disk"""
    from emu68hatcher.config.schema import OutputType

    if workflow.config.output is None or workflow.config.output.type != OutputType.DEVICE:
        return
    from emu68hatcher.utils.disk_enum import find_disk, unmount_disk

    info = find_disk(str(workflow.config.output.path))
    if info is None or not info.mounted_partitions:
        return
    unmount_disk(info, workflow.logger, elevation=workflow.state.elevation)


def _copy_staged_files_to_image(workflow: BuildWorkflow) -> None:
    """fs copy into the image (FAT32: mbr/1, amiga RDB: mbr/2/rdb/<dev>)"""
    from emu68hatcher.builder.host.hst_commands import HSTCommand, HSTCommandLine, hst_path
    from emu68hatcher.builder.host.hst_runner import HSTRunner
    from emu68hatcher.config.schema import OutputType

    if not workflow.state.image_path:
        workflow.logger.warning("No image path set, skipping file copy")
        return
    if (
        workflow.config.output is not None
        and workflow.config.output.type != OutputType.DEVICE
        and not workflow.state.image_path.exists()
    ):
        workflow.logger.warning("No image file found, skipping file copy")
        return

    runner = HSTRunner(cancel_check=lambda: workflow._cancelled)

    if not runner.is_available():
        workflow.logger.warning("HST Imager not available, skipping file copy")
        return

    # log raw + posix form - buildlog needs to show what hst-imager actually got (forward slashes)
    workflow.logger.info(
        f"finalize: image path: raw={workflow.state.image_path!s} "
        f"posix={workflow.state.image_path.as_posix()!s}"
    )

    # device -> 1-based MBR partition number
    device_to_mbr: dict[str, int] = {}
    id76_mbr_num: int | None = None

    if workflow.config.partitions:
        for index, mbr_part in enumerate(workflow.config.partitions.layout, start=1):
            if mbr_part.type == "fat32":
                device_to_mbr[EMU68_BOOT_PARTITION_NAME] = index
            elif mbr_part.type == "id76" and mbr_part.amiga_partitions:
                id76_mbr_num = index
                for amiga_part in mbr_part.amiga_partitions:
                    device_to_mbr[amiga_part.device] = index

    if id76_mbr_num is None:
        # no Amiga RDB to copy onto - bail before trying
        raise BuildError("partition layout has no ID76/Amiga partition; nothing to install")

    workflow.logger.info(f"finalize: device->MBR mapping: {device_to_mbr}")

    _ensure_device_unmounted(workflow)

    devices_copied = 0
    devices_failed = 0

    for device_dir in workflow.state.staging_dir.iterdir():
        if not device_dir.is_dir():
            continue

        # cancel checkpoint - each per-partition copy can take minutes
        workflow._check_cancelled()

        device_name = device_dir.name

        file_count = 0
        total_bytes = 0
        for f in device_dir.rglob("*"):
            if f.is_file():
                file_count += 1
                total_bytes += f.stat().st_size

        if file_count == 0:
            workflow.logger.info(f"Skipping empty staging directory: {device_name}")
            continue

        if device_name == EMU68_BOOT_PARTITION_NAME:
            mbr_num = device_to_mbr.get(EMU68_BOOT_PARTITION_NAME, 1)
            dest = hst_path(workflow.state.image_path, "mbr", mbr_num)
        else:
            dest = hst_path(workflow.state.image_path, "mbr", id76_mbr_num, "rdb", device_name)

        source_pattern = f"{device_dir.as_posix()}/*"

        args = [
            source_pattern,
            dest,
            "--makedir",
            "TRUE",
            "--recursive",
            "TRUE",
            "--force",
            "TRUE",
        ]

        # UAE metadata keeps amiga attrs (protection bits, comment, timestamps)
        if device_name != EMU68_BOOT_PARTITION_NAME:
            args.extend(["--uaemetadata", "UaeFsDb"])

        command = HSTCommandLine(
            command=HSTCommand.FS_COPY,
            args=args,
            description=f"Copy files to {device_name}",
        )

        workflow.logger.info(f"finalize: {device_name} dest: {dest!r}")
        workflow.logger.info(f"Running: {command.to_string()}")

        start_time = time.time()
        result = runner.run_command(command, elevation=workflow.state.elevation)
        duration_ms = int((time.time() - start_time) * 1000)

        if result.success:
            devices_copied += 1
            workflow.logger.info(
                f"Copied {file_count} files ({total_bytes:,} bytes) to {device_name} in {duration_ms}ms"
            )
        else:
            devices_failed += 1
            workflow.logger.error(f"Failed to copy files to {device_name}: {result.error}")
            if result.stdout:
                workflow.logger.error(f"stdout: {result.stdout}")
            if result.stderr:
                workflow.logger.error(f"stderr: {result.stderr}")

    workflow.logger.info(f"Copied files to {devices_copied} partitions ({devices_failed} failed)")
    if devices_failed:
        raise BuildError(
            f"{devices_failed} partition(s) failed to copy - the image is not bootable"
        )
