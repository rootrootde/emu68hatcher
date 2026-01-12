"""
startup files manager - tool download definitions

uses local startup_files.yaml for tool definitions (HST Imager, HST Amiga, PFS3AIO).
for GitHub-hosted tools, queries the GitHub API to find platform-specific assets.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

from emu68hatcher.data.data_manager import load_yaml_data
from emu68hatcher.utils.platform import get_platform_info


@dataclass
class StartupFile:
    """A startup file/tool definition from CSV"""

    package_name: str
    source: str  # "Web" or "Github"
    source_location: str  # URL or API endpoint
    github_release: str  # version pattern
    github_name: str  # asset name pattern
    file_download_name: str
    hash: str
    files_to_install: str
    file_hash: str
    location_to_install: str


def get_platform_asset_patterns() -> list[str]:
    """
    get GitHub asset name patterns for the current platform

    returns patterns to try in order (newer naming first).
    """
    info = get_platform_info()

    # map our platform names to GitHub asset patterns
    # include both old (osx) and new (macos) naming conventions
    platform_map = {
        ("darwin", "arm64"): ["_console_macos_arm64.zip", "_console_osx_arm64.zip"],
        ("darwin", "x64"): ["_console_macos_x64.zip", "_console_osx_x64.zip"],
        ("linux", "x64"): ["_console_linux_x64.zip"],
        ("linux", "arm64"): ["_console_linux_arm64.zip"],
        ("windows", "x64"): ["_console_windows_x64.zip"],
        ("windows", "x86"): ["_console_windows_x86.zip", "_console_windows_x64.zip"],
    }

    key = (info.os.value, info.arch.value)
    return platform_map.get(key, ["_console_linux_x64.zip"])


def filter_startup_files(package_name: str) -> list[StartupFile]:
    """
    filter startup files for a specific package from local YAML"""
    results = []

    rows = load_yaml_data("startup_files")

    for row in rows:
        if row.get("package_name") != package_name:
            continue

        results.append(
            StartupFile(
                package_name=row.get("package_name", ""),
                source=row.get("source", ""),
                source_location=row.get("source_location", ""),
                github_release=row.get("github_release", ""),
                github_name=row.get("github_name", ""),
                file_download_name=row.get("file_download_name", ""),
                hash=row.get("hash", ""),
                files_to_install=row.get("files_to_install", ""),
                file_hash=row.get("file_hash", ""),
                location_to_install=row.get("location_to_install", ""),
            )
        )

    return results


def get_github_release_asset(
    api_url: str,
    version_pattern: str = "",
    use_latest: bool = True,
) -> Optional[tuple[str, str]]:
    """
    query GitHub API to find a release asset for the current platform"""
    # get our platform's patterns to try
    platform_patterns = get_platform_asset_patterns()

    try:
        with urlopen(api_url, timeout=30) as response:
            releases = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"Error fetching releases: {e}")
        return None

    # try releases (sorted by date, latest first)
    for release in releases:
        # skip pre-releases unless no stable found
        if release.get("prerelease", False):
            continue

        tag = release.get("tag_name", "")

        # check version if not using latest
        if not use_latest and version_pattern:
            if version_pattern not in tag:
                continue

        # try each platform pattern
        for pattern in platform_patterns:
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                # check if this asset matches our platform pattern
                if pattern in name:
                    return asset.get("browser_download_url"), name

        # if we found a matching release (by version), stop here even if no asset
        if not use_latest:
            break

    return None


def get_tool_download_info(tool_name: str) -> Optional[dict]:
    """
    get download info for a tool from the startup files CSV"""
    files = filter_startup_files(tool_name)
    if not files:
        return None

    # get the first file entry (they all have same source info)
    f = files[0]

    if f.source == "Github":
        result = get_github_release_asset(
            f.source_location,
            f.github_release,
        )
        if result:
            return {
                "download_url": result[0],
                "filename": result[1],
                "hash": f.hash,
                "package_name": f.package_name,
            }

    elif f.source == "Web":
        return {
            "download_url": f.source_location,
            "filename": f.file_download_name,
            "hash": f.hash,
            "package_name": f.package_name,
        }

    return None


if __name__ == "__main__":
    # test
    print("Platform asset patterns:", get_platform_asset_patterns())

    for tool in ["HST-Imager", "HST-Amiga", "PFS3AIO"]:
        print(f"\n{tool}:")
        info = get_tool_download_info(tool)
        if info:
            print(f"  URL: {info['download_url']}")
            print(f"  File: {info['filename']}")
        else:
            print("  Not found")
