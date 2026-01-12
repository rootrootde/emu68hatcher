"""validate build configuration stage"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.schema import OutputType
from emu68hatcher.extractor.adf import (
    check_install_media_complete,
    find_workbench_for_version,
    get_required_install_media,
    scan_install_media_by_hash,
)
from emu68hatcher.data.rom_detection import (
    find_kickstart_for_version,
    identify_kickstart,
    scan_for_kickstart_roms,
)

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_validate(workflow: BuildWorkflow) -> None:
    """validate configuration before build"""
    workflow._update_state(BuildStage.VALIDATE, 0.0, "Validating configuration...")

    # check required fields
    if not workflow.config.kickstart.rom_directory:
        raise BuildError("Kickstart ROM directory not specified")

    # auto-detect ROM from directory
    workflow._update_state(progress=20.0)
    workflow._log("Scanning for Kickstart ROM")
    rom_dir = Path(workflow.config.kickstart.rom_directory)
    if not rom_dir.exists():
        raise BuildError(f"Kickstart ROM directory not found: {rom_dir}")

    kickstart_version = workflow.config.kickstart.version.value
    rom_path = find_kickstart_for_version(rom_dir, kickstart_version)

    if not rom_path:
        # list what ROMs were found for better error message
        found_roms = scan_for_kickstart_roms(rom_dir)
        if found_roms:
            versions = ", ".join(set(r["version"] for r in found_roms))
            raise BuildError(
                f"No Kickstart {kickstart_version} ROM found in {rom_dir}. "
                f"Found versions: {versions}"
            )
        else:
            raise BuildError(
                f"No valid Kickstart ROMs found in {rom_dir}. "
                "Ensure the directory contains .rom files."
            )

    workflow.state.resolved_rom_path = rom_path
    # get full ROM info including FAT32 name for boot partition
    workflow.state.resolved_rom_info = identify_kickstart(rom_path)
    workflow.logger.info(f"Auto-detected Kickstart ROM: {rom_path}")

    # auto-detect Workbench/install media using hash-based detection
    # this matches the original Emu68 Imager's behavior (Compare-ADFHashes.ps1)
    # debug logging for install media configuration
    workflow.logger.debug(
        f"Install media config: has_config={workflow.config.install_media is not None}, "
        f"directory={workflow.config.install_media.directory if workflow.config.install_media else 'N/A'}"
    )

    # determine which directory to scan for install media
    # priority: 1) Explicit install_media.directory, 2) ROM directory as fallback
    media_dir_to_scan = None
    workflow.logger.info(f"Install media config check: install_media={workflow.config.install_media}, directory={workflow.config.install_media.directory if workflow.config.install_media else 'N/A'}")
    if workflow.config.install_media and workflow.config.install_media.directory:
        media_dir_to_scan = Path(workflow.config.install_media.directory)
        workflow.logger.info(f"Using configured install_media directory: {media_dir_to_scan}")
    elif rom_dir.exists():
        # fallback: scan ROM directory for ADFs (common to keep them together)
        media_dir_to_scan = rom_dir
        workflow.logger.info(
            f"No separate ADF directory configured - scanning ROM directory for Workbench ADFs: {rom_dir}"
        )

    if not media_dir_to_scan:
        workflow.logger.warning(
            "No install media directory configured. "
            "Set 'install_media.directory' in config to point to your Workbench ADFs/ISOs. "
            "Build will continue but Workbench won't be installed."
        )
    elif media_dir_to_scan:
        workflow._update_state(progress=40.0)
        workflow._log("Scanning for install media (ADFs/ISOs)")
        media_dir = media_dir_to_scan  # use the determined directory (explicit or fallback)

        if media_dir.exists():
            # scan for media first, then check completeness
            found_media = scan_install_media_by_hash(media_dir)
            is_complete, missing_media = check_install_media_complete(
                found_media, kickstart_version
            )

            if found_media:
                workflow.state.resolved_install_media = found_media
                workflow.state.missing_install_media = missing_media

                workflow.logger.info(
                    f"Found {len(found_media)} install media files in {media_dir}"
                )

                if missing_media:
                    workflow.logger.warning(
                        f"Missing install media for {kickstart_version}: {missing_media}"
                    )
            else:
                # fallback to filename-based detection for backwards compatibility
                workflow.logger.info("No hash-matched media found, trying filename detection...")
                wb_disks = find_workbench_for_version(media_dir, kickstart_version)
                if wb_disks:
                    workflow.state.resolved_workbench_disks = wb_disks
                    workflow.logger.info(
                        f"Filename-detected Workbench {wb_disks.version}: "
                        f"{len(wb_disks.disks)} disk(s)"
                    )
                    if not wb_disks.complete:
                        workflow.logger.warning(
                            f"Incomplete Workbench set - missing: {wb_disks.missing_disks}"
                        )
                else:
                    required = get_required_install_media(kickstart_version)
                    workflow.logger.warning(
                        f"No install media found in {media_dir}. "
                        f"Required for {kickstart_version}: {required}"
                    )

    if not workflow.config.partitions:
        raise BuildError("Partition configuration not specified")

    if not workflow.config.output:
        raise BuildError("Output configuration not specified")

    # ensure output path is a Path object
    output_path = Path(workflow.config.output.path)

    # validate output path
    if workflow.config.output.type == OutputType.DISK:
        if not output_path.exists():
            raise BuildError(f"Physical disk not found: {output_path}")
    else:
        # for image files, check parent directory exists
        if not output_path.parent.exists():
            raise BuildError(
                f"Output directory not found: {output_path.parent}"
            )

    workflow._update_state(progress=100.0)
    workflow._log("Configuration validated")
