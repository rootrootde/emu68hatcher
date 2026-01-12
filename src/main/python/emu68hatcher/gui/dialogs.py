"""
dialog windows for the GUI
"""

from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTextEdit,
)
from PySide6.QtGui import QDesktopServices, QFont

from emu68hatcher.config.schema import BuildConfig
from emu68hatcher.gui.workers import BuildWorker


class BuildProgressDialog(QDialog):
    """dialog showing build progress"""

    def __init__(self, config: BuildConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Building Image...")
        self.setMinimumSize(500, 300)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # stage label
        self.stage_label = QLabel("Initializing...")
        self.stage_label.setFont(QFont("", 12, QFont.Bold))
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
        "partition": "Partitioning",
        "install_workbench": "Installing Workbench",
        "install_packages": "Installing Packages",
        "configure": "Configuring",
        "finalize": "Finalizing",
        "complete": "Complete",
        "failed": "Failed",
    }

    @Slot(str, float, str)
    def on_progress(self, stage: str, progress: float, message: str):
        """handle transient status updates - progress bar and status label only"""
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
            if "blocked raw disk access" in error:
                self._show_full_disk_access_dialog()

    def _show_full_disk_access_dialog(self):
        """prompt the user to grant Full Disk Access after macOS TCC blocked dd"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Full Disk Access Required")
        box.setText("macOS blocked raw disk access.")
        box.setInformativeText(
            "Emu68 Hatcher needs <b>Full Disk Access</b> to write directly to "
            "SD cards. This is a one-time setup:<br><br>"
            "1. Click <b>Open System Settings</b> below.<br>"
            "2. Enable <b>Emu68 Hatcher</b> in the list.<br>"
            "3. Quit and relaunch Emu68 Hatcher, then try flashing again."
        )
        box.setTextFormat(Qt.TextFormat.RichText)
        open_btn = box.addButton("Open System Settings", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(
                "x-apple.systempreferences:com.apple.preference.security"
                "?Privacy_AllFiles"
            ))

    def cancel_build(self):
        """cancel the build process"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Cancelling...")
            self.log_output.append("Cancellation requested...")

    def closeEvent(self, event):
        """handle dialog close"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)  # wait up to 5 seconds
        super().closeEvent(event)
