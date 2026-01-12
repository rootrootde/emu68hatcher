"""install Workbench files from ADFs stage"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.builder.amiga_files import FileMapping, stage_files
from emu68hatcher.extractor.adf import (
    find_workbench_for_version,
    scan_install_media_by_hash,
)

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_install_workbench(workflow: BuildWorkflow) -> None:
    """install Workbench files from ADFs"""
    if not workflow.state.staging_dir or not workflow.state.workbench_dir:
        raise BuildError("Staging or workbench directory not set - setup stage may have failed")

    workflow._update_state(
        BuildStage.INSTALL_WORKBENCH, 0.0, "Installing Workbench..."
    )

    # get ADF paths to extract - prefer hash-identified media
    adf_paths: list[Path] = []
    media_description = ""

    if workflow.state.resolved_install_media:
        # filter to only ADFs referenced by extraction rules for this KS version
        from emu68hatcher.data.package_loader import get_adf_rules_for_version
        ks_version = workflow.config.kickstart.version.value
        needed_adf_names = {r.adf for r in get_adf_rules_for_version(ks_version)}

        needed_media = []
        seen_names = set()
        for m in workflow.state.resolved_install_media:
            if m.adf_name in needed_adf_names and m.adf_name not in seen_names:
                needed_media.append(m)
                seen_names.add(m.adf_name)

        adf_paths = [m.path for m in needed_media]
        media_names = sorted(set(m.friendly_name for m in needed_media))
        media_description = f"{len(adf_paths)} ADFs for KS {ks_version}"
        workflow.logger.info(f"Using {media_description}: {', '.join(media_names)}")

    elif workflow.state.resolved_workbench_disks:
        # fallback to filename-detected disks
        wb_disks = workflow.state.resolved_workbench_disks
        adf_paths = list(wb_disks.disks.values())
        media_description = f"Workbench {wb_disks.version} ({len(adf_paths)} disk(s))"
        workflow.logger.info(f"Using filename-detected media: {media_description}")

    # last resort: try scanning again if validation didn't find anything
    if not adf_paths:
        workflow.logger.info("No pre-resolved media, attempting direct ADF scan...")
        # try install_media.directory first, then ROM directory
        scan_dir = None
        if workflow.config.install_media and workflow.config.install_media.directory:
            scan_dir = Path(workflow.config.install_media.directory)
        elif workflow.config.kickstart.rom_directory:
            scan_dir = Path(workflow.config.kickstart.rom_directory)

        if scan_dir and scan_dir.exists():
            workflow.logger.info(f"Scanning {scan_dir} for ADFs...")
            found_media = scan_install_media_by_hash(scan_dir)
            if found_media:
                # filter to needed ADFs only
                from emu68hatcher.data.package_loader import get_adf_rules_for_version as _get_rules
                _needed = {r.adf for r in _get_rules(workflow.config.kickstart.version.value)}
                _seen = set()
                filtered = []
                for m in found_media:
                    if m.adf_name in _needed and m.adf_name not in _seen:
                        filtered.append(m)
                        _seen.add(m.adf_name)
                adf_paths = [m.path for m in filtered]
                media_names = sorted(set(m.friendly_name for m in filtered))
                media_description = f"{len(adf_paths)} ADFs"
                workflow.logger.info(f"Direct scan found: {media_description}")
            else:
                # try filename-based detection
                kickstart_version = workflow.config.kickstart.version.value
                wb_disks = find_workbench_for_version(scan_dir, kickstart_version)
                if wb_disks and wb_disks.disks:
                    adf_paths = list(wb_disks.disks.values())
                    media_description = f"Workbench {wb_disks.version} ({len(adf_paths)} disk(s))"
                    workflow.logger.info(f"Filename detection found: {media_description}")

    if not adf_paths:
        workflow.logger.warning(
            "No Workbench disks detected - skipping OS installation. "
            "To install Workbench, set 'install_media.directory' in your config "
            "to point to a folder containing your Workbench ADF files."
        )
        workflow._update_state(progress=100.0)
        workflow._log("Skipped - no Workbench ADFs configured")
        return

    workflow._update_state(progress=10.0)
    workflow._log(f"Extracting {media_description}")

    # use CSV-based extraction rules (matching original Emu68 Imager)
    total_files, errors = _extract_adfs_with_rules(workflow, adf_paths)

    if errors:
        workflow.logger.warning(f"Some ADF extractions failed: {'; '.join(errors[:5])}")

    workflow._update_state(progress=50.0)
    workflow._log("Copying Workbench files to staging")

    # copy extracted Workbench files to the DH0 staging directory
    # find the boot partition (DH0 typically)
    boot_device = "DH0"
    if workflow.config.partitions:
        for mbr_part in workflow.config.partitions.layout:
            if mbr_part.amiga_partitions:
                for amiga_part in mbr_part.amiga_partitions:
                    if amiga_part.bootable:
                        boot_device = amiga_part.device
                        break

    boot_staging = workflow.state.staging_dir / boot_device

    # decompress .Z files for Workbench 3.2.x (uses Unix compress format)
    ks_version = workflow.config.kickstart.version.value
    if ks_version.startswith("3.2"):
        _decompress_z_files(workflow, workflow.state.workbench_dir)

    # copy Workbench files to staging
    file_mapping = FileMapping()
    file_mapping.add_directory(
        workflow.state.workbench_dir,
        "",  # root of the partition
        device=boot_device,
        recursive=True,
    )

    files_staged = stage_files(file_mapping, workflow.state.staging_dir)
    workflow.state.files_copied += files_staged

    workflow.logger.info(f"Staged {files_staged} Workbench files to {boot_device}")
    workflow._update_state(progress=100.0)
    workflow._log(f"Workbench installed ({files_staged} files)")


def _extract_adfs_with_rules(workflow: BuildWorkflow, adf_paths: list[Path]) -> tuple[int, list[str]]:
    """
    extract ADFs using YAML rules from adf_rules.yaml.

    this matches the original Emu68 Imager behavior - extracting specific
    files/folders from each ADF to their correct destinations."""
    from emu68hatcher.data.package_loader import get_filtered_adf_rules
    from emu68hatcher.utils.platform import find_hst_imager

    hst_imager = find_hst_imager()
    if not hst_imager:
        return 0, ["HST Imager not found"]

    # get kickstart version for filtering
    ks_version = workflow.config.kickstart.version.value

    # build a mapping of ADF names (like "Workbench3_2") to actual paths
    adf_name_to_path: dict[str, Path] = {}
    if workflow.state.resolved_install_media:
        for media in workflow.state.resolved_install_media:
            # store exact name
            adf_name_to_path[media.adf_name] = media.path

            # also store base name without sub-version suffix
            # e.g., "Workbench3_2_3" -> "Workbench3_2", "Storage3_2" stays as is
            match = re.match(r'^(.+\d+_\d+)_\d+$', media.adf_name)
            if match:
                base_name = match.group(1)  # e.g., "Workbench3_2" from "Workbench3_2_3"
                if base_name not in adf_name_to_path:
                    adf_name_to_path[base_name] = media.path

    # also try to map ADFs by filename pattern (for any not already detected by hash)
    for adf_path in adf_paths:
        stem = adf_path.stem.lower()

        # handle locale-specific ADFs (LocaleDE, LocaleFR, LocaleES, etc.)
        locale_match = re.match(r'^locale([a-z]{2}).*$', stem)
        if locale_match:
            locale_code = locale_match.group(1).upper()
            for ver in ["3_2_3", "3_2", "3_1"]:
                if ver.replace("_", ".") in ks_version or ver.replace("_", "") in ks_version:
                    adf_name = f"Locale{locale_code}{ver}"
                    if adf_name not in adf_name_to_path:
                        adf_name_to_path[adf_name] = adf_path
                        workflow.logger.debug(f"Mapped locale ADF: {adf_name} -> {adf_path}")
                    break
            continue

        # try common patterns for other ADFs
        for name_pattern in ["workbench", "extras", "fonts", "storage", "locale", "install", "classes"]:
            if name_pattern in stem:
                # create ADF name like "Workbench3_1"
                for ver in ["3_2_3", "3_2", "3_1"]:
                    if ver.replace("_", ".") in ks_version or ver.replace("_", "") in ks_version:
                        adf_name = f"{name_pattern.capitalize()}{ver}"
                        if adf_name not in adf_name_to_path:
                            adf_name_to_path[adf_name] = adf_path
                        break
                break

    workflow.logger.debug(f"Mapped {len(adf_name_to_path)} ADFs: {list(adf_name_to_path.keys())}")

    # build set of enabled package names from user config + mandatory packages
    enabled_packages = {p.name.lower() for p in workflow.config.packages if p.enabled}
    # add mandatory packages (os_install, etc.) - use package_loader directly
    from emu68hatcher.data.package_loader import get_mandatory_packages as get_mandatory_pkg_objs
    mandatory_pkgs = get_mandatory_pkg_objs(ks_version)
    enabled_packages.update(pkg.name.lower() for pkg in mandatory_pkgs)
    workflow.logger.debug(f"Enabled packages for ADF rules: {enabled_packages}")

    # get user's selected icon set
    user_icon_set = getattr(workflow.config, 'icon_set', 'Standard') or 'Standard'

    # get filtered ADF rules from YAML
    adf_rules = get_filtered_adf_rules(ks_version, enabled_packages, user_icon_set)
    workflow.logger.info(f"Found {len(adf_rules)} ADF extraction rules for Kickstart {ks_version}")

    # drive mapping
    drive_map = {
        "System": "SDH0",
        "Work": "SDH1",
    }

    total_files = 0
    errors = []
    processed_rules = 0
    last_logged_adf: Optional[str] = None

    for rule in adf_rules:
        source_location = rule.adf  # ADF name like "Workbench3_1"
        files_to_install = rule.source  # pattern like "*" or "C/*"
        drive_to_install = rule.drive
        location_to_install = rule.dest.rstrip("/")
        copy_recursive = rule.recursive
        new_file_name = rule.rename

        # find the ADF path for this source
        adf_path = adf_name_to_path.get(source_location)
        if not adf_path:
            # try exact match with different separators (e.g., Classes3_2_3 vs Classes 3.2.3)
            for name, path in adf_name_to_path.items():
                # normalize both to compare: remove spaces, underscores, dots
                norm_source = source_location.lower().replace("_", "").replace(" ", "").replace(".", "")
                norm_name = name.lower().replace("_", "").replace(" ", "").replace(".", "")
                if norm_source == norm_name:
                    adf_path = path
                    workflow.logger.debug(f"Matched {source_location} -> {name} via normalization")
                    break


        if not adf_path:
            # log when mandatory ADF is missing
            if rule.mandatory:
                workflow.logger.warning(f"Missing ADF for mandatory rule: {source_location} (need {files_to_install})")
            continue

        # build destination path
        device = drive_map.get(drive_to_install, "SDH0")
        dest_dir = workflow.state.workbench_dir / location_to_install if location_to_install else workflow.state.workbench_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        # build source path within ADF
        source_path = f"{adf_path}/{files_to_install}" if files_to_install else str(adf_path)

        # build HST extract command
        # fs extract "adf_path/pattern" "dest_dir/" --recursive TRUE --force TRUE
        if new_file_name:
            dest_path = str(dest_dir / new_file_name)
        else:
            dest_path = str(dest_dir) + "/"

        args = [
            str(hst_imager), "fs", "extract",
            source_path,
            dest_path,
            "--force", "TRUE",
            "--uaemetadata", "None",
        ]

        if copy_recursive:
            args.extend(["--recursive", "TRUE"])

        # run extraction
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                # count files (rough estimate from output or directory)
                total_files += 1
                processed_rules += 1
            else:
                # not all failures are errors - some patterns might not match
                if "not found" not in result.stdout.lower() and "not found" not in result.stderr.lower():
                    errors.append(f"{source_location}/{files_to_install}: {result.stderr or result.stdout}")
        except subprocess.TimeoutExpired:
            errors.append(f"{source_location}/{files_to_install}: Timeout")
        except Exception as e:
            errors.append(f"{source_location}/{files_to_install}: {e}")

        # update progress + status (transient, not logged per rule)
        progress = 10.0 + (40.0 * processed_rules / max(len(adf_rules), 1))
        workflow._update_state(
            progress=progress,
            message=f"Extracting {source_location}: {files_to_install}",
        )
        # log once per ADF source (many rules typically share one ADF)
        if source_location != last_logged_adf:
            workflow._log(f"Extracting from {source_location}")
            last_logged_adf = source_location

    # count actual files extracted
    if workflow.state.workbench_dir.exists():
        total_files = sum(1 for _ in workflow.state.workbench_dir.rglob("*") if _.is_file())

    workflow.logger.info(f"Extracted {total_files} files from ADFs using {processed_rules} YAML rules")

    return total_files, errors


def _decompress_z_files(workflow: BuildWorkflow, directory: Path) -> None:
    """
    decompress .Z files (Unix compress format) used in Workbench 3.2.x.

    uses 7-Zip for decompression, same as original Emu68 Imager.
    """
    from emu68hatcher.utils.platform import find_7z

    z_files = list(directory.rglob("*.Z"))
    if not z_files:
        return

    sevenz = find_7z()
    if not sevenz:
        workflow.logger.warning(f"7-Zip not found, cannot decompress {len(z_files)} .Z files")
        return

    workflow.logger.info(f"Decompressing {len(z_files)} .Z files...")

    for z_file in z_files:
        try:
            # 7z e file.Z extracts to current directory
            result = subprocess.run(
                [str(sevenz), "e", str(z_file), f"-o{z_file.parent}", "-y"],
                capture_output=True,
                text=True,
                cwd=z_file.parent,
            )
            if result.returncode == 0:
                # delete the .Z file after successful extraction
                z_file.unlink()
            else:
                workflow.logger.warning(f"Failed to decompress {z_file.name}: {result.stderr}")
        except Exception as e:
            workflow.logger.warning(f"Error decompressing {z_file.name}: {e}")
