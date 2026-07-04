"""start tab - welcome screen and required-tool setup"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _render_icon(path: Path, size: int) -> QPixmap:
    """render an svg/png/icns to a square QPixmap of the given size"""
    if path.suffix.lower() == ".svg":
        renderer = QSvgRenderer(str(path))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap
    return QIcon(str(path)).pixmap(size, size)


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
    ("hst-amiga", "Amiga filesystem tools"),
    ("7z", "Archive extraction (p7zip)"),
]


class StartTab(QWidget):
    """welcome screen with tool-status table and download button"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._row_widgets: dict[str, tuple[QLabel, QLabel]] = {}
        self._fresh_downloads: set[str] = set()
        self._setup_ui()
        self.refresh_status()

    # --- UI ---
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # welcome header: app icon + title/subtitle stacked to its right
        header = QHBoxLayout()
        header.setSpacing(16)

        icon_path = _find_app_icon()
        if icon_path is not None:
            icon_label = QLabel()
            icon_label.setPixmap(_render_icon(icon_path, 96))
            icon_label.setFixedSize(96, 96)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
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

            status_label = QLabel("…")
            status_label.setFixedWidth(24)
            status_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

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
        from emu68hatcher.utils.host_tools import find_7z, find_hst_amiga, find_hst_imager

        finders = {
            "hst-imager": find_hst_imager,
            "hst-amiga": find_hst_amiga,
            "7z": find_7z,
        }
        any_missing = False
        any_stale = False

        for name, _ in _TOOL_ROWS:
            path = finders[name]()
            status_label, path_label = self._row_widgets[name]
            if not path:
                status_label.setText("❌")
                path_label.setText("not installed")
                any_missing = True
            elif tool_needs_download(name):
                status_label.setText("⚠️")
                path_label.setText(f"{path} (update available)")
                any_stale = True
            else:
                status_label.setText("✅")
                path_label.setText(str(path))

        self.download_btn.setEnabled(any_missing or any_stale)
        if any_missing:
            self.download_btn.setText("Download Missing Tools…")
        elif any_stale:
            self.download_btn.setText("Update Tools…")
        else:
            self.download_btn.setText("All Tools Installed")

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
        self._worker.start()

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

        if sys.platform == "darwin" and "hst-imager" in self._fresh_downloads:
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
