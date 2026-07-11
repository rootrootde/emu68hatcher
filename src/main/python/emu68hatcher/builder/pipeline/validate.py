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

    asset_dirs = [Path(p) for p in workflow.config.asset_directories]
    existing_dirs = [d for d in asset_dirs if d.exists() and d.is_dir()]

    if not asset_dirs:
        raise BuildError("No asset directories configured (ROMs / ADFs)")
    if not existing_dirs:
        missing = ", ".join(str(d) for d in asset_dirs)
        raise BuildError(f"None of the configured asset directories exist: {missing}")

    workflow._update_state(progress=20.0)
    workflow._milestone(f"Scanning {len(existing_dirs)} asset directories for Kickstart ROM")

    kickstart_version = workflow.config.kickstart.version.value
    rom_path = find_kickstart_for_version(existing_dirs, kickstart_version)

    if not rom_path:
        # list found ROMs for a useful error message
        found_roms, _ = scan_for_kickstart_roms(existing_dirs)
        dir_list = ", ".join(str(d) for d in existing_dirs)
        if found_roms:
            versions = ", ".join({r["version"] for r in found_roms})
            raise BuildError(
                f"No Kickstart {kickstart_version} ROM found across {len(existing_dirs)} "
                f"asset director{'ies' if len(existing_dirs) != 1 else 'y'} ({dir_list}). "
                f"Found versions: {versions}"
            )
        else:
            raise BuildError(
                f"No valid Kickstart ROMs found across {len(existing_dirs)} "
                f"asset director{'ies' if len(existing_dirs) != 1 else 'y'} ({dir_list}). "
                "Add a directory containing .rom files."
            )

    workflow.state.resolved_rom_path = rom_path
    # full ROM info incl. FAT32 name for the boot partition
    workflow.state.resolved_rom_info = identify_kickstart(rom_path)
    workflow.logger.info(f"Auto-detected Kickstart ROM: {rom_path}")

    workflow._update_state(progress=40.0)
    workflow._milestone("Scanning for install media (ADFs/ISOs)")

    found_media, _ = scan_install_media_by_hash(existing_dirs)
    _, missing_media = check_install_media_complete(found_media, kickstart_version)

    if found_media:
        workflow.state.resolved_install_media = found_media
        workflow.logger.info(
            f"Found {len(found_media)} install media files across "
            f"{len(existing_dirs)} asset director{'ies' if len(existing_dirs) != 1 else 'y'}"
        )
        if missing_media:
            workflow.logger.warning(
                f"Missing install media for {kickstart_version}: {missing_media}"
            )
    else:
        required = get_required_install_media(kickstart_version)
        workflow.logger.warning(
            f"No install media found. Required for {kickstart_version}: {required}"
        )

    _check_optional_package_adfs(workflow, found_media, kickstart_version)

    if not workflow.config.partitions:
        raise BuildError("Partition configuration not specified")

    if not workflow.config.output:
        raise BuildError("Output configuration not specified")

    _check_output_target(workflow)
    _check_roadshow_archive(workflow)
    _check_picasso96_archive(workflow)

    workflow._update_state(progress=100.0)
    workflow._milestone("Configuration validated")


def _check_optional_package_adfs(
    workflow: BuildWorkflow,
    found_media: list,
    kickstart_version: str,
) -> None:
    """flag ADFs needed by enabled packages but missing from the user's library"""
    from emu68hatcher.builder.pipeline._selection import resolve_selection
    from emu68hatcher.data.package_loader import get_adf_rules_for_version

    emu68_version = workflow.config.emu68_version.value
    enabled = resolve_selection(workflow.config, kickstart_version, emu68_version).selected

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
    from emu68hatcher.builder.host.disk_enum import find_disk
    from emu68hatcher.config.schema import OutputType

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


def _check_roadshow_archive(workflow: BuildWorkflow) -> None:
    """probe the user's Roadshow archive (file or already-extracted dir) and stash its kind"""
    archive = workflow.config.roadshow_archive
    if archive is None:
        return

    archive = Path(archive).expanduser()
    if not archive.exists():
        raise BuildError(f"Roadshow archive not found: {archive}")

    if archive.is_dir():
        kind = _classify_roadshow_dir(archive)
    elif archive.is_file():
        kind = _classify_roadshow_file(archive)
    else:
        raise BuildError(f"Roadshow archive is neither a file nor a directory: {archive}")

    workflow.state.roadshow_archive_path = archive
    workflow.state.roadshow_archive_kind = kind
    workflow.logger.info(f"Roadshow archive accepted ({kind}): {archive}")


def _check_picasso96_archive(workflow: BuildWorkflow) -> None:
    """probe the user's Picasso96 archive; require a .lha containing Picasso96Install/"""
    archive = workflow.config.display.picasso96_archive
    if archive is None:
        return

    archive = Path(archive).expanduser()
    if not archive.exists():
        raise BuildError(f"Picasso96 archive not found: {archive}")
    if not archive.is_file():
        raise BuildError(f"Picasso96 archive must be a .lha file: {archive}")

    if not _archive_has_picasso96install(archive):
        raise BuildError(
            f"{archive.name} does not look like a Picasso96 archive "
            "(no Picasso96Install/ directory inside)"
        )

    workflow.state.picasso96_archive_path = archive
    workflow.logger.info(f"Picasso96 archive accepted: {archive}")


def _archive_has_picasso96install(path: Path) -> bool:
    """true if the archive lists any entry under Picasso96Install/"""
    import os.path
    import subprocess

    from emu68hatcher.utils.host_tools import find_7z

    sevenz = find_7z()
    if sevenz is None:
        raise BuildError("7-Zip not found; cannot probe Picasso96 archive")
    try:
        result = subprocess.run(
            [str(sevenz), "l", "-slt", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise BuildError(f"could not list Picasso96 archive {path.name}: {e}") from e
    if result.returncode != 0:
        raise BuildError(
            f"7-Zip rejected Picasso96 archive {path.name}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    for line in result.stdout.splitlines():
        if not line.startswith("Path = "):
            continue
        value = line[7:]
        if os.path.isabs(value):
            continue
        if value == "Picasso96Install" or value.startswith("Picasso96Install/"):
            return True
    return False


# names inside the full commercial Roadshow.lha (outer envelope ships these three)
_ROADSHOW_INNER_FULL_NAMES = ("Roadshow-1.15.lha", "Roadshow-1.16.lha")


def _classify_roadshow_file(path: Path) -> str:
    """sniff archive contents via 7z l; return 'outer' or 'inner_full' or raise"""
    import subprocess

    from emu68hatcher.utils.host_tools import find_7z

    sevenz = find_7z()
    if sevenz is None:
        raise BuildError("7-Zip not found; cannot probe Roadshow archive")

    try:
        result = subprocess.run(
            [str(sevenz), "l", "-slt", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise BuildError(f"could not list Roadshow archive {path.name}: {e}") from e

    if result.returncode != 0:
        raise BuildError(
            f"7-Zip rejected Roadshow archive {path.name}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    import os.path

    # archive header line ("Path = <absolute path>") is dropped so it cannot fake an entry match
    entry_paths = []
    for line in result.stdout.splitlines():
        if not line.startswith("Path = "):
            continue
        value = line[7:]
        if os.path.isabs(value):
            continue
        entry_paths.append(value)

    has_full_tree = any(p.startswith("Roadshow-1.15/Workbench") for p in entry_paths)
    has_inner_entry = any(p in _ROADSHOW_INNER_FULL_NAMES for p in entry_paths)
    has_demo_marker = any(p.startswith("Roadshow-Demo-") for p in entry_paths)

    if has_full_tree:
        return "inner_full"
    if has_inner_entry:
        return "outer"
    if has_demo_marker:
        raise BuildError(
            f"{path.name} looks like a Roadshow demo archive; "
            "leave the field empty to use the bundled demo instead."
        )
    raise BuildError(
        f"{path.name} does not look like a Roadshow release archive "
        "(expected an outer envelope with Roadshow-1.15.lha, or the full release itself)."
    )


def _classify_roadshow_dir(path: Path) -> str:
    """return 'dir_full' if the dir contains Roadshow-1.15/Workbench/, 'dir_inner' if it IS the release dir"""
    if (path / "Roadshow-1.15" / "Workbench" / "Libs" / "bsdsocket.library").exists():
        return "dir_full"
    if (path / "Workbench" / "Libs" / "bsdsocket.library").exists():
        return "dir_inner"
    raise BuildError(
        f"{path} does not look like an extracted Roadshow release "
        "(expected Roadshow-1.15/Workbench/ or Workbench/ inside)."
    )


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
    from emu68hatcher.utils.host_tools import find_hst_imager

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
