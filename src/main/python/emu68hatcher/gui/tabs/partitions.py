"""
partition configuration tab with editable partition layout
"""

from typing import Optional

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter, QFont, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QComboBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QCheckBox,
    QToolTip,
)

from emu68hatcher.config.defaults import (
    COMMON_DISK_SIZES,
    CYLINDER_SIZE,
    DEFAULT_NEW_PARTITION_SIZE,
    MAX_AMIGA_PARTITIONS,
    MIN_AMIGA_PARTITION_SIZE,
)
from emu68hatcher.config.partition_helpers import (
    build_partition_config,
    calculate_boot_default,
    calculate_free_space,
    calculate_id76_size,
    disk_size_for_gb,
    next_device_name,
    next_volume_name,
    round_to_cylinder,
    round_to_mbr_sector,
    validate_partition_layout,
)
from emu68hatcher.config.schema import (
    AmigaPartition,
    Filesystem,
    PartitionConfig,
)


# ── Partition bar visualization ──────────────────────────────────────

BOOT_COLOR = QColor("#546E7A")       # blue-gray
AMIGA_COLORS = [
    QColor("#009688"),  # teal
    QColor("#FF9800"),  # orange
    QColor("#4CAF50"),  # green
    QColor("#9C27B0"),  # purple
    QColor("#F44336"),  # red
    QColor("#3F51B5"),  # indigo
]
FREE_COLOR = QColor("#424242")       # dark gray
SELECTED_BORDER = QColor("#FFEB3B")  # yellow highlight


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    return f"{size_bytes // (1024 ** 2)} MB"


class PartitionBar(QWidget):
    """horizontal bar showing proportional partition sizes with drag-resize"""

    GRAB_ZONE = 5  # pixels from border edge to activate resize

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMaximumHeight(70)
        self.setMouseTracking(True)
        self._segments: list[tuple[str, int, str, QColor, bool]] = []
        self._disk_size = 1
        self._rects: list[tuple[QRect, str]] = []
        self._on_resize_callback = None  # callable(left_idx, left_size, right_idx, right_size)
        # drag state
        self._borders: list[tuple[int, int, int]] = []
        self._dragging = False
        self._drag_border_idx = -1
        self._drag_start_x = 0
        self._bytes_per_pixel = 1.0
        self._amiga_partitions = []
        self._free_space = 0

    def set_data(self, disk_size: int, boot_size: int, amiga_partitions, free_space: int, selected: int = -1):
        self._disk_size = max(disk_size, 1)
        self._amiga_partitions = list(amiga_partitions)
        self._free_space = free_space
        self._segments = []
        self._segments.append(("EMU68BOOT", boot_size, "FAT32", BOOT_COLOR, False))
        for i, p in enumerate(amiga_partitions):
            color = AMIGA_COLORS[i % len(AMIGA_COLORS)]
            star = " *" if p.bootable else ""
            sublabel = f"{p.filesystem.value}{star}"
            self._segments.append((p.volume, p.size, sublabel, color, i == selected))
        if free_space > 0:
            self._segments.append(("free", free_space, "", FREE_COLOR, False))
        self.update()

    def _resizable_border(self, seg_idx: int) -> bool:
        """check if the border between seg_idx and seg_idx+1 is resizable.
        only borders between two Amiga partitions, or between the last
        amiga partition and the free space block, are resizable"""
        # seg 0 = boot. amiga partitions start at seg 1
        left = seg_idx
        right = seg_idx + 1
        if right >= len(self._segments):
            return False
        # boot border (0|1) is not resizable
        if left == 0:
            return False
        return True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width() - 2
        h = self.height() - 2
        x = 1

        total = sum(s[1] for s in self._segments)
        if total <= 0:
            painter.end()
            return

        self._bytes_per_pixel = total / w if w > 0 else 1.0
        self._rects = []
        self._borders = []
        name_font = QFont()
        name_font.setPointSize(9)
        name_font.setBold(True)
        sub_font = QFont()
        sub_font.setPointSize(8)

        for idx, (label, size, sublabel, color, selected) in enumerate(self._segments):
            seg_w = max(2, int((size / total) * w))
            if x + seg_w > self.width() - 1:
                seg_w = self.width() - 1 - x
            rect = QRect(x, 1, seg_w, h)
            self._rects.append((rect, f"{label}\n{_format_size(size)}\n{sublabel}"))

            painter.fillRect(rect, QBrush(color))

            if selected:
                pen = QPen(SELECTED_BORDER, 2)
                painter.setPen(pen)
                painter.drawRect(rect.adjusted(1, 1, -1, -1))

            painter.setPen(QPen(QColor("#222222"), 1))
            painter.drawRect(rect)

            painter.setPen(QColor("#FFFFFF"))
            text_rect = rect.adjusted(4, 2, -4, -2)
            if seg_w > 80:
                painter.setFont(name_font)
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, label)
                painter.setFont(sub_font)
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignBottom, f"{_format_size(size)}  {sublabel}")
            elif seg_w > 40:
                painter.setFont(sub_font)
                painter.drawText(text_rect, Qt.AlignCenter, label)

            x += seg_w

            # record border position for drag detection
            if idx < len(self._segments) - 1 and self._resizable_border(idx):
                self._borders.append((x, idx, idx + 1))

        painter.end()

    def _border_at(self, x: int) -> int:
        """return index into self._borders if x is near a border, else -1"""
        for i, (bx, _, _) in enumerate(self._borders):
            if abs(x - bx) <= self.GRAB_ZONE:
                return i
        return -1

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()

        if self._dragging:
            dx = pos.x() - self._drag_start_x
            delta_bytes = round_to_cylinder(int(dx * self._bytes_per_pixel))
            if delta_bytes == 0:
                return
            _, left_seg, right_seg = self._borders[self._drag_border_idx]
            # left_seg and right_seg are segment indices (0=boot, 1+=amiga, last=free)
            left_amiga = left_seg - 1   # index into amiga_partitions
            right_amiga = right_seg - 1

            left_is_amiga = 0 <= left_amiga < len(self._amiga_partitions)
            right_is_free = right_seg == len(self._segments) - 1 and self._segments[right_seg][0] == "free"
            right_is_amiga = 0 <= right_amiga < len(self._amiga_partitions)

            if left_is_amiga and (right_is_amiga or right_is_free):
                left_size = self._amiga_partitions[left_amiga].size
                if right_is_amiga:
                    right_size = self._amiga_partitions[right_amiga].size
                else:
                    right_size = self._free_space

                new_left = left_size + delta_bytes
                new_right = right_size - delta_bytes

                min_size = round_to_cylinder(MIN_AMIGA_PARTITION_SIZE)
                if right_is_free:
                    # free space can go to 0
                    if new_left < min_size or new_right < 0:
                        return
                else:
                    if new_left < min_size or new_right < min_size:
                        return

                self._amiga_partitions[left_amiga].size = new_left
                if right_is_amiga:
                    self._amiga_partitions[right_amiga].size = new_right

                self._drag_start_x = pos.x()
                if self._on_resize_callback:
                    self._on_resize_callback(left_amiga, new_left, right_amiga if right_is_amiga else -1, new_right)
            return

        # not dragging - update cursor and tooltip
        bi = self._border_at(pos.x())
        if bi >= 0:
            self.setCursor(Qt.SizeHorCursor)
            QToolTip.hideText()
        else:
            self.setCursor(Qt.ArrowCursor)
            for rect, tip in self._rects:
                if rect.contains(pos):
                    gpos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else self.mapToGlobal(pos)
                    QToolTip.showText(gpos, tip, self, rect)
                    return
            QToolTip.hideText()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        bi = self._border_at(pos.x())
        if bi >= 0:
            self._dragging = True
            self._drag_border_idx = bi
            self._drag_start_x = pos.x()

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._drag_border_idx = -1


# column indices
COL_DEVICE = 0
COL_VOLUME = 1
COL_SIZE = 2
COL_FS = 3
COL_BOOTABLE = 4


class PartitionsTab(QWidget):
    """partition configuration tab with editable layout"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False  # guard against re-entrant table updates
        self._disk_size_bytes = disk_size_for_gb(64)
        self._boot_size = calculate_boot_default(self._disk_size_bytes)
        self._amiga_partitions: list[AmigaPartition] = []
        self.setup_ui()
        self._reset_to_default()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Disk Size + Boot Partition (side by side) ---
        top_row = QHBoxLayout()

        size_group = QGroupBox("Disk Size")
        size_layout = QHBoxLayout(size_group)
        self.size_combo = QComboBox()
        for gb in COMMON_DISK_SIZES:
            self.size_combo.addItem(f"{gb} GB", gb)
        self.size_combo.setCurrentIndex(COMMON_DISK_SIZES.index(64))
        self.size_combo.currentIndexChanged.connect(self._on_disk_size_changed)
        size_layout.addWidget(self.size_combo)
        top_row.addWidget(size_group)

        boot_group = QGroupBox("Boot Partition (EMU68BOOT - FAT32)")
        boot_layout = QHBoxLayout(boot_group)
        boot_layout.addWidget(QLabel("Size:"))
        self.boot_spin = QSpinBox()
        self.boot_spin.setRange(128, 1024)
        self.boot_spin.setSuffix(" MB")
        self.boot_spin.setSingleStep(64)
        self.boot_spin.setValue(self._boot_size // (1024 * 1024))
        self.boot_spin.editingFinished.connect(self._on_boot_size_changed)
        boot_layout.addWidget(self.boot_spin)
        top_row.addWidget(boot_group)

        layout.addLayout(top_row)

        # --- Partition Bar ---
        self.partition_bar = PartitionBar()
        self.partition_bar._on_resize_callback = self._on_bar_resize
        layout.addWidget(self.partition_bar)

        # --- Amiga Partitions ---
        amiga_group = QGroupBox("Amiga Partitions")
        amiga_layout = QVBoxLayout(amiga_group)

        self.part_table = QTableWidget()
        self.part_table.setColumnCount(5)
        self.part_table.setHorizontalHeaderLabels(["Device", "Volume", "Size (MB)", "Filesystem", "Boot"])
        self.part_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.part_table.horizontalHeader().setSectionResizeMode(COL_BOOTABLE, QHeaderView.ResizeToContents)
        self.part_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.part_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.part_table.cellChanged.connect(self._on_cell_changed)
        self.part_table.itemSelectionChanged.connect(self._on_selection_changed)
        amiga_layout.addWidget(self.part_table)

        # buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Partition")
        self.add_btn.clicked.connect(self._on_add_partition)
        btn_layout.addWidget(self.add_btn)

        self.remove_btn = QPushButton("Remove Partition")
        self.remove_btn.clicked.connect(self._on_remove_partition)
        btn_layout.addWidget(self.remove_btn)

        self.reset_btn = QPushButton("Reset to Default")
        self.reset_btn.clicked.connect(self._reset_to_default)
        btn_layout.addWidget(self.reset_btn)

        btn_layout.addStretch()
        amiga_layout.addLayout(btn_layout)

        layout.addWidget(amiga_group)

        # --- Status ---
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

    # ── Event handlers ──────────────────────────────────────────────────

    def _on_disk_size_changed(self):
        gb = self.size_combo.currentData()
        if gb is None:
            return
        self._disk_size_bytes = disk_size_for_gb(gb)
        # recalculate boot default
        new_boot = calculate_boot_default(self._disk_size_bytes)
        self._boot_size = new_boot
        self.boot_spin.blockSignals(True)
        self.boot_spin.setValue(new_boot // (1024 * 1024))
        self.boot_spin.blockSignals(False)

        # check if existing partitions still fit
        id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
        free = calculate_free_space(id76, self._amiga_partitions)
        if free < 0:
            # partitions don't fit - reset to default
            self._reset_to_default()
        else:
            self._refresh_table()

    def _on_boot_size_changed(self):
        mb = self.boot_spin.value()
        self._boot_size = round_to_mbr_sector(mb * 1024 * 1024)
        self._refresh_table()

    def _on_add_partition(self):
        if len(self._amiga_partitions) >= MAX_AMIGA_PARTITIONS:
            return

        id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
        free = calculate_free_space(id76, self._amiga_partitions)

        if free < MIN_AMIGA_PARTITION_SIZE:
            return

        size = round_to_cylinder(free)
        if size < MIN_AMIGA_PARTITION_SIZE:
            return

        existing_devices = [p.device for p in self._amiga_partitions]
        existing_volumes = [p.volume for p in self._amiga_partitions]

        self._amiga_partitions.append(
            AmigaPartition(
                device=next_device_name(existing_devices),
                volume=next_volume_name(existing_volumes),
                filesystem=Filesystem.PFS3,
                size=size,
                bootable=False,
            )
        )
        self._refresh_table()

    def _on_remove_partition(self):
        row = self.part_table.currentRow()
        if row < 0 or len(self._amiga_partitions) <= 1:
            return
        self._amiga_partitions.pop(row)
        self._refresh_table()

    def _on_cell_changed(self, row, col):
        if self._updating or row < 0 or row >= len(self._amiga_partitions):
            return

        part = self._amiga_partitions[row]

        if col == COL_DEVICE:
            item = self.part_table.item(row, col)
            if item:
                val = item.text().strip().upper()
                if val and val != part.device:
                    part.device = val

        elif col == COL_VOLUME:
            item = self.part_table.item(row, col)
            if item:
                val = item.text().strip()
                if val and val != part.volume:
                    part.volume = val

        elif col == COL_SIZE:
            item = self.part_table.item(row, col)
            if item:
                try:
                    mb = int(item.text())
                    new_size = round_to_cylinder(mb * 1024 * 1024)
                    if new_size < MIN_AMIGA_PARTITION_SIZE:
                        new_size = round_to_cylinder(MIN_AMIGA_PARTITION_SIZE)
                    # cap at max available (free space + this partition's current size)
                    id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
                    free = calculate_free_space(id76, self._amiga_partitions)
                    max_size = round_to_cylinder(free + part.size)
                    if new_size > max_size:
                        new_size = max_size
                    part.size = new_size
                except ValueError:
                    pass
            self._refresh_table()
            return

        elif col == COL_FS:
            # handled by combo widget signal, not cellChanged
            pass

        self._update_status()

    def _on_fs_changed(self, row, fs_text):
        if self._updating or row < 0 or row >= len(self._amiga_partitions):
            return
        try:
            self._amiga_partitions[row].filesystem = Filesystem(fs_text)
        except ValueError:
            pass
        self._update_status()

    def _on_bar_resize(self, left_idx, left_size, right_idx, right_size):
        """handle partition resize from the bar widget"""
        if 0 <= left_idx < len(self._amiga_partitions):
            self._amiga_partitions[left_idx].size = left_size
        if 0 <= right_idx < len(self._amiga_partitions):
            self._amiga_partitions[right_idx].size = right_size
        self._refresh_table()

    def _on_selection_changed(self):
        if self._updating:
            return
        self._update_bar()

    def _on_bootable_changed(self, row, state):
        if self._updating or row < 0 or row >= len(self._amiga_partitions):
            return
        is_checked = state == Qt.CheckState.Checked.value or state == 2
        if is_checked:
            # uncheck all others
            for i, p in enumerate(self._amiga_partitions):
                p.bootable = (i == row)
        else:
            self._amiga_partitions[row].bootable = False
        self._refresh_table()

    # ── Table sync ──────────────────────────────────────────────────────

    def _refresh_table(self):
        """rebuild the table from internal state"""
        self._updating = True
        try:
            self.part_table.setRowCount(len(self._amiga_partitions))

            for i, part in enumerate(self._amiga_partitions):
                # device
                device_item = QTableWidgetItem(part.device)
                self.part_table.setItem(i, COL_DEVICE, device_item)

                # volume
                volume_item = QTableWidgetItem(part.volume)
                self.part_table.setItem(i, COL_VOLUME, volume_item)

                # size (MB) - round to nearest rather than truncate
                size_mb = round(part.size / (1024 * 1024))
                size_item = QTableWidgetItem(str(size_mb))
                size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.part_table.setItem(i, COL_SIZE, size_item)

                # filesystem combo
                fs_combo = QComboBox()
                for fs in Filesystem:
                    fs_combo.addItem(fs.value)
                fs_combo.setCurrentText(part.filesystem.value)
                row_idx = i  # capture for lambda
                fs_combo.currentTextChanged.connect(lambda text, r=row_idx: self._on_fs_changed(r, text))
                self.part_table.setCellWidget(i, COL_FS, fs_combo)

                # bootable checkbox
                boot_widget = QWidget()
                boot_layout = QHBoxLayout(boot_widget)
                boot_layout.setContentsMargins(0, 0, 0, 0)
                boot_layout.setAlignment(Qt.AlignCenter)
                boot_cb = QCheckBox()
                boot_cb.setChecked(part.bootable)
                boot_cb.stateChanged.connect(lambda state, r=row_idx: self._on_bootable_changed(r, state))
                boot_layout.addWidget(boot_cb)
                self.part_table.setCellWidget(i, COL_BOOTABLE, boot_widget)

            # update button states
            self.remove_btn.setEnabled(len(self._amiga_partitions) > 1)

            id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
            free = calculate_free_space(id76, self._amiga_partitions)
            self.add_btn.setEnabled(
                len(self._amiga_partitions) < MAX_AMIGA_PARTITIONS
                and free >= MIN_AMIGA_PARTITION_SIZE
            )
        finally:
            self._updating = False

        self._update_status()

    def _update_bar(self):
        """update the partition bar visualization"""
        id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
        from emu68hatcher.config.partition_helpers import calculate_usable_amiga_space
        usable = calculate_usable_amiga_space(id76)
        allocated = sum(p.size for p in self._amiga_partitions)
        free = max(0, usable - allocated)
        selected = self.part_table.currentRow()
        self.partition_bar.set_data(
            self._disk_size_bytes, self._boot_size,
            self._amiga_partitions, free, selected,
        )

    def _update_status(self):
        """update the status and error labels"""
        id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
        from emu68hatcher.config.partition_helpers import calculate_usable_amiga_space
        usable = calculate_usable_amiga_space(id76)
        allocated = sum(p.size for p in self._amiga_partitions)
        free = usable - allocated

        used_gb = allocated / (1024 ** 3)
        total_gb = usable / (1024 ** 3)
        free_mb = free / (1024 ** 2)

        self.status_label.setText(
            f"Amiga space: {used_gb:.2f} GB used / {total_gb:.2f} GB total "
            f"({free_mb:.0f} MB free)"
        )

        errors = validate_partition_layout(
            self._disk_size_bytes, self._boot_size, self._amiga_partitions
        )
        if errors:
            self.error_label.setText("\n".join(errors))
        else:
            self.error_label.setText("")

        self._update_bar()

    def _reset_to_default(self):
        """reset partitions to the default layout for current disk size"""
        from emu68hatcher.config.schema import create_default_partition_layout

        gb = self.size_combo.currentData()
        if gb is None:
            gb = 8

        layout = create_default_partition_layout(gb)
        self._disk_size_bytes = layout.disk_size

        # extract boot and amiga partitions from default layout
        for mbr in layout.layout:
            if mbr.type == "fat32":
                self._boot_size = mbr.size
                self.boot_spin.blockSignals(True)
                self.boot_spin.setValue(mbr.size // (1024 * 1024))
                self.boot_spin.blockSignals(False)
            elif mbr.type == "id76" and mbr.amiga_partitions:
                self._amiga_partitions = list(mbr.amiga_partitions)

        self._refresh_table()

    # ── Config I/O ──────────────────────────────────────────────────────

    def get_config(self) -> PartitionConfig:
        """build a PartitionConfig from the current editor state"""
        return build_partition_config(
            self._disk_size_bytes, self._boot_size, self._amiga_partitions
        )

    def set_config(self, config: Optional[PartitionConfig]):
        """populate the tab from a PartitionConfig"""
        if config is None:
            return

        self._disk_size_bytes = config.disk_size

        # find closest disk size preset
        approx_gb = config.disk_size / (1_000_000_000 * 0.95)
        closest_gb = min(COMMON_DISK_SIZES, key=lambda x: abs(x - approx_gb))
        idx = COMMON_DISK_SIZES.index(closest_gb)
        self.size_combo.blockSignals(True)
        self.size_combo.setCurrentIndex(idx)
        self.size_combo.blockSignals(False)

        # extract boot and amiga partitions
        for mbr in config.layout:
            if mbr.type == "fat32":
                self._boot_size = mbr.size
                self.boot_spin.blockSignals(True)
                self.boot_spin.setValue(mbr.size // (1024 * 1024))
                self.boot_spin.blockSignals(False)
            elif mbr.type == "id76" and mbr.amiga_partitions:
                self._amiga_partitions = list(mbr.amiga_partitions)

        self._refresh_table()
