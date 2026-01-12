"""download, extract, and workspace setup stages"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.builder.amiga_files import prepare_staging_directory
from emu68hatcher.builder.downloads import (
    DownloadManager,
    get_emu68_boot_files,
    get_mandatory_packages,
    get_package_downloads,
    get_required_startup_files,
)
from emu68hatcher.extractor.archive import extract_archive
from emu68hatcher.utils.paths import get_temp_dir, ensure_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_setup_workspace(workflow: BuildWorkflow) -> None:
    """set up working directories"""
    workflow._update_state(BuildStage.INIT, 0.0)
    workflow._log("Setting up workspace")

    # create work directory
    workflow.state.work_dir = get_temp_dir()
    workflow.state.staging_dir = ensure_dir(workflow.state.work_dir / "staging")
    workflow.state.downloads_dir = ensure_dir(workflow.state.work_dir / "downloads")
    workflow.state.extracted_dir = ensure_dir(workflow.state.work_dir / "extracted")
    workflow.state.workbench_dir = ensure_dir(workflow.state.work_dir / "workbench")

    # prepare staging directories for each partition
    devices = ["EMU68BOOT"]
    if workflow.config.partitions:
        for mbr_part in workflow.config.partitions.layout:
            if mbr_part.amiga_partitions:
                for amiga_part in mbr_part.amiga_partitions:
                    devices.append(amiga_part.device)

    prepare_staging_directory(workflow.state.staging_dir, devices)

    workflow._update_state(progress=100.0)
    workflow._log("Workspace ready")


def _download_pfs3aio_if_needed(workflow: BuildWorkflow, manager: DownloadManager) -> None:
    """download PFS3AIO filesystem handler if any partition uses PFS3

    stores the handler path in workflow.state so create_image can use it
    without a separate network call.
    """
    from emu68hatcher.builder.hst_commands import Filesystem

    if not workflow.config.partitions:
        return

    uses_pfs3 = any(
        amiga_part.filesystem == Filesystem.PFS3
        for mbr_part in workflow.config.partitions.layout
        if mbr_part.amiga_partitions
        for amiga_part in mbr_part.amiga_partitions
    )

    if not uses_pfs3:
        return

    workflow._update_state(progress=2.0)
    workflow._log("Downloading PFS3AIO filesystem handler")
    startup_files = get_required_startup_files()

    for item in startup_files:
        if item.name == "pfs3aio":
            result = manager.download(item)
            if result.success and result.extracted_path:
                workflow.state.downloaded_files["pfs3aio"] = result.path
                workflow.state.extracted_paths["pfs3aio"] = result.extracted_path
                workflow.state.pfs3_handler_path = result.extracted_path
                workflow.logger.info(f"PFS3AIO handler ready: {result.extracted_path}")
            else:
                raise BuildError(f"Failed to download PFS3AIO filesystem handler: {result.error}")
            return

    raise BuildError("PFS3AIO not found in startup files configuration")


def stage_download(workflow: BuildWorkflow) -> None:
    """download required packages using the robust DownloadManager

    downloads ALL network resources upfront (Emu68 boot files, PFS3AIO
    filesystem handler, user packages) so network failures surface early,
    before any disk image work begins.
    """
    workflow._update_state(BuildStage.DOWNLOAD, 0.0)
    workflow._log("Preparing downloads")

    # create download manager with caching
    manager = DownloadManager(
        work_dir=workflow.state.downloads_dir,
        max_retries=3,
        timeout=120.0,
    )

    # download PFS3AIO filesystem handler if needed (must happen before CREATE_IMAGE)
    _download_pfs3aio_if_needed(workflow, manager)

    # download all Emu68 boot file variants (pistorm32lite + pistorm + pistorm16)
    workflow._update_state(progress=5.0)
    workflow._log("Downloading Emu68 boot files")
    emu68_items = get_emu68_boot_files()
    if emu68_items:
        workflow.logger.info(f"Downloading {len(emu68_items)} Emu68 boot file variant(s) from GitHub...")
        for item in emu68_items:
            result = manager.download(item)
            if result.success:
                workflow.state.downloaded_files[item.name] = result.path
                if result.extracted_path:
                    workflow.state.extracted_paths[item.name] = result.extracted_path
                workflow.logger.info(f"Downloaded Emu68 variant: {item.name} -> {result.path}")
            elif item.optional:
                workflow.logger.warning(f"Optional Emu68 variant failed (non-fatal): {item.name} - {result.error}")
            else:
                workflow.logger.error(f"Failed to download Emu68 boot files: {result.error}")
                raise BuildError(f"Failed to download required Emu68 boot files: {result.error}")
    else:
        workflow.logger.warning("Could not get Emu68 boot file download info from GitHub")

    # get user-selected packages (non-System packages from GUI)
    user_packages = [p for p in workflow.config.packages if p.enabled]
    user_package_names = [p.name for p in user_packages]

    # ensure the selected network stack package is included
    # (config.network_stack is set but the package may not be in the packages list)
    if workflow.config.network_stack:
        stack_name = workflow.config.network_stack.value.lower()
        if stack_name not in [n.lower() for n in user_package_names]:
            user_package_names.append(stack_name)
            workflow.logger.info(f"Added network stack package: {stack_name}")

    # get mandatory packages (all System group + any with mandatory=True)
    # note: get_mandatory_packages() from downloads.py returns list[str], not Package objects
    ks_version = workflow.config.kickstart.version.value
    mandatory_names = get_mandatory_packages(ks_version)

    # combine user-selected and mandatory packages (deduped)
    all_package_names = list(set(user_package_names + mandatory_names))
    workflow.state.packages_total = len(all_package_names)

    workflow.logger.info(f"User-selected packages: {user_package_names}")
    workflow.logger.info(f"Mandatory packages: {mandatory_names}")
    workflow.logger.info(f"Total packages to process: {len(all_package_names)}")

    if all_package_names:
        # get download items for all packages
        download_items = get_package_downloads(all_package_names, ks_version)

        if download_items:
            count = len(download_items)

            # item-start callback: one log entry per package, advances the bar
            def progress_callback(name: str, current: int, total: int) -> None:
                workflow._check_cancelled()
                progress = 20 + (current / total) * 80 if total > 0 else 20
                workflow._update_state(progress=progress)
                workflow._log(f"Downloading {name}")

            # byte-level callback: transient status row only (never logged)
            def file_progress(name: str, downloaded: int, total: int) -> None:
                if total > 0:
                    mb_down = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    workflow._update_state(
                        message=f"Downloading {name} - {mb_down:.1f}/{mb_total:.1f} MB"
                    )

            # download all packages
            workflow.logger.info(f"Downloading {count} packages...")
            results = manager.download_all(
                download_items, progress_callback, file_progress=file_progress
            )

            # process results
            for name, result in results.items():
                if result.success:
                    # store the archive path for potential re-extraction
                    if result.path:
                        workflow.state.downloaded_files[name] = result.path
                    # if already extracted by download manager, record the extracted path
                    if result.extracted_path:
                        workflow.state.extracted_paths[name] = result.extracted_path
                    workflow.state.packages_downloaded += 1
                    workflow.logger.info(f"Downloaded {name}: {result.path}")
                else:
                    workflow.logger.warning(f"Failed to download {name}: {result.error}")

            # log any packages that weren't in the download list
            downloaded_names = set(results.keys())
            for pkg_name in all_package_names:
                if pkg_name.lower() not in [n.lower() for n in downloaded_names]:
                    workflow.logger.info(f"Package {pkg_name} not configured for download (may be local or built-in)")

    workflow._update_state(progress=100.0)
    workflow._log(f"Downloaded {workflow.state.packages_downloaded + 1} items")


def stage_extract(workflow: BuildWorkflow) -> None:
    """extract downloaded archives"""
    workflow._update_state(BuildStage.EXTRACT, 0.0)
    workflow._log("Extracting archives")

    archive_extensions = {'.lha', '.zip', '.7z', '.tar', '.gz', '.tgz'}

    if not workflow.state.downloaded_files:
        workflow._update_state(progress=100.0)
        workflow._log("No archives to extract")
        # still check local packages below
    else:
        total = len(workflow.state.downloaded_files)
        completed = 0
        extracted_count = 0

        for package_name, archive_path in workflow.state.downloaded_files.items():
            workflow._check_cancelled()

            # if already extracted by download manager, ensure it's in the
            # standard extracted_dir so the package installer can find it
            if package_name in workflow.state.extracted_paths:
                dm_path = workflow.state.extracted_paths[package_name]
                std_path = workflow.state.extracted_dir / package_name
                if dm_path.is_dir() and dm_path != std_path and not std_path.exists():
                    std_path.symlink_to(dm_path)
                workflow.logger.info(f"Already extracted: {package_name}")
                extracted_count += 1
                completed += 1
                continue

            workflow._update_state(progress=(completed / total) * 80)
            workflow._log(f"Extracting {package_name}")

            # determine output directory for this package
            output_dir = workflow.state.extracted_dir / package_name

            # check if this is an archive or a raw binary file
            if archive_path.suffix.lower() not in archive_extensions:
                # raw binary file - just copy it to the output directory
                output_dir.mkdir(parents=True, exist_ok=True)
                dest_file = output_dir / archive_path.name
                shutil.copy2(archive_path, dest_file)
                workflow.state.extracted_paths[package_name] = output_dir
                extracted_count += 1
                workflow.logger.info(f"Copied raw file {package_name}: {archive_path.name}")
                completed += 1
                continue

            # per-file status update during extraction (flickers through filenames
            # in the status row, never logged). only fires for ZIP/TAR - the 7z/LHA
            # shell-out paths don't expose per-entry callbacks
            def on_extract_file(filename: str, current: int, total_files: int,
                                _pkg=package_name) -> None:
                workflow._update_state(
                    message=f"Extracting {_pkg}: {filename}"
                )

            # extract the archive
            result = extract_archive(archive_path, output_dir, progress_callback=on_extract_file)

            if result.success:
                workflow.state.extracted_paths[package_name] = result.output_dir
                extracted_count += 1
                workflow.logger.info(
                    f"Extracted {package_name}: {result.files_extracted} files to {result.output_dir}"
                )
            else:
                workflow.logger.warning(f"Failed to extract {package_name}: {result.error}")

            completed += 1

        workflow._update_state(progress=80.0)
        workflow._log(f"Extracted {extracted_count} of {total} downloaded packages")

    # extract local package archives (e.g., bundled Roadshow .lha)
    from pathlib import Path as _Path
    from emu68hatcher.data.package_loader import get_package_by_name as _get_pkg
    from emu68hatcher.data.package_schema import SourceType

    local_packages_dir = _Path(__file__).parent.parent.parent / "data" / "local_packages"

    # build full package name list (same logic as stage_download)
    user_package_names = [p.name for p in workflow.config.packages if p.enabled]
    if workflow.config.network_stack:
        stack_name = workflow.config.network_stack.value.lower()
        if stack_name not in [n.lower() for n in user_package_names]:
            user_package_names.append(stack_name)
    ks_version = workflow.config.kickstart.version.value
    mandatory_names = get_mandatory_packages(ks_version)
    all_package_names = list(set(user_package_names + mandatory_names))

    local_extracted = 0
    for pkg_name in all_package_names:
        if pkg_name in workflow.state.extracted_paths:
            continue  # already extracted from download
        pkg = _get_pkg(pkg_name)
        if not pkg or not pkg.download or pkg.download.source != SourceType.LOCAL:
            continue
        if not pkg.download.path:
            continue
        archive_path = local_packages_dir / pkg.download.path
        if not archive_path.exists() or archive_path.suffix.lower() not in archive_extensions:
            continue
        # extract the local archive
        output_dir = workflow.state.extracted_dir / pkg_name
        workflow._log(f"Extracting {pkg_name} (local)")

        def on_local_extract_file(filename: str, current: int, total_files: int,
                                  _pkg=pkg_name) -> None:
            workflow._update_state(
                message=f"Extracting {_pkg}: {filename}"
            )

        result = extract_archive(archive_path, output_dir,
                                 progress_callback=on_local_extract_file)
        if result.success:
            workflow.state.extracted_paths[pkg_name] = output_dir
            local_extracted += 1
            workflow.logger.info(f"Extracted local archive {pkg_name}: {result.files_extracted} files")
        else:
            workflow.logger.warning(f"Failed to extract local archive {pkg_name}: {result.error}")

    workflow._update_state(progress=100.0)
    workflow._log(
        "Extraction complete" + (f" ({local_extracted} local)" if local_extracted else "")
    )
