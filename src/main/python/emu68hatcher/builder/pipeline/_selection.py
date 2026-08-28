"""shared package-selection resolution for the build pipeline"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emu68hatcher.config.schema import NetworkStack
from emu68hatcher.data.package_loader import get_mandatory_packages
from emu68hatcher.data.package_resolver import Resolution, resolve

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
    """resolve the build's package selection (user-enabled + network stack + deps)."""
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

    # order_hint = the legacy assembly order (user, network, mandatory) so independent
    # packages install in the same sequence as before; the resolver only reorders for deps.
    mandatory = [p.name for p in get_mandatory_packages(kickstart_version, emu68_version)]
    order_hint = [n.lower() for n in (enabled + net + mandatory)]

    return resolve(
        requested,
        deselected,
        kickstart_version,
        emu68_version,
        order_hint=order_hint,
    )
