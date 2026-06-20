"""configure phase 3: Amiga preferences, WiFi, Picasso96 tooltypes, icon set"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.utils.paths import ensure_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


# tooltypes for Videocore.info monitor driver
VIDEOCORE_TOOLTYPES = [
    "BOARDTYPE=Videocore",
    "SETTINGSFILE=SYS:DEVS/Picasso96Settings",
    "(BORDERBLANK=Yes)",
    "(BorderBlank=System)",
    "(BIGSPRITE=Yes)",
    "SOFTSPRITE=Yes",
    "IGNOREMASK=Yes",
    "(VC4_INTEGER_SCALING=1)",
    "(VC4_KERNEL=0)",
    "VC4_KERNEL=1",
    "VC4_KERNEL_B=1",
    "VC4_KERNEL_C=500",
    "VC4_PHASE=120",
    "VC4_SCALER=3",
    "(VC4_SPRITE_OPACITY=118)",
    "(VC4_SWITCH_METHOD=SEL)",
    "(VC4_SWITCH_INVERT=YES)",
    "(VC4_SWITCH_METHOD=CSI)",
    "(VC4_SWITCH_METHOD=CTS)",
    "VC4_LEGACY_ID",
]

# tooltypes for uaegfx.info (UAE mode)
UAEGFX_TOOLTYPES = [
    "BOARDTYPE=uaegfx",
    "SETTINGSFILE=SYS:DEVS/Picasso96Settings",
    "SOFTSPRITE=Yes",
    "IGNOREMASK=Yes",
]


def _wpa_escape(value: str) -> str:
    """escape value for WirelessManager quoted form (backslash then quote, wpa_supplicant convention)"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def generate_wireless_prefs(ssid: str, password: str) -> str:
    """wireless.prefs in WirelessManager format; empty password means an open network"""
    body = f'   ssid="{_wpa_escape(ssid)}"\n'
    body += f'   psk="{_wpa_escape(password)}"\n' if password else "   key_mgmt=NONE\n"
    body += "   scan_ssid=1\n"  # probe for hidden SSIDs (matches NetworkConfig.rexx)
    return f"network={{\n{body}}}\n"


# all three writers mirror NetworkConfig.rexx so build-time output matches the runtime tool
_MANAGED_TAG = "# emu68hatcher: managed by Network Config"


def _write_netinterface(path: Path, mode: str, address: str | None, netmask: str | None) -> None:
    """rewrite a DEVS:NetInterfaces file's IP keys, keeping device=/unit=/tuning lines.
    roadshow rejects gateway= on an interface - the default route lives in DEVS:Internet/routes."""
    kept: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="iso-8859-1").splitlines():
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip().lower() if stripped[:1] not in ("", "#") else ""
            if key in ("configure", "address", "netmask", "gateway"):
                continue
            kept.append(line)
    kept.append(_MANAGED_TAG)
    if mode == "static" and address and netmask:
        kept += [f"address={address}", f"netmask={netmask}"]
    else:
        kept.append("configure=dhcp")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(kept) + "\n", encoding="iso-8859-1")


def _write_default_route(path: Path, gateway: str) -> None:
    """set the default route in DEVS:Internet/routes, keeping other routes"""
    kept: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="iso-8859-1").splitlines():
            stripped = line.strip()
            if stripped[:1] not in ("", "#") and stripped.split()[0].lower() == "default":
                continue
            kept.append(line)
    kept += [_MANAGED_TAG, f"default {gateway}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(kept) + "\n", encoding="iso-8859-1")


def _write_name_resolution(path: Path, dns_servers: list[str]) -> None:
    """write DEVS:Internet/name_resolution nameserver lines"""
    lines = [_MANAGED_TAG] + [f"nameserver {ip}" for ip in dns_servers]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="iso-8859-1")


def _configure_network(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """write the Roadshow per-interface IP + global gateway/DNS files from config"""
    net = workflow.config.network
    devs = boot_staging / "Devs"
    # the bundled NetInterfaces files carry the device= line; only rewrite ones that exist
    # so a missing install never yields a device-less (broken) interface
    for iface, ip in (("genet", net.ethernet), ("wifipi", net.wifi)):
        path = devs / "NetInterfaces" / iface
        if not path.exists():
            workflow.logger.warning(f"NetInterfaces/{iface} not staged; skipping its IP config")
            continue
        _write_netinterface(path, ip.mode.value, ip.address, ip.netmask)
    # gateway/dns are global; author them only when set, else DHCP/stock provides them
    if net.gateway:
        _write_default_route(devs / "Internet" / "routes", net.gateway)
    if net.dns_servers:
        _write_name_resolution(devs / "Internet" / "name_resolution", net.dns_servers)
    workflow.logger.info(
        f"Configured network: ethernet={net.ethernet.mode.value} wifi={net.wifi.mode.value} "
        f"gateway={net.gateway or '-'} dns={net.dns_servers or '-'}"
    )


def stage_whdload_kickstarts(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """stage Roms for WHDLoad (kick33180.A500 etc) into SDH0:Devs/Kickstarts/"""
    import shutil

    from emu68hatcher.data.rom_detection import WHDLOAD_ROM_NAMES, find_whdload_kickstarts

    existing_dirs = [Path(d) for d in workflow.config.asset_directories if Path(d).exists()]
    if not existing_dirs:
        workflow.logger.info("No asset directories configured - skipping WHDLoad Kickstart staging")
        return

    matched: dict[str, Path] = {}
    for d in existing_dirs:
        # earliest dir wins on dupes - matches find_whdload_kickstarts single-dir behaviour
        for name, src in find_whdload_kickstarts(d).items():
            matched.setdefault(name, src)

    # include the boot ROM
    boot_info = workflow.state.resolved_rom_info or {}
    boot_whd = boot_info.get("whdload_name")
    if boot_whd and workflow.state.resolved_rom_path and boot_whd not in matched:
        matched[boot_whd] = workflow.state.resolved_rom_path

    kickstarts_dir = ensure_dir(boot_staging / "Devs" / "Kickstarts")

    for name, src in matched.items():
        shutil.copy2(src, kickstarts_dir / name)

    found = sorted(matched)
    missing = [n for n in WHDLOAD_ROM_NAMES if n not in matched]
    workflow.logger.info(
        f"Staged {len(found)} WHDLoad ROM(s) to DEVS:Kickstarts/: "
        f"{', '.join(found) if found else '(none)'}"
    )
    if missing:
        workflow.logger.info(f"Missing WHDLoad ROMs (optional): {', '.join(missing)}")


def configure_preferences(
    workflow: BuildWorkflow,
    boot_staging: Path,
    prefs_dir: Path,
    env_archive: Path,
) -> None:
    """configure Amiga preferences, WiFi, Picasso96 tooltypes, and icon set"""
    from emu68hatcher.builder.staging.prefs import install_default_prefs

    workflow._update_state(progress=70.0)
    workflow._milestone("Configuring Amiga preferences")

    install_default_prefs(prefs_dir)

    workflow.logger.info("Configured Amiga preferences (wbpattern + env vars)")

    # wifi set with an empty password is an open network (generate_wireless_prefs handles it)
    if workflow.config.wifi:
        workflow._update_state(progress=80.0)
        workflow._milestone("Configuring WiFi")
        sys_dir = ensure_dir(env_archive / "Sys")
        (sys_dir / "wireless.prefs").write_text(
            generate_wireless_prefs(workflow.config.wifi.ssid, workflow.config.wifi.password),
            encoding="iso-8859-1",
        )
        workflow.logger.info("Generated wireless.prefs")

    if workflow.config.network_stack is not None:
        _configure_network(workflow, boot_staging)

    workflow._update_state(progress=85.0)
    workflow._milestone("Configuring Picasso96 monitor")
    _configure_videocore_tooltypes(workflow, boot_staging)
    _override_videocore_card(workflow, boot_staging)

    # HDToolBox SCSI name: brcm-emmc on Pi4/CM4, brcm-sdhc on Pi3/Zero (FirstBoot picks at runtime)
    _configure_hdtoolbox_tooltypes(workflow, boot_staging)

    workflow._update_state(progress=90.0)
    workflow._milestone("Generating drawer icons")
    from emu68hatcher.builder.staging.icons import (
        ensure_dirs_for_orphan_drawer_icons,
        ensure_drawer_icons,
    )

    created = ensure_drawer_icons(boot_staging)
    if created:
        workflow.logger.info(f"Created {created} drawer icons")
    fixed = ensure_dirs_for_orphan_drawer_icons(boot_staging)
    if fixed:
        workflow.logger.info(f"Created {fixed} missing drawers for orphan icons")

    workflow._update_state(progress=95.0)
    workflow._milestone("Configuring icons")
    _install_icon_set(workflow, boot_staging)


def _override_videocore_card(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """replace Emu68-tools VideoCore.card with the version-specific one (1.1+ needs v1.5)"""
    import shutil

    src = workflow.state.downloaded_files.get("emu68_videocore")
    if not src or not src.exists():
        return
    dest = boot_staging / "Libs" / "Picasso96" / "VideoCore.card"
    if not dest.parent.exists():
        workflow.logger.warning(f"VideoCore.card destination not found: {dest.parent}")
        return
    shutil.copy2(src, dest)
    workflow.logger.info(f"Overrode VideoCore.card with {src.name}")


def _configure_videocore_tooltypes(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """set tooltypes on Videocore.info and uaegfx.info for Picasso96 board detection"""
    from emu68hatcher.builder.staging.files import write_info_tooltypes

    monitors_dir = boot_staging / "Devs" / "Monitors"
    storage_monitors = boot_staging / "Storage" / "Monitors"

    for info_name, tooltypes, search_dirs in [
        ("Videocore.info", VIDEOCORE_TOOLTYPES, [monitors_dir, storage_monitors]),
        ("uaegfx.info", UAEGFX_TOOLTYPES, [storage_monitors, monitors_dir]),
    ]:
        info_path = None
        for d in search_dirs:
            candidate = d / info_name
            if candidate.exists():
                info_path = candidate
                break

        if not info_path:
            workflow.logger.debug(f"{info_name} not found, skipping tooltype configuration")
            continue

        try:
            write_info_tooltypes(info_path, tooltypes)
            workflow.logger.info(f"Configured {info_name} tooltypes (BOARDTYPE set)")
        except (OSError, ValueError):
            workflow.logger.exception(f"Failed to set {info_name} tooltypes")


def _configure_hdtoolbox_tooltypes(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """patch HDToolBoxPi3/Pi4.info SCSI_DEVICE_NAME (brcm-sdhc for Pi3, brcm-emmc for Pi4)"""
    from emu68hatcher.builder.staging.files import (
        read_info_tooltypes,
        write_info_tooltypes,
    )

    tools_dir = boot_staging / "Tools"
    targets = (
        ("HDToolBoxPi3.info", "brcm-sdhc.device", "brcm-emmc.device"),
        ("HDToolBoxPi4.info", "brcm-emmc.device", "brcm-sdhc.device"),
    )
    for info_name, active, alternate in targets:
        info_path = tools_dir / info_name
        if not info_path.exists():
            workflow.logger.debug(f"{info_name} not found, skipping")
            continue
        try:
            tt = read_info_tooltypes(info_path)
            patched: list[str] = []
            for entry in tt:
                if entry.strip() == "SCSI_DEVICE_NAME=scsi.device":
                    patched.append(f"SCSI_DEVICE_NAME={active}")
                else:
                    patched.append(entry)
            # disabled alternates in parens - Workbench shows struck-through, program ignores; user can flip via Info
            patched.append("(SCSI_DEVICE_NAME=scsi.device)")
            patched.append(f"(SCSI_DEVICE_NAME={alternate})")
            write_info_tooltypes(info_path, patched)
            workflow.logger.info(f"Patched {info_name}: SCSI_DEVICE_NAME={active}")
        except (OSError, ValueError):
            workflow.logger.exception(f"Failed to patch {info_name}")


def _install_icon_set(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """install selected icon set (GlowIcons, Standard...) per icon_sets.yaml"""
    icon_set_name = workflow.config.icon_set
    ks_version = workflow.config.kickstart.version.value

    workflow.logger.info(f"Installing icon set: {icon_set_name} for KS {ks_version}")

    try:
        from emu68hatcher.data.data_manager import load_yaml_data

        rows = load_yaml_data("icon_sets")
        icon_set_config = None

        for row in rows:
            row_name = row.get("name", "")
            row_versions = row.get("versions", [])

            if row_name == icon_set_name and ks_version in row_versions:
                icon_set_config = row
                break

        if not icon_set_config:
            workflow.logger.warning(f"Icon set '{icon_set_name}' not found for KS {ks_version}")
            return

        new_folder = icon_set_config.get("new_folder_icon", {})

        workflow.logger.info(
            f"  Default drawer icon: {new_folder.get('source', '')}/{new_folder.get('file', '')}"
        )

        _apply_icon_set_new_folder(workflow, boot_staging, new_folder)

    except (OSError, ValueError, KeyError):
        workflow.logger.exception("Failed to install icon set")


def _apply_icon_set_new_folder(
    workflow: BuildWorkflow,
    boot_staging: Path,
    new_folder_cfg: dict,
) -> None:
    """replace managed drawer icons with the selected icon set's NewFolder icon"""
    source = new_folder_cfg.get("source")
    file_in_adf = new_folder_cfg.get("file")
    if not source or not file_in_adf:
        return

    adf_path: Path | None = None
    if workflow.state.resolved_install_media:
        for media in workflow.state.resolved_install_media:
            if media.adf_name == source:
                adf_path = media.path
                break
    if not adf_path:
        workflow.logger.warning(
            f"Icon set source ADF '{source}' not available; keeping bundled drawer"
        )
        return

    from emu68hatcher.builder.staging.icons import apply_icon_set_drawer

    count = apply_icon_set_drawer(boot_staging, adf_path, file_in_adf)
    if count:
        workflow.logger.info(
            f"Applied icon-set drawer from {source}/{file_in_adf} to {count} folders"
        )
