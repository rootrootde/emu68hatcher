"""shared package-selection resolution for the build pipeline"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emu68hatcher.data.package_loader import get_mandatory_packages
from emu68hatcher.data.package_resolver import Resolution, resolve

if TYPE_CHECKING:
    from emu68hatcher.config.schema import BuildConfig


def resolve_selection(
    config: BuildConfig, kickstart_version: str, emu68_version: str | None
) -> Resolution:
    """resolve the build's package selection (user-enabled + network stack + deps)."""
    enabled = [p.name for p in config.packages if p.enabled]
    requested = {n.lower() for n in enabled}

    net: list[str] = []
    if config.network_stack:
        net = [config.network_stack.value]
        requested.add(config.network_stack.value.lower())

    # order_hint = the legacy assembly order (user, network, mandatory) so independent
    # packages install in the same sequence as before; the resolver only reorders for deps.
    mandatory = [p.name for p in get_mandatory_packages(kickstart_version, emu68_version)]
    order_hint = [n.lower() for n in (enabled + net + mandatory)]

    # deselected stays empty until the gui lets users untick a recommended package
    return resolve(requested, set(), kickstart_version, emu68_version, order_hint=order_hint)
