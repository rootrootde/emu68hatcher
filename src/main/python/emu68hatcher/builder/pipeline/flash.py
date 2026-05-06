"""flash stage - write built .img to a physical disk (IMG + flash mode only)"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.builder.workflow import BuildStage
from emu68hatcher.config.schema import OutputType

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def stage_flash(workflow: BuildWorkflow) -> None:
    """flash .img to flash_target; no-op for DEVICE mode or IMG mode without flash_target"""
    output = workflow.config.output
    if output is None or output.type != OutputType.IMG or not output.flash_target:
        return

    workflow._update_state(BuildStage.FLASH, 0.0)
    workflow._milestone(f"Flashing image to {output.flash_target}")

    if not workflow.state.image_path or not workflow.state.image_path.exists():
        raise BuildError("image not found - cannot flash")

    from emu68hatcher.builder.host.disk_writer import flash_image_to_disk
    from emu68hatcher.utils.disk_enum import find_disk

    info = find_disk(output.flash_target)
    if info is None:
        raise BuildError(f"target {output.flash_target} is no longer present or not removable")
    if info.is_system_disk:
        raise BuildError(f"refusing to flash to system disk {output.flash_target}")

    if info.mounted_partitions:
        from emu68hatcher.utils.disk_enum import unmount_disk

        unmount_disk(info, workflow.logger, elevation=workflow.state.elevation)

    # online_disk() is a no-op on macos/linux; windows-only re-online after unmount
    from emu68hatcher.utils.disk_enum import online_disk

    online_disk(info, workflow.logger, elevation=workflow.state.elevation)

    def progress_cb(pct: float, msg: str) -> None:
        workflow._update_state(progress=pct, message=msg)

    def cancel_predicate() -> bool:
        return workflow._cancelled

    flash_image_to_disk(
        workflow.state.image_path,
        output.flash_target,
        verify=True,
        skip_unused_sectors=True,  # huge saving on sparse images
        elevation=workflow.state.elevation,
        progress_callback=progress_cb,
        cancel_predicate=cancel_predicate,
    )

    workflow._update_state(progress=100.0)
    workflow._milestone(f"Flashed to {output.flash_target}")
