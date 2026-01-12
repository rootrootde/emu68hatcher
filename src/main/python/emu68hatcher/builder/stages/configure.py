"""configure Amiga system stage - generate startup scripts and preferences"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.builder.script_generator import (
    ScriptConfig,
    generate_startup_sequence,
    generate_shell_startup,
    generate_onetimerun_wb,
    generate_boot_partition_files,
)
from emu68hatcher.builder.script_injector import apply_standard_injections
from emu68hatcher.data.package_loader import get_local_packages_dir
from emu68hatcher.utils.paths import ensure_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_configure(workflow: BuildWorkflow) -> None:
    """configure the Amiga system - generate startup scripts and preferences

    delegates to three sub-phases:
    1. script configuration (injections, User-Startup, Shell-Startup, OneTimeRun)
    2. boot partition setup (Emu68 files, ROM, config.txt, cmdline.txt)
    3. system preferences (ScreenMode, Locale, Input, icons, tooltypes)
    """
    if not workflow.state.staging_dir or not workflow.state.staging_dir.exists():
        raise BuildError("Staging directory not available - setup stage may have failed")
    if not workflow.state.resolved_rom_path:
        raise BuildError("ROM not resolved - validate stage may have failed")

    workflow._update_state(BuildStage.CONFIGURE, 0.0)
    workflow._log("Configuring system")

    # resolve boot/work devices from partition config
    boot_device, work_device = _resolve_devices(workflow)
    boot_staging = workflow.state.staging_dir / boot_device
    s_dir = ensure_dir(boot_staging / "S")
    prefs_dir = ensure_dir(boot_staging / "Prefs")
    env_archive = ensure_dir(prefs_dir / "Env-Archive")
    ensure_dir(boot_staging / "Devs" / "DOSDrivers")

    # build the set of all enabled packages (user-selected + mandatory)
    all_packages = _collect_enabled_packages(workflow)

    # phase 1: Script configuration (0-40%)
    script_config = _build_script_config(workflow, boot_device, work_device, all_packages)
    _configure_scripts(workflow, boot_staging, s_dir, all_packages, script_config)

    # phase 2: Boot partition setup (40-70%)
    _configure_boot_partition(workflow, boot_staging, all_packages)

    # phase 3: System preferences (70-100%)
    _configure_preferences(workflow, boot_staging, prefs_dir, env_archive)

    workflow._update_state(progress=100.0)
    workflow._log("System configured")


# =============================================================================
# helpers
# =============================================================================


def _resolve_devices(workflow: BuildWorkflow) -> tuple[str, str]:
    """determine boot and work device names from partition config"""
    boot_device = "SDH0"
    work_device = "SDH1"
    if workflow.config.partitions:
        for mbr_part in workflow.config.partitions.layout:
            if mbr_part.amiga_partitions:
                for amiga_part in mbr_part.amiga_partitions:
                    if amiga_part.bootable:
                        boot_device = amiga_part.device
                    elif work_device == "SDH1":
                        work_device = amiga_part.device
    return boot_device, work_device


def _collect_enabled_packages(workflow: BuildWorkflow) -> set[str]:
    """build set of all enabled package names (user-selected + mandatory)"""
    enabled = {p.name.lower() for p in workflow.config.packages if p.enabled}

    from emu68hatcher.builder.package_installer import PackageInstaller
    installer = PackageInstaller(
        kickstart_version=workflow.config.kickstart.version.value,
        staging_dir=workflow.state.staging_dir,
        extracted_packages_dir=workflow.state.extracted_dir if workflow.state.extracted_dir else workflow.state.work_dir / "extracted",
    )
    mandatory = {p.lower() for p in installer.get_mandatory_packages()}
    return enabled | mandatory


def _build_script_config(
    workflow: BuildWorkflow, boot_device: str, work_device: str, all_packages: set[str]
) -> ScriptConfig:
    """create the ScriptConfig for template-based script generation"""
    return ScriptConfig(
        kickstart_version=workflow.config.kickstart.version.value,
        boot_device=boot_device,
        work_device=work_device,
        has_picasso96="picasso96" in all_packages,
        has_amissl="amissl" in all_packages,
        has_mui="mui" in all_packages or "mui38" in all_packages,
        has_roadshow="roadshow" in all_packages,
        has_whdload="whdload" in all_packages,
        has_dopus="dopus" in all_packages or "directoryopus" in all_packages,
        wifi_enabled=workflow.config.wifi is not None,
        wifi_ssid=workflow.config.wifi.ssid if workflow.config.wifi else "",
        wifi_password=workflow.config.wifi.password if workflow.config.wifi else "",
    )


def _write_amiga_script(path: Path, content: str) -> None:
    """write script with Amiga-compatible encoding and LF line endings"""
    normalized = content.replace('\r\n', '\n').replace('\r', '\n')
    path.write_bytes(normalized.encode('iso-8859-1'))


# =============================================================================
# phase 1: Script Configuration
# =============================================================================


def _configure_scripts(
    workflow: BuildWorkflow,
    boot_staging: Path,
    s_dir: Path,
    all_packages: set[str],
    script_config: ScriptConfig,
) -> None:
    """inject into or generate Startup-Sequence, User-Startup, Shell-Startup, OneTimeRun"""
    # Startup-Sequence: inject into ADF version or generate from template
    workflow._update_state(progress=10.0)
    workflow._log("Injecting into Startup-Sequence")
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
        if "OneTimeRun" in verify_content and "RexxMast" in verify_content:
            workflow.logger.debug("Startup-Sequence injection verified OK")
        else:
            workflow.logger.warning("Startup-Sequence may be missing required injections")
    else:
        workflow.logger.warning("No Startup-Sequence from ADF, generating from template")
        startup_sequence = generate_startup_sequence(script_config)
        _write_amiga_script(startup_path, startup_sequence)
        workflow.logger.info(f"Generated Startup-Sequence ({len(startup_sequence)} bytes)")

    # user-Startup: ensure it exists for package injections
    workflow._update_state(progress=20.0)
    workflow._log("Setting up User-Startup")
    user_startup_path = s_dir / "User-Startup"
    if not user_startup_path.exists():
        _write_amiga_script(user_startup_path, "; User-Startup\n; Emu68 Hatcher\n")
    workflow.logger.info("User-Startup ready for package injections")

    # shell-Startup
    workflow._update_state(progress=30.0)
    workflow._log("Generating Shell-Startup")
    shell_startup = generate_shell_startup()
    _write_amiga_script(s_dir / "Shell-Startup", shell_startup)
    workflow.logger.info(f"Generated Shell-Startup ({len(shell_startup)} bytes)")

    # OneTimeRunWB first-boot script
    workflow._update_state(progress=40.0)
    workflow._log("Setting up first-boot scripts")
    ensure_dir(s_dir / "OneTimeRunWB")
    onetimerun_wb_content = generate_onetimerun_wb()
    _write_amiga_script(s_dir / "OneTimeRunWB.script", onetimerun_wb_content)
    workflow.logger.info(f"Generated OneTimeRunWB.script ({len(onetimerun_wb_content)} bytes)")

    # configure network icons and menu entries (Roadshow only)
    _configure_network_scripts(workflow, boot_staging)
    _inject_menutools_entries(workflow, boot_staging)


def _configure_network_scripts(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """network script configuration (placeholder)

    HatcherNet.rexx and HatcherTunings are installed directly by
    pistorm_local_files. A single "Network Manager" menu entry is injected
    by _inject_menutools_entries.
    """
    if workflow.config.network_stack is None:
        workflow.logger.debug("No network stack selected")
        return

    workflow.logger.info("Network scripts configured (Roadshow)")


def _inject_menutools_entries(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """inject network menu entries into the WB 3.2.x MenuTools ARexx script

    the WB MenuTools script in WBStartup runs at boot and adds entries to
    the Tools menu. we inject our network entries (Go Online, Go Offline)
    before the EXIT line.
    """
    if workflow.config.network_stack is None:
        workflow.logger.debug("No network stack, skipping menu entry injection")
        return

    menutools_path = boot_staging / "WBStartup" / "MenuTools"
    if not menutools_path.exists():
        workflow.logger.debug("No WBStartup/MenuTools script, skipping menu injection")
        return

    content = menutools_path.read_text(encoding="iso-8859-1", errors="replace")

    # single menu entry - HatcherNet.rexx shows a RequestChoice dialog and
    # handles WiFi/Ethernet/Offline selection inline
    network_entries = (
        '\n'
        'MENU ADD NAME HatcherNetMgr TITLE \'"Network Manager"\' '
        "CMD \"'address command ''rx sys:Pistorm/Network/HatcherNet.rexx'''\"\n"
    )

    # inject before EXIT
    if "EXIT" in content:
        content = content.replace("EXIT", network_entries + "\nEXIT", 1)
        menutools_path.write_bytes(content.encode("iso-8859-1"))
        workflow.logger.info("Injected network menu entries into MenuTools")
    else:
        # no EXIT found, append
        content += network_entries
        menutools_path.write_bytes(content.encode("iso-8859-1"))
        workflow.logger.info("Appended network menu entries to MenuTools")


# =============================================================================
# phase 2: Boot Partition Setup
# =============================================================================


def _configure_boot_partition(
    workflow: BuildWorkflow, boot_staging: Path, all_packages: set[str]
) -> None:
    """copy Emu68 boot files, ROM, and generate config.txt/cmdline.txt."""
    emu68_boot_staging = workflow.state.staging_dir / "EMU68BOOT"
    ensure_dir(emu68_boot_staging)

    # copy Emu68 boot files from downloaded archives
    workflow._update_state(progress=45.0)
    workflow._log("Copying Emu68 boot files")
    _copy_emu68_boot_files(workflow, emu68_boot_staging)

    # copy Kickstart ROM
    workflow._update_state(progress=55.0)
    workflow._log("Copying Kickstart ROM to boot partition")
    rom_filename = _copy_kickstart_rom(workflow, emu68_boot_staging)

    # generate config.txt and cmdline.txt
    workflow._update_state(progress=60.0)
    workflow._log("Generating Emu68 boot config")
    _generate_boot_config(workflow, rom_filename)


def _copy_emu68_boot_files(workflow: BuildWorkflow, emu68_boot_staging: Path) -> None:
    """copy Emu68 boot files from all variant archives to EMU68BOOT staging"""
    emu68_extracted = workflow.state.extracted_paths.get("emu68_boot")

    if not emu68_extracted or not emu68_extracted.exists():
        workflow.logger.warning("No extracted Emu68 boot files found - boot partition may be incomplete")
        return

    # step 1: Copy ALL files from primary variant (pistorm32lite)
    boot_files_copied = 0
    for item in emu68_extracted.iterdir():
        if item.name.lower() == "config.txt":
            workflow.logger.debug("Skipping config.txt from archive (we generate our own)")
            continue
        dest = emu68_boot_staging / item.name
        if item.is_file():
            shutil.copy2(item, dest)
            boot_files_copied += 1
            workflow.logger.debug(f"Copied boot file: {item.name}")
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
            boot_files_copied += 1

    workflow.logger.info(f"Copied {boot_files_copied} Emu68 boot files from primary variant")

    # step 2: Copy Emu68-* kernel binaries from additional variants
    for variant_name in ("emu68_boot_pistorm", "emu68_boot_pistorm16"):
        variant_dir = workflow.state.extracted_paths.get(variant_name)
        if not variant_dir or not variant_dir.exists():
            continue
        for item in variant_dir.iterdir():
            if item.is_file() and item.name.lower().startswith("emu68-"):
                dest = emu68_boot_staging / item.name
                shutil.copy2(item, dest)
                boot_files_copied += 1
                workflow.logger.info(f"Copied kernel from {variant_name}: {item.name}")

    # step 3: Ensure pistorm16 kernel exists (config.txt references it by name)
    _ensure_pistorm16_kernel(emu68_boot_staging, workflow.logger)

    workflow.logger.info(f"Total Emu68 boot files copied: {boot_files_copied}")

    # copy bundled stealth firmware for PS32Lite stealth mode
    stealth_fw = Path(__file__).parent.parent.parent / "data" / "boot_files" / "ps32lite-stealth-firmware.gz"
    if stealth_fw.exists():
        shutil.copy2(stealth_fw, emu68_boot_staging / "ps32lite-stealth-firmware.gz")
        workflow.logger.info("Copied ps32lite-stealth-firmware.gz for stealth mode")


def _copy_kickstart_rom(workflow: BuildWorkflow, emu68_boot_staging: Path) -> str:
    """copy Kickstart ROM to boot partition. returns the ROM filename used"""
    rom_filename = "kick.rom"
    if workflow.state.resolved_rom_info and workflow.state.resolved_rom_info.get("fat32_name"):
        rom_filename = workflow.state.resolved_rom_info["fat32_name"]
    workflow.state.rom_boot_filename = rom_filename

    if workflow.state.resolved_rom_path and workflow.state.resolved_rom_path.exists():
        rom_dest = emu68_boot_staging / rom_filename
        shutil.copy2(workflow.state.resolved_rom_path, rom_dest)
        workflow.logger.info(f"Copied Kickstart ROM to EMU68BOOT as {rom_filename}")
    else:
        workflow.logger.warning("No Kickstart ROM found - boot partition will be incomplete")

    return rom_filename


def _generate_boot_config(workflow: BuildWorkflow, rom_filename: str) -> None:
    """generate config.txt and cmdline.txt for Emu68 boot partition"""
    screen_mode = "1280*720-50"  # default to 720p50 (PAL-friendly)
    custom_cvt = ""

    if workflow.config.display:
        if hasattr(workflow.config.display, 'hdmi_mode') and workflow.config.display.hdmi_mode:
            screen_mode = workflow.config.display.hdmi_mode
        else:
            mode_type = workflow.config.display.screen_mode.value
            if mode_type == "PAL":
                screen_mode = "1280*720-50"
            elif mode_type == "NTSC":
                screen_mode = "1280*720-60"
            elif mode_type == "Custom":
                screen_mode = "Custom"

        if screen_mode == "Custom" and workflow.config.display.custom:
            custom = workflow.config.display.custom
            custom_cvt = f"{custom.width} {custom.height} {custom.framerate}"

    ks_version = workflow.config.kickstart.version.value
    is_ks32 = ks_version.startswith("3.2")

    generate_boot_partition_files(
        workflow.state.staging_dir,
        kickstart_version=ks_version,
        screen_mode=screen_mode,
        custom_cvt=custom_cvt,
        rom_filename=rom_filename,
        first_boot=is_ks32,
    )
    workflow.logger.info(f"Generated config.txt (HDMI mode: {screen_mode}, ROM: {rom_filename}) and cmdline.txt")


def _ensure_pistorm16_kernel(boot_dir: Path, logger) -> None:
    """if Emu68-pistorm kernel exists but Emu68-pistorm16 doesn't, copy it

    config.txt references Emu68-pistorm16 by name for GPIO-based kernel
    selection. if the release doesn't ship a separate pistorm16 build,
    use the pistorm kernel as a fallback.
    """
    pistorm_kernel = None
    has_pistorm16 = False
    for f in boot_dir.iterdir():
        if not f.is_file():
            continue
        name_lower = f.name.lower()
        if name_lower.startswith("emu68-pistorm") and "32lite" not in name_lower and "16" not in name_lower:
            pistorm_kernel = f
        if name_lower.startswith("emu68-pistorm16"):
            has_pistorm16 = True

    if pistorm_kernel and not has_pistorm16:
        ps16_name = pistorm_kernel.name.replace("-pistorm", "-pistorm16", 1)
        dest = boot_dir / ps16_name
        shutil.copy2(pistorm_kernel, dest)
        logger.info(f"Copied {pistorm_kernel.name} as {ps16_name} (pistorm16 fallback)")


# =============================================================================
# phase 3: System Preferences
# =============================================================================


def _configure_preferences(
    workflow: BuildWorkflow,
    boot_staging: Path,
    prefs_dir: Path,
    env_archive: Path,
) -> None:
    """configure Amiga preferences, WiFi, Picasso96 tooltypes, and icon set"""
    from emu68hatcher.builder.prefs import (
        install_default_prefs, LocalePrefs, InputPrefs,
        WBPatternPrefs,
    )

    # binary IFF preference files
    workflow._update_state(progress=70.0)
    workflow._log("Configuring Amiga preferences")

    wb = workflow.config.display.workbench
    locale = LocalePrefs(country="united_kingdom", language="english")
    input_prefs = InputPrefs(keymap="usa", key_repeat_delay=50, key_repeat_speed=10)
    wb_pattern = WBPatternPrefs(backdrop=wb.backdrop if wb else True)

    install_default_prefs(
        prefs_dir,
        screen_mode=None,
        locale=locale,
        input_prefs=input_prefs,
        wb_pattern=wb_pattern,
    )
    workflow.logger.info("Configured Amiga preferences (locale, input, pattern)")

    # WiFi
    if workflow.config.wifi:
        workflow._update_state(progress=80.0)
        workflow._log("Configuring WiFi")
        sys_dir = ensure_dir(env_archive / "Sys")
        wifi_content = f"SSID={workflow.config.wifi.ssid}\nPASSWORD={workflow.config.wifi.password}\n"
        (sys_dir / "wireless.prefs").write_text(wifi_content)
        workflow.logger.info("Generated wireless.prefs")

    # videocore/UAEGFX monitor tooltypes
    workflow._update_state(progress=85.0)
    workflow._log("Configuring Picasso96 monitor")
    _configure_videocore_tooltypes(workflow, boot_staging)

    # icon set
    workflow._update_state(progress=90.0)
    workflow._log("Configuring icons")
    _install_icon_set(workflow, boot_staging, env_archive)



# tooltypes for Videocore.info monitor driver (from reference implementation)
# active tooltypes have no prefix; parenthesized ones are inactive/optional
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

# tooltypes for uaegfx.info (UAE mode) - same BOARDTYPE for P96 compatibility
UAEGFX_TOOLTYPES = [
    "BOARDTYPE=uaegfx",
    "SETTINGSFILE=SYS:DEVS/Picasso96Settings",
    "SOFTSPRITE=Yes",
    "IGNOREMASK=Yes",
]


def _configure_videocore_tooltypes(workflow: BuildWorkflow, boot_staging: Path) -> None:
    """set tooltypes on Videocore.info and uaegfx.info for Picasso96 board detection"""
    from emu68hatcher.builder.amiga_files import write_info_tooltypes

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
        except Exception as e:
            workflow.logger.warning(f"Failed to set {info_name} tooltypes: {e}")


def _install_icon_set(workflow: BuildWorkflow, boot_staging: Path, env_archive: Path) -> None:
    """
    install the selected icon set (GlowIcons, Standard, etc.)

    reads icon_sets.yaml to determine which icons to install and from where.
    """
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
        system_disk = icon_set_config.get("system_disk_icon", {})

        workflow.logger.info(f"  Default drawer icon: {new_folder.get('source', '')}/{new_folder.get('file', '')}")
        workflow.logger.info(f"  System disk icon: {system_disk.get('source', '')}/{system_disk.get('file', '')}")

        # TODO: Extract icons from source ADFs (GlowIcons3_2, Storage3_1, etc.)
        # for now, GlowIcons defaults are typically already in the Workbench 3.2.x ADFs

    except Exception as e:
        workflow.logger.warning(f"Failed to install icon set: {e}")
