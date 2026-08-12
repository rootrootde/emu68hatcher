"""Contained recursive tree copying."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TreeCopyResult:
    files_copied: int = 0
    skipped_cycles: int = 0
    skipped_outside: int = 0

    def __add__(self, other: TreeCopyResult) -> TreeCopyResult:
        return TreeCopyResult(
            self.files_copied + other.files_copied,
            self.skipped_cycles + other.skipped_cycles,
            self.skipped_outside + other.skipped_outside,
        )


TargetResolver = Callable[[Path, str], Path]


def copy_contained_tree(
    source: Path,
    dest: Path,
    *,
    resolve_target: TargetResolver | None = None,
) -> TreeCopyResult:
    """Merge a tree while containing links and repeated directory identities."""
    source_root = source.resolve(strict=True)
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve(strict=True)
    visited: set[Path] = set()

    def target_for(parent: Path, name: str) -> Path:
        return resolve_target(parent, name) if resolve_target else parent / name

    def walk(current_source: Path, current_dest: Path) -> TreeCopyResult:
        real_source = current_source.resolve(strict=True)
        if not real_source.is_relative_to(source_root):
            return TreeCopyResult(skipped_outside=1)
        if real_source in visited:
            return TreeCopyResult(skipped_cycles=1)
        visited.add(real_source)

        result = TreeCopyResult()
        current_dest.mkdir(parents=True, exist_ok=True)
        for item in current_source.iterdir():
            try:
                real_item = item.resolve(strict=True)
            except OSError:
                result += TreeCopyResult(skipped_outside=1)
                continue
            if not real_item.is_relative_to(source_root):
                result += TreeCopyResult(skipped_outside=1)
                continue

            target = target_for(current_dest, item.name)
            resolved_target = target.resolve()
            if resolved_target != dest_root and not resolved_target.is_relative_to(dest_root):
                result += TreeCopyResult(skipped_outside=1)
                continue

            if item.is_dir():
                result += walk(item, target)
            elif item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                result += TreeCopyResult(files_copied=1)
        return result

    return walk(source, dest)
