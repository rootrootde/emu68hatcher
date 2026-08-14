"""configure startup scripts and ToolsDaemon menus"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.staging.scripts.generator import generate_shell_startup
from emu68hatcher.builder.staging.scripts.injector import (
    apply_package_scripts,
    apply_standard_injections,
    write_amiga_script,
)
from emu68hatcher.builder.staging.toolsdaemon import patch_toolsdaemon
from emu68hatcher.config.schema import NetworkStack
from emu68hatcher.data.package_loader import get_local_packages_dir, get_package_by_name

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


@dataclass(frozen=True)
class _MenuLauncher:
    menu: str
    title: str
    command: str
    wb_launch: bool = False
    selected_icons: bool = False


def _menu_cmd(script: str) -> str:
    """Build an rx invocation whose diagnostic window stays open."""
    return f"SYS:Rexxc/rx >CON:0/20/680/400/{script}/AUTO/WAIT s:{script}.rexx"


def _connect_cmd(con_title: str, iface: str) -> str:
    """one-click connect - AUTO/CLOSE self-dismisses on success (con title must stay space-free)"""
    return (
        f"SYS:Rexxc/rx >CON:0/20/680/400/{con_title}/AUTO/CLOSE s:NetworkConfig.rexx ONLINE {iface}"
    )


def _miamidx_cmd(con_title: str, action: str, *, close: bool) -> str:
    window = "CLOSE" if close else "WAIT"
    return f"SYS:Rexxc/rx >CON:0/20/680/400/{con_title}/AUTO/{window} S:MiamiNetwork.rexx {action}"


# System->Prefs submenu launchers.
# requires: package name(s) that must be installed for the editor to exist; empty = stock editor.
# p96_modern: editor exists only in the user-supplied modern Picasso96 archive, not the aminet one.
# wb_launch: Workbench mode keeps the icon stack and tooltypes for editors that need them.
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
        "requires": ("magicmenu",),
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
    {"title": "Trident", "exe": "Prefs/Trident", "requires": ("poseidon",), "wb_launch": True},
    {"title": "WBPattern", "exe": "Prefs/WBPattern"},
    {"title": "Workbench", "exe": "Prefs/Workbench"},
)


def configure_scripts(
    workflow: BuildWorkflow,
    boot_staging: Path,
    s_dir: Path,
    all_packages: list[str],
    extracted_paths: dict[str, Path],
) -> None:
    """inject into or generate Startup-Sequence, User-Startup, Shell-Startup, FirstBoot"""
    workflow._update_state(progress=10.0)
    workflow._milestone("Injecting into Startup-Sequence")
    startup_path = s_dir / "Startup-Sequence"

    if startup_path.exists():
        local_packages_dir = get_local_packages_dir()
        content_base = local_packages_dir / "System"

        injection_results = apply_standard_injections(
            staging_dir=boot_staging,
            content_base_path=content_base,
        )
        failures = [result.error for result in injection_results if result.error]
        if failures:
            details = "; ".join(failures)
            raise BuildError(f"Startup-Sequence update failed: {details}")
        injection_count = sum(result.changed for result in injection_results)
        workflow.logger.info(f"Applied {injection_count} script injections to Startup-Sequence")

        verify_content = startup_path.read_text(encoding="iso-8859-1", errors="replace")
        if "FirstBoot" in verify_content and "RexxMast" in verify_content:
            workflow.logger.debug("Startup-Sequence injection verified OK")
        else:
            raise BuildError("Startup-Sequence is missing required FirstBoot or RexxMast setup")
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

    # user-supplied archives switch when_user_archive-gated script variants (e.g. the full
    # Roadshow auto-runs Network-Startup; the demo timer starts when bsdsocket.library opens)
    user_archives = set()
    if workflow.config.roadshow_archive is not None:
        user_archives.add("roadshow")
    if workflow.config.display.picasso96_archive is not None:
        user_archives.add("picasso96")

    script_count = apply_package_scripts(boot_staging, all_packages, user_archives)
    workflow.logger.info(f"Applied {script_count} package script blocks to User-Startup")

    workflow._update_state(progress=30.0)
    workflow._milestone("Generating Shell-Startup")
    shell_startup = generate_shell_startup()
    write_amiga_script(s_dir / "Shell-Startup", shell_startup.splitlines())
    workflow.logger.info(f"Generated Shell-Startup ({len(shell_startup)} bytes)")

    workflow._update_state(progress=40.0)
    _configure_toolsdaemon(workflow, boot_staging, s_dir, all_packages, extracted_paths)


def _collect_app_entries(all_packages: list[str]) -> list[_MenuLauncher]:
    """Collect launchers declared by installed packages."""
    entries: list[_MenuLauncher] = []
    for name in all_packages:
        pkg = get_package_by_name(name)
        if pkg and pkg.menu_entry:
            me = pkg.menu_entry
            command = f"SYS:{me.path}" if me.wb_launch else f"Run >NIL: SYS:{me.path}"
            entries.append(
                _MenuLauncher(
                    menu=me.menu,
                    title=me.title,
                    command=command,
                    wb_launch=me.wb_launch,
                    selected_icons=me.selected_icons,
                )
            )
    return entries


def _network_entries(network_stack: NetworkStack | None) -> list[_MenuLauncher]:
    entries: list[_MenuLauncher] = []
    if network_stack == NetworkStack.ROADSHOW:
        entries.extend(
            (
                _MenuLauncher("Network", "Config", _menu_cmd("NetworkConfig")),
                _MenuLauncher("Network", "Connect WiFi", _connect_cmd("Connect-WiFi", "WIFI")),
                _MenuLauncher(
                    "Network",
                    "Connect Ethernet",
                    _connect_cmd("Connect-Ethernet", "ETHERNET"),
                ),
            )
        )
    elif network_stack == NetworkStack.MIAMIDX:
        entries.extend(
            (
                _MenuLauncher("Network", "MiamiDX", _miamidx_cmd("MiamiDX", "CONFIG", close=False)),
                _MenuLauncher(
                    "Network",
                    "Connect WiFi",
                    _miamidx_cmd("Connect-WiFi", "ONLINE WIFIPI", close=True),
                ),
                _MenuLauncher(
                    "Network",
                    "Connect Ethernet",
                    _miamidx_cmd("Connect-Ethernet", "ONLINE GENET", close=True),
                ),
                _MenuLauncher(
                    "Network",
                    "Disconnect",
                    _miamidx_cmd("Disconnect", "OFFLINE", close=True),
                ),
            )
        )
    return entries


def _prefs_entries(all_packages: list[str], p96_modern: bool) -> list[_MenuLauncher]:
    entries: list[_MenuLauncher] = []
    installed = set(all_packages)
    for entry in _PREFS_ENTRIES:
        requires = entry.get("requires")
        if requires and not (installed & set(requires)):
            continue
        if entry.get("p96_modern") and not p96_modern:
            continue
        wb_launch = bool(entry.get("wb_launch"))
        path = f"SYS:{entry['exe']}"
        entries.append(
            _MenuLauncher(
                menu="System",
                title=entry["title"],
                command=path if wb_launch else f"Run >NIL: {path}",
                wb_launch=wb_launch,
            )
        )
    return entries


def _append_launcher(lines: list[str], entry: _MenuLauncher, keyword: str = "ITEM") -> None:
    lines.append(f"\t{keyword} {entry.title}")
    selected = " []" if entry.selected_icons else ""
    if entry.wb_launch:
        lines.append(f"\t(WB) {entry.command}{selected}")
    else:
        lines.append(f"\t(CLI) 8192 {entry.command}{selected}")


def _build_toolsdaemon_menu(
    network_stack: NetworkStack | None,
    all_packages: list[str],
    p96_modern: bool = False,
) -> list[str]:
    """Build the complete ToolsDaemon.menu file."""
    network_actions = _network_entries(network_stack)
    package_entries = _collect_app_entries(all_packages)
    package_menus: dict[str, list[_MenuLauncher]] = {}
    for entry in sorted(package_entries, key=lambda item: (item.menu.lower(), item.title.lower())):
        package_menus.setdefault(entry.menu, []).append(entry)

    lines: list[str] = []
    network_apps = package_menus.pop("Network", [])
    if network_actions or network_apps:
        lines.append("TITLE Network")
        for entry in network_actions:
            _append_launcher(lines, entry)
        if network_actions and network_apps:
            lines.append("\tITEMBAR")
        for entry in network_apps:
            _append_launcher(lines, entry)

    apps = package_menus.pop("Apps", [])
    if apps:
        lines.append("TITLE Apps")
        for entry in apps:
            _append_launcher(lines, entry)

    system_apps = package_menus.pop("System", [])
    lines.append("TITLE System")
    for entry in system_apps:
        _append_launcher(lines, entry)
    if system_apps:
        lines.append("\tITEMBAR")

    lines.append("\tITEM Prefs")
    for entry in _prefs_entries(all_packages, p96_modern):
        _append_launcher(lines, entry, keyword="SUB")
    lines.append("\tSUBBAR")
    _append_launcher(
        lines,
        _MenuLauncher("System", "Open Prefs", "SYS:Rexxc/rx >NIL: S:Win SYS:Prefs"),
        keyword="SUB",
    )
    lines.append("\tITEMBAR")
    _append_launcher(lines, _MenuLauncher("System", "Reboot", "C:Reboot"))

    for menu in sorted(package_menus, key=str.lower):
        lines.append(f"TITLE {menu}")
        for entry in package_menus[menu]:
            _append_launcher(lines, entry)

    lines.append("END")
    return lines


def _configure_toolsdaemon(
    workflow: BuildWorkflow,
    boot_staging: Path,
    s_dir: Path,
    all_packages: list[str],
    extracted_paths: dict[str, Path],
) -> None:
    """Patch ToolsDaemon and replace the native MenuTools source."""
    workflow._milestone("Installing ToolsDaemon 2.2 menus")
    patched = patch_toolsdaemon(boot_staging, extracted_paths)
    workflow.logger.info(f"Patched ToolsDaemon 2.2 files: {', '.join(patched)}")

    p96_modern = workflow.config.display.picasso96_archive is not None
    lines = _build_toolsdaemon_menu(workflow.config.network_stack, all_packages, p96_modern)
    write_amiga_script(s_dir / "ToolsDaemon.menu", lines)

    removed = 0
    for relative_path in (
        "WBStartup/MenuTools",
        "WBStartup/MenuTools.info",
        "WBStartup/Disabled/MenuTools",
        "WBStartup/Disabled/MenuTools.info",
    ):
        path = boot_staging / Path(relative_path)
        if path.is_file():
            path.unlink()
            removed += 1
    workflow.logger.info(
        f"Generated S:ToolsDaemon.menu ({len(lines)} lines); removed {removed} native MenuTools files"
    )
