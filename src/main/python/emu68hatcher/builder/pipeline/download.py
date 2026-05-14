"""download, extract, and workspace setup stages"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.host.archive import extract_archive
from emu68hatcher.builder.host.downloads import (
    DownloadManager,
    get_emu68_boot_files,
    get_mandatory_packages,
    get_package_downloads,
    get_required_startup_files,
)
from emu68hatcher.builder.staging.files import prepare_staging_directory
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.defaults import EMU68_BOOT_PARTITION_NAME
from emu68hatcher.utils.paths import ensure_dir, make_temp_workdir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_setup_workspace(workflow: BuildWorkflow) -> None:
    """set up working directories"""
    workflow._update_state(BuildStage.INIT, 0.0)
    workflow._milestone("Setting up workspace")

    workflow.state.work_dir = make_temp_workdir()
    workflow.state.staging_dir = ensure_dir(workflow.state.work_dir / "staging")
    workflow.state.downloads_dir = ensure_dir(workflow.state.work_dir / "downloads")
    workflow.state.extracted_dir = ensure_dir(workflow.state.work_dir / "extracted")
    workflow.state.workbench_dir = ensure_dir(workflow.state.work_dir / "workbench")

    devices = [EMU68_BOOT_PARTITION_NAME]
    if workflow.config.partitions:
        devices.extend(p.device for p in workflow.config.partitions.iter_amiga_partitions())

    prepare_staging_directory(workflow.state.staging_dir, devices)

    workflow._update_state(progress=100.0)
    workflow._milestone("Workspace ready")


def _download_pfs3aio_if_needed(workflow: BuildWorkflow, manager: DownloadManager) -> None:
    """download PFS3AIO FS handler if any partition uses PFS3. path stored on workflow.state for create_image"""
    if not workflow.config.partitions or not workflow.config.partitions.uses_pfs3:
        return

    workflow._update_state(progress=2.0)
    workflow._milestone("Downloading PFS3AIO filesystem handler")
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


def _extract_ffs_handler_if_needed(workflow: BuildWorkflow) -> None:
    """extract L/FastFileSystem from Install ADF if any partition uses FFS (Intl needs a registered RDB handler)"""
    if not workflow.config.partitions or not workflow.config.partitions.uses_ffs:
        return

    import subprocess
    from pathlib import Path

    from emu68hatcher.utils.host_tools import find_hst_imager

    # match KS and WB on parsed version tuples (string startswith would treat "3.1" as a prefix of "3.10")
    ks_version = workflow.config.kickstart.version.value
    ks_parts = tuple(ks_version.split("."))

    def _versions_match(wbv: str) -> bool:
        if not wbv:
            return False
        wb_parts = tuple(wbv.split("."))
        prefix_len = min(len(ks_parts), len(wb_parts))
        return ks_parts[:prefix_len] == wb_parts[:prefix_len]

    install_adf: Path | None = None
    for m in workflow.state.resolved_install_media:
        if "install" not in m.adf_name.lower():
            continue
        if _versions_match(m.workbench_version or ""):
            install_adf = m.path
            break

    # filename fallback (sorted for determinism across filesystems / repeated runs)
    if install_adf is None:
        scan_dirs: list[Path] = []
        if workflow.config.install_media and workflow.config.install_media.directory:
            scan_dirs.append(Path(workflow.config.install_media.directory))
        if workflow.config.kickstart.rom_directory:
            scan_dirs.append(Path(workflow.config.kickstart.rom_directory))
        for d in scan_dirs:
            if not d.exists():
                continue
            candidates = sorted(p for p in d.rglob("*.adf") if p.name.lower().startswith("install"))
            if candidates:
                install_adf = candidates[0]
                break

    if install_adf is None or not install_adf.exists():
        checked = (
            ", ".join(
                str(d)
                for d in (
                    workflow.config.install_media.directory
                    if workflow.config.install_media
                    else None,
                    workflow.config.kickstart.rom_directory,
                )
                if d
            )
            or "(no directories configured)"
        )
        raise BuildError(
            "FFS partition selected but no Install ADF found to extract "
            f"L/FastFileSystem from. Checked: {checked}. "
            "Place an Install3.x.adf in the ADF or ROM directory."
        )

    hst_imager = find_hst_imager()
    if not hst_imager:
        raise BuildError("hst-imager not available; cannot extract FFS handler")

    scratch = ensure_dir(workflow.state.extracted_dir / "ffs_handler")
    args = [
        str(hst_imager),
        "fs",
        "extract",
        f"{install_adf.as_posix()}/L/FastFileSystem",
        scratch.as_posix() + "/",
        "--force",
        "TRUE",
        "--uaemetadata",
        "UaeFsDb",
    ]
    workflow._update_state(progress=3.0)
    workflow._milestone("Extracting FFS handler from Install ADF")
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    handler = scratch / "FastFileSystem"
    if result.returncode != 0 or not handler.exists():
        raise BuildError(
            f"Failed to extract L/FastFileSystem from {install_adf.name}: "
            f"{result.stderr.strip() or result.stdout.strip() or 'handler not found'}"
        )
    workflow.state.ffs_handler_path = handler
    workflow.logger.info(f"FFS handler ready: {handler}")


def stage_download(workflow: BuildWorkflow) -> None:
    """download all network resources (Emu68 boot files, PFS3AIO handler, user packages) abort on any failures"""
    workflow._update_state(BuildStage.DOWNLOAD, 0.0)
    workflow._milestone("Preparing downloads")

    manager = DownloadManager(
        work_dir=workflow.state.downloads_dir,
        max_retries=3,
        timeout=120.0,
        # bail out early on flaky mirrors / dead DNS instead of waiting for socket timeout
        cancel_callback=lambda: workflow._cancelled,
    )

    # PFS3AIO must be available before CREATE_IMAGE
    _download_pfs3aio_if_needed(workflow, manager)

    _extract_ffs_handler_if_needed(workflow)

    # both Emu68 variants for the selected release (asset names differ between 1.0.7 and 1.1+)
    workflow._update_state(progress=5.0)
    workflow._milestone(f"Downloading Emu68 {workflow.config.emu68_version.value} boot files")
    emu68_items = get_emu68_boot_files(version=workflow.config.emu68_version.value)
    if emu68_items:
        workflow.logger.info(
            f"Downloading {len(emu68_items)} Emu68 boot file variant(s) from GitHub..."
        )
        for item in emu68_items:
            result = manager.download(item)
            if result.success:
                workflow.state.downloaded_files[item.name] = result.path
                if result.extracted_path:
                    workflow.state.extracted_paths[item.name] = result.extracted_path
                workflow.logger.info(f"Downloaded Emu68 variant: {item.name} -> {result.path}")
            elif item.optional:
                workflow.logger.warning(
                    f"Optional Emu68 variant failed (non-fatal): {item.name} - {result.error}"
                )
            else:
                workflow.logger.error(f"Failed to download Emu68 boot files: {result.error}")
                raise BuildError(f"Failed to download required Emu68 boot files: {result.error}")
    else:
        workflow.logger.warning("Could not get Emu68 boot file download info from GitHub")

    user_package_names = [p.name for p in workflow.config.packages if p.enabled]
    user_lower = {n.lower() for n in user_package_names}

    # include the network stack set in config (not in packages[])
    if workflow.config.network_stack:
        stack_name = workflow.config.network_stack.value.lower()
        if stack_name not in user_lower:
            user_package_names.append(stack_name)
            workflow.logger.info(f"Added network stack package: {stack_name}")

    # get mandatory packages (all System group + any mandatory=True)
    ks_version = workflow.config.kickstart.version.value
    mandatory_names = get_mandatory_packages(ks_version)

    # dict.fromkeys dedupes while preserving order (set() would shuffle via hash randomisation)
    all_package_names = list(dict.fromkeys(user_package_names + mandatory_names))

    workflow.logger.info(f"User-selected packages: {user_package_names}")
    workflow.logger.info(f"Mandatory packages: {mandatory_names}")
    workflow.logger.info(f"Total packages to process: {len(all_package_names)}")

    if all_package_names:
        download_items = get_package_downloads(all_package_names)

        if download_items:
            count = len(download_items)

            def progress_callback(name: str, current: int, total: int) -> None:
                workflow._check_cancelled()
                progress = 20 + (current / total) * 80 if total > 0 else 20
                workflow._update_state(progress=progress)
                # status label only - the download manager logs cached/downloading separately
                workflow._log(f"Working on {name}")

            def file_progress(name: str, downloaded: int, total: int) -> None:
                if total > 0:
                    mb_down = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    workflow._update_state(
                        message=f"Downloading {name} - {mb_down:.1f}/{mb_total:.1f} MB"
                    )

            workflow.logger.info(f"Downloading {count} packages...")
            results = manager.download_all(
                download_items, progress_callback, file_progress=file_progress
            )

            mandatory_set = {n.lower() for n in mandatory_names}
            mandatory_failures: list[str] = []
            optional_failures: list[str] = []
            for name, result in results.items():
                if result.success:
                    if result.path:
                        workflow.state.downloaded_files[name] = result.path
                    if result.extracted_path:
                        workflow.state.extracted_paths[name] = result.extracted_path
                    workflow.logger.info(f"Downloaded {name}: {result.path}")
                else:
                    # hard-fail on mandatory
                    if name.lower() in mandatory_set:
                        mandatory_failures.append(f"{name}: {result.error}")
                        workflow.logger.error(f"Mandatory package failed: {name}: {result.error}")
                    else:
                        optional_failures.append(f"{name}: {result.error}")
                        workflow.logger.warning(f"Optional package failed: {name}: {result.error}")

            if optional_failures:
                workflow.logger.warning(
                    f"{len(optional_failures)} optional package(s) skipped: "
                    + ", ".join(f.split(":", 1)[0] for f in optional_failures)
                )

            if mandatory_failures:
                detail = "\n  - ".join(mandatory_failures)
                blob = " ".join(mandatory_failures).lower()
                if "hash mismatch" in blob:
                    kind = "hash mismatch"
                elif any(s in blob for s in ("getaddrinfo", "name or service", "nodename nor")):
                    kind = "DNS lookup failed"
                elif "not yet valid" in blob or "has expired" in blob:
                    kind = "TLS certificate not yet valid / expired"
                elif "certificate" in blob or "ssl:" in blob:
                    kind = "TLS handshake failed"
                else:
                    kind = "download failed"
                raise BuildError(f"{kind}:\n  - " + detail)

            downloaded_names = set(results.keys())
            for pkg_name in all_package_names:
                if pkg_name.lower() not in [n.lower() for n in downloaded_names]:
                    workflow.logger.info(
                        f"Package {pkg_name} not configured for download (may be local or built-in)"
                    )

    workflow._update_state(progress=100.0)
    workflow._milestone(f"Downloaded {len(workflow.state.downloaded_files)} items")


def stage_extract(workflow: BuildWorkflow) -> None:
    """extract downloaded archives"""
    workflow._update_state(BuildStage.EXTRACT, 0.0)
    workflow._milestone("Extracting archives")

    import re

    from emu68hatcher.builder.host.archive import ARCHIVE_EXTENSIONS

    archive_extensions = ARCHIVE_EXTENSIONS
    # safe package names - no slashes, dots-only, or empties (used as path components)
    _safe_pkg = re.compile(r"^[\w][\w.+-]*$")

    if not workflow.state.downloaded_files:
        workflow._update_state(progress=100.0)
        workflow._milestone("No archives to extract")
        # still check local packages below
    else:
        total = len(workflow.state.downloaded_files)
        completed = 0
        extracted_count = 0

        for package_name, archive_path in workflow.state.downloaded_files.items():
            workflow._check_cancelled()
            if not _safe_pkg.match(package_name):
                raise BuildError(f"refusing unsafe package name from YAML: {package_name!r}")

            # mirror download-manager extractions into extracted_dir (symlink, copy on windows w/o privilege)
            if package_name in workflow.state.extracted_paths:
                dm_path = workflow.state.extracted_paths[package_name]
                std_path = workflow.state.extracted_dir / package_name
                if dm_path.is_dir() and dm_path != std_path and not std_path.exists():
                    std_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        std_path.symlink_to(dm_path, target_is_directory=True)
                    except (OSError, NotImplementedError):
                        # WinError 1314 (no symlink privilege) or similar - fall back to copying
                        shutil.copytree(dm_path, std_path)
                workflow.logger.info(f"Already extracted: {package_name}")
                extracted_count += 1
                completed += 1
                continue

            workflow._update_state(progress=(completed / total) * 80)
            workflow._milestone(f"Extracting {package_name}")

            output_dir = workflow.state.extracted_dir / package_name

            if archive_path.suffix.lower() not in archive_extensions:
                # raw binary, not an archive - just copy it through
                output_dir.mkdir(parents=True, exist_ok=True)
                dest_file = output_dir / archive_path.name
                shutil.copy2(archive_path, dest_file)
                workflow.state.extracted_paths[package_name] = output_dir
                extracted_count += 1
                workflow.logger.info(f"Copied raw file {package_name}: {archive_path.name}")
                completed += 1
                continue

            def on_extract_file(
                filename: str, current: int, total_files: int, _pkg=package_name
            ) -> None:
                workflow._update_state(message=f"Extracting {_pkg}: {filename}")

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
        workflow._milestone(f"Extracted {extracted_count} of {total} downloaded packages")

    # extract bundled package archives
    from emu68hatcher.data.package_loader import (
        get_local_packages_dir,
        get_package_by_name,
    )
    from emu68hatcher.data.package_schema import SourceType

    local_packages_dir = get_local_packages_dir()

    # build full package name list (same logic as stage_download)
    user_package_names = [p.name for p in workflow.config.packages if p.enabled]
    user_lower = {n.lower() for n in user_package_names}
    if workflow.config.network_stack:
        stack_name = workflow.config.network_stack.value.lower()
        if stack_name not in user_lower:
            user_package_names.append(stack_name)
    ks_version = workflow.config.kickstart.version.value
    mandatory_names = get_mandatory_packages(ks_version)
    all_package_names = list(dict.fromkeys(user_package_names + mandatory_names))

    local_extracted = 0
    for pkg_name in all_package_names:
        if pkg_name in workflow.state.extracted_paths:
            continue  # already extracted from download
        pkg = get_package_by_name(pkg_name)
        if not pkg or not pkg.download or pkg.download.source != SourceType.LOCAL:
            continue
        if not pkg.download.path:
            continue
        archive_path = local_packages_dir / pkg.download.path
        if not archive_path.exists() or archive_path.suffix.lower() not in archive_extensions:
            continue
        output_dir = workflow.state.extracted_dir / pkg_name
        workflow._milestone(f"Extracting {pkg_name} (local)")

        def on_local_extract_file(
            filename: str, current: int, total_files: int, _pkg=pkg_name
        ) -> None:
            workflow._update_state(message=f"Extracting {_pkg}: {filename}")

        result = extract_archive(archive_path, output_dir, progress_callback=on_local_extract_file)
        if result.success:
            workflow.state.extracted_paths[pkg_name] = output_dir
            local_extracted += 1
            workflow.logger.info(
                f"Extracted local archive {pkg_name}: {result.files_extracted} files"
            )
        else:
            workflow.logger.warning(f"Failed to extract local archive {pkg_name}: {result.error}")

    workflow._update_state(progress=100.0)
    workflow._milestone(
        "Extraction complete" + (f" ({local_extracted} local)" if local_extracted else "")
    )
