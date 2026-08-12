"""Partition table rendering and typed edit signals."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from emu68hatcher.config.partition_models import AmigaPartition, Filesystem

COL_DEVICE = 0
COL_VOLUME = 1
COL_SIZE = 2
COL_FS = 3
COL_BOOTABLE = 4


class PartitionTable(QTableWidget):
    device_edited = Signal(int, str)
    volume_edited = Signal(int, str)
    size_edited = Signal(int, str)
    filesystem_edited = Signal(int, str)
    bootable_edited = Signal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rendering = False
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(["Device", "Volume", "Size (MB)", "Filesystem", "Boot"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(
            COL_BOOTABLE,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.cellChanged.connect(self._cell_changed)

    def render(self, partitions: list[AmigaPartition]) -> None:
        self._rendering = True
        try:
            self.setRowCount(len(partitions))
            for row, partition in enumerate(partitions):
                self.setItem(row, COL_DEVICE, QTableWidgetItem(partition.device))
                self.setItem(row, COL_VOLUME, QTableWidgetItem(partition.volume))
                size_item = QTableWidgetItem(str(round(partition.size / (1024 * 1024))))
                size_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.setItem(row, COL_SIZE, size_item)
                self.setCellWidget(row, COL_FS, self._filesystem_combo(row, partition))
                self.setCellWidget(row, COL_BOOTABLE, self._bootable_widget(row, partition))
        finally:
            self._rendering = False

    def selected_row(self) -> int:
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        return rows[0].row() if rows else -1

    def _filesystem_combo(self, row: int, partition: AmigaPartition) -> QComboBox:
        combo = QComboBox()
        for filesystem in Filesystem:
            combo.addItem(filesystem.value)
        combo.setCurrentText(partition.filesystem.value)
        combo.currentTextChanged.connect(
            lambda text, current=row: self.filesystem_edited.emit(current, text)
        )
        return combo

    def _bootable_widget(self, row: int, partition: AmigaPartition) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox = QCheckBox()
        checkbox.setChecked(partition.bootable)
        checkbox.stateChanged.connect(
            lambda state, current=row: self.bootable_edited.emit(current, state == 2)
        )
        layout.addWidget(checkbox)
        return widget

    def _cell_changed(self, row: int, column: int) -> None:
        if self._rendering:
            return
        item = self.item(row, column)
        if item is None:
            return
        text = item.text()
        if column == COL_DEVICE:
            self.device_edited.emit(row, text)
        elif column == COL_VOLUME:
            self.volume_edited.emit(row, text)
        elif column == COL_SIZE:
            self.size_edited.emit(row, text)
