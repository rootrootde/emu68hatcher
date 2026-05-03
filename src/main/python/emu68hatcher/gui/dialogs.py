"""dialog windows"""

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
    QTextEdit,
    QVBoxLayout,
)

from emu68hatcher.config.schema import BuildConfig
from emu68hatcher.gui.workers import BuildWorker


class BuildProgressDialog(QDialog):
    """dialog showing build progress"""

    def __init__(self, config: BuildConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.worker = None
        self._success: bool = False
        self._output_path: str = ""
        self._error: str = ""
        self.setup_ui()

    @property
    def success(self) -> bool:
        return self._success

    @property
    def output_path(self) -> str:
        return self._output_path

    @property
    def error(self) -> str:
        return self._error

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
        """start the build process"""
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
        "finalize": "Finalizing",
        "complete": "Complete",
        "failed": "Failed",
    }

    @Slot(str, float, str)
    def on_progress(self, stage: str, progress: float, message: str):
        """handle transient status updates - progress bar adn status label only"""
        self.stage_label.setText(self._STAGE_NAMES.get(stage, stage.title()))
        self.progress_bar.setValue(int(progress))
        self.status_label.setText(message)

    @Slot(str, str)
    def on_log_event(self, stage: str, message: str):
        """append one discrete log entry per meaningful unit of work"""
        self.log_output.append(f"[{stage}] {message}")

    @Slot(bool, str, str)
    def on_finished(self, success: bool, output_path: str, error: str):
        """handle build completion"""
        self._success = success
        self._output_path = output_path
        self._error = error
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
        """cancel the build process"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Cancelling...")
            self.log_output.append("Cancellation requested...")

    def closeEvent(self, event):
        """refuse close while the worker is still running - tearing down the dialog mid-thread crashes Qt"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(5000):
                self.status_label.setText(
                    "Build is still cancelling - please wait a moment and try again"
                )
                event.ignore()
                return
        super().closeEvent(event)


class ADFDetailsDialog(QDialog):
    """per-ADF breakdown for Kickstart tab's 'Show details...' dialog"""

    _STATUS_GLYPH = {
        "found": "✓",
        "missing_required": "✗",
        "missing_optional": "-",
    }
    _STATUS_COLOR = {
        "found": QColor(60, 150, 60),  # green
        "missing_required": QColor(180, 40, 40),  # red
        "missing_optional": QColor(130, 130, 130),  # grey
    }

    def __init__(self, rows: list[tuple[str, str, str, str, bool]], title: str, parent=None):
        super().__init__(parent)
        self._rows = list(rows)
        self._title = title
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle(self._title)
        self.setMinimumSize(640, 500)
        self.resize(900, 650)
        self.setModal(True)

        layout = QVBoxLayout(self)

        header = QLabel(self._title)
        header.setFont(QFont("", 11, QFont.Weight.Bold))
        layout.addWidget(header)

        self.table = QTableWidget(len(self._rows), 5)
        self.table.setHorizontalHeaderLabels(
            ["Status", "ADF", "Friendly Name", "Version", "Required"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)  # enable after populating

        for row_idx, (status, adf, friendly, version, required) in enumerate(self._rows):
            glyph = self._STATUS_GLYPH.get(status, "?")
            colour = self._STATUS_COLOR.get(status)
            cells = [
                glyph,
                adf,
                friendly,
                version,
                "yes" if required else "",
            ]
            for col_idx, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if colour is not None:
                    item.setForeground(QBrush(colour))
                if col_idx == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

        self.table.setSortingEnabled(True)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
