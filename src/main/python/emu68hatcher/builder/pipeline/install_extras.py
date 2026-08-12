"""mirror per-partition extra_content_directory into staging/<device>/"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.staging.tree_copy import copy_contained_tree
from emu68hatcher.builder.state import BuildStage, CreatedImage

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_install_extras(workflow: BuildWorkflow, image: CreatedImage) -> CreatedImage:
    """copy each amiga partitions extra_content_directory contents into staging/<device>/"""
    workflow._update_state(BuildStage.INSTALL_EXTRAS, 0.0)
    workflow._milestone("Mirroring per-partition extra content")

    if not workflow.config.partitions:
        workflow._update_state(progress=100.0)
        workflow._milestone("No partitions configured - nothing to mirror")
        return image

    parts = [
        p
        for p in workflow.config.partitions.iter_amiga_partitions()
        if p.extra_content_directory is not None
    ]
    if not parts:
        workflow._update_state(progress=100.0)
        workflow._milestone("No per-partition extras configured")
        return image

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

        dest = image.workspace.staging_dir / part.device
        dest.mkdir(parents=True, exist_ok=True)

        # user content wins on collision (intentional - "put my files in the image")
        result = copy_contained_tree(src, dest)
        total_files += result.files_copied
        workflow.logger.info(
            f"Mirrored {result.files_copied} files from {src} -> staging/{part.device}/"
        )
        if result.skipped_cycles:
            workflow.logger.warning(
                f"Skipped {result.skipped_cycles} repeated directories while copying {src}"
            )
        if result.skipped_outside:
            workflow.logger.warning(
                f"Skipped {result.skipped_outside} paths outside the extras root {src}"
            )

        progress = ((i + 1) / len(parts)) * 100
        workflow._update_state(progress=progress)

    workflow._update_state(progress=100.0)
    workflow._milestone(f"Extras mirrored ({total_files} files across {len(parts)} partition(s))")
    return image
