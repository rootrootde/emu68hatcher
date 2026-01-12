"""
script generator for Amiga startup scripts

uses Jinja2 templates to generate Startup-Sequence, User-Startup, and other scripts
that match the original Emu68 Imager output.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from emu68hatcher.builder.templates import render_template
from emu68hatcher.utils.paths import ensure_dir


@dataclass
class ScriptConfig:
    """configuration for script generation"""

    # system settings
    kickstart_version: str = "3.1"
    boot_device: str = "SDH0"
    work_device: str = "SDH1"

    # features enabled
    has_picasso96: bool = True
    has_amissl: bool = True
    has_mui: bool = True
    has_roadshow: bool = True
    has_whdload: bool = False
    has_dopus: bool = False

    # network settings
    wifi_enabled: bool = False
    wifi_ssid: str = ""
    wifi_password: str = ""

    # display settings
    screen_mode: str = "Videocore"


def generate_startup_sequence(config: ScriptConfig) -> str:
    """
    generate Startup-Sequence that matches the original Emu68 Imager

    the original injects several sections into the Workbench Startup-Sequence.
    this generates a complete one with all the standard sections.
    """
    return render_template("startup_sequence.j2", config=config)


def generate_shell_startup() -> str:
    """generate Shell-Startup script"""
    return render_template("shell_startup.j2")


def generate_onetimerun_wb() -> str:
    """
    generate OneTimeRunWB script for first-boot Workbench tasks

    this runs after Workbench loads on first boot.
    """
    return render_template("onetimerun_wb.j2")


def get_screen_modes() -> list[dict]:
    """load screen modes from YAML"""
    try:
        from emu68hatcher.data.data_manager import load_yaml_data
        return load_yaml_data("screen_modes")
    except Exception:
        # fallback to hardcoded modes
        return [
            {"name": "Auto", "friendly_name": "Automatic", "hdmi_group": 0},
            {"name": "1280*720-50", "friendly_name": "720p 50hz", "hdmi_group": 1, "hdmi_mode": 19},
            {"name": "1280*720-60", "friendly_name": "720p 60hz", "hdmi_group": 2, "hdmi_mode": 85},
            {"name": "1920*1080-50", "friendly_name": "1080p 50hz", "hdmi_group": 1, "hdmi_mode": 31},
            {"name": "1920*1080-60", "friendly_name": "1080p 60hz", "hdmi_group": 2, "hdmi_mode": 82},
        ]


def generate_config_txt(
    kickstart_version: str = "3.1",
    screen_mode: str = "1080*50",
    custom_cvt: str = "",
    rom_filename: str = "kick.rom",
) -> str:
    """
    generate config.txt for Emu68 boot partition

    this is the Raspberry Pi config file that configures Emu68.
    includes GPIO-based detection for different PiStorm variants."""
    # load available screen modes from YAML
    available_modes = get_screen_modes()

    # handle legacy PAL/NTSC names
    mode_name_map = {
        "pal": "1080*50",
        "ntsc": "1080*60",
        "custom": "Custom",
    }
    screen_mode_normalized = mode_name_map.get(screen_mode.lower(), screen_mode)

    # determine if using custom mode
    is_custom_mode = screen_mode_normalized.lower() == "custom" and custom_cvt

    return render_template(
        "config_txt.j2",
        kickstart_version=kickstart_version,
        screen_mode=screen_mode_normalized,
        custom_cvt=custom_cvt,
        rom_filename=rom_filename,
        available_modes=available_modes,
        is_custom_mode=is_custom_mode,
    )


def generate_boot_partition_files(
    staging_dir: Path,
    kickstart_version: str = "3.1",
    screen_mode: str = "1080*50",
    custom_cvt: str = "",
    rom_filename: str = "kick.rom",
    first_boot: bool = False,
) -> None:
    """
    generate files for the EMU68BOOT (FAT32) partition"""
    boot_dir = ensure_dir(staging_dir / "EMU68BOOT")

    # generate config.txt with GPIO-based kernel selection
    config_txt = generate_config_txt(
        kickstart_version=kickstart_version,
        screen_mode=screen_mode,
        custom_cvt=custom_cvt,
        rom_filename=rom_filename,
    )
    (boot_dir / "config.txt").write_text(config_txt)

    # generate cmdline.txt with Emu68 boot parameters
    # base parameters always included
    base_cmdline = "sd.low_speed emmc.low_speed sd.unit0=rw emmc.unit0=rw"

    # add FirstBoot parameters for KS 3.2.x
    if first_boot:
        cmdline = f"buptest=512 bupiter=1 {base_cmdline}"
    else:
        cmdline = base_cmdline

    (boot_dir / "cmdline.txt").write_text(cmdline + "\n")

    # write backup cmdline without buptest/bupiter for post-first-boot restore
    # the Cmdline OneTimeRunWB script renames this back to cmdline.txt
    if first_boot:
        (boot_dir / "cmdlineBAK.txt").write_text(base_cmdline + "\n")
