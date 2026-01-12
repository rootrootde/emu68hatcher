"""
background worker threads for GUI operations
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from emu68hatcher.config.schema import BuildConfig


class BuildWorker(QThread):
    """worker thread for running the build process"""

    progress_updated = Signal(str, float, str)  # stage, progress, message
    log_event = Signal(str, str)  # stage, message
    build_finished = Signal(bool, str, str)  # success, output_path, error

    def __init__(self, config: BuildConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._cancelled = False

    def run(self):
        """execute the build workflow"""
        from emu68hatcher.builder.workflow import BuildWorkflow, BuildState

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

        # check for cancellation periodically
        def check_cancel():
            if self._cancelled:
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
        """request build cancellation"""
        self._cancelled = True


class ToolDownloadWorker(QThread):
    """worker thread for downloading required tools

    downloads each missing tool individually so we can thread byte-level
    progress back to the GUI via `tool_progress`. previously this called
    `download_all_tools()` which had no progress hook.
    """

    status_updated = Signal(str)  # kept for backwards compatibility
    tool_started = Signal(str)  # tool_name
    tool_progress = Signal(str, int, int)  # tool_name, bytes_downloaded, bytes_total
    tool_finished = Signal(str, bool)  # tool_name, success
    download_finished = Signal(bool, list)  # overall success, failed tool names

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        """download every missing tool, emitting per-tool progress"""
        from emu68hatcher.builder.tools import (
            check_tools,
            download_7zip,
            download_tool,
        )

        status = check_tools()
        missing = [t for t, ok in status.items() if not ok]

        if not missing:
            self.download_finished.emit(True, [])
            return

        failed: list[str] = []
        for tool_name in missing:
            self.tool_started.emit(tool_name)
            self.status_updated.emit(f"Downloading {tool_name}...")

            # callback closes over tool_name so the Start tab can label the bar
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
    """worker thread for scanning ROM directories"""

    scan_finished = Signal(list)  # list of found ROMs

    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        """scan for Kickstart ROMs"""
        from emu68hatcher.data.rom_detection import scan_for_kickstart_roms
        found_roms = scan_for_kickstart_roms(self.directory)
        self.scan_finished.emit(found_roms)


class ADFScanWorker(QThread):
    """worker thread for scanning ADF directories"""

    scan_finished = Signal(list)  # list of IdentifiedInstallMedia

    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        """scan for Workbench ADFs"""
        from emu68hatcher.extractor.adf import scan_install_media_by_hash
        found_media = scan_install_media_by_hash(self.directory)
        self.scan_finished.emit(found_media)
