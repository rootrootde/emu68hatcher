"""shared package-selection resolution for the build pipeline"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.config.schema import NetworkStack
from emu68hatcher.data.package_loader import get_mandatory_packages
from emu68hatcher.data.package_resolver import Resolution, resolve
from emu68hatcher.data.themes import get_workbench_theme

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow
    from emu68hatcher.config.schema import BuildConfig


def get_resolution(workflow: BuildWorkflow) -> Resolution:
    """Resolve and cache the package selection once per build."""
    if workflow._resolution is None:
        ks = workflow.config.kickstart.version.value
        emu = workflow.config.emu68_version.value
        workflow._resolution = resolve_selection(workflow.config, ks, emu)
    return workflow._resolution


def resolve_selection(
    config: BuildConfig, kickstart_version: str, emu68_version: str | None
) -> Resolution:
    """resolve software, theme and network dependencies."""
    stack_packages = {stack.value.lower() for stack in NetworkStack}
    enabled = [
        p.name for p in config.packages if p.enabled and p.name.lower() not in stack_packages
    ]
    requested = {n.lower() for n in enabled}
    deselected = {
        p.name.lower()
        for p in config.packages
        if not p.enabled and p.name.lower() not in stack_packages
    }

    net: list[str] = []
    if config.network_stack:
        net = [config.network_stack.value]
        requested.add(config.network_stack.value.lower())

    theme = get_workbench_theme(config.display.workbench_theme)
    theme_packages = [name.lower() for name in theme.required_packages] if theme else []
    requested.update(theme_packages)
    deselected.difference_update(theme_packages)

    # preserve the order of independent packages.
    mandatory = [p.name for p in get_mandatory_packages(kickstart_version, emu68_version)]
    order_hint = [n.lower() for n in (enabled + net + mandatory + theme_packages)]

    resolution = resolve(
        requested,
        deselected,
        kickstart_version,
        emu68_version,
        order_hint=order_hint,
    )
    missing = set(theme_packages) - resolution.selected
    if theme and missing:
        raise BuildError(
            f"Workbench theme '{theme.display_name}' needs packages that could not be selected: "
            f"{', '.join(sorted(missing))}. Check package availability and conflicts, "
            "or select the default theme."
        )
    return resolution
