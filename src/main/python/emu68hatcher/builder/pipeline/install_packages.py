"""install packages stage"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.staging.packages import PackageInstaller
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.data.package_loader import get_local_packages_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_install_packages(workflow: BuildWorkflow) -> None:
    """install selected packages to the disk image using YAML rules"""
    if not workflow.state.staging_dir:
        raise BuildError("Staging directory not set - setup stage may have failed")

    workflow._update_state(BuildStage.INSTALL_PACKAGES, 0.0)
    workflow._milestone("Installing packages")

    if not workflow.state.extracted_paths and not workflow.state.downloaded_files:
        workflow._update_state(progress=100.0)
        workflow._milestone("No packages to install")
        return

    extracted_dir = (
        workflow.state.extracted_dir
        if workflow.state.extracted_dir
        else (workflow.state.work_dir / "extracted")
    )

    local_packages_dir = get_local_packages_dir()

    ks_version = workflow.config.kickstart.version.value
    emu68_version = workflow.config.emu68_version.value
    installer = PackageInstaller(
        kickstart_version=ks_version,
        staging_dir=workflow.state.staging_dir,
        extracted_packages_dir=extracted_dir,
        local_packages_dir=local_packages_dir if local_packages_dir.exists() else None,
        emu68_version=emu68_version,
    )

    from emu68hatcher.builder.pipeline._selection import resolve_selection

    resolution = resolve_selection(workflow.config, ks_version, emu68_version)
    all_packages = resolution.install_order  # dep-before-dependent; independent order preserved
    for token, reqs in resolution.unsatisfiable.items():
        workflow.logger.warning(f"unsatisfiable dependency '{token}' required by {sorted(reqs)}")
    for name, reason in resolution.dropped.items():
        workflow.logger.info(f"dropped {name}: {reason}")

    workflow.logger.info(f"Installing {len(all_packages)} packages using YAML rules")

    total = len(all_packages)
    completed = 0
    files_installed = 0

    for package_name in all_packages:
        workflow._check_cancelled()

        workflow._update_state(
            progress=(completed / total) * 100 if total > 0 else 0,
        )
        workflow._milestone(f"Installing {package_name}")

        count = installer.install_package(package_name)
        files_installed += count

        if count > 0:
            workflow.logger.info(f"Installed {count} files for {package_name}")
        else:
            workflow.logger.debug(f"No files installed for {package_name} (may use ADF/CD source)")

        completed += 1

    workflow._update_state(progress=95.0)
    workflow._milestone("Applying script modifications")
    script_mods = installer.apply_script_modifications()
    if script_mods > 0:
        workflow.logger.info(f"Applied {script_mods} script modifications")

    workflow._update_state(progress=100.0)
    workflow._milestone(f"Installed {total} packages ({files_installed} files)")
