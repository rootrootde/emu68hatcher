"""
emu68 Hatcher CLI - Command Line Interface for creating Amiga disk images

this is the main entry point for the CLI application.
"""

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

# path setup no longer needed - package is properly installed

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="emu68-hatcher")
def cli():
    """
    emu68 Hatcher - Create bootable Amiga disk images for PiStorm/Emu68

    this tool helps you create SD card images or write directly to disks
    for use with Raspberry Pi-based Amiga accelerators.
    """
    pass


# =============================================================================
# setup Commands
# =============================================================================


@cli.command()
@click.option("--force", is_flag=True, help="Force re-download of all tools")
def setup(force: bool):
    """download required external tools (HST Imager, HST Amiga, etc.)"""
    from emu68hatcher.utils.platform import get_platform_info
    from emu68hatcher.builder.tools import check_tools, download_all_tools
    import shutil

    from emu68hatcher.utils.paths import get_tools_dir

    info = get_platform_info()
    console.print(f"[bold]Platform:[/bold] {info.platform_string}")
    console.print(f"[bold]Tools directory:[/bold] {get_tools_dir()}")
    console.print()

    # check what's already installed
    status = check_tools()

    if all(status.values()) and not force:
        console.print("[green]All tools are already installed![/green]")
        for tool, installed in status.items():
            console.print(f"  {tool}: [green]OK[/green]")
        return

    # show current status
    console.print("[bold]Current status:[/bold]")
    for tool, installed in status.items():
        status_str = "[green]installed[/green]" if installed else "[yellow]missing[/yellow]"
        console.print(f"  {tool}: {status_str}")
    console.print()

    # download missing tools (including 7-Zip)
    console.print("[bold]Downloading tools...[/bold]")
    results = download_all_tools(force=force)

    console.print()
    console.print("[bold]Results:[/bold]")
    all_ok = True
    failed_7z = False
    for tool, path in results.items():
        if path:
            console.print(f"  {tool}: [green]OK[/green] ({path})")
        else:
            console.print(f"  {tool}: [red]FAILED[/red]")
            all_ok = False
            if tool == "7z":
                failed_7z = True

    # show platform-specific help for 7z if it failed
    if failed_7z:
        console.print()
        console.print("[yellow]7-Zip must be installed manually:[/yellow]")
        if info.os.value == "darwin":
            console.print("  brew install p7zip")
        elif info.os.value == "linux":
            console.print("  apt install p7zip-full  (Debian/Ubuntu)")
            console.print("  dnf install p7zip       (Fedora)")

    if not all_ok:
        console.print()
        console.print("[red]Some tools failed to download.[/red]")
        raise SystemExit(1)

    console.print()
    console.print("[green]Setup complete![/green]")


@cli.command()
def status():
    """show current platform info and tool availability"""
    from emu68hatcher.utils.platform import (
        get_platform_info,
        check_dependencies,
        check_optional_dependencies,
        get_platform_tools_dir,
    )

    info = get_platform_info()

    console.print("[bold]Platform Information[/bold]")
    console.print(f"  OS:           {info.os.value}")
    console.print(f"  Architecture: {info.arch.value}")
    console.print(f"  OS Version:   {info.os_version}")
    console.print(f"  Platform ID:  {info.platform_string}")
    console.print(f"  Root/Admin:   {'Yes' if info.is_root else 'No'}")
    console.print()

    console.print("[bold]Required Tools[/bold]")
    console.print(f"  Tools dir: {get_platform_tools_dir()}")
    console.print()

    deps = check_dependencies()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Tool")
    table.add_column("Status")

    for name, available in deps.items():
        status = "[green]Available[/green]" if available else "[red]Missing[/red]"
        table.add_row(name, status)

    console.print(table)

    if not all(deps.values()):
        console.print()
        console.print("[yellow]Run 'emu68-hatcher setup' to download missing tools.[/yellow]")

    # show optional dependencies
    console.print()
    opt_deps = check_optional_dependencies()
    if opt_deps:
        console.print("[bold]Optional Tools[/bold]")
        opt_table = Table(show_header=True, header_style="bold")
        opt_table.add_column("Tool")
        opt_table.add_column("Status")
        for name, available in opt_deps.items():
            status = "[green]Available[/green]" if available else "[dim]Not installed[/dim]"
            opt_table.add_row(name, status)
        console.print(opt_table)


# =============================================================================
# configuration Commands
# =============================================================================


@cli.command()
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output path for config file (default: emu68-config.json)",
)
@click.option(
    "--kickstart", "-k",
    type=click.Choice(["3.1", "3.2", "3.2.2.1", "3.2.3", "3.9"]),
    default="3.2.3",
    help="Kickstart version",
)
@click.option(
    "--size", "-s",
    type=click.Choice(["4", "8", "16", "32", "64", "128", "256", "512"]),
    default="8",
    help="Disk size in GB",
)
@click.option(
    "--boot-size",
    type=int,
    default=None,
    help="Boot partition size in MB (default: auto)",
)
@click.option(
    "--partitions", "-p",
    type=str,
    default=None,
    help="Partition spec: 'Workbench:500M,Work:4G,Games:8G' (default: auto)",
)
def configure(output: Optional[str], kickstart: str, size: str, boot_size: Optional[int], partitions: Optional[str]):
    """create a new build configuration"""
    from emu68hatcher.config.schema import (
        AmigaPartition,
        BuildConfig,
        Filesystem,
        KickstartConfig,
        KickstartVersion,
        create_default_partition_layout,
    )
    from emu68hatcher.config.partition_helpers import (
        build_partition_config,
        calculate_boot_default,
        disk_size_for_gb,
        parse_partition_spec,
        round_to_mbr_sector,
        validate_partition_layout,
    )

    # map string to enum
    ks_map = {
        "3.1": KickstartVersion.V3_1,
        "3.2": KickstartVersion.V3_2,
        "3.2.2.1": KickstartVersion.V3_2_2_1,
        "3.2.3": KickstartVersion.V3_2_3,
        "3.9": KickstartVersion.V3_9,
    }

    if partitions:
        # custom partition layout
        disk_bytes = disk_size_for_gb(int(size))
        if boot_size:
            boot_bytes = round_to_mbr_sector(boot_size * 1024 * 1024)
        else:
            boot_bytes = calculate_boot_default(disk_bytes)

        try:
            specs = parse_partition_spec(partitions)
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            return

        amiga_parts = []
        for i, (vol, sz) in enumerate(specs):
            amiga_parts.append(AmigaPartition(
                device=f"SDH{i}",
                volume=vol,
                filesystem=Filesystem.PFS3,
                size=sz,
                bootable=(i == 0),
            ))

        errors = validate_partition_layout(disk_bytes, boot_bytes, amiga_parts)
        if errors:
            console.print("[red]Partition layout errors:[/red]")
            for err in errors:
                console.print(f"  [red]- {err}[/red]")
            return

        part_config = build_partition_config(disk_bytes, boot_bytes, amiga_parts)
    else:
        # default layout
        part_config = create_default_partition_layout(int(size))

    config = BuildConfig(
        kickstart=KickstartConfig(version=ks_map[kickstart]),
        partitions=part_config,
    )

    output_path = Path(output) if output else Path("emu68-config.json")
    config.to_json_file(output_path)

    console.print(f"[green]Configuration saved to: {output_path}[/green]")

    # show partition summary
    if config.partitions:
        for mbr in config.partitions.layout:
            if mbr.type == "fat32":
                console.print(f"  EMU68BOOT (FAT32): {mbr.size // (1024*1024)} MB")
            elif mbr.amiga_partitions:
                for ap in mbr.amiga_partitions:
                    size_str = f"{ap.size / (1024**3):.1f} GB" if ap.size >= 1024**3 else f"{ap.size // (1024**2)} MB"
                    boot_str = " [boot]" if ap.bootable else ""
                    console.print(f"  {ap.device} ({ap.volume}): {size_str} {ap.filesystem.value}{boot_str}")

    console.print()
    console.print("Next steps:")
    console.print(f"  1. Edit {output_path} to set ROM paths and customize")
    console.print(f"  2. Run: emu68-hatcher validate {output_path}")
    console.print(f"  3. Run: emu68-hatcher build {output_path}")


@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
def validate(config_file: str):
    """validate a build configuration file"""
    from emu68hatcher.config.schema import BuildConfig

    config_path = Path(config_file)

    try:
        config = BuildConfig.from_json_file(config_path)
        console.print(f"[green]Configuration is valid![/green]")
        console.print()
        console.print(f"  Kickstart: {config.kickstart.version.value}")
        hdmi = getattr(config.display, 'hdmi_mode', None) or config.display.screen_mode.value
        console.print(f"  HDMI Mode: {hdmi}")

        if config.partitions:
            disk_gb = config.partitions.disk_size / (1024**3)
            console.print(f"  Disk Size: {disk_gb:.1f} GB")
            console.print(f"  Partitions: {len(config.partitions.layout)}")

        console.print(f"  Packages: {len(config.packages)} selected")

    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/red]")
        raise SystemExit(1)


@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
def info(config_file: str):
    """show detailed information about a config file"""
    from emu68hatcher.config.schema import BuildConfig

    config_path = Path(config_file)

    try:
        config = BuildConfig.from_json_file(config_path)
    except Exception as e:
        console.print(f"[red]Failed to load config: {e}[/red]")
        raise SystemExit(1)

    console.print(f"[bold]Configuration: {config_path.name}[/bold]")
    console.print()

    # metadata
    console.print("[bold]Metadata[/bold]")
    console.print(f"  Version:     {config.version}")
    console.print(f"  Description: {config.metadata.description or '(none)'}")
    console.print(f"  Author:      {config.metadata.author or '(none)'}")
    console.print()

    # kickstart
    console.print("[bold]Kickstart[/bold]")
    console.print(f"  Version: {config.kickstart.version.value}")
    console.print(f"  ROM Dir: {config.kickstart.rom_directory or '(not set)'}")
    console.print()

    # display
    console.print("[bold]Display[/bold]")
    console.print(f"  Screen Mode: {config.display.screen_mode.value}")
    console.print(f"  WB Mode:     {config.display.workbench.screen_mode}")
    console.print(f"  Color Depth: {config.display.workbench.color_depth}")
    console.print()

    # partitions
    if config.partitions:
        console.print("[bold]Partitions[/bold]")
        disk_gb = config.partitions.disk_size / (1024**3)
        console.print(f"  Total Size: {disk_gb:.1f} GB")

        for part in config.partitions.layout:
            size_mb = part.size / (1024**2)
            console.print(f"  [{part.type.upper()}] {part.name}: {size_mb:.0f} MB")

            if part.amiga_partitions:
                for ap in part.amiga_partitions:
                    ap_size_mb = ap.size / (1024**2)
                    boot = " (boot)" if ap.bootable else ""
                    console.print(
                        f"    {ap.device}: {ap.volume} - {ap.filesystem.value} "
                        f"{ap_size_mb:.0f} MB{boot}"
                    )
        console.print()

    # packages
    if config.packages:
        console.print("[bold]Packages[/bold]")
        enabled = [p for p in config.packages if p.enabled]
        console.print(f"  {len(enabled)} packages selected:")
        for pkg in enabled[:10]:
            console.print(f"    - {pkg.name}")
        if len(enabled) > 10:
            console.print(f"    ... and {len(enabled) - 10} more")
        console.print()

    # output
    if config.output:
        console.print("[bold]Output[/bold]")
        console.print(f"  Type: {config.output.type.value}")
        console.print(f"  Path: {config.output.path}")


# =============================================================================
# build Commands
# =============================================================================


@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Override output path from config",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done without doing it")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
def build(config_file: str, output: Optional[str], dry_run: bool, verbose: bool):
    """
    build a disk image from a configuration file

    the config file should be a JSON file created by 'configure' or manually.
    """
    from emu68hatcher.config.schema import BuildConfig, OutputConfig, OutputType
    from emu68hatcher.utils.platform import find_hst_imager
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

    config_path = Path(config_file)

    try:
        config = BuildConfig.from_json_file(config_path)
    except Exception as e:
        console.print(f"[red]Failed to load config: {e}[/red]")
        raise SystemExit(1)

    # override output if specified
    if output:
        output_path = Path(output)
        if str(output_path).startswith("/dev/"):
            config.output = OutputConfig(type=OutputType.DISK, path=output_path)
        else:
            config.output = OutputConfig(type=OutputType.IMG, path=output_path)

    if not config.output:
        console.print("[red]No output path specified in config or command line.[/red]")
        console.print("Use --output or set output.path in the config file.")
        raise SystemExit(1)

    # check for HST Imager
    if not find_hst_imager():
        console.print("[red]HST Imager not found.[/red]")
        console.print("Run 'emu68-hatcher setup' to download required tools.")
        raise SystemExit(1)

    kickstart_version = config.kickstart.version.value

    if dry_run:
        console.print("[yellow]Dry run mode - no changes will be made[/yellow]")
        console.print()
        console.print(f"Would build image for Kickstart {kickstart_version}")
        console.print(f"Would create {config.output.type.value} at {config.output.path}")
        if config.partitions:
            disk_gb = config.partitions.disk_size / (1024**3)
            console.print(f"Disk size: {disk_gb:.1f} GB with {len(config.partitions.layout)} partitions")
        console.print(f"Packages: {len([p for p in config.packages if p.enabled])} enabled")
        return

    # show build summary
    console.print("[bold]Build Configuration[/bold]")
    console.print(f"  Kickstart: {kickstart_version}")
    console.print(f"  Output: {config.output.path}")
    if config.partitions:
        disk_gb = config.partitions.disk_size / (1024**3)
        console.print(f"  Size: {disk_gb:.1f} GB")
    console.print()

    # run the build
    from emu68hatcher.builder.workflow import BuildWorkflow, BuildState, BuildStage

    current_stage = ""
    current_progress = 0.0
    current_message = ""

    def progress_callback(state: BuildState):
        nonlocal current_stage, current_progress, current_message
        current_stage = state.stage.value
        current_progress = state.progress
        current_message = state.message
        if verbose:
            console.print(f"  [{state.stage.value}] {state.message}")

    console.print("[bold]Starting build...[/bold]")
    console.print()

    workflow = BuildWorkflow(config, progress_callback=progress_callback)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
        transient=not verbose,
    ) as progress:
        task = progress.add_task("Building...", total=100)

        # run build in main thread (workflow handles async internally)
        import threading
        result_holder = [None]
        error_holder = [None]

        def run_build():
            try:
                result_holder[0] = workflow.build()
            except Exception as e:
                error_holder[0] = e

        build_thread = threading.Thread(target=run_build)
        build_thread.start()

        # update progress while building
        stage_names = {
            "init": "Initializing",
            "validate": "Validating",
            "download": "Downloading",
            "extract": "Extracting",
            "create_image": "Creating image",
            "install_workbench": "Installing Workbench",
            "install_packages": "Installing packages",
            "configure": "Configuring",
            "finalize": "Finalizing",
            "complete": "Complete",
        }

        while build_thread.is_alive():
            fallback = stage_names.get(current_stage, current_stage.title())
            desc = current_message if current_message else fallback
            if len(desc) > 60:
                desc = desc[:57] + "..."
            progress.update(task, completed=current_progress, description=desc)
            build_thread.join(timeout=0.1)

        progress.update(task, completed=100)

    if error_holder[0]:
        console.print(f"[red]Build error: {error_holder[0]}[/red]")
        raise SystemExit(1)

    result = result_holder[0]
    console.print()

    if result and result.success:
        console.print("[green]Build successful![/green]")
        console.print(f"  Output: {result.output_path}")
        console.print(f"  Duration: {result.duration:.1f} seconds")
        if result.output_path and result.output_path.exists():
            size_mb = result.output_path.stat().st_size / (1024**2)
            console.print(f"  Size: {size_mb:.1f} MB")
    else:
        console.print("[red]Build failed![/red]")
        if result:
            console.print(f"  Error: {result.error}")
        console.print()
        console.print("Stages completed:")
        if result:
            for stage in result.stages_completed:
                console.print(f"  [green]OK[/green] {stage.value}")
        raise SystemExit(1)


# =============================================================================
# list Commands
# =============================================================================


@cli.command("list-kickstarts")
def list_kickstarts():
    """list supported Kickstart versions"""
    from emu68hatcher.config.schema import KickstartVersion

    console.print("[bold]Supported Kickstart Versions[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Version")
    table.add_column("Notes")

    notes = {
        "3.1": "Classic - Most compatible with older software",
        "3.2": "Enhanced - Base Hyperion release",
        "3.2.2.1": "Updated - Bug fixes and improvements",
        "3.2.3": "Latest - Recommended for new setups",
        "3.9": "Bonus Edition - Uses 3.1 ROM with BoingBag updates",
    }

    for ks in KickstartVersion:
        table.add_row(ks.value, notes.get(ks.value, ""))

    console.print(table)


@cli.command("list-packages")
@click.option(
    "--kickstart", "-k",
    type=click.Choice(["3.1", "3.2", "3.2.2.1", "3.2.3", "3.9"]),
    help="Filter packages by Kickstart compatibility",
)
@click.option("--source", "-s", type=click.Choice(["aminet", "github", "all"]), default="all", help="Package source")
def list_packages(kickstart: Optional[str], source: str):
    """list available packages"""
    from emu68hatcher.builder.downloads import get_aminet_packages

    console.print("[bold]Available Packages[/bold]")
    console.print()

    # built-in package definitions
    builtin_packages = {
        "System": [
            ("pfs3aio", "PFS3 All-in-One", "Aminet", "Professional File System 3 handler"),
            ("fat95", "FAT95", "Aminet", "FAT filesystem handler for accessing PC disks"),
            ("mmulibs", "MMU Libraries", "Aminet", "Memory Management Unit libraries"),
        ],
        "Utilities": [
            ("whdload", "WHDLoad", "Web", "Run games and demos from hard disk"),
            ("lha", "LhA", "Aminet", "LHA archive compression/decompression"),
            ("dopus", "Directory Opus", "Aminet", "File manager and desktop replacement"),
            ("sysinfo", "SysInfo", "Aminet", "System information and benchmarking"),
        ],
        "Multimedia": [
            ("multiview", "MultiView", "System", "Universal file viewer"),
        ],
        "Emu68/PiStorm": [
            ("emu68tools", "Emu68 Tools", "GitHub", "Emu68-specific utilities"),
            ("picasso96", "Picasso96", "Aminet", "RTG graphics system"),
            ("brcmwifi", "Broadcom WiFi", "GitHub", "WiFi driver for Raspberry Pi"),
        ],
        "Development": [
            ("vasm", "vasm", "Web", "Portable multi-target assembler"),
            ("vlink", "vlink", "Web", "Portable multi-format linker"),
        ],
    }

    # display packages by category
    for category, packages in builtin_packages.items():
        console.print(f"[bold cyan]{category}[/bold cyan]")

        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("Package", width=15)
        table.add_column("Source", width=8)
        table.add_column("Description")

        for pkg_id, pkg_name, pkg_source, pkg_desc in packages:
            if source != "all":
                if source == "aminet" and pkg_source != "Aminet":
                    continue
                if source == "github" and pkg_source != "GitHub":
                    continue

            source_style = {
                "Aminet": "[blue]Aminet[/blue]",
                "GitHub": "[green]GitHub[/green]",
                "Web": "[yellow]Web[/yellow]",
                "System": "[dim]System[/dim]",
            }.get(pkg_source, pkg_source)

            table.add_row(pkg_name, source_style, pkg_desc)

        console.print(table)
        console.print()

    # show Aminet paths for reference
    if source in ("all", "aminet"):
        console.print("[bold]Aminet Package Paths[/bold]")
        console.print()
        for name, path in sorted(get_aminet_packages().items()):
            console.print(f"  {name}: [dim]{path}[/dim]")


@cli.command("list-screen-modes")
def list_screen_modes():
    """list available screen modes"""
    console.print("[bold]Standard Screen Modes[/bold]")
    console.print()
    console.print("  PAL   - 50Hz European standard (recommended)")
    console.print("  NTSC  - 60Hz American standard")
    console.print("  Custom - CVT-calculated custom mode")
    console.print()
    console.print("[bold]Custom Mode Parameters[/bold]")
    console.print()
    console.print("  Width:    320-1920 pixels")
    console.print("  Height:   200-1200 pixels")
    console.print("  Refresh:  24-75 Hz")
    console.print("  Options:  Interlace, Reduced Blanking")


@cli.command("scan-media")
@click.argument("directory", type=click.Path(exists=True))
@click.option(
    "--kickstart", "-k",
    type=click.Choice(["1.3", "2.04", "3.0", "3.1", "3.2", "3.2.2.1", "3.2.3", "3.9"]),
    help="Check completeness for specific Kickstart version",
)
@click.option("--verbose", "-v", is_flag=True, help="Show all scanned files including unrecognized")
def scan_media(directory: str, kickstart: Optional[str], verbose: bool):
    """
    scan a directory for Kickstart ROMs and install media (ADFs/ISOs)

    uses hash-based detection to identify official Amiga files, matching
    the behavior of the original Emu68 Imager tool.
    """
    from emu68hatcher.data.rom_detection import scan_for_kickstart_roms
    from emu68hatcher.extractor.adf import (
        scan_install_media_by_hash,
        check_install_media_complete,
        get_required_install_media,
    )

    media_dir = Path(directory)

    console.print(f"[bold]Scanning: {media_dir}[/bold]")
    console.print()

    # scan for ROMs
    console.print("[bold cyan]Kickstart ROMs[/bold cyan]")
    roms = scan_for_kickstart_roms(media_dir)

    if roms:
        table = Table(show_header=True, header_style="bold")
        table.add_column("File")
        table.add_column("Version")
        table.add_column("Model")
        table.add_column("Size")

        for rom in roms:
            size_kb = Path(rom["path"]).stat().st_size / 1024
            table.add_row(
                Path(rom["path"]).name,
                rom["version"],
                rom.get("model", "Unknown"),
                f"{size_kb:.0f} KB",
            )

        console.print(table)
    else:
        console.print("[dim]No Kickstart ROMs found[/dim]")

    console.print()

    # scan for install media
    console.print("[bold cyan]Install Media (ADFs/ISOs)[/bold cyan]")

    if kickstart:
        # check completeness for specific version
        # first scan the directory, then check completeness
        all_media = scan_install_media_by_hash(media_dir)
        is_complete, missing = check_install_media_complete(all_media, kickstart)

        # filter found media to only those matching the requested version
        # note: base version disks (e.g., 3.2) are needed for sub-versions (e.g., 3.2.3)
        required = get_required_install_media(kickstart)
        found = [m for m in all_media if m.adf_name in required]

        if found:
            table = Table(show_header=True, header_style="bold")
            table.add_column("File")
            table.add_column("Name")
            table.add_column("Type")
            table.add_column("Hash Match")

            for media in found:
                table.add_row(
                    media.path.name,
                    media.friendly_name,
                    media.install_media,
                    f"[green]{media.md5_hash[:8]}...[/green]",
                )

            console.print(table)

        if missing:
            console.print()
            console.print(f"[yellow]Missing for Kickstart {kickstart}:[/yellow]")
            for name in missing:
                console.print(f"  [red]✗[/red] {name}")
        elif found:
            console.print()
            console.print(f"[green]Complete install media set for Kickstart {kickstart}![/green]")
        else:
            console.print(f"[red]No matching install media found for Kickstart {kickstart}[/red]")
            required = get_required_install_media(kickstart)
            console.print(f"[dim]Required: {', '.join(required)}[/dim]")
    else:
        # scan all media
        media_files = scan_install_media_by_hash(media_dir)

        if media_files:
            table = Table(show_header=True, header_style="bold")
            table.add_column("File")
            table.add_column("Name")
            table.add_column("Type")
            table.add_column("Source")

            for media in media_files:
                table.add_row(
                    media.path.name,
                    media.friendly_name,
                    media.install_media,
                    media.source,
                )

            console.print(table)
            console.print()
            console.print(f"Found {len(media_files)} recognized install media files.")
        else:
            console.print("[dim]No recognized install media found[/dim]")

    console.print()
    console.print("[dim]Tip: Use --kickstart to check completeness for a specific version[/dim]")


@cli.command("list-drives")
def list_drives():
    """list removable drives for physical disk writing"""
    from emu68hatcher.utils.platform import list_removable_drives, get_platform_info

    info = get_platform_info()

    if not info.is_root:
        console.print("[yellow]Warning: Not running as root. Some drives may not be visible.[/yellow]")
        console.print()

    drives = list_removable_drives()

    if not drives:
        console.print("No removable drives found.")
        return

    console.print("[bold]Removable Drives[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Device")
    table.add_column("Name")
    table.add_column("Size")
    table.add_column("Mounted")

    for drive in drives:
        mounted = "[green]Yes[/green]" if drive["mounted"] else "[dim]No[/dim]"
        table.add_row(drive["path"], drive["name"], drive["size"], mounted)

    console.print(table)
    console.print()
    console.print("[yellow]Warning: Writing to a disk will ERASE ALL DATA on it![/yellow]")


# =============================================================================
# flash Command
# =============================================================================


@cli.command()
@click.argument("image_file", type=click.Path(exists=True))
@click.argument("disk", required=False)
@click.option("--verify", is_flag=True, help="Verify write by reading back")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def flash(image_file: str, disk: Optional[str], verify: bool, yes: bool):
    """
    write a disk image to a physical SD card or USB drive

    if DISK is not specified, lists available removable drives for selection.

    \b"""
    from emu68hatcher.builder.disk_manager import DiskManager, WriteProgress
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

    image_path = Path(image_file)
    size_mb = image_path.stat().st_size / (1024 * 1024)
    console.print(f"Image: {image_path.name} ({size_mb:.1f} MB)")
    console.print()

    dm = DiskManager()

    # if no disk specified, list available and let user choose
    if not disk:
        disks = dm.list_removable_disks()
        if not disks:
            console.print("[red]No removable drives found.[/red]")
            console.print("Insert an SD card and try again.")
            raise SystemExit(1)

        console.print("[bold]Available drives:[/bold]")
        for i, d in enumerate(disks, 1):
            console.print(f"  {i}) {d.path}  {d.model}  {d.size_human}")
        console.print()

        if len(disks) == 1:
            choice = 1
            console.print(f"Using only available drive: {disks[0].path}")
        else:
            choice_str = click.prompt("Select drive number", type=int)
            if choice_str < 1 or choice_str > len(disks):
                console.print("[red]Invalid selection.[/red]")
                raise SystemExit(1)
            choice = choice_str

        disk = str(disks[choice - 1].path)
    console.print()

    disk_path = Path(disk)

    # safety checks
    disk_info = dm.get_disk_info(disk_path)
    if disk_info and not disk_info.is_removable:
        console.print(f"[red]WARNING: {disk_path} does not appear to be a removable drive![/red]")
        if not click.confirm("Are you SURE you want to write to this device?"):
            raise SystemExit(1)

    # confirmation
    if not yes:
        console.print(f"[yellow]This will ERASE ALL DATA on {disk_path}![/yellow]")
        console.print(f"  Image:  {image_path} ({size_mb:.1f} MB)")
        console.print(f"  Target: {disk_path}")
        if disk_info:
            console.print(f"  Disk:   {disk_info.model} ({disk_info.size_human})")
        console.print()
        if not click.confirm("Proceed?"):
            console.print("Cancelled.")
            return

    console.print()

    success, error = dm.write_image_to_disk(
        image_path, disk_path, verify=verify,
    )

    console.print()
    if success:
        console.print(f"[green]Image written to {disk_path}[/green]")
    else:
        console.print(f"[red]Flash failed: {error}[/red]")
        raise SystemExit(1)


# =============================================================================
# GUI Command
# =============================================================================


@cli.command()
def gui():
    """launch the graphical user interface"""
    try:
        from emu68hatcher.gui.main_window import launch_gui
        launch_gui()
    except ImportError as e:
        console.print("[red]GUI requires PySide6 package.[/red]")
        console.print("Install with: pip install 'emu68-hatcher[gui]'")
        console.print(f"Error: {e}")
        raise SystemExit(1)


# =============================================================================
# entry Point
# =============================================================================


def main():
    """main entry point"""
    cli()


if __name__ == "__main__":
    main()
