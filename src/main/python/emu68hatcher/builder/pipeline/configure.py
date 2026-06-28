"""configure Amiga system stage - orchestrates script, boot, and prefs phases"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.pipeline.configure_boot import configure_boot_partition
from emu68hatcher.builder.pipeline.configure_prefs import (
    configure_preferences,
    stage_whdload_kickstarts,
)
from emu68hatcher.builder.pipeline.configure_scripts import configure_scripts
from emu68hatcher.builder.pipeline.relocate import apply_relocations
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.defaults import DEFAULT_BOOT_DEVICE
from emu68hatcher.utils.paths import ensure_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_configure(workflow: BuildWorkflow) -> None:
    """configure stage: scripts (injections, startup, FirstBoot), boot partition (Emu68/ROM/config), prefs"""
    if not workflow.state.staging_dir or not workflow.state.staging_dir.exists():
        raise BuildError("Staging directory not available - setup stage may have failed")
    if not workflow.state.resolved_rom_path:
        raise BuildError("ROM not resolved - validate stage may have failed")

    workflow._update_state(BuildStage.CONFIGURE, 0.0)
    workflow._milestone("Configuring system")

    boot_device = _resolve_boot_device(workflow)
    boot_staging = workflow.state.staging_dir / boot_device
    s_dir = ensure_dir(boot_staging / "S")
    prefs_dir = ensure_dir(boot_staging / "Prefs")
    env_archive = ensure_dir(prefs_dir / "Env-Archive")
    ensure_dir(boot_staging / "Devs" / "DOSDrivers")

    all_packages = _collect_enabled_packages(workflow)

    # phase 1: Script configuration (0-40%)
    configure_scripts(workflow, boot_staging, s_dir, all_packages)

    # relocate stock OS files per enabled packages (e.g. commodity -> WBStartup)
    moved = apply_relocations(workflow, boot_staging, all_packages)
    if moved:
        workflow.logger.info(f"Relocated {moved} staged file(s)")

    # phase 2: Boot partition setup (40-70%)
    configure_boot_partition(workflow)

    if "whdload" in all_packages:
        stage_whdload_kickstarts(workflow, boot_staging)

    # phase 3: System preferences (70-100%)
    configure_preferences(workflow, boot_staging, prefs_dir, env_archive)

    workflow._update_state(progress=100.0)
    workflow._milestone("System configured")


def _resolve_boot_device(workflow: BuildWorkflow) -> str:
    """find the bootable Amiga device name from partition config"""
    if not workflow.config.partitions:
        return DEFAULT_BOOT_DEVICE
    return workflow.config.partitions.bootable_device or DEFAULT_BOOT_DEVICE


def _collect_enabled_packages(workflow: BuildWorkflow) -> set[str]:
    """all package names to install (user-selected + mandatory + resolved deps)"""
    from emu68hatcher.builder.pipeline._selection import resolve_selection

    ks_version = workflow.config.kickstart.version.value
    emu68_version = workflow.config.emu68_version.value
    return resolve_selection(workflow.config, ks_version, emu68_version).selected
