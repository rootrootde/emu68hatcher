"""tool downloader for tools.yaml types: - platform-url (per os-arch) - direct-url (single url)"""

import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

from emu68hatcher.builder.host.archive import (
    DEFAULT_MAX_EXTRACTED_BYTES,
    _validate_tar_member,
    extract_archive,
)
from emu68hatcher.data.data_manager import load_yaml_data
from emu68hatcher.utils.hashing import verify_hash
from emu68hatcher.utils.paths import get_tools_dir
from emu68hatcher.utils.platform import get_platform_info

logger = logging.getLogger("emu68hatcher.tools")


def resolve_tool_download(name: str) -> dict | None:
    """tools.yaml entry -> dict with at least 'url' (+optional filename, hash, binary, extract_method). None if unresolvable"""
    try:
        tools = load_yaml_data("tools")
    except Exception as e:
        logger.error(f"failed to load tools.yaml: {e}")
        return None

    entry = tools.get(name)
    if not entry:
        return None

    t = entry["type"]

    if t == "platform-url":
        info = get_platform_info()
        platform_key = f"{info.os.value}-{info.arch.value}"
        platforms = entry["platforms"]
        matched = platforms.get(platform_key) or platforms.get(info.os.value)
        return dict(matched) if matched else None

    if t == "direct-url":
        out = {"url": entry["url"]}
        for k in ("filename", "hash", "extract_method"):
            if k in entry:
                out[k] = entry[k]
        return out

    logger.warning(f"unknown tool type {t!r} for {name}")
    return None


def _verify_hash(path: Path, expected_hash: str | None, label: str) -> bool:
    """verify md5 of 'path' against 'expected_hash'; warns and returns True when no hash is configured"""
    if not expected_hash:
        logger.warning(f"{label}: tools.yaml has no hash for this download; integrity unchecked")
        return True
    if not verify_hash(path, expected_hash):
        logger.error(f"{label}: hash mismatch against {expected_hash.lower()} - rejecting")
        return False
    return True


def download_file(url: str, dest: Path, progress_callback=None) -> bool:
    """download file from URL to destination"""
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
        logger.error(f"Download error: {e}")
        return False


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """extract zip with path-traversal + zip-bomb guards, return list of extracted files"""
    result = extract_archive(zip_path, dest_dir)
    if not result.success:
        raise RuntimeError(result.error or f"zip extraction failed: {zip_path}")
    return [p for p in dest_dir.rglob("*") if p.is_file()]


def download_7zip(force: bool = False, progress_callback=None) -> Path | None:
    """download full 7-Zip for current platform"""
    tools_dir = get_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)

    info = get_platform_info()
    os_name = info.os.value
    arch = info.arch.value
    platform_key = f"{os_name}-{arch}"
    is_windows = os_name == "windows"

    # target binary path
    target_path = tools_dir / ("7z.exe" if is_windows else "7zz")

    if not force and target_path.exists():
        print(f"7-Zip already installed at {target_path}")
        return target_path

    # prefer system wide 7zip installation if available
    system_7z = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")
    if system_7z:
        print(f"7-Zip found in system: {system_7z}")
        return Path(system_7z)

    dl_info = resolve_tool_download("7zip")
    if not dl_info or not dl_info.get("url"):
        print(f"No 7-Zip download available for {platform_key}")
        return None

    url = dl_info["url"]
    extract_method = dl_info["extract_method"]
    print(f"Downloading 7-Zip for {platform_key}...")

    # ignore_cleanup_errors: windows defender can hold 7zr.exe handle after subprocess exits and triggers WinError 5
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / url.rsplit("/", 1)[-1]

        if not download_file(url, archive_path, progress_callback):
            print("Failed to download 7-Zip")
            return None

        if not _verify_hash(archive_path, dl_info.get("hash"), "7-Zip"):
            return None

        print("Extracting...")
        extract_dir = temp_path / "extracted"
        extract_dir.mkdir()

        if extract_method == "self-installer-win":
            wanted = _extract_7z_installer(archive_path, extract_dir, temp_path)
        elif extract_method == "tar-xz":
            wanted = _extract_7z_tarxz(archive_path, extract_dir)
        else:
            print(f"Unknown 7-Zip extract method: {extract_method}")
            return None
        if wanted is None:
            return None

        installed_target: Path | None = None
        for name in wanted:
            found = _first_in_tree(extract_dir, name)
            if not found:
                print(f"Could not find {name} in extracted archive")
                return None
            dest = tools_dir / name
            shutil.copy2(found, dest)
            if dest.suffix.lower() in (".exe",) or dest.suffix == "" and dest.name == "7zz":
                os.chmod(dest, 0o755)
            if dest.name == target_path.name:
                installed_target = dest

        if installed_target:
            print(f"Installed: {installed_target}")
            return installed_target

        print("Failed to install 7-Zip binary")
        return None


def _extract_7z_installer(
    archive_path: Path, extract_dir: Path, temp_path: Path
) -> list[str] | None:
    """bootstrap 7zr.exe, unpack the self-extracting windows installer; wanted files or None"""
    # installer .exe is itself a self-extracting 7-Zip archive - need 7zr.exe to bootstrap
    bootstrap = resolve_tool_download("7zr-bootstrap")
    if not bootstrap or not bootstrap.get("url"):
        print("7zr-bootstrap not configured; cannot unpack installer")
        return None
    sevenzr = temp_path / "7zr.exe"
    print("Downloading 7-Zip bootstrap...")
    if not download_file(bootstrap["url"], sevenzr):
        print("Failed to download 7zr.exe bootstrap")
        return None
    try:
        subprocess.run(
            [str(sevenzr), "x", str(archive_path), f"-o{extract_dir}", "-y"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace")
        print(f"7zr extraction failed: {stderr[:300] or e}")
        return None
    return ["7z.exe", "7z.dll", "License.txt"]


def _extract_7z_tarxz(archive_path: Path, extract_dir: Path) -> list[str]:
    """extract the unix tar.xz build with a zip-bomb guard; return wanted files"""
    with tarfile.open(archive_path, "r:xz") as tar:
        members = tar.getmembers()
        cumulative = 0
        for member in members:
            _validate_tar_member(member, extract_dir)
            cumulative += getattr(member, "size", 0) or 0
            if cumulative > DEFAULT_MAX_EXTRACTED_BYTES:
                raise RuntimeError(
                    f"tar would exceed {DEFAULT_MAX_EXTRACTED_BYTES} bytes uncompressed (bomb?)"
                )
        try:
            tar.extractall(extract_dir, filter="data")
        except TypeError:
            tar.extractall(extract_dir)
    return ["7zz", "License.txt"]


def _first_in_tree(root: Path, name: str) -> Path | None:
    """return the first file named 'name' anywhere under 'root', or None"""
    for candidate in root.rglob(name):
        if candidate.is_file():
            return candidate
    return None


def _exe_suffix() -> str:
    """return '.exe' on windows, '' everywhere else"""
    return ".exe" if get_platform_info().os.value == "windows" else ""


# display labels
TOOL_LABELS = {
    "hst-imager": "HST-Imager",
    "hst-amiga": "HST-Amiga",
    "7z": "7-Zip",
}


# a sidecar .version file records which pinned download produced the installed
# binary; an app upgrade that bumps tools.yaml then re-fetches the new version.
def _tool_target_path(tool_name: str) -> Path | None:
    """path our downloader installs 'tool_name' to inside the tools dir"""
    suf = _exe_suffix()
    names = {"hst-imager": f"hst-imager{suf}", "hst-amiga": f"hst-amiga{suf}"}
    name = names.get(tool_name)
    return get_tools_dir() / name if name else None


def _stamp_path(target_path: Path) -> Path:
    return target_path.with_name(target_path.name + ".version")


def _read_stamp(target_path: Path) -> str | None:
    try:
        return _stamp_path(target_path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_stamp(target_path: Path, stamp: str | None) -> None:
    if not stamp:
        return
    try:
        _stamp_path(target_path).write_text(stamp, encoding="utf-8")
    except OSError as e:
        logger.warning(f"could not write version stamp for {target_path.name}: {e}")


def tool_needs_download(tool_name: str) -> bool:
    """True if a pinned tool is missing, or our installed copy is stale vs. tools.yaml"""
    from emu68hatcher.utils.host_tools import find_7z, find_hst_amiga, find_hst_imager

    finders = {"hst-imager": find_hst_imager, "hst-amiga": find_hst_amiga, "7z": find_7z}
    finder = finders.get(tool_name)
    if finder is None:
        return False
    resolved = finder()
    if resolved is None:
        return True  # not installed anywhere
    # only the two pinned GitHub tools are version-managed; 7z is any-recent-version
    target = _tool_target_path(tool_name)
    if target is None or resolved != target:
        return False  # 7z, or resolved from system PATH - not ours to version-manage
    info = resolve_tool_download(tool_name)
    expected = info.get("url") if info else None
    if not expected:
        return False  # can't determine the pinned version - don't churn
    return _read_stamp(target) != expected


def download_tool(
    tool_name: str,
    force: bool = False,
    progress_callback=None,
) -> Path | None:
    """download a GitHub-hosted host tool (hst-imager / hst-amiga)"""
    tools_dir = get_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)
    suf = _exe_suffix()
    label = TOOL_LABELS.get(tool_name, tool_name)

    # target path + published-archive name candidates per tool
    layout = {
        "hst-imager": (
            f"hst-imager{suf}",
            [f"hst.imager{suf}", f"Hst.Imager.Console{suf}"],
        ),
        "hst-amiga": (
            f"hst-amiga{suf}",
            [f"hst.amiga{suf}", f"Hst.Amiga.ConsoleApp{suf}", f"Hst.Amiga{suf}"],
        ),
    }
    if tool_name not in layout:
        print(f"Unknown tool: {tool_name}")
        return None

    target_name, archive_names = layout[tool_name]
    if not suf:
        # unix zips sometimes ship the hyphenated name directly
        archive_names = [target_name] + archive_names
    target_path = tools_dir / target_name

    info = resolve_tool_download(tool_name)
    if not info or not info.get("url"):
        print(f"Could not find download info for {label}")
        return None
    url = info["url"]

    # skip only when the installed copy matches the pinned download (version stamp)
    if target_path.exists() and not force and _read_stamp(target_path) == url:
        print(f"{label} already installed at {target_path}")
        return target_path

    filename = info.get("filename") or url.rsplit("/", 1)[-1]
    print(f"Downloading {filename}...")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / filename

        if not download_file(url, archive_path, progress_callback):
            print(f"Failed to download {label}")
            return None

        if not _verify_hash(archive_path, info.get("hash"), label):
            return None

        if not filename.endswith(".zip"):
            print(f"Unknown archive format: {filename}")
            return None

        print("Extracting...")
        extract_dir = temp_path / "extracted"
        extract_dir.mkdir()
        extract_zip(archive_path, extract_dir)

        binary_path = None
        for name in archive_names:
            candidate = extract_dir / name
            if candidate.is_file():
                binary_path = candidate
                break
        if not binary_path:
            for name in archive_names:
                for candidate in extract_dir.rglob(name):
                    if candidate.is_file():
                        binary_path = candidate
                        break
                if binary_path:
                    break

        if not binary_path:
            print("Could not find binary in archive")
            return None

        shutil.copy2(binary_path, target_path)
        os.chmod(target_path, 0o755)
        _write_stamp(target_path, url)
        print(f"Installed: {target_path}")
        return target_path
