"""
package installer using YAML package definitions

installs packages according to their YAML definitions, handling:
- file extraction from downloaded archives
- nested archive extraction (e.g., .lha inside .zip)
- local file copying
- script modifications
"""

import re
import shutil
from pathlib import Path
from typing import Optional, Callable

from emu68hatcher.data.package_loader import (
    get_packages_for_version,
    get_mandatory_packages as _get_mandatory,
    get_default_packages as _get_default,
    get_package_by_name,
)
from emu68hatcher.data.package_schema import Package, InstallRule, ScriptModification, ScriptAction
from emu68hatcher.extractor.archive import extract_archive
from emu68hatcher.utils.paths import ensure_dir

# archive extensions that can be nested and need extraction
ARCHIVE_EXTENSIONS = {'.lha', '.lzh', '.zip', '.7z', '.tar', '.gz', '.tgz'}
from emu68hatcher.utils.logging import get_logger


def _ci_glob_pattern(pattern: str) -> str:
    """convert a glob pattern to be case-insensitive

    amiga filesystems are case-insensitive, so YAML install rules shouldn't
    need to match the exact case of extracted archive paths. this converts
    each letter in the pattern to a [aA] character class, preserving existing
    wildcards and special characters.

    example: "Ibrowse*-OS3/Icons" -> "[iI][bB][rR][oO][wW][sS][eE]*-[oO][sS]3/[iI][cC][oO][nN][sS]"
    """
    result = []
    for ch in pattern:
        if ch.isalpha():
            result.append(f"[{ch.lower()}{ch.upper()}]")
        else:
            result.append(ch)
    return "".join(result)


def _ci_resolve_path(base: Path, rel_path: str) -> Optional[Path]:
    """resolve a relative path case-insensitively against a base directory

    walks each path component and finds a case-insensitive match in the
    filesystem. returns None if any component can't be resolved.
    """
    current = base
    for part in rel_path.split("/"):
        if not part:
            continue
        # try exact match first (fast path)
        exact = current / part
        if exact.exists():
            current = exact
            continue
        # case-insensitive search
        found = False
        if current.is_dir():
            part_lower = part.lower()
            for child in current.iterdir():
                if child.name.lower() == part_lower:
                    current = child
                    found = True
                    break
        if not found:
            return None
    return current


def _merge_tree(source: Path, dest: Path) -> int:
    """merge source directory into dest, preserving existing files

    unlike ``shutil.copytree``, this never deletes existing files in ``dest``.
    new files overwrite same-named files (case-insensitive match via
    ``resolve_staging_path``), and directories are merged recursively.
    """
    from emu68hatcher.builder.amiga_files import resolve_staging_path

    count = 0
    dest.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = resolve_staging_path(dest, item.name)
        if item.is_file():
            shutil.copy2(item, target)
            count += 1
        elif item.is_dir():
            count += _merge_tree(item, target)
    return count


class PackageInstaller:
    """
    installs packages according to YAML definitions

    handles:
    - extracting specific files from archives
    - copying local files
    - script modifications
    """

    def __init__(
        self,
        kickstart_version: str,
        staging_dir: Path,
        extracted_packages_dir: Path,
        local_packages_dir: Optional[Path] = None,
    ):
        """
        initialize the package installer"""
        self.kickstart_version = kickstart_version
        self.staging_dir = staging_dir
        self.extracted_dir = extracted_packages_dir
        self.local_packages_dir = local_packages_dir
        self.logger = get_logger()

        # load packages for this version
        self.packages = get_packages_for_version(kickstart_version)

        # track pending script modifications
        self.pending_scripts: list[tuple[Package, ScriptModification]] = []

        # drive name mapping (System: -> SDH0)
        self.drive_map = {
            "System": "SDH0",
            "Work": "SDH1",
            "Emu68Boot": "EMU68BOOT",
        }

    def get_packages_to_download(self) -> list[dict]:
        """
        get list of packages that need to be downloaded

        returns list of dicts with download info.
        """
        downloads = []
        seen = set()

        for pkg in self.packages:
            if not pkg.download:
                continue

            # skip local packages (no download needed)
            if pkg.download.source.value == "local":
                continue

            # deduplicate by URL/path
            key = pkg.download.url or pkg.download.path or pkg.download.repo
            if key in seen:
                continue
            seen.add(key)

            info = {
                "name": pkg.name,
                "friendly_name": pkg.friendly_name,
                "source": pkg.download.source.value,
            }

            if pkg.download.source.value == "aminet":
                info["path"] = pkg.download.path
                info["search"] = getattr(pkg.download, "search", None)
            elif pkg.download.source.value == "github":
                info["repo"] = pkg.download.repo
                info["asset_pattern"] = pkg.download.asset_pattern
                info["version"] = pkg.download.version
            elif pkg.download.source.value == "web":
                info["url"] = pkg.download.url
                info["backup_url"] = getattr(pkg.download, "backup_url", None)

            if pkg.download.hash:
                info["hash"] = pkg.download.hash
            if pkg.download.filename:
                info["filename"] = pkg.download.filename

            downloads.append(info)

        return downloads

    def get_mandatory_packages(self) -> list[str]:
        """get list of mandatory package names"""
        return [p.name for p in _get_mandatory(self.kickstart_version)]

    def get_default_packages(self) -> list[str]:
        """get list of default package names"""
        return [p.name for p in _get_default(self.kickstart_version)]

    def install_package(
        self,
        package_name: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> int:
        """
        install a single package"""
        pkg = get_package_by_name(package_name)

        if not pkg:
            self.logger.warning(f"Package not found: {package_name}")
            return 0

        if progress_callback:
            progress_callback(f"Installing {pkg.friendly_name}")

        files_installed = 0

        # determine source directory for files
        source_dir = self._get_source_dir(pkg)

        # apply install rules
        for rule in pkg.install:
            count = self._apply_install_rule(pkg, rule, source_dir)
            files_installed += count

        # queue script modifications for later
        for script_mod in pkg.scripts:
            self.pending_scripts.append((pkg, script_mod))

        return files_installed

    def _get_source_dir(self, pkg: Package) -> Optional[Path]:
        """get the source directory for package files"""
        if not pkg.download:
            return None

        if pkg.download.source.value == "local":
            # check extracted dir first (for local archives extracted during build)
            source_dir = self.extracted_dir / pkg.name
            if source_dir.exists():
                return source_dir
            # fall back to local_packages_dir for non-archive local files
            return self.local_packages_dir

        # for downloaded packages, look in extracted_dir
        # try package name first
        source_dir = self.extracted_dir / pkg.name
        if source_dir.exists():
            return source_dir

        # try filename without extension
        if pkg.download.filename:
            base_name = pkg.download.filename
            for ext in [".lha", ".zip", ".7z", ".tar.gz"]:
                if base_name.lower().endswith(ext):
                    base_name = base_name[:-len(ext)]
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
        """
        resolve a path that may contain nested archives

        if a path component is an archive file (e.g., "Contrib/Emu68Info.lha/Emu68Info"),
        extract the archive and return the new base path and remaining pattern."""
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
                            self.logger.warning(f"Failed to extract nested archive {next_path}: {result.error}")
                            return source_dir, path_pattern

                    # return the extracted directory and remaining path
                    remaining = "/".join(parts[i+1:])
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
        source_dir: Optional[Path],
    ) -> int:
        """apply a single install rule"""
        from emu68hatcher.builder.amiga_files import resolve_staging_path

        if not source_dir:
            return 0

        # get source pattern
        source_pattern = rule.source  # 'from' field

        # check for nested archives in the path and extract if needed
        source_dir, source_pattern = self._resolve_nested_archive(source_dir, source_pattern)

        # get destination - resolve case-insensitively to match PFS3 behavior
        # archives may use different casing than Workbench ADFs (e.g. "classes/"
        # vs "Classes/"); without resolution these become separate directories
        # on a case-sensitive host filesystem, causing data loss on PFS3
        dest_base = self.staging_dir / "SDH0"  # default to System drive
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

            # number of directory levels in the glob pattern to strip from matches
            # E.g. "IBrowse*-OS3/Catalogs/*" has 2 nav levels (IBrowse*-OS3, Catalogs)
            # so matched "IBrowse3.0-OS3/Catalogs/bosnian" strips to just "bosnian"
            glob_nav_levels = len(glob_part.split("/")) - 1

            # use case-insensitive glob (Amiga is case-insensitive)
            ci_glob = _ci_glob_pattern(glob_part)

            if search_dir.exists():
                for source_item in search_dir.glob(ci_glob):
                    # strip navigation directories from the matched path
                    rel_parts = source_item.relative_to(search_dir).parts
                    if len(rel_parts) > glob_nav_levels:
                        keep_parts = rel_parts[glob_nav_levels:]
                    else:
                        keep_parts = (source_item.name,)

                    if rule.rename:
                        dest_path = resolve_staging_path(dest_dir, rule.rename)
                    else:
                        dest_path = resolve_staging_path(
                            dest_dir, str(Path(*keep_parts))
                        )

                    if source_item.is_file():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_item, dest_path)
                        files_installed += 1
                    elif source_item.is_dir():
                        files_installed += _merge_tree(
                            source_item, dest_path
                        )
        else:
            # specific file - resolve case-insensitively (Amiga is case-insensitive)
            source_file = _ci_resolve_path(source_dir, source_pattern)
            if not source_file:
                source_file = source_dir / source_pattern  # fallback for logging

            if source_file.exists():
                if rule.rename:
                    dest_path = resolve_staging_path(dest_dir, rule.rename)
                else:
                    dest_path = resolve_staging_path(
                        dest_dir, source_file.name
                    )

                dest_path.parent.mkdir(parents=True, exist_ok=True)

                if source_file.is_dir() and rule.recursive:
                    files_installed += _merge_tree(source_file, dest_path)
                else:
                    shutil.copy2(source_file, dest_path)
                    files_installed = 1

        return files_installed

    def apply_script_modifications(self) -> int:
        """
        apply all pending script modifications

        returns number of modifications applied.
        """
        # group by script target
        by_script: dict[str, list[tuple[Package, ScriptModification]]] = {}

        for pkg, mod in self.pending_scripts:
            target = mod.target
            if target not in by_script:
                by_script[target] = []
            by_script[target].append((pkg, mod))

        count = 0

        for script_path, mods in by_script.items():
            # scripts are in System drive (SDH0)
            full_path = self.staging_dir / "SDH0" / script_path

            if not full_path.exists():
                self.logger.warning(f"Script not found: {full_path}")
                continue

            content = full_path.read_text()

            for pkg, mod in mods:
                if mod.action == ScriptAction.APPEND:
                    content = content.rstrip() + "\n\n" + mod.content + "\n"
                    count += 1

                elif mod.action == ScriptAction.PREPEND:
                    content = mod.content + "\n\n" + content
                    count += 1

                elif mod.action == ScriptAction.INJECT:
                    if mod.marker and mod.marker in content:
                        content = content.replace(
                            mod.marker,
                            mod.content + "\n" + mod.marker
                        )
                        count += 1

            full_path.write_text(content)
            self.logger.info(f"Modified script: {script_path}")

        return count

