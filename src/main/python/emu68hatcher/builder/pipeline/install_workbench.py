"""install Workbench files from ADFs stage"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.staging.files import FileMapping, stage_files
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.data.install_media import scan_install_media_by_hash

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def _filter_needed_media(media, ks_version):
    """ADFs referenced by this KS version's rules, deduped by name -> (paths, friendly names)"""
    from emu68hatcher.data.package_loader import get_adf_rules_for_version

    needed = {r.adf for r in get_adf_rules_for_version(ks_version)}
    seen: set[str] = set()
    picked = []
    for m in media:
        if m.adf_name in needed and m.adf_name not in seen:
            picked.append(m)
            seen.add(m.adf_name)
    return [m.path for m in picked], sorted({m.friendly_name for m in picked})


def stage_install_workbench(workflow: BuildWorkflow) -> None:
    """install Workbench files from ADFs"""
    if not workflow.state.staging_dir or not workflow.state.workbench_dir:
        raise BuildError("Staging or workbench directory not set - setup stage may have failed")

    workflow._update_state(BuildStage.INSTALL_WORKBENCH, 0.0, "Installing Workbench...")

    # get ADF paths to extract - prefer hash-identified media
    adf_paths: list[Path] = []
    media_description = ""

    if workflow.state.resolved_install_media:
        # filter to only ADFs referenced by extraction rules for this KS version
        ks_version = workflow.config.kickstart.version.value
        adf_paths, media_names = _filter_needed_media(
            workflow.state.resolved_install_media, ks_version
        )
        media_description = f"{len(adf_paths)} ADFs for KS {ks_version}"
        # not all of these will actually be extracted (e.g. locale ADFs for unenabled languages)
        workflow.logger.info(f"Identified {media_description}: {', '.join(media_names)}")

    # last resort: try scanning again if validation didn't find anything
    if not adf_paths:
        workflow.logger.info("No pre-resolved media, attempting direct ADF scan...")
        scan_dirs = [Path(p) for p in workflow.config.asset_directories if Path(p).exists()]

        if scan_dirs:
            workflow.logger.info(
                f"Scanning {len(scan_dirs)} asset director"
                f"{'ies' if len(scan_dirs) != 1 else 'y'} for ADFs..."
            )
            found_media, _ = scan_install_media_by_hash(scan_dirs)
            if found_media:
                adf_paths, _ = _filter_needed_media(
                    found_media, workflow.config.kickstart.version.value
                )
                media_description = f"{len(adf_paths)} ADFs"
                workflow.logger.info(f"Direct scan found: {media_description}")

    if not adf_paths:
        raise BuildError(
            "No Workbench disks detected. "
            "Add a directory containing your Workbench ADF files to the Amiga Files tab."
        )

    workflow._update_state(progress=10.0)
    workflow._milestone(f"Extracting {media_description}")

    total_files, errors = _extract_adfs_with_rules(workflow, adf_paths)

    if errors:
        workflow.logger.warning(f"Some ADF extractions failed: {'; '.join(errors[:5])}")

    if total_files == 0:
        raise BuildError(
            "ADF extraction produced no files - hst-imager could not read the "
            "Workbench ADFs. Check the build log for extraction errors."
        )

    workflow._update_state(progress=50.0)
    workflow._milestone("Copying Workbench files to staging")

    # find the boot partition - first bootable Amiga partition wins
    from emu68hatcher.builder.pipeline.configure import _resolve_boot_device

    boot_device = _resolve_boot_device(workflow)

    # decompress .Z files for Workbench 3.2.x (uses Unix compress format)
    ks_version = workflow.config.kickstart.version.value
    if ks_version.startswith("3.2"):
        _decompress_z_files(workflow, workflow.state.workbench_dir)

    file_mapping = FileMapping()
    file_mapping.add_directory(
        workflow.state.workbench_dir,
        "",  # root of the partition
        device=boot_device,
        recursive=True,
    )

    files_staged = stage_files(file_mapping, workflow.state.staging_dir)

    workflow.logger.info(f"Staged {files_staged} Workbench files to {boot_device}")
    workflow._update_state(progress=100.0)
    workflow._milestone(f"Workbench installed ({files_staged} files)")


def _extract_adfs_with_rules(
    workflow: BuildWorkflow, adf_paths: list[Path]
) -> tuple[int, list[str]]:
    """extract ADFs per adf_rules.yaml - mirrors upstream Emu68 Imager file/folder picks per ADF"""
    from emu68hatcher.utils.host_tools import find_hst_imager

    hst_imager = find_hst_imager()
    if not hst_imager:
        # fatal: silently producing 0 files trips later stages on the empty Workbench dir
        raise BuildError("HST Imager not found - run 'emu68hatcher tools setup' first")

    adf_name_to_path = _build_adf_name_map(workflow, adf_paths)
    adf_rules = _resolve_adf_rules(workflow)
    return _run_extraction_rules(workflow, adf_rules, adf_name_to_path, hst_imager)


def _build_adf_name_map(workflow: BuildWorkflow, adf_paths: list[Path]) -> dict[str, Path]:
    """resolve every ADF (hash-detected + filename-guessed) to an ADF-name -> path map"""
    ks_version = workflow.config.kickstart.version.value

    # ADF name ("Workbench3_2") -> path
    adf_name_to_path: dict[str, Path] = {}
    if workflow.state.resolved_install_media:
        for media in workflow.state.resolved_install_media:
            adf_name_to_path[media.adf_name] = media.path

            # also alias sub-version to base: "Workbench3_2_3" -> "Workbench3_2"
            match = re.match(r"^(.+\d+_\d+)_\d+$", media.adf_name)
            if match:
                base_name = match.group(1)
                if base_name not in adf_name_to_path:
                    adf_name_to_path[base_name] = media.path

    # map remaining ADFs by filename pattern (anything not hash-detected)
    for adf_path in adf_paths:
        stem = adf_path.stem.lower()

        # locale-specific ADFs (LocaleDE, LocaleFR, ...)
        locale_match = re.match(r"^locale([a-z]{2}).*$", stem)
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

        # try common patterns for other ADFs - keep this list aligned with the
        # ADF names in install_media.py REQUIRED so a non-hash-matched dump (a
        # redump or fresh Hyperion ISO rip) still resolves by name fragment.
        for name_pattern in [
            "workbench",
            "extras",
            "fonts",
            "storage",
            "locale",
            "install",
            "classes",
            "backdrops",
            "update",
            "diskdoctor",
        ]:
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
    return adf_name_to_path


def _resolve_adf_rules(workflow: BuildWorkflow) -> list:
    """resolved package set -> filtered ADF extraction rules for this Kickstart"""
    from emu68hatcher.builder.pipeline._selection import resolve_selection
    from emu68hatcher.data.package_loader import get_filtered_adf_rules

    ks_version = workflow.config.kickstart.version.value
    emu68_version = workflow.config.emu68_version.value

    # full resolved set (incl. requires-pulled) so a dep's optional ADF rule isn't missed
    enabled_packages = resolve_selection(workflow.config, ks_version, emu68_version).selected
    workflow.logger.debug(f"Enabled packages for ADF rules: {enabled_packages}")

    user_icon_set = getattr(workflow.config, "icon_set", "Standard") or "Standard"

    adf_rules = get_filtered_adf_rules(ks_version, enabled_packages, user_icon_set)
    workflow.logger.info(f"Found {len(adf_rules)} ADF extraction rules for Kickstart {ks_version}")
    return adf_rules


def _run_extraction_rules(
    workflow: BuildWorkflow,
    adf_rules: list,
    adf_name_to_path: dict[str, Path],
    hst_imager: Path,
) -> tuple[int, list[str]]:
    """run each ADF rule through hst-imager; return (file_count, errors)"""
    from emu68hatcher.utils.host_tools import localize_for_hst, run_hst_extract

    errors: list[str] = []
    processed_rules = 0
    last_logged_adf: str | None = None

    for rule in adf_rules:
        # cancel honored between hst-imager invocations (no mid-run kill)
        workflow._check_cancelled()

        source_location = rule.adf  # ADF name like "Workbench3_1"
        files_to_install = rule.source  # pattern like "*" or "C/*"
        location_to_install = rule.dest.rstrip("/")
        copy_recursive = rule.recursive
        new_file_name = rule.rename

        adf_path = adf_name_to_path.get(source_location)
        if not adf_path:
            # exact match with different separators (e.g., Classes3_2_3 vs Classes 3.2.3)
            for name, path in adf_name_to_path.items():
                norm_source = (
                    source_location.lower().replace("_", "").replace(" ", "").replace(".", "")
                )
                norm_name = name.lower().replace("_", "").replace(" ", "").replace(".", "")
                if norm_source == norm_name:
                    adf_path = path
                    workflow.logger.debug(f"Matched {source_location} -> {name} via normalization")
                    break

        if not adf_path:
            if rule.mandatory:
                workflow.logger.warning(
                    f"Missing ADF for mandatory rule: {source_location} (need {files_to_install})"
                )
            continue

        try:
            adf_path = localize_for_hst(adf_path, workflow.state.extracted_dir / "network_media")
        except OSError as e:
            errors.append(f"{source_location}: copy from network path failed: {e}")
            continue

        dest_dir = (
            workflow.state.workbench_dir / location_to_install
            if location_to_install
            else workflow.state.workbench_dir
        )
        dest_dir.mkdir(parents=True, exist_ok=True)

        # hst-imager splits on "/", so normalise windows backslashes in adf_path first
        adf_posix = adf_path.as_posix()
        source_path = f"{adf_posix}/{files_to_install}" if files_to_install else adf_posix

        if new_file_name:
            dest_path = str(dest_dir / new_file_name)
        else:
            dest_path = dest_dir.as_posix() + "/"

        try:
            # _UAEFSDB.___ sidecars preserve script bit through ADF -> PFS3 (else SYS:System/Help fails)
            result = run_hst_extract(
                hst_imager,
                source_path,
                dest_path,
                uaemetadata="UaeFsDb",
                recursive=copy_recursive,
            )

            if result.returncode == 0:
                processed_rules += 1
                if new_file_name:
                    _normalize_rename_case(Path(dest_path))
            else:
                # not all failures are errors - some patterns might not match
                if (
                    "not found" not in result.stdout.lower()
                    and "not found" not in result.stderr.lower()
                ):
                    errors.append(
                        f"{source_location}/{files_to_install}: {result.stderr or result.stdout}"
                    )
                elif rule.mandatory:
                    # "Path not found" also covers an unreadable ADF, so a mandatory
                    # rule failing this way must not disappear into the pattern-no-match case
                    workflow.logger.warning(
                        f"Extraction failed for mandatory rule {source_location}/{files_to_install}"
                    )
        except subprocess.TimeoutExpired:
            errors.append(f"{source_location}/{files_to_install}: Timeout")
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(f"{source_location}/{files_to_install}: {e}")

        # update progress + status (transient, not logged per rule)
        progress = 10.0 + (40.0 * processed_rules / max(len(adf_rules), 1))
        workflow._update_state(
            progress=progress,
            message=f"Extracting {source_location}: {files_to_install}",
        )
        # log once per ADF source (many rules typically share one ADF)
        if source_location != last_logged_adf:
            workflow._milestone(f"Extracting from {source_location}")
            last_logged_adf = source_location

    total_files = 0
    if workflow.state.workbench_dir.exists():
        total_files = sum(1 for _ in workflow.state.workbench_dir.rglob("*") if _.is_file())

    workflow.logger.info(
        f"Extracted {total_files} files from ADFs using {processed_rules} YAML rules"
    )

    return total_files, errors


def _normalize_rename_case(target: Path) -> None:
    # hst-imager case-folds dest against existing files (.NET): extracting to
    # S/Startup-Sequence when S/Startup-sequence is there keeps the lowercase name.
    if target.exists():
        return
    if not target.parent.is_dir():
        return
    target_lower = target.name.lower()
    for sibling in target.parent.iterdir():
        if sibling.is_file() and sibling.name.lower() == target_lower:
            sibling.rename(target)
            return


def _decompress_z_files(workflow: BuildWorkflow, directory: Path) -> None:
    """decompress .Z files (Unix compress) used in Workbench 3.2.x, via 7-Zip"""
    from emu68hatcher.utils.host_tools import find_7z

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
            result = subprocess.run(
                [str(sevenz), "e", str(z_file), f"-o{z_file.parent}", "-y"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=z_file.parent,
            )
            if result.returncode == 0:
                z_file.unlink()
            else:
                workflow.logger.warning(f"Failed to decompress {z_file.name}: {result.stderr}")
        except (OSError, subprocess.SubprocessError):
            workflow.logger.exception(f"Error decompressing {z_file.name}")
