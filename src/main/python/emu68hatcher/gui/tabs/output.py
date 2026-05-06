"""output tab - image file, image+flash, or direct-to-SD"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import OutputConfig, OutputType
from emu68hatcher.gui.workers import DiskListWorker


class OutputTab(QWidget):
    """output config tab"""

    # `object` so the byte count stays a python int - Qt would truncate
    # multi-GB values on a 32-bit signed int signal
    target_size_changed = Signal(object, str)
    target_size_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._disks: list = []
        self._disk_worker: DiskListWorker | None = None
        self.setup_ui()
        # disk list populates lazily - first refresh on tab show is fine

    # ------------------------------------------------------------------ UI

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Output mode radio group ---
        mode_group = QGroupBox("Output mode")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_buttons = QButtonGroup(self)

        self.mode_img = QRadioButton("Image file (.img)")
        self.mode_img.setChecked(True)
        self.mode_buttons.addButton(self.mode_img)
        mode_layout.addWidget(self.mode_img)

        self.mode_img_flash = QRadioButton("Image file + flash to SD card")
        self.mode_buttons.addButton(self.mode_img_flash)
        mode_layout.addWidget(self.mode_img_flash)

        self.mode_device = QRadioButton("Direct to SD card (no .img file)")
        self.mode_buttons.addButton(self.mode_device)
        mode_layout.addWidget(self.mode_device)

        # one signal per click - off-edge + on-edge would otherwise both fire
        self.mode_buttons.buttonClicked.connect(self._on_mode_changed)

        layout.addWidget(mode_group)

        # --- Image file group ---
        self.image_group = QGroupBox("Image file")
        image_layout = QVBoxLayout(self.image_group)

        path_row = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Select output location...")
        path_row.addWidget(self.output_path)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_output)
        path_row.addWidget(self.browse_btn)
        image_layout.addLayout(path_row)

        self.sparse_cb = QCheckBox(
            "Sparse - allocates only the data actually used (saves disk space)"
        )
        self.sparse_cb.setChecked(True)
        image_layout.addWidget(self.sparse_cb)

        layout.addWidget(self.image_group)

        # --- SD card group ---
        self.disk_group = QGroupBox("SD card")
        disk_layout = QVBoxLayout(self.disk_group)

        disk_row = QHBoxLayout()
        disk_row.addWidget(QLabel("Disk:"))
        self.disk_combo = QComboBox()
        self.disk_combo.setMinimumWidth(380)
        self.disk_combo.currentIndexChanged.connect(self._emit_target_size)
        disk_row.addWidget(self.disk_combo, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_disks)
        disk_row.addWidget(self.refresh_btn)
        disk_layout.addLayout(disk_row)

        warning = QLabel("⚠ This will ERASE the selected disk!")
        warning.setStyleSheet("color: #b00; font-weight: bold;")
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disk_layout.addWidget(warning)

        layout.addWidget(self.disk_group)
        layout.addStretch()

        self._on_mode_changed()  # apply initial visibility

    # ------------------------------------------------------------------ behaviour

    def _on_mode_changed(self):
        """show/hide groups based on selected mode"""
        is_img_only = self.mode_img.isChecked()
        is_flash = self.mode_img_flash.isChecked()
        is_device = self.mode_device.isChecked()

        self.image_group.setVisible(is_img_only or is_flash)
        self.disk_group.setVisible(is_flash or is_device)

        if is_device or is_flash:
            # both modes write to a real card, so disk_size is locked to it
            self.refresh_disks()
            self._emit_target_size()
        else:
            self.target_size_cleared.emit()

    def _browse_output(self):
        current = self.output_path.text().strip()
        start = current or str(Path.home() / "amiga.img")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output Location",
            start,
            "Disk Images (*.img);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.output_path.setText(path)

    def refresh_disks(self):
        """spawn DiskListWorker, fill combo on result"""
        if self._disk_worker is not None and self._disk_worker.isRunning():
            return  # already in flight
        # block signals: clear() flips the index and would emit a stale
        # target_size_changed(0, "") before the new list lands
        self.disk_combo.blockSignals(True)
        self.disk_combo.clear()
        self.disk_combo.addItem("Scanning…", None)
        self.disk_combo.blockSignals(False)
        self._disk_worker = DiskListWorker(self)
        self._disk_worker.disks_loaded.connect(self._on_disks_loaded)
        self._disk_worker.start()

    @Slot(list)
    def _on_disks_loaded(self, disks: list):
        self._disks = disks
        self.disk_combo.blockSignals(True)
        self.disk_combo.clear()
        if not disks:
            self.disk_combo.addItem(
                "(no removable disks found - insert an SD card and refresh)", None
            )
        else:
            for d in disks:
                self.disk_combo.addItem(d.display_label, d.device)
        self.disk_combo.blockSignals(False)
        self._emit_target_size()

    def _emit_target_size(self):
        """DEVICE or IMG+flash: push the picked card's size so partitions can auto-size"""
        if not (self.mode_device.isChecked() or self.mode_img_flash.isChecked()):
            return
        device = self.disk_combo.currentData()
        info = next((d for d in self._disks if d.device == device), None)
        if info is None:
            self.target_size_cleared.emit()
            return
        self.target_size_changed.emit(info.size_bytes, info.display_label)

    # ------------------------------------------------------------------ config IO

    def get_config(self) -> dict:
        if self.mode_device.isChecked():
            device = self.disk_combo.currentData()
            return {
                "type": OutputType.DEVICE.value,
                "path": device or "",
                "sparse": False,
                "flash_target": None,
            }
        if self.mode_img_flash.isChecked():
            return {
                "type": OutputType.IMG.value,
                "path": self.output_path.text(),
                "sparse": self.sparse_cb.isChecked(),
                "flash_target": self.disk_combo.currentData(),
            }
        return {
            "type": OutputType.IMG.value,
            "path": self.output_path.text(),
            "sparse": self.sparse_cb.isChecked(),
            "flash_target": None,
        }

    def set_config(self, config: OutputConfig | None):
        if config is None:
            return
        if config.type == OutputType.DEVICE:
            self.mode_device.setChecked(True)
        elif getattr(config, "flash_target", None):
            self.mode_img_flash.setChecked(True)
            if config.path:
                self.output_path.setText(str(config.path))
            self.sparse_cb.setChecked(getattr(config, "sparse", True))
        else:
            self.mode_img.setChecked(True)
            if config.path:
                self.output_path.setText(str(config.path))
            self.sparse_cb.setChecked(getattr(config, "sparse", True))
        # programmatic setChecked doesnt fire buttonClicked; call the handler directly
        self._on_mode_changed()
