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
from emu68hatcher.data.package_loader import get_local_packages_dir, get_package_by_name

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow

_MENUTOOLS_EXIT_RE = re.compile(r"(?m)^EXIT\b")


def _menu_cmd(script: str) -> str:
    """build the rx invocation injected into MenuTools - /WAIT pins the diagnostic window open"""
    return f"SYS:Rexxc/rx >CON:0/20/680/400/{script}/AUTO/WAIT s:{script}.rexx"


def _connect_cmd(con_title: str, iface: str) -> str:
    """one-click connect - AUTO/CLOSE self-dismisses on success (con title must stay space-free)"""
    return (
        f"SYS:Rexxc/rx >CON:0/20/680/400/{con_title}/AUTO/CLOSE s:NetworkConfig.rexx ONLINE {iface}"
    )


_NETWORK_SUBMENU = "Network"

# entries injected into the WB 3.2.x MenuTools ARexx script (network=True ones only when a stack is configured)
_MENUTOOLS_ENTRIES: tuple[dict, ...] = (
    {
        "name": "NetConfig",
        "submenu": _NETWORK_SUBMENU,
        "title": "Config",
        "cmd": _menu_cmd("NetworkConfig"),
        "network": True,
    },
    {
        "name": "NetConnectWifi",
        "submenu": _NETWORK_SUBMENU,
        "title": "Connect WiFi",
        "cmd": _connect_cmd("Connect-WiFi", "WIFI"),
        "network": True,
    },
    {
        "name": "NetConnectEth",
        "submenu": _NETWORK_SUBMENU,
        "title": "Connect Ethernet",
        "cmd": _connect_cmd("Connect-Ethernet", "ETHERNET"),
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
            roadshow_full=workflow.config.roadshow_archive is not None,
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
    _inject_menutools_entries(workflow, boot_staging, all_packages)


def _compose_menu_title(submenu: str, title: str) -> str:
    """\\Sub\\Item nests under a Tools submenu; bare title stays at the Tools level"""
    return f"\\{submenu}\\{title}" if submenu else title


def _menu_add_line(name: str, menu_title: str, cmd: str) -> str:
    """one MENU ADD line; menu_title may be a backslash path (\\Sub\\Item) for a Tools submenu"""
    return f"MENU ADD NAME {name} TITLE '\"{menu_title}\"' CMD \"'address command ''{cmd}'''\""


def _collect_app_entries(all_packages: set[str]) -> list[tuple[str, str, str]]:
    """(name, menu_title, cmd) for installed packages with a menu_entry; submenu items first"""
    entries: list[tuple[bool, str, str, str, str]] = []
    for name in all_packages:
        pkg = get_package_by_name(name)
        if pkg and pkg.menu_entry:
            me = pkg.menu_entry
            cmd = f"run >NIL: SYS:{me.path}"
            sub = me.submenu or ""
            menu_title = _compose_menu_title(sub, me.title)
            entries.append((sub == "", sub.lower(), me.title.lower(), name, menu_title, cmd))
    # submenu items grouped+alphabetical first; top-level items sort to the bottom of the menu
    entries.sort()
    return [(name, menu_title, cmd) for *_key, name, menu_title, cmd in entries]


def _build_menutools_entries(has_network: bool, all_packages: set[str]) -> list[str]:
    """build the MENU ADD lines to inject into the WBStartup/MenuTools script"""
    lines: list[str] = []
    for entry in _MENUTOOLS_ENTRIES:
        if entry.get("network") and not has_network:
            continue
        menu_title = _compose_menu_title(entry.get("submenu", ""), entry["title"])
        lines.append(_menu_add_line(entry["name"], menu_title, entry["cmd"]))
    for name, menu_title, cmd in _collect_app_entries(all_packages):
        lines.append(_menu_add_line(name, menu_title, cmd))
    return lines


def _inject_menutools_entries(
    workflow: BuildWorkflow, boot_staging: Path, all_packages: set[str]
) -> None:
    """add Hatcher entries to WB 3.2.x WBStartup/MenuTools (before EXIT)"""
    menutools_path = boot_staging / "WBStartup" / "MenuTools"
    if not menutools_path.exists():
        workflow.logger.debug("No WBStartup/MenuTools script, skipping menu injection")
        return

    has_network = workflow.config.network_stack is not None
    lines = _build_menutools_entries(has_network, all_packages)
    if not lines:
        workflow.logger.debug("No menu entries to inject")
        return

    block = "\n" + "\n".join(lines) + "\n"
    content = menutools_path.read_text(encoding="iso-8859-1", errors="replace")

    # match start-of-line EXIT only - matching anywhere also hit "EXIT" inside comments/strings.
    # callable repl: submenu titles contain backslashes (\Network\Config) that a string repl
    # would parse as regex escapes ("bad escape \N")
    new_content, count = _MENUTOOLS_EXIT_RE.subn(lambda _m: block + "\nEXIT", content, count=1)
    if count:
        content = new_content
        action = "Injected"
    else:
        content += block
        action = "Appended"
    menutools_path.write_bytes(content.encode("iso-8859-1"))
    workflow.logger.info(f"{action} {len(lines)} menu entries into MenuTools")
