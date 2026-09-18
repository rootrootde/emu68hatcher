"""Copy the selected theme into the boot partition."""

from pathlib import Path

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.staging.files import resolve_source_path, resolve_staging_path
from emu68hatcher.config.display_models import WorkbenchTheme
from emu68hatcher.data.package_loader import get_local_packages_dir
from emu68hatcher.data.themes import get_workbench_theme


def install_workbench_theme(boot_staging: Path, theme: WorkbenchTheme) -> list[Path]:
    definition = get_workbench_theme(theme)
    if definition is None:
        return []

    source_root = get_local_packages_dir().resolve()
    staged: list[Path] = []
    try:
        # read every source before replacing any staged prefs.
        pending: list[tuple[list[str], bytes]] = []
        for files in definition.components.values():
            for file in files:
                source = resolve_source_path(source_root, file.source)
                if source is None or not source.is_file():
                    raise FileNotFoundError(f"Missing theme file: {file.source}")
                if not source.resolve().is_relative_to(source_root):
                    raise ValueError(f"Theme source is outside the bundled files: {file.source}")
                pending.append((file.targets, source.read_bytes()))

        for targets, data in pending:
            for relative in targets:
                target = resolve_staging_path(boot_staging, relative)
                if not target.resolve().is_relative_to(boot_staging.resolve()):
                    raise ValueError(f"Theme target is outside the boot partition: {relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                staged.append(target)
    except (OSError, ValueError) as exc:
        raise BuildError(
            f"Cannot install Workbench theme '{definition.display_name}': {exc}. "
            "Check the bundled theme files and that the build folder is writable, "
            "or select the default theme."
        ) from exc
    return staged
