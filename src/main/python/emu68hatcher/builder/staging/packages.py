"""package installer driven by YAML defs - extract (incl nested), copy locals, edit scripts"""

import shutil
from collections.abc import Callable
from pathlib import Path

from emu68hatcher.builder.host.archive import ARCHIVE_EXTENSIONS, extract_archive
from emu68hatcher.config.defaults import DEFAULT_BOOT_DEVICE, DEFAULT_WORK_DEVICE
from emu68hatcher.data.package_loader import (
    get_default_packages as _get_default,
)
from emu68hatcher.data.package_loader import (
    get_mandatory_packages as _get_mandatory,
)
from emu68hatcher.data.package_loader import (
    get_package_by_name,
    get_packages_for_version,
)
from emu68hatcher.data.package_schema import InstallRule, Package, ScriptAction, ScriptModification
from emu68hatcher.utils.logging import get_logger
from emu68hatcher.utils.paths import ensure_dir


def _ci_glob_pattern(pattern: str) -> str:
    """expand glob pattern wiht [aA] char classes for case-insensitive matching (Amiga FS semantics)"""
    result = []
    for ch in pattern:
        if ch.isalpha():
            result.append(f"[{ch.lower()}{ch.upper()}]")
        else:
            result.append(ch)
    return "".join(result)


def _ci_resolve_path(base: Path, rel_path: str) -> Path | None:
    """case-insensitive lookup of 'rel_path' under 'base', returning None on any miss (cf. 'resolve_staging_path')"""
    from emu68hatcher.builder.staging.files import ci_match_child

    current = base
    for part in rel_path.split("/"):
        if not part:
            continue
        matched = ci_match_child(current, part)
        if matched is None:
            return None
        current = current / matched
    return current


def _merge_tree(source: Path, dest: Path) -> int:
    """recursively merge source into dest; same-name collisions overwrite (case-insensitive)"""
    from emu68hatcher.builder.staging.files import resolve_staging_path

    count = 0
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    for item in source.iterdir():
        target = resolve_staging_path(dest, item.name)
        # double-check no symlink-out, even though extractors already filter
        if not target.resolve().parent.is_relative_to(dest_root) and target.resolve() != dest_root:
            continue
        if item.is_symlink():
            # follow the link only if its real target stays under source root
            try:
                real = item.resolve(strict=True)
            except OSError:
                continue
            if not real.is_relative_to(source.resolve()):
                continue
        if item.is_file():
            shutil.copy2(item, target)
            count += 1
        elif item.is_dir():
            count += _merge_tree(item, target)
    return count


class PackageInstaller:
    """installs packages per YAML defs - extract, copy locals, apply script modifications"""

    def __init__(
        self,
        kickstart_version: str,
        staging_dir: Path,
        extracted_packages_dir: Path,
        local_packages_dir: Path | None = None,
        emu68_version: str | None = None,
    ):
        self.kickstart_version = kickstart_version
        self.emu68_version = emu68_version
        self.staging_dir = staging_dir
        self.extracted_dir = extracted_packages_dir
        self.local_packages_dir = local_packages_dir
        self.logger = get_logger()

        self.packages = get_packages_for_version(kickstart_version, emu68_version)

        self.pending_scripts: list[tuple[Package, ScriptModification]] = []

        # System: -> SDH0
        self.drive_map = {
            "System": DEFAULT_BOOT_DEVICE,
            "Work": DEFAULT_WORK_DEVICE,
            "Emu68Boot": "EMU68BOOT",
        }

    def get_mandatory_packages(self) -> list[str]:
        """get list of mandatory package names"""
        return [p.name for p in _get_mandatory(self.kickstart_version, self.emu68_version)]

    def get_default_packages(self) -> list[str]:
        """get list of default package names"""
        return [p.name for p in _get_default(self.kickstart_version, self.emu68_version)]

    def install_package(
        self,
        package_name: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        """install a single package"""
        pkg = get_package_by_name(package_name)

        if not pkg:
            self.logger.warning(f"Package not found: {package_name}")
            return 0

        if progress_callback:
            progress_callback(f"Installing {pkg.friendly_name}")

        files_installed = 0

        source_dir = self._get_source_dir(pkg)

        for rule in pkg.install:
            count = self._apply_install_rule(pkg, rule, source_dir)
            files_installed += count

        for script_mod in pkg.scripts:
            self.pending_scripts.append((pkg, script_mod))

        return files_installed

    def _get_source_dir(self, pkg: Package) -> Path | None:
        """get the source directory for package files"""
        if not pkg.download:
            return None

        if pkg.download.source.value == "local":
            # extracted dir first (for local archives), fall back to local_packages_dir
            source_dir = self.extracted_dir / pkg.name
            if source_dir.exists():
                return source_dir
            return self.local_packages_dir

        source_dir = self.extracted_dir / pkg.name
        if source_dir.exists():
            return source_dir

        # try filename without archive extension
        if pkg.download.filename:
            base_name = pkg.download.filename
            for ext in [".lha", ".zip", ".7z", ".tar.gz"]:
                if base_name.lower().endswith(ext):
                    base_name = base_name[: -len(ext)]
                    break

            source_dir = self.extracted_dir / base_name
            if source_dir.exists():
                return source_dir

        # try case-insensitive search
        for d in self.extracted_dir.iterdir():
            if d.is_dir() and d.name.lower() == pkg.name.lower():
                return d

        self.logger.debug(f"Source directory not found for {pkg.name}")
        return None

    def _resolve_nested_archive(self, source_dir: Path, path_pattern: str) -> tuple[Path, str]:
        """resolve path with nested archives - e.g. "Contrib/Emu68Info.lha/Emu68Info" extracts the .lha and returns (new base, remainder)"""
        parts = path_pattern.split("/")
        current_path = source_dir

        for i, part in enumerate(parts):
            # try case-insensitive resolution for this component
            next_path = current_path / part
            if not next_path.exists() and current_path.is_dir():
                part_lower = part.lower()
                for child in current_path.iterdir():
                    if child.name.lower() == part_lower:
                        next_path = child
                        break

            # check if this is an archive file that needs extraction
            if next_path.is_file():
                suffix = next_path.suffix.lower()
                if suffix in ARCHIVE_EXTENSIONS:
                    # extract the archive to a temp directory
                    extract_dir = next_path.parent / f"_extracted_{next_path.stem}"

                    if not extract_dir.exists():
                        self.logger.info(f"Extracting nested archive: {next_path.name}")
                        result = extract_archive(next_path, extract_dir)

                        if not result.success:
                            self.logger.warning(
                                f"Failed to extract nested archive {next_path}: {result.error}"
                            )
                            return source_dir, path_pattern

                    # return the extracted directory and remaining path
                    remaining = "/".join(parts[i + 1 :])
                    return extract_dir, remaining

            elif next_path.exists():
                current_path = next_path
            else:
                # path doesn't exist, return original
                break

        return source_dir, path_pattern

    def _apply_install_rule(
        self,
        pkg: Package,
        rule: InstallRule,
        source_dir: Path | None,
    ) -> int:
        """apply a single install rule"""
        from emu68hatcher.builder.staging.files import resolve_staging_path

        if not source_dir:
            return 0

        # get source pattern
        source_pattern = rule.source  # 'form' field

        # check for nested archives in the path and extract if needed
        source_dir, source_pattern = self._resolve_nested_archive(source_dir, source_pattern)

        # case-insensitive dest resolution: archives may use different casing than ADFs
        dest_base = self.staging_dir / DEFAULT_BOOT_DEVICE  # default to System drive
        dest_dir = resolve_staging_path(dest_base, rule.dest.strip("/"))

        ensure_dir(dest_dir)

        files_installed = 0

        # handle wildcards
        if "*" in source_pattern:
            # glob pattern - e.g. "IBrowse*-OS3/Catalogs/*"
            parts = source_pattern.split("/")

            # find base directory (non-wildcard prefix) and glob part
            base_parts = []
            glob_part = ""

            for i, part in enumerate(parts):
                if "*" in part:
                    glob_part = "/".join(parts[i:])
                    break
                base_parts.append(part)

            search_dir = source_dir
            if base_parts:
                # resolve non-wildcard prefix case-insensitively
                resolved = _ci_resolve_path(source_dir, "/".join(base_parts))
                if resolved:
                    search_dir = resolved

            # nav-level count to strip from matches: "a/b/*" -> strip 2 ("a", "b")
            glob_nav_levels = len(glob_part.split("/")) - 1

            # use case-insensitive glob (Amiga is case-insensitive)
            ci_glob = _ci_glob_pattern(glob_part)

            if search_dir.exists():
                for source_item in search_dir.glob(ci_glob):
                    # strip navigation directories form the matched path
                    rel_parts = source_item.relative_to(search_dir).parts
                    if len(rel_parts) > glob_nav_levels:
                        keep_parts = rel_parts[glob_nav_levels:]
                    else:
                        keep_parts = (source_item.name,)

                    if rule.rename:
                        dest_path = resolve_staging_path(dest_dir, rule.rename)
                    else:
                        dest_path = resolve_staging_path(dest_dir, str(Path(*keep_parts)))

                    if source_item.is_file():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_item, dest_path)
                        files_installed += 1
                    elif source_item.is_dir():
                        files_installed += _merge_tree(source_item, dest_path)
        else:
            # specific file - resolve case-insensitively (Amiga is case-insensitive)
            source_file = _ci_resolve_path(source_dir, source_pattern)
            if not source_file:
                source_file = source_dir / source_pattern  # fallback for logging

            if source_file.exists():
                if rule.rename:
                    dest_path = resolve_staging_path(dest_dir, rule.rename)
                else:
                    dest_path = resolve_staging_path(dest_dir, source_file.name)

                dest_path.parent.mkdir(parents=True, exist_ok=True)

                if source_file.is_dir() and rule.recursive:
                    files_installed += _merge_tree(source_file, dest_path)
                else:
                    shutil.copy2(source_file, dest_path)
                    files_installed = 1

        return files_installed

    def apply_script_modifications(self) -> int:
        """apply all pending script modifications, returns count"""
        by_script: dict[str, list[tuple[Package, ScriptModification]]] = {}

        for pkg, mod in self.pending_scripts:
            target = mod.target
            if target not in by_script:
                by_script[target] = []
            by_script[target].append((pkg, mod))

        count = 0

        for script_path, mods in by_script.items():
            # scripts are in System drive
            full_path = self.staging_dir / DEFAULT_BOOT_DEVICE / script_path

            if not full_path.exists():
                self.logger.warning(f"Script not found: {full_path}")
                continue

            # AmigaDOS scripts are ISO-8859-1 (windows default would corrupt high bytes)
            content = full_path.read_text(encoding="iso-8859-1")

            for _pkg, mod in mods:
                if mod.action == ScriptAction.APPEND:
                    content = content.rstrip() + "\n\n" + mod.content + "\n"
                    count += 1

                elif mod.action == ScriptAction.PREPEND:
                    content = mod.content + "\n\n" + content
                    count += 1

                elif mod.action == ScriptAction.INJECT:
                    if mod.marker and mod.marker in content:
                        content = content.replace(mod.marker, mod.content + "\n" + mod.marker)
                        count += 1

            full_path.write_text(content, encoding="iso-8859-1")
            self.logger.info(f"Modified script: {script_path}")

        return count
