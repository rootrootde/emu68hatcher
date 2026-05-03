"""output config tab - image file path"""

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import OutputConfig


class OutputTab(QWidget):
    """output configuration tab"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.image_group = QGroupBox("Image File")
        image_layout = QHBoxLayout(self.image_group)

        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Select output location...")
        image_layout.addWidget(self.output_path)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_output)
        image_layout.addWidget(self.browse_btn)

        layout.addWidget(self.image_group)
        layout.addStretch()

    def _browse_output(self):
        """open file dialog for image output location"""
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

    def get_config(self) -> dict:
        """get current output configuration"""
        return {
            "type": "img",
            "path": self.output_path.text(),
        }

    def set_config(self, config: OutputConfig | None):
        """populate the tab from config object"""
        if config is None:
            return
        if config.path:
            self.output_path.setText(str(config.path))
