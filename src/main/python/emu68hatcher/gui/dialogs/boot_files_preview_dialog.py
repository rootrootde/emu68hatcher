"""Boot-file preview dialog."""

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)


class BootFilesPreviewDialog(QDialog):
    def __init__(self, files: dict[str, str], parent=None):
        super().__init__(parent)
        self._files = files
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Boot Files Preview")
        self.setMinimumSize(720, 520)
        self.resize(900, 680)
        self.setModal(True)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for filename, content in self._files.items():
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            editor.setFont(fixed_font)
            editor.setPlainText(content)
            self.tabs.addTab(editor, filename)
        layout.addWidget(self.tabs)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
