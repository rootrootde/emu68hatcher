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

    # dict.fromkeys dedupes while preserving order - install order matters for some amiga packages
    user_packages = [p.name for p in workflow.config.packages if p.enabled]
    user_lower = {n.lower() for n in user_packages}
    if workflow.config.network_stack:
        stack_name = workflow.config.network_stack.value.lower()
        if stack_name not in user_lower:
            user_packages.append(stack_name)
    mandatory = installer.get_mandatory_packages()
    all_packages = list(dict.fromkeys(user_packages + mandatory))

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
