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
    {
        # reboot is a mandatory package, so C:Reboot is always present
        "name": "SysReboot",
        "submenu": "System",
        "title": "Reboot",
        "cmd": "C:Reboot",
        "rank": 2,  # sort after the app entries (rank 1) in the System submenu
    },
)


# System->Prefs submenu launchers (WB 3.2 nests 3 deep via menuclass; 3.1/3.9 have no MenuTools yet).
# requires: package name(s) that must be installed for the editor to exist; empty = stock editor.
# p96_modern: editor exists only in the user-supplied modern Picasso96 archive, not the aminet one.
# wb_launch: launch via WBRun so the editor gets its icon stack + tooltypes - the MUI/GUI editors
# warn or fail on the default 4096-byte CLI stack; stock OS editors are fine on plain run.
_PREFS_SUBMENU = "System\\Prefs"
_PREFS_ENTRIES: tuple[dict, ...] = (
    {"title": "AHI", "exe": "Prefs/AHI", "requires": ("ahi",), "wb_launch": True},
    {"title": "DefaultIcons", "exe": "Prefs/DefaultIcons"},
    {"title": "Font", "exe": "Prefs/Font"},
    {"title": "IControl", "exe": "Prefs/IControl"},
    {"title": "Input", "exe": "Prefs/Input"},
    {"title": "Locale", "exe": "Prefs/Locale"},
    {
        "title": "MagicMenu",
        "exe": "Prefs/MagicMenuPrefs",
        "requires": ("magicmenu", "magicmenu235"),
        "wb_launch": True,
    },
    {"title": "MUI", "exe": "Programs/MUI/MUI", "requires": ("mui38", "mui5"), "wb_launch": True},
    {"title": "Overscan", "exe": "Prefs/Overscan"},
    {
        "title": "P96Prefs",
        "exe": "Prefs/P96Prefs",
        "requires": ("picasso96",),
        "p96_modern": True,
        "wb_launch": True,
    },
    {"title": "Palette", "exe": "Prefs/Palette"},
    {
        "title": "Picasso96Mode",
        "exe": "Prefs/Picasso96Mode",
        "requires": ("picasso96",),
        "wb_launch": True,
    },
    {"title": "ScreenMode", "exe": "Prefs/ScreenMode"},
    {"title": "WBPattern", "exe": "Prefs/WBPattern"},
    {"title": "Workbench", "exe": "Prefs/Workbench"},
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


def _collect_app_entries(all_packages: set[str]) -> list[tuple[str, str, str, str]]:
    """(submenu, title, name, cmd) for installed packages that declare a menu_entry"""
    entries: list[tuple[str, str, str, str]] = []
    for name in all_packages:
        pkg = get_package_by_name(name)
        if pkg and pkg.menu_entry:
            me = pkg.menu_entry
            # WBRun starts the tool in workbench mode (icon stack + tooltypes) for apps that
            # need it (e.g. AmiSpeedTest); plain GUI apps just get a detached CLI run
            launch = "WBRun" if me.wb_launch else "run"
            entries.append((me.submenu or "", me.title, name, f"{launch} >NIL: SYS:{me.path}"))
    return entries


def _build_menutools_entries(
    has_network: bool, all_packages: set[str], p96_modern: bool = False
) -> list[str]:
    """build MENU ADD lines, keeping each submenu's items contiguous (top-level items last)"""
    # sort key: (top-level last, submenu, rank, order) - rank 0 builtins, 1 apps, 2 late builtins.
    # contiguity matters: non-adjacent same-submenu adds can spawn a duplicate submenu.
    rows: list[tuple[tuple, str, str, str]] = []
    for i, entry in enumerate(_MENUTOOLS_ENTRIES):
        if entry.get("network") and not has_network:
            continue
        sub = entry.get("submenu", "")
        key = (sub == "", sub.lower(), entry.get("rank", 0), f"{i:03d}")
        rows.append((key, entry["name"], _compose_menu_title(sub, entry["title"]), entry["cmd"]))
    for sub, title, name, cmd in _collect_app_entries(all_packages):
        key = (sub == "", sub.lower(), 1, title.lower())
        rows.append((key, name, _compose_menu_title(sub, title), cmd))
    for entry in _PREFS_ENTRIES:
        requires = entry.get("requires")
        if requires and not (all_packages & set(requires)):
            continue
        if entry.get("p96_modern") and not p96_modern:
            continue
        title = entry["title"]
        key = (False, _PREFS_SUBMENU.lower(), 1, title.lower())
        launch = "WBRun" if entry.get("wb_launch") else "run"
        cmd = f"{launch} >NIL: SYS:{entry['exe']}"
        rows.append((key, f"Prefs{title}", _compose_menu_title(_PREFS_SUBMENU, title), cmd))
    rows.sort(key=lambda r: r[0])
    return [_menu_add_line(name, menu_title, cmd) for _key, name, menu_title, cmd in rows]


def _inject_menutools_entries(
    workflow: BuildWorkflow, boot_staging: Path, all_packages: set[str]
) -> None:
    """add Hatcher entries to WB 3.2.x WBStartup/MenuTools (before EXIT)"""
    menutools_path = boot_staging / "WBStartup" / "MenuTools"
    if not menutools_path.exists():
        workflow.logger.debug("No WBStartup/MenuTools script, skipping menu injection")
        return

    has_network = workflow.config.network_stack is not None
    # P96Prefs ships only in the modern user-supplied Picasso96 archive
    p96_modern = workflow.config.display.picasso96_archive is not None
    lines = _build_menutools_entries(has_network, all_packages, p96_modern)
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
