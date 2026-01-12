"""
tool downloader - downloads HST Imager, 7-Zip, and other required tools

uses tools.csv for download URLs and platform-specific binaries.
"""

import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

from emu68hatcher.data.data_manager import load_yaml_data
from emu68hatcher.data.startup_files import get_tool_download_info
from emu68hatcher.utils.platform import get_platform_info
from emu68hatcher.utils.paths import get_tools_dir


def get_tool_url(name: str, platform: str) -> Optional[dict]:
    """
    get tool download info from YAML"""
    try:
        tools = load_yaml_data("tools")
        tool_entry = tools.get(name, {})

        # try exact platform match first
        if platform in tool_entry:
            return tool_entry[platform]

        # try platform-agnostic entry (e.g., "windows" instead of "windows-x64")
        base_platform = platform.split("-")[0]
        if base_platform in tool_entry:
            return tool_entry[base_platform]
    except Exception:
        pass
    return None


def download_file(url: str, dest: Path, progress_callback=None) -> bool:
    """
    download a file from URL to destination"""
    try:
        with urlopen(url) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 8192

            with open(dest, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        return True
    except Exception as e:
        print(f"Download error: {e}")
        return False


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """extract a zip file. returns list of extracted files"""
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            extracted_path = zf.extract(info, dest_dir)
            extracted.append(Path(extracted_path))
    return extracted


def download_7zip(force: bool = False, progress_callback=None) -> Optional[Path]:
    """
    download 7-Zip standalone binary for the current platform"""
    tools_dir = get_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)

    info = get_platform_info()
    os_name = info.os.value
    arch = info.arch.value
    platform_key = f"{os_name}-{arch}"

    # target binary path
    if os_name == "windows":
        target_path = tools_dir / "7za.exe"
    else:
        target_path = tools_dir / "7za"

    # check if already installed
    if not force and target_path.exists():
        print(f"7-Zip already installed at {target_path}")
        return target_path

    # check system path
    system_7z = shutil.which("7z") or shutil.which("7za")
    if system_7z:
        print(f"7-Zip found in system: {system_7z}")
        return Path(system_7z)

    # get download info from CSV
    dl_info = get_tool_url("7zip", platform_key)
    if not dl_info or not dl_info["url"]:
        if os_name == "darwin":
            print("No pre-built 7-Zip available for macOS.")
            print("Please install via Homebrew: brew install p7zip")
            return None
        print(f"No 7-Zip download available for {platform_key}")
        return None

    url = dl_info["url"]
    binary_subpath = dl_info["binary"]
    extract_method = dl_info["extract_method"]

    print(f"Downloading 7-Zip for {platform_key}...")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        filename = url.split("/")[-1]
        archive_path = temp_path / filename

        if not download_file(url, archive_path, progress_callback):
            print("Failed to download 7-Zip")
            return None

        print("Extracting...")
        extract_dir = temp_path / "extracted"
        extract_dir.mkdir()

        binary_file = None

        if extract_method == "zip":
            extract_zip(archive_path, extract_dir)
            binary_name = "7za.exe" if os_name == "windows" else "7za"
            for candidate in extract_dir.rglob(binary_name):
                if candidate.is_file():
                    binary_file = candidate
                    break

        elif extract_method == "tar":
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(extract_dir)
            for candidate in extract_dir.rglob("7za"):
                if candidate.is_file():
                    binary_file = candidate
                    break

        elif extract_method == "self":
            # windows .7z file - need 7zr.exe to bootstrap
            if os_name == "windows":
                print("Downloading 7-Zip bootstrap...")
                bootstrap = get_tool_url("7zr-bootstrap", "windows")
                if bootstrap and bootstrap["url"]:
                    sevenzr_path = temp_path / "7zr.exe"
                    if download_file(bootstrap["url"], sevenzr_path):
                        try:
                            subprocess.run(
                                [str(sevenzr_path), "x", str(archive_path), f"-o{extract_dir}"],
                                check=True,
                                capture_output=True,
                            )
                            candidate = extract_dir / binary_subpath
                            if candidate.exists():
                                binary_file = candidate
                        except subprocess.CalledProcessError as e:
                            print(f"Extraction failed: {e}")

        # install the binary if found
        if binary_file:
            shutil.copy2(binary_file, target_path)
            os.chmod(target_path, 0o755)
            print(f"Installed: {target_path}")
            return target_path

        print("Failed to extract 7-Zip binary")
        return None




def download_tool(
    tool_name: str,
    force: bool = False,
    progress_callback=None,
) -> Optional[Path]:
    """
    download a tool using info from startup_files.csv."""
    tools_dir = get_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)

    binary_names = {
        "HST-Imager": "hst-imager",
        "HST-Amiga": "hst-amiga",
    }

    binary_name = binary_names.get(tool_name)
    if not binary_name:
        print(f"Unknown tool: {tool_name}")
        return None

    target_path = tools_dir / binary_name

    if target_path.exists() and not force:
        print(f"{tool_name} already installed at {target_path}")
        return target_path

    print(f"Fetching download info for {tool_name}...")
    info = get_tool_download_info(tool_name)

    if not info:
        print(f"Could not find download info for {tool_name}")
        return None

    download_url = info["download_url"]
    filename = info["filename"]

    print(f"Downloading {filename}...")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / filename

        if not download_file(download_url, archive_path, progress_callback):
            print(f"Failed to download {tool_name}")
            return None

        if filename.endswith(".zip"):
            print("Extracting...")
            extract_dir = temp_path / "extracted"
            extract_dir.mkdir()
            extract_zip(archive_path, extract_dir)

            direct_names = {
                "HST-Imager": ["hst.imager", "Hst.Imager.Console"],
                "HST-Amiga": ["hst.amiga", "Hst.Amiga.ConsoleApp"],
            }

            binary_path = None
            for name in direct_names.get(tool_name, []):
                candidate = extract_dir / name
                if candidate.exists() and candidate.is_file():
                    binary_path = candidate
                    break

            if not binary_path:
                for name in direct_names.get(tool_name, []):
                    for candidate in extract_dir.rglob(name):
                        if candidate.is_file():
                            binary_path = candidate
                            break
                    if binary_path:
                        break

            if binary_path:
                shutil.copy2(binary_path, target_path)
                os.chmod(target_path, 0o755)
                print(f"Installed: {target_path}")
                return target_path
            else:
                print("Could not find binary in archive")
                return None

        else:
            print(f"Unknown archive format: {filename}")
            return None

    return None


def download_all_tools(force: bool = False) -> dict[str, Optional[Path]]:
    """
    download all required tools (HST Imager, HST Amiga, 7-Zip)

    returns dict of tool_name -> installed_path (or None if failed)
    """
    results = {}

    print(f"\n{'='*50}")
    print("Tool: 7-Zip")
    print("=" * 50)
    results["7z"] = download_7zip(force=force)

    for tool in ["HST-Imager", "HST-Amiga"]:
        print(f"\n{'='*50}")
        print(f"Tool: {tool}")
        print("=" * 50)
        results[tool] = download_tool(tool, force=force)

    return results


def check_tools() -> dict[str, bool]:
    """check which tools are installed. returns dict of tool_name -> is_installed"""
    tools_dir = get_tools_dir()
    info = get_platform_info()

    if info.os.value == "windows":
        local_7z = tools_dir / "7za.exe"
    else:
        local_7z = tools_dir / "7za"

    has_7z = (
        local_7z.exists()
        or shutil.which("7z") is not None
        or shutil.which("7za") is not None
    )

    return {
        "HST-Imager": (tools_dir / "hst-imager").exists(),
        "HST-Amiga": (tools_dir / "hst-amiga").exists(),
        "7z": has_7z,
    }


def get_tool_path(tool_name: str) -> Optional[Path]:
    """
    get path to an installed tool"""
    tools_dir = get_tools_dir()
    info = get_platform_info()

    if tool_name == "7z":
        if info.os.value == "windows":
            local_7z = tools_dir / "7za.exe"
        else:
            local_7z = tools_dir / "7za"

        if local_7z.exists():
            return local_7z

        path = shutil.which("7z") or shutil.which("7za")
        return Path(path) if path else None

    tool_path = tools_dir / tool_name
    return tool_path if tool_path.exists() else None


if __name__ == "__main__":
    print("Checking installed tools...")
    status = check_tools()
    for tool, installed in status.items():
        status_str = "installed" if installed else "NOT FOUND"
        print(f"  {tool}: {status_str}")

    print("\nDownloading missing tools...")
    download_all_tools()
