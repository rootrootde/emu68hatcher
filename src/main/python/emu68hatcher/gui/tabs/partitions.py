"""partition tab - editable layout"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.defaults import (
    COMMON_DISK_SIZES,
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
from emu68hatcher.gui.widgets.partition_bar import PartitionBar

# column indices
COL_DEVICE = 0
COL_VOLUME = 1
COL_SIZE = 2
COL_FS = 3
COL_BOOTABLE = 4


class PartitionsTab(QWidget):
    """partition layout editor"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False  # guard re-entrant table updates
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
        size_layout = QVBoxLayout(size_group)
        self.size_combo = QComboBox()
        for gb in COMMON_DISK_SIZES:
            self.size_combo.addItem(f"{gb} GB", gb)
        self.size_combo.setCurrentIndex(COMMON_DISK_SIZES.index(64))
        self.size_combo.currentIndexChanged.connect(self._on_disk_size_changed)
        size_layout.addWidget(self.size_combo)
        # shown only when output mode locks the size (Direct-to-SD card)
        self.auto_size_label = QLabel()
        self.auto_size_label.setStyleSheet("color: #666; font-style: italic;")
        self.auto_size_label.setVisible(False)
        size_layout.addWidget(self.auto_size_label)
        top_row.addWidget(size_group)

        boot_group = QGroupBox("Boot Partition (EMU68BOOT - FAT32)")
        boot_layout = QHBoxLayout(boot_group)
        boot_layout.addWidget(QLabel("Size:"))
        self.boot_spin = QSpinBox()
        self.boot_spin.setRange(128, 16384)
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
        self.part_table.setHorizontalHeaderLabels(
            ["Device", "Volume", "Size (MB)", "Filesystem", "Boot"]
        )
        self.part_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.part_table.horizontalHeader().setSectionResizeMode(
            COL_BOOTABLE, QHeaderView.ResizeMode.ResizeToContents
        )
        self.part_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.part_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.part_table.cellChanged.connect(self._on_cell_changed)
        self.part_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.partition_bar.partition_clicked.connect(self.part_table.selectRow)
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

        # per-partition detail panel: selected row -> extra content directory picker
        self._extras_box = QWidget()
        extras_layout = QHBoxLayout(self._extras_box)
        extras_layout.setContentsMargins(0, 6, 0, 0)
        self._extras_label = QLabel("Extra content directory:")
        extras_layout.addWidget(self._extras_label)
        self._extras_edit = QLineEdit()
        self._extras_edit.setPlaceholderText("(optional) contents mirrored into this partition")
        self._extras_edit.setReadOnly(True)
        extras_layout.addWidget(self._extras_edit, 1)
        self._extras_browse_btn = QPushButton("Browse...")
        self._extras_browse_btn.clicked.connect(self._browse_extras_directory)
        extras_layout.addWidget(self._extras_browse_btn)
        self._extras_clear_btn = QPushButton("Clear")
        self._extras_clear_btn.clicked.connect(self._clear_extras_directory)
        extras_layout.addWidget(self._extras_clear_btn)
        self._extras_box.setEnabled(False)
        amiga_layout.addWidget(self._extras_box)

        layout.addWidget(amiga_group)

        # --- Status ---
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

    # ── External signals (output tab → here) ────────────────────────────

    def set_auto_disk_size(self, size_bytes, label) -> None:
        """lock disk_size + reset to the SD card's exact bytes; boot_spin stays editable"""
        gb = max(1, size_bytes // (1024**3))  # for combo display only
        existing = [self.size_combo.itemData(i) for i in range(self.size_combo.count())]
        self.size_combo.blockSignals(True)
        if gb not in existing:
            self.size_combo.addItem(f"{gb} GB", gb)
        idx = next(
            (i for i in range(self.size_combo.count()) if self.size_combo.itemData(i) == gb), -1
        )
        if idx >= 0:
            self.size_combo.setCurrentIndex(idx)
        self.size_combo.blockSignals(False)
        self.size_combo.setEnabled(False)
        self.reset_btn.setEnabled(False)
        self.auto_size_label.setText(f"Auto: {label}")
        self.auto_size_label.setVisible(True)
        self._apply_disk_size_bytes(size_bytes)

    def clear_auto_disk_size(self) -> None:
        """unlock disk_size combo + reset, re-apply the GB-snapped layout"""
        if not self.size_combo.isEnabled():
            self.size_combo.setEnabled(True)
            self.reset_btn.setEnabled(True)
            self.auto_size_label.setVisible(False)
            self.auto_size_label.clear()
            self._on_disk_size_changed()  # snap layout to the GB combo's current value

    # ── Event handlers ──────────────────────────────────────────────────

    def _load_boot_and_amiga_from(self, layout) -> None:
        """pull boot_size + amiga partitions out of an mbr layout into editor state"""
        for mbr in layout.layout:
            if mbr.type == "fat32":
                self._boot_size = mbr.size
                self.boot_spin.blockSignals(True)
                self.boot_spin.setValue(mbr.size // (1024 * 1024))
                self.boot_spin.blockSignals(False)
            elif mbr.type == "id76" and mbr.amiga_partitions:
                self._amiga_partitions = list(mbr.amiga_partitions)

    def _apply_disk_size_bytes(self, disk_size_bytes: int) -> None:
        """recompute the Workbench+Work default for this exact byte size"""
        from emu68hatcher.config.schema import create_default_partition_layout

        self._disk_size_bytes = disk_size_bytes
        # carry user-picked extra-content dirs across the default rebuild (keyed by device)
        extras = {
            p.device: p.extra_content_directory
            for p in self._amiga_partitions
            if p.extra_content_directory
        }
        # rebuild the Workbench+Work default sized for this exact disk
        layout = create_default_partition_layout(disk_size_bytes=disk_size_bytes)
        self._load_boot_and_amiga_from(layout)
        for p in self._amiga_partitions:
            if p.device in extras:
                p.extra_content_directory = extras[p.device]
        self._refresh_table()

    def _on_disk_size_changed(self):
        gb = self.size_combo.currentData()
        if gb is None:
            return
        # 95% safety factor: destination disk size isnt known when picking GB manually
        self._disk_size_bytes = disk_size_for_gb(gb)
        # recompute boot default
        new_boot = calculate_boot_default(self._disk_size_bytes)
        self._boot_size = new_boot
        self.boot_spin.blockSignals(True)
        self.boot_spin.setValue(new_boot // (1024 * 1024))
        self.boot_spin.blockSignals(False)

        # do existing partitions still fit?
        id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
        free = calculate_free_space(id76, self._amiga_partitions)
        if free < 0:
            # partitions dont fit - reset to default
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
        """resize from the bar widget drag"""
        if 0 <= left_idx < len(self._amiga_partitions):
            self._amiga_partitions[left_idx].size = left_size
        if 0 <= right_idx < len(self._amiga_partitions):
            self._amiga_partitions[right_idx].size = right_size
        self._refresh_table()

    def _on_selection_changed(self):
        if self._updating:
            return
        self._update_bar()
        self._refresh_extras_panel()

    def _selected_partition_row(self) -> int:
        rows = (
            self.part_table.selectionModel().selectedRows()
            if self.part_table.selectionModel()
            else []
        )
        if not rows:
            return -1
        return rows[0].row()

    def _refresh_extras_panel(self):
        row = self._selected_partition_row()
        if not (0 <= row < len(self._amiga_partitions)):
            self._extras_box.setEnabled(False)
            self._extras_edit.clear()
            self._extras_label.setText("Extra content directory:")
            return
        part = self._amiga_partitions[row]
        self._extras_box.setEnabled(True)
        self._extras_label.setText(f"Extra content for {part.device} ({part.volume}):")
        self._extras_edit.setText(
            str(part.extra_content_directory) if part.extra_content_directory else ""
        )

    def _browse_extras_directory(self):
        row = self._selected_partition_row()
        if not (0 <= row < len(self._amiga_partitions)):
            return
        start = self._extras_edit.text() or ""
        path = QFileDialog.getExistingDirectory(
            self,
            "Select directory to mirror into this partition",
            start,
            QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        self._amiga_partitions[row].extra_content_directory = Path(path)
        self._extras_edit.setText(path)

    def _clear_extras_directory(self):
        row = self._selected_partition_row()
        if not (0 <= row < len(self._amiga_partitions)):
            return
        self._amiga_partitions[row].extra_content_directory = None
        self._extras_edit.clear()

    def _on_bootable_changed(self, row, state):
        if self._updating or row < 0 or row >= len(self._amiga_partitions):
            return
        is_checked = state == Qt.CheckState.Checked.value or state == 2
        if is_checked:
            # only one bootable - uncheck the rest
            for i, p in enumerate(self._amiga_partitions):
                p.bootable = i == row
        else:
            self._amiga_partitions[row].bootable = False
        self._refresh_table()

    # ── Table sync ──────────────────────────────────────────────────────

    def _refresh_table(self):
        """rebuild table from internal state"""
        self._updating = True
        try:
            self.part_table.setRowCount(len(self._amiga_partitions))

            for i, part in enumerate(self._amiga_partitions):
                device_item = QTableWidgetItem(part.device)
                self.part_table.setItem(i, COL_DEVICE, device_item)

                volume_item = QTableWidgetItem(part.volume)
                self.part_table.setItem(i, COL_VOLUME, volume_item)

                # size (MB) - round to nearest, not truncate
                size_mb = round(part.size / (1024 * 1024))
                size_item = QTableWidgetItem(str(size_mb))
                size_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.part_table.setItem(i, COL_SIZE, size_item)

                fs_combo = QComboBox()
                for fs in Filesystem:
                    fs_combo.addItem(fs.value)
                fs_combo.setCurrentText(part.filesystem.value)
                row_idx = i  # capture for lambda
                fs_combo.currentTextChanged.connect(
                    lambda text, r=row_idx: self._on_fs_changed(r, text)
                )
                self.part_table.setCellWidget(i, COL_FS, fs_combo)

                boot_widget = QWidget()
                boot_layout = QHBoxLayout(boot_widget)
                boot_layout.setContentsMargins(0, 0, 0, 0)
                boot_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                boot_cb = QCheckBox()
                boot_cb.setChecked(part.bootable)
                boot_cb.stateChanged.connect(
                    lambda state, r=row_idx: self._on_bootable_changed(r, state)
                )
                boot_layout.addWidget(boot_cb)
                self.part_table.setCellWidget(i, COL_BOOTABLE, boot_widget)

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
        self._refresh_extras_panel()

    def _space(self) -> tuple[int, int, int]:
        """(usable, allocated, free) amiga space in bytes; free may be negative when over-allocated"""
        from emu68hatcher.config.partition_helpers import calculate_usable_amiga_space

        id76 = calculate_id76_size(self._disk_size_bytes, self._boot_size)
        usable = calculate_usable_amiga_space(id76)
        allocated = sum(p.size for p in self._amiga_partitions)
        return usable, allocated, usable - allocated

    def _update_bar(self):
        """refresh the partition bar viz"""
        _usable, _allocated, free = self._space()
        free = max(0, free)
        selected = self.part_table.currentRow()
        self.partition_bar.set_data(
            self._disk_size_bytes,
            self._boot_size,
            self._amiga_partitions,
            free,
            selected,
        )

    def _update_status(self):
        """refresh status + error labels"""
        usable, allocated, free = self._space()

        used_gb = allocated / (1024**3)
        total_gb = usable / (1024**3)
        free_mb = free / (1024**2)

        self.status_label.setText(
            f"Amiga space: {used_gb:.2f} GB used / {total_gb:.2f} GB total ({free_mb:.0f} MB free)"
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
        """reset partitions to the default for the current disk size"""
        from emu68hatcher.config.schema import create_default_partition_layout

        gb = self.size_combo.currentData()
        if gb is None:
            gb = 8

        layout = create_default_partition_layout(gb)
        self._disk_size_bytes = layout.disk_size
        self._load_boot_and_amiga_from(layout)
        self._refresh_table()

    # ── Config I/O ──────────────────────────────────────────────────────

    def get_config(self) -> PartitionConfig:
        """PartitionConfig from current editor state"""
        return build_partition_config(
            self._disk_size_bytes, self._boot_size, self._amiga_partitions
        )

    def set_config(self, config: PartitionConfig | None):
        """populate tab from a PartitionConfig"""
        if config is None:
            return

        self._disk_size_bytes = config.disk_size

        # snap to the closest disk-size preset
        approx_gb = config.disk_size / (1_000_000_000 * 0.95)
        closest_gb = min(COMMON_DISK_SIZES, key=lambda x: abs(x - approx_gb))
        idx = COMMON_DISK_SIZES.index(closest_gb)
        self.size_combo.blockSignals(True)
        self.size_combo.setCurrentIndex(idx)
        self.size_combo.blockSignals(False)

        self._load_boot_and_amiga_from(config)
        self._refresh_table()
