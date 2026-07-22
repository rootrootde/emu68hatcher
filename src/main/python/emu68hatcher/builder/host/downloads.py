"""download manager - pulls all required files (startup files, Aminet + GitHub packages) before build"""

import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from emu68hatcher.builder.host.archive import extract_archive
from emu68hatcher.utils.hashing import verify_hash
from emu68hatcher.utils.logging import get_logger
from emu68hatcher.utils.paths import get_cache_dir, get_downloads_dir


@dataclass
class DownloadItem:
    """item to download"""

    name: str
    url: str
    filename: str
    expected_hash: str | None = None
    extract: bool = True
    extract_file: str | None = None  # specific file to extract
    mirrors: list[str] = field(default_factory=list)
    optional: bool = False  # if True, download failure is non-fatal


@dataclass
class DownloadResult:
    """result of a download"""

    name: str
    success: bool
    path: Path | None = None
    extracted_path: Path | None = None
    error: str | None = None


DownloadProgressCallback = Callable[[str, int, int], None]  # (name, current, total)


class DownloadManager:
    """manages downloads (caching, retry, mirrors)"""

    # https first, fallback to http
    AMINET_MIRRORS = [
        "https://aminet.net",
        "http://de.aminet.net",
        "http://us.aminet.net",
    ]

    def __init__(
        self,
        cache_dir: Path | None = None,
        work_dir: Path | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
        cancel_callback: Callable[[], bool] | None = None,
    ):
        self.cache_dir = cache_dir or get_cache_dir() / "downloads"
        self.work_dir = work_dir or get_downloads_dir()
        self.max_retries = max_retries
        self.timeout = timeout
        self.logger = get_logger()
        # returns True if cancelled
        self._cancel_cb = cancel_callback
        # latest failure reason -> DownloadResult.error
        self._last_error: str | None = None
        self._last_error_permanent: bool = False

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.results: dict[str, DownloadResult] = {}

    def _cancelled(self) -> bool:
        return bool(self._cancel_cb and self._cancel_cb())

    def _sleep_cancellable(self, seconds: float) -> bool:
        """sleep for given seconds and break early on cancel"""
        step = 0.25
        slept = 0.0
        while slept < seconds:
            if self._cancelled():
                return False
            time.sleep(step)
            slept += step
        return True

    def _get_cached_path(self, filename: str, pkg_name: str | None = None) -> Path:
        """get path in cache for a file; namespaced by package name to avoid filename collisions"""
        if pkg_name:
            return self.cache_dir / pkg_name / filename
        return self.cache_dir / filename

    def _is_cached(
        self, filename: str, expected_hash: str | None = None, pkg_name: str | None = None
    ) -> bool:
        """check if file is in cache (+optionaly verify hash)"""
        cached = self._get_cached_path(filename, pkg_name)
        if not cached.exists():
            return False
        if expected_hash:
            return verify_hash(cached, expected_hash)
        return True

    def _download_file(
        self,
        url: str,
        dest: Path,
        file_progress: Callable[[str, int, int], None] | None = None,
        name: str = "",
    ) -> bool:
        """download with retries, writes to .tmp file and only renames on success"""
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        self._last_error_permanent = False
        for attempt in range(self.max_retries):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Emu68 Hatcher/1.0"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    total = int(response.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 8192
                    with open(tmp, "wb") as f:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if file_progress:
                                file_progress(name, downloaded, total)
                    tmp.replace(dest)
                    return True
            except urllib.error.HTTPError as e:
                self._last_error = f"HTTP {e.code} {e.reason}"
                self.logger.warning(f"Download failed for {url}: {self._last_error}")
                tmp.unlink(missing_ok=True)
                if e.code == 404:  # skip all mirrors on error 404 - somethings off
                    self._last_error_permanent = True
                    return False
                # 5xx / 429 / etc. - keep retrying
            except Exception as e:
                self._last_error = str(e) or type(e).__name__
                self.logger.warning(
                    f"Download attempt {attempt + 1} failed for {url}: {self._last_error}"
                )
                tmp.unlink(missing_ok=True)
            if attempt < self.max_retries - 1:
                if not self._sleep_cancellable(2**attempt):
                    return False  # cancelled
        return False

    def _try_mirrors(
        self,
        path: str,
        dest: Path,
        mirrors: list[str],
        file_progress: Callable[[str, int, int], None] | None = None,
        name: str = "",
        expected_hash: str | None = None,
    ) -> bool:
        """try mirrors in order; 404 short-circuits the rest (aminet mirrors share layout), hash mismatch falls through like a miss"""
        for mirror in mirrors:
            if self._cancelled():
                return False
            # without an expected hash, http:// mirrors can serve tampered bytes undetectably; refuse them
            if not expected_hash and mirror.startswith("http://"):
                self.logger.warning(
                    f"skipping {mirror} for {name}: no hash configured, refusing http mirror"
                )
                continue
            url = f"{mirror.rstrip('/')}/{path.lstrip('/')}"
            self.logger.info(f"Trying mirror: {url}")
            if not self._download_file(url, dest, file_progress=file_progress, name=name):
                if self._last_error_permanent:
                    # 404 on one mirror = skip all other mirrors for this file
                    self.logger.info(
                        f"Giving up on {name}: {self._last_error} (same path on every mirror)"
                    )
                    return False
                continue
            if expected_hash and not verify_hash(dest, expected_hash):
                self.logger.warning(f"hash mismatch from {mirror} for {name}; trying next mirror")
                dest.unlink(missing_ok=True)
                continue
            return True
        return False

    def download(
        self,
        item: DownloadItem,
        file_progress: Callable[[str, int, int], None] | None = None,
    ) -> DownloadResult:
        """download a single item"""
        result = DownloadResult(name=item.name, success=False)

        # check cache first; namespace by package name so two pkgs with the same filename never collide
        cached = self._get_cached_path(item.filename, item.name)
        if self._is_cached(item.filename, item.expected_hash, item.name):
            self.logger.info(f"Using cached: {item.name}")
        else:
            # download
            self.logger.info(f"Downloading: {item.name}")

            # parse hostname properly to block lookalikes like notaminet.net.example.com
            from urllib.parse import urlparse

            parsed = urlparse(item.url)
            host = parsed.hostname or ""
            if host == "aminet.net" or host.endswith(".aminet.net"):
                mirrors = item.mirrors if item.mirrors else self.AMINET_MIRRORS
                success = self._try_mirrors(
                    parsed.path,
                    cached,
                    mirrors,
                    file_progress=file_progress,
                    name=item.name,
                    expected_hash=item.expected_hash,
                )
            else:
                success = self._download_file(
                    item.url,
                    cached,
                    file_progress=file_progress,
                    name=item.name,
                )
                # declared backup_url(s) are independent full URLs (possibly another host);
                # try each in turn when the primary fails
                if not success and item.mirrors:
                    for mirror in item.mirrors:
                        if self._cancelled():
                            break
                        self.logger.info(f"Trying backup URL for {item.name}: {mirror}")
                        if not self._download_file(
                            mirror, cached, file_progress=file_progress, name=item.name
                        ):
                            continue
                        if item.expected_hash and not verify_hash(cached, item.expected_hash):
                            self.logger.warning(
                                f"hash mismatch from backup {mirror} for {item.name}"
                            )
                            cached.unlink(missing_ok=True)
                            continue
                        success = True
                        break

            if not success:
                # log exact error if possible
                detail = self._last_error or "download failed"
                result.error = f"{detail} ({item.url})"
                self.results[item.name] = result
                return result

            if item.expected_hash and not verify_hash(cached, item.expected_hash):
                # log got-hash + size so 'flaky mirror returned an html error page' is
                # distinguishable from 'upstream actually changed'
                from emu68hatcher.utils.hashing import HashAlgorithm, calculate_hash

                try:
                    got = calculate_hash(cached, HashAlgorithm.MD5)
                except Exception:
                    got = "(unreadable)"
                try:
                    size = cached.stat().st_size
                except OSError:
                    size = -1
                result.error = (
                    f"Hash mismatch: got {got} ({size} bytes), expected {item.expected_hash}"
                )
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

                # locate requested file case-insensitively, with symlink-escape check
                if item.extract_file:
                    target = item.extract_file.lower()
                    extract_root = extract_dir.resolve()
                    for f in extract_dir.rglob("*"):
                        if not (f.is_file() and f.name.lower() == target):
                            continue
                        if not f.resolve().is_relative_to(extract_root):
                            continue
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
        progress_callback: DownloadProgressCallback | None = None,
        file_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, DownloadResult]:
        """download all items (cancel between items)"""
        total = len(items)
        for i, item in enumerate(items):
            if self._cancelled():
                break
            if progress_callback:
                progress_callback(item.name, i, total)
            self.download(item, file_progress=file_progress)

        if progress_callback:
            progress_callback("Done", total, total)

        return self.results
