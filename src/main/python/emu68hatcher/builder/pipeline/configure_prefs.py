"""Ordered preference configuration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.pipeline.configure_hardware import (
    configure_hardware,
    stage_whdload_kickstarts,
)
from emu68hatcher.builder.pipeline.configure_icons import configure_icons
from emu68hatcher.builder.pipeline.configure_network import (
    configure_network,
    generate_wireless_prefs,
)
from emu68hatcher.builder.state import CreatedImage
from emu68hatcher.utils.paths import ensure_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow

__all__ = ["configure_preferences", "stage_whdload_kickstarts"]


def configure_preferences(
    workflow: BuildWorkflow,
    image: CreatedImage,
    boot_staging: Path,
    prefs_dir: Path,
    env_archive: Path,
) -> None:
    from emu68hatcher.builder.staging.prefs import install_default_prefs

    workflow._update_state(progress=70.0)
    workflow._milestone("Configuring Amiga preferences")
    install_default_prefs(prefs_dir)
    workflow.logger.info("Configured Amiga preferences (wbpattern + env vars)")

    if workflow.config.wifi:
        workflow._update_state(progress=80.0)
        workflow._milestone("Configuring WiFi")
        sys_dir = ensure_dir(env_archive / "Sys")
        (sys_dir / "wireless.prefs").write_text(
            generate_wireless_prefs(
                workflow.config.wifi.ssid,
                workflow.config.wifi.password,
            ),
            encoding="iso-8859-1",
            newline="\n",
        )
        workflow.logger.info("Generated wireless.prefs")
    if workflow.config.network_stack is not None:
        configure_network(workflow, boot_staging)

    workflow._update_state(progress=85.0)
    workflow._milestone("Configuring hardware")
    configure_hardware(workflow, image, boot_staging)

    workflow._update_state(progress=90.0)
    workflow._milestone("Generating drawer icons")
    configure_icons(workflow, image, boot_staging)

    workflow._update_state(progress=97.0)
    workflow._milestone("Arranging icons")
    from emu68hatcher.builder.staging.icon_grid import arrange_icons

    arranged = arrange_icons(boot_staging)
    if arranged:
        workflow.logger.info(f"Arranged {arranged} icons into alphabetical drawer grids")
