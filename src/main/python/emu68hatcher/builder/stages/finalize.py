"""finalize build stage - copy staged files to image and optionally write to disk"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.builder.disk_manager import DiskManager
from emu68hatcher.config.schema import OutputType

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_finalize(workflow: BuildWorkflow) -> None:
    """finalize the build - copy staged files to image and optionally write to disk"""
    workflow._update_state(BuildStage.FINALIZE, 0.0)
    workflow._log("Finalizing")

    if workflow.config.output is None:
        raise BuildError("Missing output configuration")
    if not workflow.state.image_path or not workflow.state.image_path.exists():
        raise BuildError("Disk image not found - create_image stage may have failed")
    if not workflow.state.staging_dir:
        raise BuildError("Staging directory not set - setup stage may have failed")

    # copy staged files to the image using HST Imager
    workflow._update_state(progress=10.0)
    workflow._log("Copying staged files to image")
    _copy_staged_files_to_image(workflow)

    # for physical disk output, write the image to the disk
    if workflow.config.output.type == OutputType.DISK:
        workflow._update_state(progress=50.0)
        workflow._log("Writing image to physical disk")

        if not workflow.state.image_path or not workflow.state.image_path.exists():
            raise BuildError("Image file not found for disk write")

        # progress callback for disk write (maps 0-100% to 50-90% overall)
        def disk_write_progress(progress):
            pct = progress.percent
            # map disk write progress (0-100) to overall progress (50-90)
            overall = 50.0 + (pct * 0.4)
            speed_mb = progress.speed_bytes_per_sec / (1024 * 1024)
            written_mb = progress.bytes_written / (1024 * 1024)
            total_mb = progress.total_bytes / (1024 * 1024)
            eta_min = progress.eta_seconds / 60

            if speed_mb > 0:
                msg = f"Writing to disk: {written_mb:.0f}/{total_mb:.0f} MB ({pct:.1f}%) - {speed_mb:.1f} MB/s, ETA {eta_min:.1f} min"
            else:
                msg = f"Writing to disk: {written_mb:.0f}/{total_mb:.0f} MB ({pct:.1f}%)"
            workflow._update_state(progress=overall, message=msg)

        disk_manager = DiskManager()
        success, error = disk_manager.write_image_to_disk(
            workflow.state.image_path,
            Path(workflow.config.output.path),
            progress_callback=disk_write_progress,
            gui_mode=workflow.gui_mode,
        )

        if not success:
            raise BuildError(f"Failed to write to disk: {error}")

        workflow.logger.info(f"Image written to {workflow.config.output.path}")

        # clean up the temp image file after successful write
        if workflow.state.work_dir and workflow.state.image_path:
            try:
                workflow.state.image_path.unlink()
            except Exception:
                pass

    # clean up temp files
    workflow._update_state(progress=90.0)
    workflow._log("Cleaning up")
    if workflow.state.work_dir and workflow.state.work_dir.exists():
        # keep the output image file, clean up work directories
        for subdir in ["staging", "downloads", "extracted", "workbench"]:
            cleanup_path = workflow.state.work_dir / subdir
            if cleanup_path.exists():
                shutil.rmtree(cleanup_path, ignore_errors=True)

    workflow._update_state(progress=100.0)
    workflow._log("Build complete")


def _copy_staged_files_to_image(workflow: BuildWorkflow) -> None:
    """copy all staged files to the disk image using HST Imager

    uses the same path format as the original Emu68 Imager:
    - FAT32: image_path/mbr/1
    - amiga RDB: image_path/mbr/2/rdb/DEVICE_NAME
    """
    from emu68hatcher.builder.hst_commands import HSTCommand, HSTCommandLine
    from emu68hatcher.builder.hst_runner import HSTRunner

    if not workflow.state.image_path or not workflow.state.image_path.exists():
        workflow.logger.warning("No image file found, skipping file copy")
        return

    runner = HSTRunner()

    if not runner.is_available():
        workflow.logger.warning("HST Imager not available, skipping file copy")
        return

    # build a mapping of device names to MBR partition numbers
    # FAT32 is always partition 1, ID76 (Amiga) is partition 2
    device_to_mbr: dict[str, int] = {}
    id76_mbr_num = 2  # amiga RDB partition is usually MBR partition 2

    if workflow.config.partitions:
        mbr_num = 0
        for mbr_part in workflow.config.partitions.layout:
            mbr_num += 1
            if mbr_part.type == "fat32":
                device_to_mbr["EMU68BOOT"] = mbr_num
            elif mbr_part.type == "id76" and mbr_part.amiga_partitions:
                id76_mbr_num = mbr_num
                for amiga_part in mbr_part.amiga_partitions:
                    device_to_mbr[amiga_part.device] = mbr_num

    # copy files from each device staging directory to the image
    devices_copied = 0
    devices_failed = 0

    for device_dir in workflow.state.staging_dir.iterdir():
        if not device_dir.is_dir():
            continue

        device_name = device_dir.name

        # count files in staging directory
        file_count = 0
        total_bytes = 0
        for f in device_dir.rglob("*"):
            if f.is_file():
                file_count += 1
                total_bytes += f.stat().st_size

        # check if there are any files to copy
        if file_count == 0:
            workflow.logger.info(f"Skipping empty staging directory: {device_name}")
            continue

        # build the destination path using HST Imager path notation
        # original format: "image/mbr/N" for FAT32, "image/mbr/N/rdb/DEVICE" for Amiga
        if device_name == "EMU68BOOT":
            # FAT32 boot partition: image/mbr/1
            mbr_num = device_to_mbr.get("EMU68BOOT", 1)
            dest = f"{workflow.state.image_path}/mbr/{mbr_num}"
        else:
            # amiga RDB partition: image/mbr/N/rdb/DEVICE
            dest = f"{workflow.state.image_path}/mbr/{id76_mbr_num}/rdb/{device_name}"

        # source with wildcard to copy contents
        source_pattern = f"{device_dir}/*"

        # build command matching original tool:
        # fs copy "source/*" "dest" --makedir TRUE --recursive TRUE --force TRUE
        # for Amiga partitions, also add --uaemetadata UaeFsDb
        args = [
            source_pattern,
            dest,
            "--makedir", "TRUE",
            "--recursive", "TRUE",
            "--force", "TRUE",
        ]

        # add UAE metadata for Amiga partitions (preserves file attributes)
        if device_name != "EMU68BOOT":
            args.extend(["--uaemetadata", "UaeFsDb"])

        command = HSTCommandLine(
            command=HSTCommand.FS_COPY,
            args=args,
            description=f"Copy files to {device_name}",
        )

        workflow.logger.info(f"Running: {command.to_string()}")

        # time the operation
        start_time = time.time()
        result = runner.run_command(command)
        duration_ms = int((time.time() - start_time) * 1000)

        if result.success:
            devices_copied += 1
            workflow.logger.info(f"Copied {file_count} files ({total_bytes:,} bytes) to {device_name} in {duration_ms}ms")
        else:
            devices_failed += 1
            workflow.logger.warning(f"Failed to copy files to {device_name}: {result.error}")
            if result.stdout:
                workflow.logger.debug(f"stdout: {result.stdout}")
            if result.stderr:
                workflow.logger.debug(f"stderr: {result.stderr}")

    workflow.logger.info(f"Copied files to {devices_copied} partitions ({devices_failed} failed)")
