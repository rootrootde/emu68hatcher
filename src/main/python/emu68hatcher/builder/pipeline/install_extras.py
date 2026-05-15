"""mirror per-partition extra_content_directory into staging/<device>/"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_install_extras(workflow: BuildWorkflow) -> None:
    """copy each amiga partitions extra_content_directory contents into staging/<device>/"""
    if not workflow.state.staging_dir:
        raise BuildError("Staging directory not set - setup stage may have failed")

    workflow._update_state(BuildStage.INSTALL_EXTRAS, 0.0)
    workflow._milestone("Mirroring per-partition extra content")

    if not workflow.config.partitions:
        workflow._update_state(progress=100.0)
        workflow._milestone("No partitions configured - nothing to mirror")
        return

    parts = [
        p
        for p in workflow.config.partitions.iter_amiga_partitions()
        if p.extra_content_directory is not None
    ]
    if not parts:
        workflow._update_state(progress=100.0)
        workflow._milestone("No per-partition extras configured")
        return

    total_files = 0
    for i, part in enumerate(parts):
        workflow._check_cancelled()
        src = Path(part.extra_content_directory).expanduser()

        if not src.exists() or not src.is_dir():
            workflow.logger.warning(
                f"extra_content_directory for {part.device} ({part.volume}) "
                f"not found or not a directory: {src}"
            )
            continue

        dest = workflow.state.staging_dir / part.device
        dest.mkdir(parents=True, exist_ok=True)

        # user content wins on collision (intentional - "put my files in the image")
        count = _mirror_tree(src, dest)
        total_files += count
        workflow.logger.info(f"Mirrored {count} files from {src} -> staging/{part.device}/")

        progress = ((i + 1) / len(parts)) * 100
        workflow._update_state(progress=progress)

    workflow._update_state(progress=100.0)
    workflow._milestone(f"Extras mirrored ({total_files} files across {len(parts)} partition(s))")


def _mirror_tree(src: Path, dest: Path) -> int:
    """recursive copy; same-name files overwrite. returns files copied"""
    count = 0
    dest_root = dest.resolve()
    src_root = src.resolve()
    for item in src.iterdir():
        # block traversal via dotfile symlinks pointing outside src
        if item.is_symlink():
            try:
                real = item.resolve(strict=True)
            except OSError:
                continue
            if not real.is_relative_to(src_root):
                continue

        target = dest / item.name
        if not target.resolve().parent.is_relative_to(dest_root) and target.resolve() != dest_root:
            continue

        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            count += _mirror_tree(item, target)
        else:
            shutil.copy2(item, target)
            count += 1
    return count
