"""validate build configuration stage"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.data.install_media import (
    check_install_media_complete,
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
    workflow._milestone("Scanning for Kickstart ROM")
    rom_dir = Path(workflow.config.kickstart.rom_directory)
    if not rom_dir.exists():
        raise BuildError(f"Kickstart ROM directory not found: {rom_dir}")

    kickstart_version = workflow.config.kickstart.version.value
    rom_path = find_kickstart_for_version(rom_dir, kickstart_version)

    if not rom_path:
        # list what ROMs were found for better error message
        found_roms, _ = scan_for_kickstart_roms(rom_dir)
        if found_roms:
            versions = ", ".join({r["version"] for r in found_roms})
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

    # install media dir: explicit config wins, otherwise fall back to the ROM dir (common layout)
    media_dir_to_scan = None
    if workflow.config.install_media and workflow.config.install_media.directory:
        media_dir_to_scan = Path(workflow.config.install_media.directory)
        workflow.logger.info(f"Using configured install_media directory: {media_dir_to_scan}")
    elif rom_dir.exists():
        media_dir_to_scan = rom_dir
        workflow.logger.info(
            f"No ADF dir configured - scanning ROM dir for Workbench ADFs: {rom_dir}"
        )

    if not media_dir_to_scan:
        workflow.logger.warning(
            "No install media directory configured. "
            "Set 'install_media.directory' in config to point to your Workbench ADFs/ISOs. "
            "Build will continue but Workbench won't be installed."
        )
    else:
        workflow._update_state(progress=40.0)
        workflow._milestone("Scanning for install media (ADFs/ISOs)")

        if media_dir_to_scan.exists():
            found_media, _ = scan_install_media_by_hash(media_dir_to_scan)
            _, missing_media = check_install_media_complete(found_media, kickstart_version)

            if found_media:
                workflow.state.resolved_install_media = found_media
                workflow.logger.info(
                    f"Found {len(found_media)} install media files in {media_dir_to_scan}"
                )
                if missing_media:
                    workflow.logger.warning(
                        f"Missing install media for {kickstart_version}: {missing_media}"
                    )
            else:
                required = get_required_install_media(kickstart_version)
                workflow.logger.warning(
                    f"No install media found in {media_dir_to_scan}. "
                    f"Required for {kickstart_version}: {required}"
                )

    if not workflow.config.partitions:
        raise BuildError("Partition configuration not specified")

    if not workflow.config.output:
        raise BuildError("Output configuration not specified")

    output_path = Path(workflow.config.output.path)
    if not output_path.parent.exists():
        raise BuildError(f"Output directory not found: {output_path.parent}")

    workflow._update_state(progress=100.0)
    workflow._milestone("Configuration validated")
