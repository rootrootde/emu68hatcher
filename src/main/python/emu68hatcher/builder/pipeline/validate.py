"""validate stage"""

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
    """check the config before build"""
    workflow._update_state(BuildStage.VALIDATE, 0.0, "Validating configuration...")

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
        # list found ROMs for a useful error message
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
    # full ROM info incl. FAT32 name for the boot partition
    workflow.state.resolved_rom_info = identify_kickstart(rom_path)
    workflow.logger.info(f"Auto-detected Kickstart ROM: {rom_path}")

    # install media dir: config wins; fall back to ROM dir (common layout)
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

            _check_optional_package_adfs(workflow, found_media, kickstart_version)

    if not workflow.config.partitions:
        raise BuildError("Partition configuration not specified")

    if not workflow.config.output:
        raise BuildError("Output configuration not specified")

    _check_output_target(workflow)

    workflow._update_state(progress=100.0)
    workflow._milestone("Configuration validated")


def _check_optional_package_adfs(
    workflow: BuildWorkflow,
    found_media: list,
    kickstart_version: str,
) -> None:
    """flag ADFs needed by enabled packages but missing from the user's library"""
    from emu68hatcher.data.package_loader import (
        get_adf_rules_for_version,
        get_mandatory_packages,
    )

    enabled = {p.name.lower() for p in workflow.config.packages if p.enabled}
    enabled.update(p.name.lower() for p in get_mandatory_packages(kickstart_version))

    # core required-disk set is checked by check_install_media_complete; here only
    # ADFs gated behind an optional package
    core_required = set(get_required_install_media(kickstart_version))

    found_adf_names = {m.adf_name for m in found_media}
    missing: dict[str, list[str]] = {}
    for rule in get_adf_rules_for_version(kickstart_version):
        if rule.mandatory or not rule.package:
            continue
        if rule.package.lower() not in enabled:
            continue
        if rule.adf in core_required:
            continue
        if rule.adf in found_adf_names:
            continue
        missing.setdefault(rule.adf, []).append(rule.package)

    if not missing:
        return

    lines = [
        f"  {adf}  (required by: {', '.join(sorted(set(pkgs)))})"
        for adf, pkgs in sorted(missing.items())
    ]
    raise BuildError(
        "Enabled package(s) need install media that wasn't found:\n"
        + "\n".join(lines)
        + "\n\nEither add the missing ADF(s) to your install_media directory, "
        "or disable the package(s) in the Software tab."
    )


def _check_output_target(workflow: BuildWorkflow) -> None:
    """check output target (file/device); acquire elevation when needed"""
    from emu68hatcher.config.schema import OutputType
    from emu68hatcher.utils.disk_enum import find_disk

    output = workflow.config.output
    required_size = workflow.config.partitions.disk_size

    if output.type == OutputType.IMG:
        out_path = Path(output.path)
        if not out_path.parent.exists():
            raise BuildError(f"Output directory not found: {out_path.parent}")

        if output.flash_target:
            info = find_disk(output.flash_target)
            if info is None:
                raise BuildError(
                    f"Flash target {output.flash_target} not found among removable disks. "
                    "Insert the SD card and refresh, or pick a different target."
                )
            _validate_target_disk(info, required_size)
            _acquire_for_workflow(workflow)
            _claim_macos_disk(workflow, output.flash_target)
        return

    # OutputType.DEVICE
    info = find_disk(str(output.path))
    if info is None:
        raise BuildError(
            f"Target device {output.path} not found among removable disks. "
            "Insert the SD card and refresh, or pick a different device."
        )
    _validate_target_disk(info, required_size)
    _acquire_for_workflow(workflow)
    _claim_macos_disk(workflow, str(output.path))


def _claim_macos_disk(workflow: BuildWorkflow, device: str) -> None:
    """macos: hold a DA claim so diskarbitrationd doesnt probe mid-build"""
    from emu68hatcher.utils.platform import OperatingSystem, get_platform_info

    if get_platform_info().os != OperatingSystem.MACOS:
        return
    from emu68hatcher.builder.host.disk_claim import claim_macos_disk

    claim = claim_macos_disk(device)
    if claim is None:
        workflow.logger.warning(
            f"could not claim {device} via DiskArbitration; the 'disk not readable' "
            "dialog may pop mid-build (click Ignore if it does)"
        )
        return
    workflow.state.disk_claim = claim
    workflow.logger.info(f"DiskArbitration claim held on {device}")


def _validate_target_disk(info, required_size: int) -> None:
    """SD target checks - size, system-disk refusal (find_disk already filtered to removable)"""
    if info.is_system_disk:
        raise BuildError(f"refusing to use system disk {info.device}")
    if info.size_bytes < required_size:
        raise BuildError(
            f"target {info.device} is {info.size_bytes:,} bytes "
            f"({info.size_human}); configured disk_size is {required_size:,} bytes. "
            "Pick a larger card or shrink the layout."
        )


def _acquire_for_workflow(workflow: BuildWorkflow) -> None:
    """grab elevation; push hst-imager settings inside the same auth window"""
    import subprocess

    from emu68hatcher.builder.host.elevation import (
        ElevationDenied,
        acquire_elevation,
        run_elevated,
    )
    from emu68hatcher.utils.platform import find_hst_imager

    if workflow.state.elevation is not None:
        return  # already have one

    try:
        workflow.state.elevation = acquire_elevation()
        workflow.logger.info(f"acquired elevation token via {workflow.state.elevation.method}")
    except ElevationDenied as e:
        raise BuildError(f"admin access required to write to a physical disk: {e}") from e

    hst = find_hst_imager()
    if not hst:
        return

    cmd = [
        str(hst),
        "settings",
        "update",
        "--all-physical-drives",
        "--skip-unused-sectors",
        "--sparse-files",
    ]
    # best-effort - build still runs without these settings, so dont wait long
    # and let the user cancel out of it
    try:
        result = run_elevated(
            cmd,
            workflow.state.elevation,
            timeout=30,
            cancel_check=lambda: workflow._cancelled,
        )
        if getattr(result, "cancelled", False):
            workflow.logger.warning("hst-imager settings push cancelled by user")
        elif result.returncode == 0:
            workflow.logger.info("hst-imager settings pushed (AllPhysicalDrives=True)")
        else:
            workflow.logger.warning(
                f"could not push hst-imager settings: {result.stderr or result.stdout}"
            )
    except (subprocess.SubprocessError, OSError) as e:
        workflow.logger.warning(f"could not push hst-imager settings: {e}")
