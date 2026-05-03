"""configure phase 1: generate/inject startup scripts and Tools menu entries"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.staging.scripts.generator import generate_shell_startup
from emu68hatcher.builder.staging.scripts.injector import (
    apply_standard_injections,
    write_amiga_script,
)
from emu68hatcher.data.package_loader import get_local_packages_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow

_MENUTOOLS_EXIT_RE = re.compile(r"(?m)^EXIT\b")


# entries injected into the WB 3.2.x MenuTools ARexx script (network=True ones only when a stack is configured)
_MENUTOOLS_ENTRIES: tuple[dict, ...] = (
    {
        "name": "NetManager",
        "title": "Network Manager",
        # CON:.../AUTO redirect: status window self-closes when rx exits
        "cmd": "SYS:Rexxc/rx >CON:0/20/680/400/NetworkManager/AUTO s:NetworkManager.rexx",
        "network": True,
    },
    {
        "name": "HatcherWifiCfg",
        "title": "Wifi Config",
        "cmd": "SYS:Rexxc/rx s:WifiConfig.rexx",
        "network": True,
    },
)


def configure_scripts(
    workflow: BuildWorkflow,
    boot_staging: Path,
    s_dir: Path,
    all_packages: set[str],
) -> None:
    """inject into or generate Startup-Sequence, User-Startup, Shell-Startup, FirstBoot"""
    workflow._update_state(progress=10.0)
    workflow._milestone("Injecting into Startup-Sequence")
    startup_path = s_dir / "Startup-Sequence"

    if startup_path.exists():
        local_packages_dir = get_local_packages_dir()
        content_base = local_packages_dir / "System"

        injection_count = apply_standard_injections(
            staging_dir=boot_staging,
            content_base_path=content_base,
            enabled_packages=all_packages,
        )
        workflow.logger.info(f"Applied {injection_count} script injections to Startup-Sequence")

        verify_content = startup_path.read_text(encoding="iso-8859-1", errors="replace")
        if "FirstBoot" in verify_content and "RexxMast" in verify_content:
            workflow.logger.debug("Startup-Sequence injection verified OK")
        else:
            workflow.logger.warning("Startup-Sequence may be missing required injections")
    else:
        raise BuildError(
            "No Startup-Sequence found in staging. "
            "ADF extraction is required - check that install media (ADF files) are configured."
        )

    workflow._update_state(progress=20.0)
    workflow._milestone("Setting up User-Startup")
    user_startup_path = s_dir / "User-Startup"
    if not user_startup_path.exists():
        write_amiga_script(user_startup_path, ["; User-Startup", "; Emu68 Hatcher"])
    workflow.logger.info("User-Startup ready for package injections")

    workflow._update_state(progress=30.0)
    workflow._milestone("Generating Shell-Startup")
    shell_startup = generate_shell_startup()
    write_amiga_script(s_dir / "Shell-Startup", shell_startup.splitlines())
    workflow.logger.info(f"Generated Shell-Startup ({len(shell_startup)} bytes)")

    workflow._update_state(progress=40.0)
    _inject_menutools_entries(workflow, boot_staging)


def _build_menutools_entries(has_network: bool) -> list[str]:
    """build the MENU ADD lines to inject into the WBStartup/MenuTools script"""
    lines: list[str] = []
    for entry in _MENUTOOLS_ENTRIES:
        if entry.get("network") and not has_network:
            continue
        line = (
            f"MENU ADD NAME {entry['name']} "
            f"TITLE '\"{entry['title']}\"' "
            f"CMD \"'address command ''{entry['cmd']}'''\""
        )
        lines.append(line)
    return lines


def _inject_menutools_entries(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """add the Network Manager / Wifi Config entries to WB 3.2.x WBStartup/MenuTools (before EXIT)"""
    menutools_path = boot_staging / "WBStartup" / "MenuTools"
    if not menutools_path.exists():
        workflow.logger.debug("No WBStartup/MenuTools script, skipping menu injection")
        return

    has_network = workflow.config.network_stack is not None
    lines = _build_menutools_entries(has_network)
    if not lines:
        workflow.logger.debug("No menu entries to inject")
        return

    block = "\n" + "\n".join(lines) + "\n"
    content = menutools_path.read_text(encoding="iso-8859-1", errors="replace")

    # match start-of-line EXIT only - matching anywhere also hit "EXIT" inside comments/strings
    new_content, count = _MENUTOOLS_EXIT_RE.subn(block + "\nEXIT", content, count=1)
    if count:
        content = new_content
        action = "Injected"
    else:
        content += block
        action = "Appended"
    menutools_path.write_bytes(content.encode("iso-8859-1"))
    workflow.logger.info(f"{action} {len(lines)} menu entries into MenuTools")
