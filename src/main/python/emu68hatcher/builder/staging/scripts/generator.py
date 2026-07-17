"""Jinja2-based Amiga startup script generator - Startup-Sequence, User-Startup etc. mirrors upstream imager"""

from pathlib import Path

from emu68hatcher.builder.staging.scripts.templates import render_template
from emu68hatcher.data.data_manager import load_yaml_data
from emu68hatcher.utils.paths import ensure_dir


def generate_shell_startup() -> str:
    """generate Shell-Startup script"""
    return render_template("shell_startup.j2")


def get_screen_modes() -> list[dict]:
    """load screen modes form bundled YAML"""
    return load_yaml_data("screen_modes")


# kernel filenames per release. modern = pistorm32-lite/16, classic = old PiStorm. 1.1+ ships .gz
EMU68_KERNELS: dict[str, dict[str, str]] = {
    "1.0.7": {
        "modern": "Emu68-pistorm32lite",
        "classic": "Emu68-pistorm",
        "pistorm16": "Emu68-pistorm",
    },
    "1.1.0-alpha.1": {
        "modern": "Emu68-pistorm.gz",
        "classic": "Emu68-pistorm-classic.gz",
        "pistorm16": "Emu68-pistorm.gz",
    },
}


def generate_config_txt(
    kickstart_version: str = "3.1",
    screen_mode: str = "1080*50",
    custom_cvt: str = "",
    rom_filename: str = "kick.rom",
    emu68_version: str = "1.0.7",
) -> str:
    """generate Emu68 boot config.txt wiht GPIO-based detection for PiStorm variants"""
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

    kernels = EMU68_KERNELS.get(emu68_version, EMU68_KERNELS["1.0.7"])

    return render_template(
        "config_txt.j2",
        kickstart_version=kickstart_version,
        screen_mode=screen_mode_normalized,
        custom_cvt=custom_cvt,
        rom_filename=rom_filename,
        available_modes=available_modes,
        is_custom_mode=is_custom_mode,
        kernel_modern=kernels["modern"],
        kernel_classic=kernels["classic"],
        kernel_pistorm16=kernels["pistorm16"],
    )


def generate_boot_partition_files(
    staging_dir: Path,
    kickstart_version: str = "3.1",
    screen_mode: str = "1080*50",
    custom_cvt: str = "",
    rom_filename: str = "kick.rom",
    emu68_version: str = "1.0.7",
) -> None:
    """generate files for the EMU68BOOT (FAT32) partition"""
    boot_dir = ensure_dir(staging_dir / "EMU68BOOT")

    # generate config.txt wiht GPIO-based kernel selection
    config_txt = generate_config_txt(
        kickstart_version=kickstart_version,
        screen_mode=screen_mode,
        custom_cvt=custom_cvt,
        rom_filename=rom_filename,
        emu68_version=emu68_version,
    )
    (boot_dir / "config.txt").write_text(config_txt, newline="\n")

    # 1.1+ hangs on buptest cmdline params; only 1.0.x runs the burn-in test
    base_cmdline = "sd.low_speed emmc.low_speed sd.unit0=rw emmc.unit0=rw"
    if emu68_version.startswith("1.1"):
        (boot_dir / "cmdline.txt").write_text(base_cmdline + "\n", newline="\n")
    else:
        (boot_dir / "cmdline.txt").write_text(
            f"buptest=512 bupiter=1 {base_cmdline}\n", newline="\n"
        )
        (boot_dir / "cmdlineBAK.txt").write_text(base_cmdline + "\n", newline="\n")
