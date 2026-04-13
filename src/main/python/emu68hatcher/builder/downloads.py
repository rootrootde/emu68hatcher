"""
robust download manager for Emu68 Hatcher

handles downloading all required files before build:
- startup files (PFS3AIO, etc.)
- packages from Aminet
- packages from GitHub

features:
- retry with exponential backoff
- mirror fallback for Aminet
- persistent caching
- progress reporting
"""

import json
import shutil
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from emu68hatcher.utils.hashing import HashAlgorithm, calculate_hash

from emu68hatcher.utils.paths import get_cache_dir, get_downloads_dir
from emu68hatcher.utils.logging import get_logger
from emu68hatcher.extractor.archive import extract_archive
from emu68hatcher.data.data_manager import load_yaml_data
from emu68hatcher.data.package_loader import (
    get_package_by_name,
    get_mandatory_packages as get_mandatory_package_objs,
)
from emu68hatcher.data.package_schema import SourceType


@dataclass
class DownloadItem:
    """item to download"""
    name: str
    url: str
    filename: str
    expected_hash: Optional[str] = None
    extract: bool = True
    extract_file: Optional[str] = None  # specific file to extract
    mirrors: list[str] = field(default_factory=list)
    optional: bool = False  # if True, download failure is non-fatal


@dataclass
class DownloadResult:
    """result of a download"""
    name: str
    success: bool
    path: Optional[Path] = None
    extracted_path: Optional[Path] = None
    error: Optional[str] = None


ProgressCallback = Callable[[str, int, int], None]  # (name, current, total)


class DownloadManager:
    """manages downloads with caching, retries, and mirrors"""

    AMINET_MIRRORS = [
        "http://aminet.net",
        "http://de.aminet.net",
        "http://us.aminet.net",
        "https://aminet.net",
    ]

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        work_dir: Optional[Path] = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        self.cache_dir = cache_dir or get_cache_dir() / "downloads"
        self.work_dir = work_dir or get_downloads_dir()
        self.max_retries = max_retries
        self.timeout = timeout
        self.logger = get_logger()

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # results
        self.results: dict[str, DownloadResult] = {}

    def _get_cached_path(self, filename: str) -> Path:
        """get path in cache for a file"""
        return self.cache_dir / filename

    def _is_cached(self, filename: str, expected_hash: Optional[str] = None) -> bool:
        """check if file is in cache (optionally verify hash)"""
        cached = self._get_cached_path(filename)
        if not cached.exists():
            return False
        if expected_hash:
            actual = calculate_hash(cached, HashAlgorithm.MD5).upper()
            return actual == expected_hash.upper()
        return True

    def _download_file(
        self,
        url: str,
        dest: Path,
        file_progress: Optional[Callable[[str, int, int], None]] = None,
        name: str = "",
    ) -> bool:
        """download a file with retries and optional byte-level progress"""
        for attempt in range(self.max_retries):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Emu68-Hatcher/1.0"}
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    total = int(response.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 8192
                    with open(dest, "wb") as f:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if file_progress:
                                file_progress(name, downloaded, total)
                    return True
            except Exception as e:
                self.logger.warning(f"Download attempt {attempt + 1} failed for {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # exponential backoff
        return False

    def _try_mirrors(
        self,
        path: str,
        dest: Path,
        mirrors: list[str],
        file_progress: Optional[Callable[[str, int, int], None]] = None,
        name: str = "",
    ) -> bool:
        """try downloading from multiple mirrors"""
        for mirror in mirrors:
            url = f"{mirror.rstrip('/')}/{path.lstrip('/')}"
            self.logger.info(f"Trying mirror: {url}")
            if self._download_file(url, dest, file_progress=file_progress, name=name):
                return True
        return False

    def download(
        self,
        item: DownloadItem,
        file_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> DownloadResult:
        """download a single item"""
        result = DownloadResult(name=item.name, success=False)

        # check cache first
        cached = self._get_cached_path(item.filename)
        if self._is_cached(item.filename, item.expected_hash):
            self.logger.info(f"Using cached: {item.name}")
        else:
            # download
            self.logger.info(f"Downloading: {item.name}")

            # for Aminet URLs, try mirrors
            if "aminet.net" in item.url.lower():
                # extract path after aminet.net
                path = item.url.split("aminet.net", 1)[-1]
                mirrors = item.mirrors if item.mirrors else self.AMINET_MIRRORS
                success = self._try_mirrors(
                    path, cached, mirrors,
                    file_progress=file_progress, name=item.name,
                )
            else:
                success = self._download_file(
                    item.url, cached,
                    file_progress=file_progress, name=item.name,
                )

            if not success:
                result.error = f"Failed to download {item.url}"
                self.results[item.name] = result
                return result

            # verify hash if provided
            if item.expected_hash:
                actual = calculate_hash(cached, HashAlgorithm.MD5).upper()
                if actual != item.expected_hash.upper():
                    result.error = f"Hash mismatch: expected {item.expected_hash}, got {actual}"
                    cached.unlink()
                    self.results[item.name] = result
                    return result

        result.success = True
        result.path = cached

        # extract if needed (always extract, even for cached files)
        if item.extract and cached.suffix.lower() in (".lha", ".zip", ".7z"):
            extract_dir = self.work_dir / "extracted" / item.name
            if extract_dir.exists():
                shutil.rmtree(extract_dir)

            extract_result = extract_archive(cached, extract_dir)
            if extract_result.success:
                result.extracted_path = extract_dir

                # if specific file requested, find it (case-insensitive)
                if item.extract_file:
                    target = item.extract_file.lower()
                    for f in extract_dir.rglob("*"):
                        if f.is_file() and f.name.lower() == target:
                            result.extracted_path = f
                            break
            else:
                result.error = f"Extraction failed: {extract_result.error}"
                result.success = False

        self.results[item.name] = result
        return result

    def download_all(
        self,
        items: list[DownloadItem],
        progress_callback: Optional[ProgressCallback] = None,
        file_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> dict[str, DownloadResult]:
        """download all items"""
        total = len(items)
        for i, item in enumerate(items):
            if progress_callback:
                progress_callback(item.name, i, total)
            self.download(item, file_progress=file_progress)

        if progress_callback:
            progress_callback("Done", total, total)

        return self.results

    def get_result(self, name: str) -> Optional[DownloadResult]:
        """get result for a specific item"""
        return self.results.get(name)

    @property
    def all_successful(self) -> bool:
        """check if all downloads succeeded"""
        return all(r.success for r in self.results.values())

    @property
    def failed_items(self) -> list[str]:
        """get names of failed downloads"""
        return [name for name, r in self.results.items() if not r.success]


# =============================================================================
# required files for builds
# =============================================================================

def get_required_startup_files() -> list[DownloadItem]:
    """get list of required startup files from YAML"""
    items = []

    try:
        rows = load_yaml_data("startup_files")
    except Exception:
        # fallback to hardcoded if YAML not available
        items.append(DownloadItem(
            name="pfs3aio",
            url="http://aminet.net/disk/misc/pfs3aio.lha",
            filename="pfs3aio.lha",
            expected_hash="7AED5D42E9977C1DF3B2B51244D00644",
            extract=True,
            extract_file="pfs3aio",
        ))
        return items

    # look for PFS3AIO in startup files
    for row in rows:
        pkg_name = row.get("package_name", "")
        if pkg_name.upper() == "PFS3AIO":
            source = row.get("source", "")
            location = row.get("source_location", "")
            filename = row.get("file_download_name", "")
            archive_hash = row.get("hash", "")
            file_to_install = row.get("files_to_install", "")

            if source == "Web" and location:
                items.append(DownloadItem(
                    name="pfs3aio",
                    url=location,
                    filename=filename or "pfs3aio.lha",
                    expected_hash=archive_hash if archive_hash else None,
                    extract=True,
                    extract_file=file_to_install.lower() if file_to_install else "pfs3aio",
                ))
                break  # only need one PFS3AIO entry

    return items


def _resolve_github_download(api_url: str, expected_filename: str, logger) -> Optional[str]:
    """
    resolve a GitHub API URL to an actual download URL"""
    try:
        # if URL is for releases (not /latest), get latest release
        if api_url.endswith("/releases"):
            api_url = api_url + "/latest"

        request = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Emu68-Hatcher/1.0"}
        )
        with urllib.request.urlopen(request, timeout=30.0) as response:
            release = json.loads(response.read().decode("utf-8"))

            # find the matching asset
            for asset in release.get("assets", []):
                asset_name = asset.get("name", "")
                # match by expected filename or by similar name
                if (asset_name.lower() == expected_filename.lower() or
                    expected_filename.lower().replace(".zip", "") in asset_name.lower()):
                    download_url = asset.get("browser_download_url")
                    if download_url:
                        logger.debug(f"Resolved GitHub asset: {asset_name} -> {download_url}")
                        return download_url

            # if no exact match, try to find any ZIP file
            for asset in release.get("assets", []):
                asset_name = asset.get("name", "")
                if asset_name.lower().endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    if download_url:
                        logger.debug(f"Resolved GitHub ZIP: {asset_name} -> {download_url}")
                        return download_url

            logger.warning(f"No matching asset found in GitHub release for {expected_filename}")

    except Exception as e:
        logger.warning(f"Failed to resolve GitHub download URL: {e}")

    return None


def get_package_downloads(package_names: list[str], kickstart_version: str = "3.1") -> list[DownloadItem]:
    """
    get download items for packages from YAML definitions

    handles all source types: aminet, github, web, local.
    properly looks up packages by name.
    """
    import logging
    from pathlib import Path
    logger = logging.getLogger("emu68hatcher")

    items = []
    seen_filenames: set[str] = set()  # avoid duplicate downloads

    for pkg_name in package_names:
        pkg = get_package_by_name(pkg_name)

        if not pkg:
            logger.debug(f"Package not found: {pkg_name}")
            continue

        if not pkg.download:
            logger.debug(f"Package has no download info: {pkg_name}")
            continue

        source = pkg.download.source

        # skip local packages (no download needed)
        if source == SourceType.LOCAL:
            logger.debug(f"Skipping local source for {pkg_name}")
            continue

        # determine filename
        if pkg.download.filename:
            filename = pkg.download.filename
        elif pkg.download.path:
            filename = Path(pkg.download.path).name
        elif pkg.download.url:
            filename = pkg.download.url.split("/")[-1]
        else:
            filename = f"{pkg.name}.lha"

        # skip if we already have this file queued
        if filename.lower() in seen_filenames:
            logger.debug(f"Skipping duplicate download: {filename}")
            continue
        seen_filenames.add(filename.lower())

        expected_hash = pkg.download.hash

        # handle different source types
        if source == SourceType.AMINET:
            # aminet download
            aminet_path = pkg.download.path
            if aminet_path:
                url = f"http://aminet.net/{aminet_path}"
                items.append(DownloadItem(
                    name=pkg_name,
                    url=url,
                    filename=filename,
                    expected_hash=expected_hash if expected_hash else None,
                    extract=True,
                ))
                logger.info(f"Queued Aminet download: {pkg_name} from {url}")
            elif pkg.download.search:
                # search-based Aminet package - use search URL
                search_term = pkg.download.search
                url = f"http://aminet.net/search?query={search_term}"
                logger.info(f"Aminet search package needs resolution: {pkg_name} ({search_term})")

        elif source == SourceType.GITHUB:
            # GitHub release download
            repo = pkg.download.repo

            if repo:
                # resolve from GitHub API
                api_url = f"https://api.github.com/repos/{repo}/releases"
                download_url = _resolve_github_download(api_url, filename, logger)
                if download_url:
                    items.append(DownloadItem(
                        name=pkg_name,
                        url=download_url,
                        filename=filename,
                        expected_hash=expected_hash if expected_hash else None,
                        extract=True,
                    ))
                    logger.info(f"Queued GitHub download: {pkg_name} from {download_url}")
                else:
                    logger.warning(f"Failed to resolve GitHub URL for {pkg_name}")

        elif source == SourceType.WEB:
            # direct web download
            url = pkg.download.url
            backup_url = pkg.download.backup_url

            if url:
                items.append(DownloadItem(
                    name=pkg_name,
                    url=url,
                    filename=filename,
                    expected_hash=expected_hash if expected_hash else None,
                    extract=True,
                    mirrors=[backup_url] if backup_url else [],
                ))
                logger.info(f"Queued web download: {pkg_name} from {url}")

        else:
            logger.debug(f"Unknown source type for {pkg_name}: {source}")

    logger.info(f"Total packages queued for download: {len(items)}")
    return items


def get_mandatory_packages(kickstart_version: str = "3.1") -> list[str]:
    """
    get list of mandatory package names that must be downloaded

    these are packages with mandatory=true that have downloadable sources.
    """
    import logging
    logger = logging.getLogger("emu68hatcher")

    mandatory = []
    seen = set()

    # get mandatory packages from YAML definitions
    mandatory_pkgs = get_mandatory_package_objs(kickstart_version)

    for pkg in mandatory_pkgs:
        # skip if no download info
        if not pkg.download:
            continue

        # skip local packages (no download needed)
        if pkg.download.source == SourceType.LOCAL:
            continue

        name = pkg.name
        if name and name.lower() not in seen:
            seen.add(name.lower())
            mandatory.append(name)
            logger.debug(f"Found mandatory package: {name}")

    return mandatory


# each variant ZIP contains one unique kernel binary plus identical common boot files
# GPIO auto-detection in config.txt selects the correct kernel at Pi boot time
EMU68_VARIANT_ZIPS = [
    # (item_name, exact_zip_filename, optional)
    ("emu68_boot", "Emu68-pistorm32lite.zip", False),           # primary - common boot files + ps32lite kernel
    ("emu68_boot_pistorm", "Emu68-pistorm.zip", True),          # original PiStorm kernel (A500/A2000)
    ("emu68_boot_pistorm16", "Emu68-pistorm16.zip", True),      # PiStorm16 kernel (may not exist)
]


def get_emu68_boot_files() -> list[DownloadItem]:
    """
    get download items for all Emu68 boot file variants from GitHub releases

    downloads all available PiStorm variant ZIPs so GPIO auto-detection
    in config.txt can select the correct kernel at boot time. the primary
    variant (pistorm32lite) is required; others are optional."""
    logger = get_logger()
    items = []

    # get latest release from GitHub API (single API call for all variants)
    api_url = "https://api.github.com/repos/michalsc/Emu68/releases/latest"

    try:
        request = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Emu68-Hatcher/1.0"}
        )
        with urllib.request.urlopen(request, timeout=30.0) as response:
            release = json.loads(response.read().decode("utf-8"))

            # build a map of exact filename -> download URL
            asset_map = {}
            for asset in release.get("assets", []):
                asset_name = asset.get("name", "")
                download_url = asset.get("browser_download_url")
                if download_url:
                    asset_map[asset_name] = download_url

            # match each variant by exact filename
            for item_name, zip_filename, is_optional in EMU68_VARIANT_ZIPS:
                if zip_filename in asset_map:
                    items.append(DownloadItem(
                        name=item_name,
                        url=asset_map[zip_filename],
                        filename=zip_filename,
                        extract=True,
                        optional=is_optional,
                    ))
                    logger.debug(f"Found Emu68 variant: {zip_filename}")
                else:
                    if is_optional:
                        logger.info(f"Optional Emu68 variant not found in release: {zip_filename}")
                    else:
                        logger.warning(f"Required Emu68 variant not found in release: {zip_filename}")

    except Exception as e:
        logger.warning(f"Failed to get Emu68 release info from GitHub: {e}")

    return items


def load_aminet_packages() -> dict[str, str]:
    """
    load Aminet package paths from YAML package definitions

    returns dict of package_name -> aminet_path
    """
    from emu68hatcher.data.package_loader import load_all_packages

    packages = {}
    for pkg in load_all_packages():
        if not pkg.download:
            continue
        if pkg.download.source != SourceType.AMINET:
            continue
        aminet_path = pkg.download.path
        if aminet_path:
            packages[pkg.name.lower()] = aminet_path
    return packages


_cached_aminet_packages: Optional[dict[str, str]] = None


def get_aminet_packages() -> dict[str, str]:
    """get Aminet package paths, loading from YAML if needed"""
    global _cached_aminet_packages
    if _cached_aminet_packages is None:
        _cached_aminet_packages = load_aminet_packages()
    return _cached_aminet_packages


