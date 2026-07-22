"""download and workspace setup stages"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.host.download_catalog import (
    get_emu68_boot_files,
    get_mandatory_packages,
    get_package_downloads,
    get_required_startup_files,
)
from emu68hatcher.builder.host.downloads import DownloadManager
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
    boot_device = None
    if workflow.config.partitions:
        devices.extend(p.device for p in workflow.config.partitions.iter_amiga_partitions())
        boot_device = workflow.config.partitions.bootable_device

    prepare_staging_directory(workflow.state.staging_dir, devices, boot_device=boot_device)

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

    from emu68hatcher.utils.host_tools import find_hst_imager, localize_for_hst, run_hst_extract

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
        for d in (Path(p) for p in workflow.config.asset_directories):
            if not d.exists():
                continue
            candidates = sorted(p for p in d.rglob("*.adf") if p.name.lower().startswith("install"))
            if candidates:
                install_adf = candidates[0]
                break

    if install_adf is None or not install_adf.exists():
        dirs_str = ", ".join(str(d) for d in workflow.config.asset_directories) or "(none)"
        raise BuildError(
            "FFS partition selected but no Install ADF found to extract "
            f"L/FastFileSystem from. Asset directories: {dirs_str}. "
            "Place an Install3.x.adf in one of them."
        )

    hst_imager = find_hst_imager()
    if not hst_imager:
        raise BuildError("hst-imager not available; cannot extract FFS handler")

    try:
        install_adf = localize_for_hst(install_adf, workflow.state.extracted_dir / "network_media")
    except OSError as e:
        raise BuildError(f"Cannot copy {install_adf.name} from network path: {e}") from e

    scratch = ensure_dir(workflow.state.extracted_dir / "ffs_handler")
    workflow._update_state(progress=3.0)
    workflow._milestone("Extracting FFS handler from Install ADF")
    result = run_hst_extract(
        hst_imager,
        f"{install_adf.as_posix()}/L/FastFileSystem",
        scratch.as_posix() + "/",
        uaemetadata="UaeFsDb",
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

    # resolver gives the full set: user-enabled + network stack + mandatory + anything
    # pulled in via requires. download has to see the requires deps or they never reach install.
    from emu68hatcher.builder.pipeline._selection import get_resolution

    ks_version = workflow.config.kickstart.version.value
    emu68_version = workflow.config.emu68_version.value
    all_package_names = get_resolution(workflow).install_order

    # a user-supplied Picasso96 archive replaces the aminet download; drop it from the fetch
    # list so the aminet .lha is neither downloaded nor extracted over the staged user archive
    download_names = all_package_names
    if workflow.state.picasso96_archive_path is not None:
        download_names = [n for n in all_package_names if n != "picasso96"]

    # only genuinely-mandatory packages are fatal on download failure; a requires-pulled
    # dep of an optional app fails as a warning (the app just won't be usable).
    mandatory_names = get_mandatory_packages(ks_version, emu68_version)

    workflow.logger.info(f"Total packages to process: {len(all_package_names)}")

    if all_package_names:
        download_items = get_package_downloads(download_names)

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
