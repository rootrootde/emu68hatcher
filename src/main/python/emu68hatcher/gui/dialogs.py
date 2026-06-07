"""GUI dialogs"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import BuildConfig
from emu68hatcher.gui.workers import BuildWorker


class BuildProgressDialog(QDialog):
    """live build progress dialog"""

    def __init__(self, config: BuildConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.worker: BuildWorker | None = None
        self._success: bool = False
        self.setup_ui()

    @property
    def success(self) -> bool:
        return self._success

    def setup_ui(self):
        self.setWindowTitle("Building Image...")
        self.setMinimumSize(700, 400)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # stage label
        self.stage_label = QLabel("Initializing...")
        self.stage_label.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(self.stage_label)

        # progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # status message
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Courier", 10))
        layout.addWidget(self.log_output)

        # buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_build)
        btn_layout.addWidget(self.cancel_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setEnabled(False)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def start_build(self):
        """kick off the build worker"""
        self.worker = BuildWorker(self.config, self)
        self.worker.progress_updated.connect(self.on_progress)
        self.worker.log_event.connect(self.on_log_event)
        self.worker.build_finished.connect(self.on_finished)
        self.worker.start()

    _STAGE_NAMES = {
        "init": "Initializing",
        "validate": "Validating",
        "download": "Downloading",
        "extract": "Extracting",
        "create_image": "Creating Image",
        "install_workbench": "Installing Workbench",
        "install_packages": "Installing Packages",
        "configure": "Configuring",
        "install_extras": "Mirroring Extras",
        "finalize": "Finalizing",
        "flash": "Flashing to SD card",
        "complete": "Complete",
        "failed": "Failed",
    }

    @Slot(str, float, str)
    def on_progress(self, stage: str, progress: float, message: str):
        """transient status update - progress bar + status label"""
        self.stage_label.setText(self._STAGE_NAMES.get(stage, stage.title()))
        self.progress_bar.setValue(int(progress))
        self.status_label.setText(message)

    @Slot(str, str)
    def on_log_event(self, stage: str, message: str):
        """append one log entry"""
        self.log_output.append(f"[{stage}] {message}")

    @Slot(bool, str, str)
    def on_finished(self, success: bool, output_path: str, error: str):
        """build done - update labels + buttons"""
        self._success = success
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

        if success:
            self.stage_label.setText("Build Complete!")
            self.progress_bar.setValue(100)
            self.status_label.setText(f"Output: {output_path}")
            self.log_output.append(f"\nBuild successful!\nOutput: {output_path}")
        else:
            self.stage_label.setText("Build Failed")
            self.status_label.setText(error)
            self.log_output.append(f"\nBuild failed: {error}")

    def cancel_build(self):
        """ask the worker to cancel"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Cancelling...")
            self.log_output.append("Cancellation requested...")

    def closeEvent(self, event):
        """block close while the worker runs - Qt crashes if the dialog tears down mid-thread"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(5000):
                self.status_label.setText(
                    "Build is still cancelling - please wait a moment and try again"
                )
                event.ignore()
                return
        super().closeEvent(event)


class DetectedFilesDialog(QDialog):
    """tabbed view of detected ROMs / WHDLoad ROMs / ADFs"""

    _STATUS_GLYPH = {
        "found": "✓",
        "boot": "★",
        "available": "✓",
        "other_version": "·",
        "excluded": "⊘",
        "missing": "✗",
        "missing_required": "✗",
        "missing_optional": "-",
    }
    _STATUS_COLOR = {
        "found": QColor(60, 150, 60),
        "boot": QColor(40, 120, 200),
        "available": QColor(60, 150, 60),
        "other_version": QColor(130, 130, 130),
        "excluded": QColor(180, 40, 40),
        "missing": QColor(180, 40, 40),
        "missing_required": QColor(180, 40, 40),
        "missing_optional": QColor(130, 130, 130),
    }

    def __init__(
        self,
        title: str,
        rom_rows: list[tuple[str, str, str, str, str]],
        whdload_rows: list[tuple[str, str, str]],
        adf_rows: list[tuple[str, str, str, str, bool]],
        parent=None,
    ):
        super().__init__(parent)
        self._title = title
        self._rom_rows = list(rom_rows)
        self._whdload_rows = list(whdload_rows)
        self._adf_rows = list(adf_rows)
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle(self._title)
        self.setMinimumSize(720, 520)
        self.resize(960, 680)
        self.setModal(True)

        layout = QVBoxLayout(self)

        header = QLabel(self._title)
        header.setFont(QFont("", 11, QFont.Weight.Bold))
        layout.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(
            self._build_rom_tab(),
            f"Kickstart ROMs ({len(self._rom_rows)})",
        )
        wh_found = sum(1 for s, *_ in self._whdload_rows if s == "found")
        tabs.addTab(
            self._build_whdload_tab(),
            f"WHDLoad ROMs ({wh_found}/{len(self._whdload_rows)})",
        )
        adf_found = sum(1 for s, *_ in self._adf_rows if s == "found")
        tabs.addTab(
            self._build_adf_tab(),
            f"Workbench ADFs ({adf_found}/{len(self._adf_rows)})",
        )
        layout.addWidget(tabs)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _build_rom_tab(self) -> QWidget:
        # rows: (status, filename, version, model, path)
        return self._build_table_tab(
            headers=["Status", "Filename", "Version", "Model", "Path"],
            rows=self._rom_rows,
            stretch_col=4,
            wide_cols=(1, 4),
        )

    def _build_whdload_tab(self) -> QWidget:
        # rows: (status, name, path)
        return self._build_table_tab(
            headers=["Status", "Name", "Source Path"],
            rows=self._whdload_rows,
            stretch_col=2,
            wide_cols=(1, 2),
        )

    def _build_adf_tab(self) -> QWidget:
        # rows: (status, adf, friendly, version, required)
        rows = [
            (status, adf, friendly, version, "yes" if required else "")
            for status, adf, friendly, version, required in self._adf_rows
        ]
        return self._build_table_tab(
            headers=["Status", "ADF", "Friendly Name", "Version", "Required"],
            rows=rows,
            stretch_col=2,
            wide_cols=(1, 2),
        )

    def _build_table_tab(
        self,
        headers: list[str],
        rows: list[tuple],
        stretch_col: int,
        wide_cols: tuple[int, ...] = (),
    ) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(0, 6, 0, 0)

        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(False)

        for row_idx, row in enumerate(rows):
            status = row[0]
            glyph = self._STATUS_GLYPH.get(status, "?")
            colour = self._STATUS_COLOR.get(status)
            cells = (glyph, *row[1:])
            for col_idx, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if colour is not None:
                    item.setForeground(QBrush(colour))
                if col_idx == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        header_view = table.horizontalHeader()
        for col in range(len(headers)):
            if col == stretch_col:
                header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            elif col in wide_cols:
                header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            else:
                header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        vbox.addWidget(table)

        if not rows:
            empty = QLabel("(nothing detected)")
            empty.setStyleSheet("color: gray; padding: 8px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vbox.addWidget(empty)

        return widget
