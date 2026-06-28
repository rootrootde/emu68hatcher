"""relocate stock OS files already on SYS: (e.g. move a commodity into WBStartup)"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.staging.files import ci_match_child, resolve_staging_path
from emu68hatcher.data.package_loader import get_package_by_name
from emu68hatcher.utils.paths import ensure_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow


def _ci_resolve(base: Path, rel: str) -> Path | None:
    """case-insensitive lookup of rel under base (Amiga FS semantics); None on any miss"""
    current = base
    for part in rel.split("/"):
        if not part:
            continue
        matched = ci_match_child(current, part)
        if matched is None:
            return None
        current = current / matched
    return current


def apply_relocations(workflow: BuildWorkflow, boot_staging: Path, all_packages: set[str]) -> int:
    """move staged files per enabled packages' relocate rules; returns files moved"""
    moved = 0
    for name in sorted(all_packages):
        pkg = get_package_by_name(name)
        if not pkg or not pkg.relocate:
            continue
        for rule in pkg.relocate:
            moved += _relocate_one(workflow, boot_staging, rule.source, rule.dest)
    return moved


def _relocate_one(workflow: BuildWorkflow, boot_staging: Path, source: str, dest: str) -> int:
    src = _ci_resolve(boot_staging, source)
    if src is None or not src.exists():
        workflow.logger.info(f"relocate: {source} not present, skipping")
        return 0

    dest_dir = resolve_staging_path(boot_staging, dest.strip("/"))
    ensure_dir(dest_dir)

    count = 0
    # move the file and, when present, its sibling .info - the icon travels with the file
    for rel in (source, source + ".info"):
        item = _ci_resolve(boot_staging, rel)
        if item is None or not item.exists():
            continue
        target = resolve_staging_path(dest_dir, item.name)
        if target.exists():
            target.unlink()
        shutil.move(str(item), str(target))
        workflow.logger.info(f"relocate: moved {rel} -> {dest}")
        count += 1
    return count
