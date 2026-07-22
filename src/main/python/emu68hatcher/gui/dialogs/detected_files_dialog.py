"""detected-files dialog - tabbed view of detected ROMs / WHDLoad ROMs / ADFs"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


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
