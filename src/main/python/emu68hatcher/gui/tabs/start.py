"""start tab - welcome screen and required-tool setup"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)


def _render_icon(path: Path, size: int) -> QPixmap:
    """render an svg/png/icns to a square QPixmap of the given size"""
    screen = QApplication.primaryScreen()
    pixel_ratio = screen.devicePixelRatio() if screen is not None else 1.0
    pixel_size = max(size, round(size * pixel_ratio))
    if path.suffix.lower() == ".svg":
        renderer = QSvgRenderer(str(path))
        pixmap = QPixmap(pixel_size, pixel_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(pixel_ratio)
        return pixmap
    return QIcon(str(path)).pixmap(QSize(size, size), pixel_ratio)


def _find_app_icon() -> Path | None:
    """locate the app icon - frozen: fbs-emitted Icon.{ico,icns} next to binary; dev: hatcher-icon.svg in src tree"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        for candidate in (
            exe_dir / "Icon.ico",  # windows + linux
            exe_dir.parent / "Resources" / "Icon.icns",  # macos .app
            exe_dir / "Icon.icns",
        ):
            if candidate.is_file():
                return candidate
        return None
    here = Path(__file__).resolve()
    for parent in here.parents:
        svg = parent / "src" / "main" / "icons" / "hatcher-icon.svg"
        if svg.is_file():
            return svg
    return None


_TOOL_ROWS = [
    ("hst-imager", "Disk image creation and manipulation"),
    ("7z", "Archive extraction (p7zip)"),
]

_STATUS_ICON_SIZE = QSize(20, 20)
_STATUS_LABEL_SIZE = QSize(24, 24)


def _set_status_icon(
    label: QLabel,
    icon: QStyle.StandardPixmap,
    accessible_name: str,
) -> None:
    screen = label.screen() or QApplication.primaryScreen()
    pixel_ratio = screen.devicePixelRatio() if screen is not None else 1.0
    label.setPixmap(label.style().standardIcon(icon).pixmap(_STATUS_ICON_SIZE, pixel_ratio))
    label.setFixedSize(_STATUS_LABEL_SIZE)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setAccessibleName(accessible_name)


def _installer_action(path: Path) -> tuple[str, bool] | None:
    from emu68hatcher.utils.platform import (
        OperatingSystem,
        detect_os,
        linux_supports_deb_packages,
    )

    os_name = detect_os()
    suffix = path.suffix.lower()
    if os_name == OperatingSystem.MACOS and suffix == ".dmg":
        return "Open DMG", False
    if os_name == OperatingSystem.WINDOWS and suffix == ".exe":
        return "Run Installer and Quit", True
    if os_name == OperatingSystem.LINUX and suffix == ".deb" and linux_supports_deb_packages():
        return "Open Package Installer", False
    return None


def _format_manifest_revision(revision: int) -> str:
    try:
        revision_date = datetime.fromtimestamp(revision, timezone.utc).date()
    except (OSError, OverflowError, ValueError):
        return f"revision {revision}"
    if revision_date.year < 2000:
        return f"revision {revision}"
    return f"{revision_date.isoformat()} (revision {revision})"


class StartTab(QWidget):
    """welcome screen with tool-status table and download button"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._update_worker = None
        self._app_download_worker = None
        self._row_widgets: dict[str, tuple[QLabel, QLabel]] = {}
        self._fresh_downloads: set[str] = set()
        from emu68hatcher.data.update_manifest import get_active_selection

        self._update_selection = get_active_selection()
        self._setup_ui()
        self.refresh_status()
        self.refresh_update_status()

    # --- UI ---
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addStretch()

        # welcome header: app icon + title/subtitle stacked to its right
        header = QHBoxLayout()
        header.setSpacing(16)

        icon_path = _find_app_icon()
        if icon_path is not None:
            icon_label = QLabel()
            icon_label.setPixmap(_render_icon(icon_path, 128))
            icon_label.setFixedSize(128, 128)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        title = QLabel("Welcome to Emu68 Hatcher")
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        text_col.addWidget(title)

        subtitle = QLabel(
            "Create bootable SD card images for PiStorm/Emu68 Amiga systems.<br>"
            "Configure your build using the tabs above and click "
            "<b>Build Image</b> when ready."
        )
        subtitle.setWordWrap(True)
        subtitle.setTextFormat(Qt.TextFormat.RichText)
        subtitle.setStyleSheet("color: #aaa;")
        text_col.addWidget(subtitle)
        text_col.addStretch()

        header.addLayout(text_col, 1)
        layout.addLayout(header)

        # horizontal divider between welcome area and tool status
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(divider)
        layout.addSpacing(8)

        # tool status group
        tools_group = QGroupBox("Required Tools")
        tools_layout = QVBoxLayout(tools_group)
        tools_layout.setSpacing(12)

        from emu68hatcher.builder.host.tools import TOOL_LABELS

        for name, description in _TOOL_ROWS:
            row = QHBoxLayout()
            row.setSpacing(10)

            status_label = QLabel()
            _set_status_icon(
                status_label,
                QStyle.StandardPixmap.SP_BrowserReload,
                "Checking",
            )

            text_col = QVBoxLayout()
            text_col.setSpacing(2)

            name_label = QLabel(f"<b>{TOOL_LABELS[name]}</b> - {description}")
            name_label.setTextFormat(Qt.TextFormat.RichText)
            name_label.setWordWrap(True)

            path_label = QLabel("")
            path_label.setStyleSheet("color: #888; font-size: 11px;")
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            text_col.addWidget(name_label)
            text_col.addWidget(path_label)

            row.addWidget(status_label)
            row.addLayout(text_col, 1)
            tools_layout.addLayout(row)

            self._row_widgets[name] = (status_label, path_label)

        # buttons
        btn_row = QHBoxLayout()

        self.reset_btn = QPushButton("Reset App Data…")
        self.reset_btn.clicked.connect(self.reset_app_data)
        btn_row.addWidget(self.reset_btn)

        btn_row.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_status)
        btn_row.addWidget(self.refresh_btn)

        self.download_btn = QPushButton("Download Missing Tools…")
        self.download_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold;"
        )
        self.download_btn.clicked.connect(self.start_download)
        btn_row.addWidget(self.download_btn)

        tools_layout.addLayout(btn_row)
        layout.addWidget(tools_group)

        updates_group = QGroupBox("Updates")
        updates_layout = QVBoxLayout(updates_group)
        updates_layout.setSpacing(12)

        self.hatcher_update_icon = QLabel()
        _set_status_icon(
            self.hatcher_update_icon,
            QStyle.StandardPixmap.SP_BrowserReload,
            "Checking",
        )
        self.hatcher_update_label = QLabel("")
        self.hatcher_update_label.setWordWrap(True)
        hatcher_row = QHBoxLayout()
        hatcher_row.addWidget(self.hatcher_update_icon)
        hatcher_row.addWidget(self.hatcher_update_label, 1)
        updates_layout.addLayout(hatcher_row)

        self.manifest_update_icon = QLabel()
        _set_status_icon(
            self.manifest_update_icon,
            QStyle.StandardPixmap.SP_BrowserReload,
            "Checking",
        )
        self.manifest_update_label = QLabel("")
        self.manifest_update_label.setWordWrap(True)
        manifest_row = QHBoxLayout()
        manifest_row.addWidget(self.manifest_update_icon)
        manifest_row.addWidget(self.manifest_update_label, 1)
        updates_layout.addLayout(manifest_row)

        update_buttons = QHBoxLayout()
        update_buttons.addStretch()
        self.check_updates_btn = QPushButton("Check for Updates")
        self.check_updates_btn.clicked.connect(self.check_for_updates)
        update_buttons.addWidget(self.check_updates_btn)
        self.open_release_btn = QPushButton("Open Download Page")
        self.open_release_btn.clicked.connect(self.open_release_page)
        update_buttons.addWidget(self.open_release_btn)
        self.download_update_btn = QPushButton("Download Update…")
        self.download_update_btn.clicked.connect(self.download_application_update)
        update_buttons.addWidget(self.download_update_btn)
        updates_layout.addLayout(update_buttons)

        self.update_download_status = QLabel("")
        self.update_download_status.setVisible(False)
        updates_layout.addWidget(self.update_download_status)
        self.update_download_bar = QProgressBar()
        self.update_download_bar.setRange(0, 100)
        self.update_download_bar.setVisible(False)
        updates_layout.addWidget(self.update_download_bar)
        layout.addWidget(updates_group)

        # download progress group (hidden until a download starts)
        self.progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(self.progress_group)

        self.progress_status = QLabel("")
        progress_layout.addWidget(self.progress_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(self.progress_group)
        self.progress_group.setVisible(False)

        layout.addStretch()

    # --- tool status ---
    @Slot()
    def refresh_status(self):
        """re-query tool install state and repaint the rows"""
        from emu68hatcher.builder.host.tools import tool_needs_download
        from emu68hatcher.utils.host_tools import find_7z, find_hst_imager

        finders = {
            "hst-imager": find_hst_imager,
            "7z": find_7z,
        }
        any_missing = False
        any_stale = False

        for name, _ in _TOOL_ROWS:
            path = finders[name]()
            status_label, path_label = self._row_widgets[name]
            if not path:
                _set_status_icon(
                    status_label,
                    QStyle.StandardPixmap.SP_DialogCancelButton,
                    "Missing",
                )
                path_label.setText("not installed")
                any_missing = True
            elif tool_needs_download(name):
                _set_status_icon(
                    status_label,
                    QStyle.StandardPixmap.SP_MessageBoxWarning,
                    "Update available",
                )
                path_label.setText(f"{path} (update available)")
                any_stale = True
            else:
                _set_status_icon(
                    status_label,
                    QStyle.StandardPixmap.SP_DialogApplyButton,
                    "Installed",
                )
                path_label.setText(str(path))

        self.download_btn.setEnabled(any_missing or any_stale)
        if any_missing:
            self.download_btn.setText("Download Missing Tools…")
        elif any_stale:
            self.download_btn.setText("Update Tools…")
        else:
            self.download_btn.setText("All Tools Installed")

    def refresh_update_status(self):
        from emu68hatcher import __version__
        from emu68hatcher.data.update_manifest import get_current_artifact, is_newer_version
        from emu68hatcher.utils.platform import (
            OperatingSystem,
            detect_os,
            linux_supports_deb_packages,
        )

        selection = self._update_selection
        release = selection.manifest.hatcher
        newer = is_newer_version(__version__, release.version)
        if newer:
            _set_status_icon(
                self.hatcher_update_icon,
                QStyle.StandardPixmap.SP_MessageBoxWarning,
                "Update available",
            )
            self.hatcher_update_label.setText(
                f"Emu68 Hatcher {release.version} is available (installed: {__version__})"
            )
        else:
            _set_status_icon(
                self.hatcher_update_icon,
                QStyle.StandardPixmap.SP_DialogApplyButton,
                "Current",
            )
            self.hatcher_update_label.setText(f"Emu68 Hatcher {__version__} is up to date")

        source_label = {
            "bundled": "bundled",
            "cache": "cached",
            "remote": "server",
        }[selection.source]
        revision_label = _format_manifest_revision(selection.manifest.revision)
        if selection.error:
            _set_status_icon(
                self.manifest_update_icon,
                QStyle.StandardPixmap.SP_MessageBoxWarning,
                "Check failed",
            )
            self.manifest_update_label.setText(
                f"Package list check failed; using {source_label} list: {revision_label}"
            )
            self.manifest_update_label.setToolTip(selection.error)
        elif selection.source == "remote" and selection.changed:
            _set_status_icon(
                self.manifest_update_icon,
                QStyle.StandardPixmap.SP_DialogApplyButton,
                "Updated",
            )
            self.manifest_update_label.setText(
                f"Package list updated from server: {revision_label}"
            )
            self.manifest_update_label.setToolTip("")
        elif selection.checked:
            _set_status_icon(
                self.manifest_update_icon,
                QStyle.StandardPixmap.SP_DialogApplyButton,
                "Current",
            )
            self.manifest_update_label.setText(f"Package list is up to date: {revision_label}")
            self.manifest_update_label.setToolTip("")
        else:
            _set_status_icon(
                self.manifest_update_icon,
                QStyle.StandardPixmap.SP_DialogApplyButton,
                "Available",
            )
            self.manifest_update_label.setText(
                f"Using {source_label} package list: {revision_label}"
            )
            self.manifest_update_label.setToolTip("")

        artifact = get_current_artifact(selection.manifest)
        self.open_release_btn.setEnabled(newer)
        self.download_update_btn.setEnabled(newer and artifact is not None)
        self.download_update_btn.setText("Download Update…")
        self.download_update_btn.setToolTip("")
        if (
            newer
            and artifact is not None
            and detect_os() == OperatingSystem.LINUX
            and artifact.filename.lower().endswith(".deb")
            and not linux_supports_deb_packages()
        ):
            self.download_update_btn.setText("Download .deb…")
            self.download_update_btn.setToolTip(
                "This package can only be opened directly on Debian-based systems."
            )

    @Slot()
    def check_for_updates(self):
        from emu68hatcher.gui.workers import UpdateCheckWorker

        if self._update_worker and self._update_worker.isRunning():
            return
        self.check_updates_btn.setEnabled(False)
        _set_status_icon(
            self.manifest_update_icon,
            QStyle.StandardPixmap.SP_BrowserReload,
            "Checking",
        )
        self.manifest_update_label.setText("Checking package list and application version…")
        self._update_worker = UpdateCheckWorker(self)
        self._update_worker.check_finished.connect(self._on_update_check_finished)
        self._update_worker.finished.connect(self._update_worker_finished)
        self._update_worker.start()

    @Slot(object)
    def _on_update_check_finished(self, selection):
        if not selection.error:
            from emu68hatcher.data.package_loader import clear_package_caches
            from emu68hatcher.data.update_manifest import activate_manifest

            try:
                activate_manifest(selection)
                clear_package_caches()
            except Exception as error:
                from emu68hatcher.data.update_manifest import (
                    ManifestSelection,
                    get_active_selection,
                )

                active = get_active_selection()
                selection = ManifestSelection(
                    active.manifest,
                    active.source,
                    error=str(error) or type(error).__name__,
                    checked=True,
                )
        self._update_selection = selection
        self.check_updates_btn.setEnabled(True)
        self.refresh_update_status()

    def _update_worker_finished(self):
        self._update_worker = None

    @Slot()
    def open_release_page(self):
        url = str(self._update_selection.manifest.hatcher.release_url)
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "Application Update", "Could not open the download page.")

    @Slot()
    def download_application_update(self):
        from emu68hatcher.data.update_manifest import get_current_artifact
        from emu68hatcher.gui.workers import ApplicationUpdateDownloadWorker

        if self._app_download_worker and self._app_download_worker.isRunning():
            return
        artifact = get_current_artifact(self._update_selection.manifest)
        if artifact is None:
            return
        download_location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        destination = Path(download_location) if download_location else Path.home() / "Downloads"
        self.download_update_btn.setEnabled(False)
        self.update_download_status.setText(f"Downloading {artifact.filename}…")
        self.update_download_status.setVisible(True)
        self.update_download_bar.setRange(0, 100)
        self.update_download_bar.setValue(0)
        self.update_download_bar.setVisible(True)
        self._app_download_worker = ApplicationUpdateDownloadWorker(artifact, destination, self)
        self._app_download_worker.download_progress.connect(self._on_update_download_progress)
        self._app_download_worker.download_finished.connect(self._on_update_download_finished)
        self._app_download_worker.finished.connect(self._app_download_worker_finished)
        self._app_download_worker.start()

    @Slot(int, int)
    def _on_update_download_progress(self, current: int, total: int):
        if total > 0:
            self.update_download_bar.setRange(0, 100)
            self.update_download_bar.setValue(min(100, int(current * 100 / total)))
            self.update_download_status.setText(
                f"Downloading update - {current / (1024 * 1024):.1f} / "
                f"{total / (1024 * 1024):.1f} MB"
            )
        else:
            self.update_download_bar.setRange(0, 0)

    @Slot(bool, str)
    def _on_update_download_finished(self, success: bool, detail: str):
        self.update_download_bar.setRange(0, 100)
        self.download_update_btn.setEnabled(True)
        if success:
            self.update_download_bar.setValue(100)
            self.update_download_status.setText(f"Downloaded to {detail}")
            self._show_downloaded_update(Path(detail))
        else:
            self.update_download_bar.setValue(0)
            self.update_download_status.setText("Update download failed")
            QMessageBox.warning(self, "Application Update", detail)

    def _show_downloaded_update(self, path: Path) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Application Update")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"{path.name} was downloaded and verified.")

        action = _installer_action(path)
        launch_btn = None
        release_btn = None
        if action is not None:
            label, quit_after_launch = action
            launch_btn = box.addButton(label, QMessageBox.ButtonRole.AcceptRole)
            note = f"Saved to:\n{path}"
            if quit_after_launch:
                note += "\n\nEmu68 Hatcher will close after the installer starts."
            box.setInformativeText(note)
        else:
            box.setInformativeText(
                f"Saved to:\n{path}\n\nThis package cannot be opened automatically on this system."
            )
            release_btn = box.addButton("Open Download Page", QMessageBox.ButtonRole.ActionRole)

        folder_btn = box.addButton("Open Downloads Folder", QMessageBox.ButtonRole.ActionRole)
        later_btn = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(later_btn)
        box.setEscapeButton(later_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is folder_btn:
            self._open_local_path(path.parent, "Could not open the Downloads folder.")
        elif release_btn is not None and clicked is release_btn:
            self.open_release_page()
        elif launch_btn is not None and clicked is launch_btn:
            if self._open_local_path(path, "Could not open the downloaded installer."):
                if action is not None and action[1]:
                    QTimer.singleShot(0, self.window().close)

    def _open_local_path(self, path: Path, error_message: str) -> bool:
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            return True
        QMessageBox.warning(self, "Application Update", f"{error_message}\n\n{path}")
        return False

    def _app_download_worker_finished(self):
        self._app_download_worker = None

    # --- reset ---
    @Slot()
    def reset_app_data(self):
        """wipe cache, temp files and downloaded tools after confirmation"""
        if any(
            worker is not None and worker.isRunning()
            for worker in (self._worker, self._update_worker, self._app_download_worker)
        ):
            return

        box = QMessageBox(self)
        box.setWindowTitle("Reset App Data")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Delete all cached downloads, temporary files and downloaded tools?")
        box.setInformativeText(
            "This resets the app to its fresh-install state. Tools and packages are "
            "re-downloaded when needed. Saved build configs are not touched."
        )
        delete_btn = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not delete_btn:
            return

        from emu68hatcher.data.package_loader import clear_package_caches
        from emu68hatcher.data.update_manifest import initialize_manifest
        from emu68hatcher.utils.paths import reset_runtime_data

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            failures = reset_runtime_data()
        finally:
            QApplication.restoreOverrideCursor()

        self.progress_group.setVisible(False)
        self._update_selection = initialize_manifest()
        clear_package_caches()
        self.refresh_status()
        self.refresh_update_status()
        if failures:
            QMessageBox.warning(
                self,
                "Reset App Data",
                "Could not remove:\n" + "\n".join(str(p) for p in failures),
            )

    # --- download flow ---
    @Slot()
    def start_download(self):
        from emu68hatcher.gui.workers import ToolDownloadWorker

        if self._worker and self._worker.isRunning():
            return

        self.download_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.progress_group.setVisible(True)
        self.progress_status.setText("Preparing download…")
        self.progress_bar.setValue(0)

        self._fresh_downloads.clear()
        self._worker = ToolDownloadWorker(self)
        self._worker.tool_started.connect(self._on_tool_started)
        self._worker.tool_progress.connect(self._on_tool_progress)
        self._worker.tool_finished.connect(self._on_tool_finished)
        self._worker.download_finished.connect(self._on_download_finished)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _worker_finished(self) -> None:
        self._worker = None

    def shutdown_workers(self, timeout_ms: int = 500) -> bool:
        workers = [self._worker, self._update_worker, self._app_download_worker]
        running = [worker for worker in workers if worker is not None and worker.isRunning()]
        for worker in running:
            worker.requestInterruption()
        for worker in running:
            worker.wait(timeout_ms)
        return not any(worker.isRunning() for worker in running)

    @Slot(str)
    def _on_tool_started(self, tool_name: str):
        from emu68hatcher.builder.host.tools import TOOL_LABELS

        label = TOOL_LABELS.get(tool_name, tool_name)
        self.progress_status.setText(f"Downloading {label}…")
        self.progress_bar.setValue(0)

    @Slot(str, int, int)
    def _on_tool_progress(self, tool_name: str, downloaded: int, total: int):
        from emu68hatcher.builder.host.tools import TOOL_LABELS

        label = TOOL_LABELS.get(tool_name, tool_name)
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(min(pct, 100))
            mb_down = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.progress_status.setText(f"Downloading {label} - {mb_down:.1f} / {mb_total:.1f} MB")
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate
            self.progress_status.setText(f"Downloading {label}…")

    @Slot(str, bool)
    def _on_tool_finished(self, tool_name: str, success: bool):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        if success:
            self._fresh_downloads.add(tool_name)

    @Slot(bool, list)
    def _on_download_finished(self, success: bool, failed: list):
        self.refresh_btn.setEnabled(True)
        self.refresh_status()

        if success:
            self.progress_status.setText("All tools downloaded successfully.")
            self.progress_bar.setValue(100)
        else:
            from emu68hatcher.builder.host.tools import TOOL_LABELS

            failed_list = (
                ", ".join(TOOL_LABELS.get(t, t) for t in failed) if failed else "one or more tools"
            )
            hint = ""
            if "7z" in failed:
                hint = " (macOS: install with <code>brew install p7zip</code>)"
            self.progress_status.setText(f"Failed to download: {failed_list}.{hint}")
            self.progress_status.setTextFormat(Qt.TextFormat.RichText)

        from emu68hatcher.utils.platform import OperatingSystem, get_platform_info

        if (
            get_platform_info().os == OperatingSystem.MACOS
            and "hst-imager" in self._fresh_downloads
        ):
            self._offer_macos_tcc_registration()

    def _offer_macos_tcc_registration(self):
        """ask whether to file hst-imager with tccd now; deferring just means the first build does it"""
        from emu68hatcher.builder.host.macos_tcc import (
            open_full_disk_access_pane,
            register_hst_imager_with_tcc,
        )
        from emu68hatcher.utils.paths import get_tools_dir

        hst = get_tools_dir() / "hst-imager"
        if not hst.is_file():
            return

        box = QMessageBox(self)
        box.setWindowTitle("Enable disk access for hst-imager")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("hst-imager needs Full Disk Access to write SD cards.")
        box.setInformativeText(
            "You'll get a password prompt, then System Settings opens - enable "
            "<b>hst-imager</b> there. You can skip and do it on the first build."
        )
        setup_btn = box.addButton("Set Up Now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not setup_btn:
            return

        if register_hst_imager_with_tcc(hst):
            open_full_disk_access_pane()
