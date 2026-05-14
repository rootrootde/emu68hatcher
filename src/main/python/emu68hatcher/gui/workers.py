"""GUI background worker threads"""

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from emu68hatcher.builder.workflow import BuildState, BuildWorkflow
from emu68hatcher.config.schema import BuildConfig


class BuildWorker(QThread):
    """run a BuildWorkflow on a Qt thread"""

    progress_updated = Signal(str, float, str)  # stage, progress, message
    log_event = Signal(str, str)  # stage, message
    build_finished = Signal(bool, str, str)  # success, output_path, error

    def __init__(self, config: BuildConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._lock = threading.Lock()
        self._cancelled = False
        self._workflow: BuildWorkflow | None = None

    def run(self):
        """drive the workflow, forward callbacks as Qt signals"""

        def progress_callback(state: BuildState):
            self.progress_updated.emit(
                state.stage.value,
                state.progress,
                state.message,
            )

        def log_callback(stage: str, message: str):
            self.log_event.emit(stage, message)

        workflow = BuildWorkflow(
            self.config,
            progress_callback=progress_callback,
            log_callback=log_callback,
            gui_mode=True,
        )

        with self._lock:
            self._workflow = workflow
            already_cancelled = self._cancelled
        if already_cancelled:
            workflow.cancel()

        result = workflow.build()

        if result.success:
            self.build_finished.emit(
                True,
                str(result.output_path) if result.output_path else "",
                "",
            )
        else:
            self.build_finished.emit(
                False,
                "",
                result.error or "Unknown error",
            )

    def cancel(self):
        """thread-safe cancel request"""
        with self._lock:
            self._cancelled = True
            workflow = self._workflow
        if workflow is not None:
            workflow.cancel()


class ToolDownloadWorker(QThread):
    """fetch missing host tools"""

    tool_started = Signal(str)  # tool_name
    tool_progress = Signal(str, int, int)  # tool_name, bytes_downloaded, bytes_total
    tool_finished = Signal(str, bool)  # tool_name, success
    download_finished = Signal(bool, list)  # overall success, failed tool names

    def run(self):
        """download each missing tool, emit per-tool progress"""
        from emu68hatcher.builder.host.tools import download_7zip, download_tool
        from emu68hatcher.utils.host_tools import check_dependencies

        status = check_dependencies()
        missing = [t for t, ok in status.items() if not ok]

        if not missing:
            self.download_finished.emit(True, [])
            return

        failed: list[str] = []
        for tool_name in missing:
            self.tool_started.emit(tool_name)

            # close over tool_name so the start tab can label the bar
            def _cb(downloaded: int, total: int, _name=tool_name):
                self.tool_progress.emit(_name, downloaded, total)

            try:
                if tool_name == "7z":
                    result = download_7zip(progress_callback=_cb)
                else:
                    result = download_tool(tool_name, progress_callback=_cb)
            except Exception as exc:
                print(f"Error downloading {tool_name}: {exc}")
                result = None

            success = result is not None
            if not success:
                failed.append(tool_name)
            self.tool_finished.emit(tool_name, success)

        self.download_finished.emit(len(failed) == 0, failed)


class ROMScanWorker(QThread):
    """scan a directory for Kickstart ROMs"""

    scan_finished = Signal(list, bool)  # (found ROMs, truncated)

    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        """scan + emit"""
        from emu68hatcher.data.rom_detection import scan_for_kickstart_roms

        try:
            found_roms, truncated = scan_for_kickstart_roms(self.directory)
        except Exception:
            found_roms, truncated = [], False
        self.scan_finished.emit(found_roms, truncated)


class ADFScanWorker(QThread):
    """scan a directory for Workbench ADFs"""

    scan_finished = Signal(list, bool)  # (found media, truncated)

    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        """scan + emit"""
        from emu68hatcher.data.install_media import scan_install_media_by_hash

        try:
            found_media, truncated = scan_install_media_by_hash(self.directory)
        except Exception:
            found_media, truncated = [], False
        self.scan_finished.emit(found_media, truncated)


class DiskListWorker(QThread):
    """enumerate removable disks off the GUI thread"""

    disks_loaded = Signal(list)  # list[DiskInfo]

    def run(self):
        from emu68hatcher.builder.host.disk_enum import list_removable_disks

        try:
            disks = list_removable_disks()
        except Exception:
            disks = []
        self.disks_loaded.emit(disks)
