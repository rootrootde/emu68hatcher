"""Commercial archive validation."""

import os.path
import subprocess
from pathlib import Path

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.utils.host_tools import find_7z, run_7z

_ROADSHOW_INNER_FULL_NAMES = ("Roadshow-1.15.lha", "Roadshow-1.16.lha")


def validate_roadshow_archive(path: Path | None) -> tuple[Path | None, str | None]:
    if path is None:
        return None, None
    archive = Path(path).expanduser()
    if not archive.exists():
        raise BuildError(f"Roadshow archive not found: {archive}")
    if archive.is_dir():
        return archive, _classify_roadshow_dir(archive)
    if archive.is_file():
        return archive, _classify_roadshow_file(archive)
    raise BuildError(f"Roadshow archive is neither a file nor a directory: {archive}")


def validate_picasso96_archive(path: Path | None) -> Path | None:
    if path is None:
        return None
    archive = Path(path).expanduser()
    if not archive.exists():
        raise BuildError(f"Picasso96 archive not found: {archive}")
    if not archive.is_file():
        raise BuildError(f"Picasso96 archive must be a .lha file: {archive}")
    if not _archive_has_picasso96install(archive):
        raise BuildError(
            f"{archive.name} does not look like a Picasso96 archive "
            "(no Picasso96Install/ directory inside)"
        )
    return archive


def _list_archive_paths(path: Path, label: str) -> list[str]:
    seven_z = find_7z()
    if seven_z is None:
        raise BuildError(f"7-Zip not found; cannot probe {label} archive")
    try:
        result = run_7z(seven_z, ["l", "-slt", str(path)], timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise BuildError(f"could not list {label} archive {path.name}: {e}") from e
    if result.returncode != 0:
        raise BuildError(
            f"7-Zip rejected {label} archive {path.name}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    paths = []
    for line in result.stdout.splitlines():
        if not line.startswith("Path = "):
            continue
        value = line[7:]
        if os.path.isabs(value):
            continue
        paths.append(value.replace("\\", "/"))
    return paths


def _archive_has_picasso96install(path: Path) -> bool:
    return any(
        entry == "Picasso96Install" or entry.startswith("Picasso96Install/")
        for entry in _list_archive_paths(path, "Picasso96")
    )


def _classify_roadshow_file(path: Path) -> str:
    entries = _list_archive_paths(path, "Roadshow")
    if any(entry.startswith("Roadshow-1.15/Workbench") for entry in entries):
        return "inner_full"
    if any(entry in _ROADSHOW_INNER_FULL_NAMES for entry in entries):
        return "outer"
    if any(entry.startswith("Roadshow-Demo-") for entry in entries):
        raise BuildError(
            f"{path.name} looks like a Roadshow demo archive; "
            "leave the field empty to use the bundled demo instead."
        )
    raise BuildError(
        f"{path.name} does not look like a Roadshow release archive "
        "(expected an outer envelope with Roadshow-1.15.lha, or the full release itself)."
    )


def _classify_roadshow_dir(path: Path) -> str:
    if (path / "Roadshow-1.15" / "Workbench" / "Libs" / "bsdsocket.library").exists():
        return "dir_full"
    if (path / "Workbench" / "Libs" / "bsdsocket.library").exists():
        return "dir_inner"
    raise BuildError(
        f"{path} does not look like an extracted Roadshow release "
        "(expected Roadshow-1.15/Workbench/ or Workbench/ inside)."
    )
