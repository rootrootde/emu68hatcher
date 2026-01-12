"""
output configuration tab - supports both image files and physical disks
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QComboBox,
    QLabel,
    QMessageBox,
)
from PySide6.QtCore import Signal

from emu68hatcher.config.schema import OutputConfig, OutputType
from emu68hatcher.builder.disk_manager import DiskManager, DiskInfo
from emu68hatcher.utils.platform import get_platform_info


class OutputTab(QWidget):
    """output configuration tab with support for image files and SD cards"""

    # emitted when output type changes
    output_type_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._disks: list[DiskInfo] = []
        self._disk_manager = DiskManager()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # output Type Selection
        type_group = QGroupBox("Output Type")
        type_layout = QVBoxLayout(type_group)

        self.type_button_group = QButtonGroup(self)

        self.img_radio = QRadioButton("Disk Image File (.img)")
        self.img_radio.setChecked(True)
        self.img_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.img_radio)
        type_layout.addWidget(self.img_radio)

        self.disk_radio = QRadioButton("Physical Disk (SD Card / USB)")
        self.disk_radio.toggled.connect(self._on_type_changed)
        self.type_button_group.addButton(self.disk_radio)
        type_layout.addWidget(self.disk_radio)

        # note: Privilege escalation happens at write time, not app startup
        platform_info = get_platform_info()
        if not platform_info.is_root:
            self.disk_radio.setToolTip("Will prompt for admin password when writing")

        layout.addWidget(type_group)

        # image File Output
        self.image_group = QGroupBox("Image File")
        image_layout = QHBoxLayout(self.image_group)

        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Select output location...")
        image_layout.addWidget(self.output_path)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_output)
        image_layout.addWidget(self.browse_btn)

        layout.addWidget(self.image_group)

        # physical Disk Output
        self.disk_group = QGroupBox("Physical Disk")
        disk_layout = QVBoxLayout(self.disk_group)

        # disk selection row
        disk_select_layout = QHBoxLayout()

        self.disk_combo = QComboBox()
        self.disk_combo.setMinimumWidth(300)
        disk_select_layout.addWidget(self.disk_combo, 1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_disks)
        disk_select_layout.addWidget(self.refresh_btn)

        disk_layout.addLayout(disk_select_layout)

        # disk info label
        self.disk_info_label = QLabel("")
        self.disk_info_label.setStyleSheet("color: gray;")
        disk_layout.addWidget(self.disk_info_label)

        # warning label
        self.warning_label = QLabel(
            "⚠️ WARNING: Writing to a physical disk will ERASE ALL DATA on that disk!"
        )
        self.warning_label.setStyleSheet("color: #cc6600; font-weight: bold;")
        disk_layout.addWidget(self.warning_label)

        layout.addWidget(self.disk_group)

        # initially hide disk group
        self.disk_group.setVisible(False)

        layout.addStretch()

        # connect disk combo change
        self.disk_combo.currentIndexChanged.connect(self._on_disk_selected)

    def _on_type_changed(self):
        """handle output type change"""
        is_image = self.img_radio.isChecked()
        self.image_group.setVisible(is_image)
        self.disk_group.setVisible(not is_image)

        if not is_image:
            self._refresh_disks()

        self.output_type_changed.emit("img" if is_image else "disk")

    def _browse_output(self):
        """open file dialog for image output location"""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output Location",
            "amiga.img",
            "Disk Images (*.img);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.output_path.setText(path)

    def _refresh_disks(self):
        """refresh the list of available removable disks"""
        self.disk_combo.clear()
        self._disks = []

        try:
            self._disks = self._disk_manager.list_removable_disks()
        except Exception as e:
            self.disk_info_label.setText(f"Error scanning disks: {e}")
            return

        if not self._disks:
            self.disk_combo.addItem("No removable disks found")
            self.disk_info_label.setText("Insert an SD card or USB drive and click Refresh")
            return

        for disk in self._disks:
            # format: "Name (Size) - /dev/xxx"
            label = f"{disk.model or 'Unknown'} ({disk.size_human}) - {disk.path}"
            self.disk_combo.addItem(label)

        self._on_disk_selected(0)

    def _on_disk_selected(self, index: int):
        """handle disk selection change"""
        if index < 0 or index >= len(self._disks):
            self.disk_info_label.setText("")
            return

        disk = self._disks[index]
        info_parts = [
            f"Path: {disk.path}",
            f"Size: {disk.size_human}",
        ]
        if disk.is_mounted:
            info_parts.append("Status: Mounted (will be unmounted before writing)")
        else:
            info_parts.append("Status: Not mounted")

        self.disk_info_label.setText(" | ".join(info_parts))

    def get_selected_disk(self) -> Optional[DiskInfo]:
        """get the currently selected disk"""
        index = self.disk_combo.currentIndex()
        if index < 0 or index >= len(self._disks):
            return None
        return self._disks[index]

    def get_config(self) -> dict:
        """get current output configuration"""
        if self.img_radio.isChecked():
            return {
                "type": "img",
                "path": self.output_path.text(),
            }
        else:
            disk = self.get_selected_disk()
            return {
                "type": "disk",
                "path": str(disk.path) if disk else "",
            }

    def set_config(self, config: Optional[OutputConfig]):
        """populate the tab from config object"""
        if config is None:
            return

        # set output type
        if config.type == OutputType.DISK:
            self.disk_radio.setChecked(True)
        else:
            self.img_radio.setChecked(True)

        # set output path (for image mode)
        if config.path:
            self.output_path.setText(str(config.path))

    def validate(self) -> tuple[bool, str]:
        """validate the output configuration"""
        if self.img_radio.isChecked():
            if not self.output_path.text():
                return False, "Please select an output file location"
            return True, ""
        else:
            disk = self.get_selected_disk()
            if not disk:
                return False, "Please select a target disk"

            # double-check it's removable
            if not disk.is_removable:
                return False, "Selected disk is not removable - refusing to write"

            return True, ""

    def confirm_disk_write(self) -> bool:
        """show confirmation dialog before writing to physical disk"""
        disk = self.get_selected_disk()
        if not disk:
            return False

        result = QMessageBox.warning(
            self,
            "Confirm Disk Write",
            f"You are about to write to:\n\n"
            f"  {disk.model or 'Unknown Device'}\n"
            f"  {disk.path}\n"
            f"  Size: {disk.size_human}\n\n"
            f"ALL DATA ON THIS DISK WILL BE PERMANENTLY ERASED!\n\n"
            f"Are you absolutely sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        return result == QMessageBox.StandardButton.Yes
