"""Emu68 boot settings tab."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.boot_models import Emu68BootSettings
from emu68hatcher.config.schema import Emu68Version
from emu68hatcher.gui.widgets import select_combo_by_data


class BootFilesTab(QWidget):
    """Edit Emu68 boot settings."""

    preview_requested = Signal()

    def __init__(
        self,
        emu68_version: Emu68Version = Emu68Version.V1_0_7,
        parent=None,
    ):
        super().__init__(parent)
        self.emu68_version = emu68_version
        self._rtg_mode_enabled = True
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(10)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

        self._label_width = self.fontMetrics().horizontalAdvance("CHIP slowdown distance:") + 8

        self.version_note = QLabel()
        self.version_note.setWordWrap(True)
        header = QHBoxLayout()
        header.addStretch()
        self.preview_button = QPushButton("Preview Files...")
        self.preview_button.clicked.connect(self.preview_requested.emit)
        header.addWidget(self.preview_button)
        self.content_layout.addLayout(header)

        main_groups = QVBoxLayout()
        main_groups.setContentsMargins(0, 0, 0, 0)
        main_groups.setSpacing(10)
        main_groups.addWidget(self._create_hardware_group())
        main_groups.addWidget(self._create_framethrower_group())
        self.content_layout.addLayout(main_groups)

        self.advanced_button = QPushButton("Advanced Settings...")
        self.advanced_button.clicked.connect(self._show_advanced_settings)
        advanced_row = QHBoxLayout()
        advanced_row.addWidget(self.advanced_button)
        advanced_row.addStretch()
        self.content_layout.addLayout(advanced_row)
        self.content_layout.addStretch()

        self._create_advanced_dialog()
        self._normalise_control_widths()
        self._sync_storage_timing_from_details()
        self.set_emu68_version(self.emu68_version)
        self._update_custom_fields()

    def _form_layout(self, parent: QWidget) -> QFormLayout:
        form = QFormLayout(parent)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        return form

    def _add_form_row(self, form: QFormLayout, text: str, field: QWidget):
        label = QLabel(text)
        label.setMinimumWidth(self._label_width)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow(label, field)

    @staticmethod
    def _paired_field(primary: QWidget, secondary: QWidget) -> QWidget:
        field = QWidget()
        row = QHBoxLayout(field)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(primary, 1)
        row.addWidget(secondary)
        return field

    def _normalise_control_widths(self):
        for combo in self.findChildren(QComboBox):
            combo.setMinimumWidth(180)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for spin in self.findChildren(QSpinBox):
            spin.setMinimumWidth(92)

    def _create_hardware_group(self) -> QGroupBox:
        hardware_group = QGroupBox("Hardware")
        form = self._form_layout(hardware_group)

        self.antenna_combo = QComboBox()
        self.antenna_combo.addItem("Release default", "default")
        self.antenna_combo.addItem("Internal (ant1)", "internal")
        self.antenna_combo.addItem("External (ant2)", "external")
        self._add_form_row(form, "CM4 antenna:", self.antenna_combo)

        self.storage_timing_combo = QComboBox()
        self.storage_timing_combo.addItem("Compatible (recommended)", "compatible")
        self.storage_timing_combo.addItem("Standard", "standard")
        self.storage_timing_combo.addItem("Custom (advanced)", "custom")
        self.storage_timing_combo.setToolTip(
            "Compatible uses low-speed SD and eMMC timing. "
            "Standard uses the normal controller clocks."
        )
        self.storage_timing_combo.currentIndexChanged.connect(self._apply_storage_timing_selection)
        self._add_form_row(form, "Storage timing:", self.storage_timing_combo)

        return hardware_group

    def _create_boot_group(self) -> QGroupBox:
        boot_group = QGroupBox("Boot and firmware defaults")
        boot_form = self._form_layout(boot_group)

        self.boot_delay_spin = QSpinBox()
        self.boot_delay_spin.setRange(0, 10)
        self.boot_delay_spin.setSuffix(" s")
        self._add_form_row(boot_form, "start.elf delay:", self.boot_delay_spin)

        self.bootcode_delay_spin = QSpinBox()
        self.bootcode_delay_spin.setRange(0, 10)
        self.bootcode_delay_spin.setValue(1)
        self.bootcode_delay_spin.setSuffix(" s")
        self._add_form_row(boot_form, "bootcode.bin delay:", self.bootcode_delay_spin)

        self.avoid_warnings_combo = QComboBox()
        self.avoid_warnings_combo.addItem("Release default", None)
        self.avoid_warnings_combo.addItem("0 - show firmware warnings", 0)
        self.avoid_warnings_combo.addItem("1 - hide warning icons", 1)
        self.avoid_warnings_combo.addItem("2 - also ignore undervoltage throttling", 2)
        self._add_form_row(boot_form, "Firmware warnings:", self.avoid_warnings_combo)

        self.arm_boost_check = QCheckBox("arm_boost=1 for Pi 4 / CM4")
        self.arm_boost_check.setChecked(True)
        self._add_form_row(boot_form, "Pi 4 boost:", self.arm_boost_check)

        self.force_hdmi_check = QCheckBox("Force HDMI output without EDID")
        self.force_hdmi_check.setChecked(True)
        self._add_form_row(boot_form, "HDMI hotplug:", self.force_hdmi_check)

        return boot_group

    def _create_storage_group(self) -> QGroupBox:
        storage_group = QGroupBox("Storage")
        form = self._form_layout(storage_group)

        self.sd_unit_combo = QComboBox()
        for label, value in (("Off", "off"), ("Read only", "ro"), ("Read/write", "rw")):
            self.sd_unit_combo.addItem(label, value)
        self.sd_unit_combo.setCurrentIndex(2)
        self._add_form_row(form, "SD card unit 0:", self.sd_unit_combo)

        self.sd_low_speed_check = QCheckBox("Low speed")
        self.sd_low_speed_check.setChecked(True)
        self.sd_low_speed_check.toggled.connect(self._update_custom_fields)
        self.sd_low_speed_check.toggled.connect(self._sync_storage_timing_from_details)
        self._add_form_row(form, "SD card timing:", self.sd_low_speed_check)

        self.sd_clock_spin = QSpinBox()
        self.sd_clock_spin.setRange(0, 100)
        self.sd_clock_spin.setSpecialValueText("Default clock")
        self.sd_clock_spin.setSuffix(" MHz")
        self.sd_clock_spin.valueChanged.connect(self._sync_storage_timing_from_details)
        self._add_form_row(form, "SD card clock:", self.sd_clock_spin)

        self.emmc_unit_combo = QComboBox()
        for label, value in (("Off", "off"), ("Read only", "ro"), ("Read/write", "rw")):
            self.emmc_unit_combo.addItem(label, value)
        self.emmc_unit_combo.setCurrentIndex(2)
        self._add_form_row(form, "eMMC unit 0:", self.emmc_unit_combo)

        self.emmc_low_speed_check = QCheckBox("Low speed")
        self.emmc_low_speed_check.setChecked(True)
        self.emmc_low_speed_check.toggled.connect(self._update_custom_fields)
        self.emmc_low_speed_check.toggled.connect(self._sync_storage_timing_from_details)
        self._add_form_row(form, "eMMC timing:", self.emmc_low_speed_check)

        self.emmc_clock_spin = QSpinBox()
        self.emmc_clock_spin.setRange(0, 100)
        self.emmc_clock_spin.setSpecialValueText("Default clock")
        self.emmc_clock_spin.setSuffix(" MHz")
        self.emmc_clock_spin.valueChanged.connect(self._sync_storage_timing_from_details)
        self._add_form_row(form, "eMMC clock:", self.emmc_clock_spin)

        self.swap_df0_combo = QComboBox()
        self.swap_df0_combo.addItem("No swap", "none")
        self.swap_df0_combo.addItem("Swap DF0 with DF1", "df1")
        self.swap_df0_combo.addItem("Swap DF0 with DF2", "df2")
        self.swap_df0_combo.addItem("Swap DF0 with DF3", "df3")
        self._add_form_row(form, "Floppy drives:", self.swap_df0_combo)

        return storage_group

    def _create_cpu_group(self) -> QGroupBox:
        cpu_group = QGroupBox("CPU and memory")
        cpu_layout = QGridLayout(cpu_group)
        cpu_layout.setHorizontalSpacing(20)

        left_fields = QWidget()
        left_form = self._form_layout(left_fields)
        right_fields = QWidget()
        right_form = self._form_layout(right_fields)

        self.memory_limit_combo = QComboBox()
        self.memory_limit_combo.addItem("Release default", None)
        self.memory_limit_combo.addItem("No limit", 0)
        self.memory_limit_combo.addItem("Custom", "custom")
        self.memory_limit_combo.currentIndexChanged.connect(self._update_custom_fields)
        self.memory_limit_spin = QSpinBox()
        self.memory_limit_spin.setRange(128, 8192)
        self.memory_limit_spin.setValue(2048)
        self.memory_limit_spin.setSuffix(" MB")
        self._add_form_row(
            left_form,
            "Total RAM:",
            self._paired_field(self.memory_limit_combo, self.memory_limit_spin),
        )

        self.gpu_memory_combo = QComboBox()
        self.gpu_memory_combo.addItem("Release default", None)
        self.gpu_memory_combo.addItem("Omit gpu_mem", 0)
        self.gpu_memory_combo.addItem("Custom", "custom")
        self.gpu_memory_combo.currentIndexChanged.connect(self._update_custom_fields)
        self.gpu_memory_spin = QSpinBox()
        self.gpu_memory_spin.setRange(16, 512)
        self.gpu_memory_spin.setValue(32)
        self.gpu_memory_spin.setSuffix(" MB")
        self._add_form_row(
            left_form,
            "GPU memory:",
            self._paired_field(self.gpu_memory_combo, self.gpu_memory_spin),
        )

        self.cpu_turbo_combo = QComboBox()
        self.cpu_turbo_combo.addItem("Release default", "default")
        self.cpu_turbo_combo.addItem("Disabled", "disabled")
        self.cpu_turbo_combo.addItem("Enabled", "enabled")
        self.cpu_turbo_combo.currentIndexChanged.connect(self._update_custom_fields)
        self._add_form_row(left_form, "CPU tuning:", self.cpu_turbo_combo)

        compatibility = QWidget()
        compatibility_grid = QGridLayout(compatibility)
        compatibility_grid.setContentsMargins(0, 0, 0, 0)
        compatibility_grid.setHorizontalSpacing(12)
        self.vbr_move_check = QCheckBox("Move VBR to Fast RAM")
        self.no_fpu_check = QCheckBox("Disable FPU")
        self.limit_2g_check = QCheckBox("Limit ARM RAM to 2 GB")
        self.disable_z3_check = QCheckBox("Disable Zorro III")
        for index, check in enumerate(
            (
                self.vbr_move_check,
                self.no_fpu_check,
                self.limit_2g_check,
                self.disable_z3_check,
            )
        ):
            compatibility_grid.addWidget(check, index // 2, index % 2)
        self._add_form_row(left_form, "Compatibility:", compatibility)

        self.arm_freq_spin = QSpinBox()
        self.arm_freq_spin.setRange(600, 2400)
        self.arm_freq_spin.setValue(1800)
        self.arm_freq_spin.setSuffix(" MHz")
        self._add_form_row(right_form, "ARM frequency:", self.arm_freq_spin)

        self.over_voltage_spin = QSpinBox()
        self.over_voltage_spin.setRange(-16, 8)
        self.over_voltage_spin.setValue(4)
        self._add_form_row(right_form, "Over voltage:", self.over_voltage_spin)

        self.z2_ram_combo = QComboBox()
        self.z2_ram_combo.addItem("Default", None)
        for size in (0, 1, 2, 4, 8):
            self.z2_ram_combo.addItem(f"{size} MB", size)
        self._add_form_row(right_form, "Z2 RAM:", self.z2_ram_combo)

        self.vc4_memory_spin = QSpinBox()
        self.vc4_memory_spin.setRange(0, 256)
        self.vc4_memory_spin.setSingleStep(2)
        self.vc4_memory_spin.setSpecialValueText("Default")
        self.vc4_memory_spin.setSuffix(" MB")
        self._add_form_row(right_form, "VC4 memory:", self.vc4_memory_spin)

        cpu_layout.addWidget(left_fields, 0, 0)
        cpu_layout.addWidget(right_fields, 0, 1)
        cpu_layout.setColumnStretch(0, 1)
        cpu_layout.setColumnStretch(1, 1)
        return cpu_group

    def _create_emu68_compatibility_group(self) -> QGroupBox:
        compatibility_group = QGroupBox("Emu68 compatibility")
        form = self._form_layout(compatibility_group)

        compatibility = QWidget()
        compatibility_grid = QGridLayout(compatibility)
        compatibility_grid.setContentsMargins(0, 0, 0, 0)
        compatibility_grid.setHorizontalSpacing(12)
        self.fast_page_zero_check = QCheckBox("Fast page zero")
        self.chip_slowdown_check = QCheckBox("CHIP slowdown")
        self.chip_slowdown_check.toggled.connect(self._update_custom_fields)
        self.dbf_slowdown_check = QCheckBox("DBF slowdown")
        self.blitwait_check = QCheckBox("Blitter waits")
        for index, check in enumerate(
            (
                self.fast_page_zero_check,
                self.chip_slowdown_check,
                self.dbf_slowdown_check,
                self.blitwait_check,
            )
        ):
            compatibility_grid.addWidget(check, index // 2, index % 2)
        self._add_form_row(form, "Emu68 options:", compatibility)

        self.chip_distance_spin = QSpinBox()
        self.chip_distance_spin.setRange(1, 8)
        self.chip_distance_spin.setSuffix(" instruction(s)")
        self._add_form_row(form, "CHIP slowdown distance:", self.chip_distance_spin)

        self.bus_test_combo = QComboBox()
        self.bus_test_combo.addItem("Release default", "default")
        self.bus_test_combo.addItem("Disabled", "disabled")
        self.bus_test_combo.addItem("First boot", "first_boot")
        self.bus_test_combo.currentIndexChanged.connect(self._update_custom_fields)
        self._add_form_row(form, "PiStorm bus test:", self.bus_test_combo)

        self.bus_test_size_spin = QSpinBox()
        self.bus_test_size_spin.setRange(1, 2048)
        self.bus_test_size_spin.setValue(512)
        self.bus_test_size_spin.setSuffix(" KB")
        self._add_form_row(form, "Test size:", self.bus_test_size_spin)

        self.bus_test_iterations_spin = QSpinBox()
        self.bus_test_iterations_spin.setRange(1, 9)
        self.bus_test_iterations_spin.setValue(1)
        self._add_form_row(form, "Test iterations:", self.bus_test_iterations_spin)

        return compatibility_group

    def _create_framethrower_group(self) -> QGroupBox:
        framethrower_group = QGroupBox("Framethrower / Unicam")
        form = self._form_layout(framethrower_group)

        self.framethrower_check = QCheckBox("Enable Framethrower / Unicam")
        self.framethrower_check.toggled.connect(self._update_custom_fields)
        self._add_form_row(form, "Configuration:", self.framethrower_check)

        self.framethrower_boot_check = QCheckBox("Start on boot")
        self.framethrower_boot_check.setChecked(True)
        self._add_form_row(form, "Startup:", self.framethrower_boot_check)

        self.framethrower_scaling_combo = QComboBox()
        self.framethrower_scaling_combo.addItem("No scaling flag", "none")
        self.framethrower_scaling_combo.addItem("Smooth", "smooth")
        self.framethrower_scaling_combo.addItem("Integer / pixel perfect", "integer")
        self.framethrower_scaling_combo.setCurrentIndex(1)
        self.framethrower_scaling_combo.currentIndexChanged.connect(self._update_custom_fields)
        self._add_form_row(form, "Unicam scaling:", self.framethrower_scaling_combo)

        self.framethrower_note = QLabel(
            "Framethrower requires a VideoCore Workbench mode. "
            "For PAL, use a fixed 50 Hz HDMI mode."
        )
        self.framethrower_note.setWordWrap(True)
        form.addRow(self.framethrower_note)
        return framethrower_group

    def _create_framethrower_tuning_group(self) -> QGroupBox:
        tuning_group = QGroupBox("Framethrower tuning")
        form = self._form_layout(tuning_group)

        self.framethrower_b_spin = QSpinBox()
        self.framethrower_b_spin.setRange(0, 1000)
        self.framethrower_b_spin.setValue(200)
        self._add_form_row(form, "Smooth scaling B:", self.framethrower_b_spin)

        self.framethrower_c_spin = QSpinBox()
        self.framethrower_c_spin.setRange(0, 1000)
        self.framethrower_c_spin.setValue(400)
        self._add_form_row(form, "Smooth scaling C:", self.framethrower_c_spin)

        return tuning_group

    def _create_manual_overrides_group(self) -> QGroupBox:
        advanced_group = QGroupBox("Manual overrides")
        layout = self._form_layout(advanced_group)

        self.extra_config_edit = QPlainTextEdit()
        self.extra_config_edit.setPlaceholderText(
            "One config.txt directive per line (for example dtoverlay=...)"
        )
        self.extra_config_edit.setToolTip(
            "1.1 overlays: emu68 (args, ICNT, CCRD, IRNG, SC, SCS, FP0, BW, DBF), "
            "diagnostic (buptest, bupiter, bupsize, membench, membase, memsize), "
            "unicam (boot, smooth, integer, full_width, full_height, width, height, bpp, "
            "mode, x, y, b, c, scaler, phase, lanes, aspect, order, type, ftmode). "
            "Turn off the Framethrower controls before adding a complete unicam overlay."
        )
        self.extra_config_edit.setMaximumHeight(100)
        self._add_form_row(layout, "config.txt:", self.extra_config_edit)

        self.extra_cmdline_edit = QLineEdit()
        self.extra_cmdline_edit.setPlaceholderText(
            "Space-separated cmdline.txt tokens (for example async_log fast_serial)"
        )
        self.extra_cmdline_edit.setToolTip(
            "Other upstream tokens include sd.verbose, emmc.verbose, debug, disassemble, "
            "async_log, fast_serial, enable_cache, checksum_rom, copy_rom, enable_c0_slow, "
            "enable_c8_slow, enable_d0_slow, move_slow_to_chip, ICNT, CCRD, and IRNG."
        )
        self._add_form_row(layout, "cmdline.txt:", self.extra_cmdline_edit)
        return advanced_group

    def _create_advanced_dialog(self):
        self.advanced_dialog = QDialog(self)
        self.advanced_dialog.setWindowTitle("Advanced Boot Settings")
        self.advanced_dialog.resize(1050, 780)

        dialog_layout = QVBoxLayout(self.advanced_dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)
        content_layout.addWidget(self.version_note)

        top_groups = QGridLayout()
        top_groups.setContentsMargins(0, 0, 0, 0)
        top_groups.setHorizontalSpacing(10)
        top_groups.addWidget(self._create_boot_group(), 0, 0)
        top_groups.addWidget(self._create_storage_group(), 0, 1)
        top_groups.setColumnStretch(0, 1)
        top_groups.setColumnStretch(1, 1)
        content_layout.addLayout(top_groups)

        content_layout.addWidget(self._create_cpu_group())

        lower_groups = QGridLayout()
        lower_groups.setContentsMargins(0, 0, 0, 0)
        lower_groups.setHorizontalSpacing(10)
        lower_groups.addWidget(self._create_emu68_compatibility_group(), 0, 0)
        lower_groups.addWidget(self._create_framethrower_tuning_group(), 0, 1)
        lower_groups.setColumnStretch(0, 1)
        lower_groups.setColumnStretch(1, 1)
        content_layout.addLayout(lower_groups)

        content_layout.addWidget(self._create_manual_overrides_group())
        content_layout.addStretch()
        scroll.setWidget(content)
        dialog_layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.advanced_dialog.reject)
        dialog_layout.addWidget(buttons)

    def _show_advanced_settings(self):
        self.advanced_dialog.exec()

    def _apply_storage_timing_selection(self, _index=None):
        if getattr(self, "_syncing_storage_timing", False) or not hasattr(
            self, "sd_low_speed_check"
        ):
            return

        mode = self.storage_timing_combo.currentData()
        if mode == "custom":
            self._show_advanced_settings()
            self._sync_storage_timing_from_details()
            return
        if mode not in ("compatible", "standard"):
            return

        self._syncing_storage_timing = True
        low_speed = mode == "compatible"
        self.sd_low_speed_check.setChecked(low_speed)
        self.emmc_low_speed_check.setChecked(low_speed)
        self.sd_clock_spin.setValue(0)
        self.emmc_clock_spin.setValue(0)
        self._syncing_storage_timing = False
        self._update_custom_fields()

    def _sync_storage_timing_from_details(self, _value=None):
        if getattr(self, "_syncing_storage_timing", False) or not hasattr(
            self, "sd_low_speed_check"
        ):
            return

        if self.sd_low_speed_check.isChecked() and self.emmc_low_speed_check.isChecked():
            mode = "compatible"
        elif (
            not self.sd_low_speed_check.isChecked()
            and not self.emmc_low_speed_check.isChecked()
            and self.sd_clock_spin.value() == 0
            and self.emmc_clock_spin.value() == 0
        ):
            mode = "standard"
        else:
            mode = "custom"

        self._syncing_storage_timing = True
        select_combo_by_data(self.storage_timing_combo, mode)
        self._syncing_storage_timing = False

    def set_emu68_version(self, version: Emu68Version | str):
        self.emu68_version = version if isinstance(version, Emu68Version) else Emu68Version(version)
        is_11 = self.emu68_version == Emu68Version.V1_1_0_ALPHA_1

        if is_11:
            self.version_note.setText(
                "Emu68 1.1 writes compatibility, bus-test, and Framethrower settings "
                "as config.txt overlays."
            )
            defaults = ("2", "no limit", "omit", "enabled", "external", "disabled")
        else:
            self.version_note.setText(
                "Emu68 1.0.7 writes compatibility, bus-test, and Framethrower settings "
                "to cmdline.txt."
            )
            defaults = ("1", "2048 MB", "32 MB", "disabled", "internal", "first boot")

        warning, memory, gpu, turbo, antenna, bus_test = defaults
        self.avoid_warnings_combo.setItemText(0, f"Release default ({warning})")
        self.memory_limit_combo.setItemText(0, f"Release default ({memory})")
        self.gpu_memory_combo.setItemText(0, f"Release default ({gpu})")
        self.cpu_turbo_combo.setItemText(0, f"Release default ({turbo})")
        self.antenna_combo.setItemText(0, f"Release default ({antenna})")
        self.bus_test_combo.setItemText(0, f"Release default ({bus_test})")
        self._update_custom_fields()

    def set_rtg_mode_enabled(self, enabled: bool):
        self._rtg_mode_enabled = enabled
        if not enabled and self.framethrower_check.isChecked():
            self.framethrower_check.setChecked(False)
        self._update_custom_fields()

    def _update_custom_fields(self, _value=None):
        if not hasattr(self, "memory_limit_combo"):
            return
        self.memory_limit_spin.setEnabled(self.memory_limit_combo.currentData() == "custom")
        self.gpu_memory_spin.setEnabled(self.gpu_memory_combo.currentData() == "custom")
        cpu_custom = self.cpu_turbo_combo.currentData() == "enabled"
        self.arm_freq_spin.setEnabled(cpu_custom)
        self.over_voltage_spin.setEnabled(cpu_custom)
        self.sd_clock_spin.setEnabled(not self.sd_low_speed_check.isChecked())
        self.emmc_clock_spin.setEnabled(not self.emmc_low_speed_check.isChecked())
        self.chip_distance_spin.setEnabled(self.chip_slowdown_check.isChecked())
        is_11 = self.emu68_version == Emu68Version.V1_1_0_ALPHA_1
        default_bus_test = not is_11 and self.bus_test_combo.currentData() == "default"
        bus_test = self.bus_test_combo.currentData() == "first_boot" or default_bus_test
        self.bus_test_size_spin.setEnabled(bus_test)
        self.bus_test_iterations_spin.setEnabled(bus_test)
        if not self._rtg_mode_enabled and self.framethrower_check.isChecked():
            self.framethrower_check.setChecked(False)
        self.framethrower_check.setEnabled(self._rtg_mode_enabled)
        framethrower = self._rtg_mode_enabled and self.framethrower_check.isChecked()
        self.framethrower_boot_check.setEnabled(framethrower)
        self.framethrower_scaling_combo.setEnabled(framethrower)
        smooth = self.framethrower_scaling_combo.currentData() == "smooth"
        self.framethrower_b_spin.setEnabled(framethrower and smooth)
        self.framethrower_c_spin.setEnabled(framethrower and smooth)
        self.framethrower_note.setVisible(framethrower)

    @staticmethod
    def _optional_custom_value(combo: QComboBox, spin: QSpinBox) -> int | None:
        value = combo.currentData()
        return spin.value() if value == "custom" else value

    def get_settings(self) -> dict:
        return {
            "config_txt": {
                "boot_delay": self.boot_delay_spin.value(),
                "bootcode_delay": self.bootcode_delay_spin.value(),
                "avoid_warnings": self.avoid_warnings_combo.currentData(),
                "memory_limit_mb": self._optional_custom_value(
                    self.memory_limit_combo, self.memory_limit_spin
                ),
                "gpu_memory_mb": self._optional_custom_value(
                    self.gpu_memory_combo, self.gpu_memory_spin
                ),
                "cpu_turbo": self.cpu_turbo_combo.currentData(),
                "arm_freq_mhz": self.arm_freq_spin.value(),
                "over_voltage": self.over_voltage_spin.value(),
                "arm_boost_pi4": self.arm_boost_check.isChecked(),
                "force_hdmi": self.force_hdmi_check.isChecked(),
                "antenna": self.antenna_combo.currentData(),
                "framethrower": self.framethrower_check.isChecked(),
                "framethrower_start_on_boot": self.framethrower_boot_check.isChecked(),
                "framethrower_scaling": self.framethrower_scaling_combo.currentData(),
                "framethrower_b": self.framethrower_b_spin.value(),
                "framethrower_c": self.framethrower_c_spin.value(),
                "extra_lines": self.extra_config_edit.toPlainText().splitlines(),
            },
            "cmdline_txt": {
                "sd_unit0": self.sd_unit_combo.currentData(),
                "emmc_unit0": self.emmc_unit_combo.currentData(),
                "sd_low_speed": self.sd_low_speed_check.isChecked(),
                "emmc_low_speed": self.emmc_low_speed_check.isChecked(),
                "sd_clock_mhz": self.sd_clock_spin.value() or None,
                "emmc_clock_mhz": self.emmc_clock_spin.value() or None,
                "vbr_move": self.vbr_move_check.isChecked(),
                "fast_page_zero": self.fast_page_zero_check.isChecked(),
                "chip_slowdown": self.chip_slowdown_check.isChecked(),
                "chip_slowdown_distance": self.chip_distance_spin.value(),
                "dbf_slowdown": self.dbf_slowdown_check.isChecked(),
                "blitwait": self.blitwait_check.isChecked(),
                "no_fpu": self.no_fpu_check.isChecked(),
                "limit_2g": self.limit_2g_check.isChecked(),
                "disable_zorro3": self.disable_z3_check.isChecked(),
                "z2_ram_size_mb": self.z2_ram_combo.currentData(),
                "vc4_memory_mb": self.vc4_memory_spin.value() or None,
                "swap_df0": self.swap_df0_combo.currentData(),
                "bus_test": self.bus_test_combo.currentData(),
                "bus_test_size_kb": self.bus_test_size_spin.value(),
                "bus_test_iterations": self.bus_test_iterations_spin.value(),
                "extra_tokens": self.extra_cmdline_edit.text().split(),
            },
        }

    def set_settings(self, settings: Emu68BootSettings):
        config = settings.config_txt
        cmdline = settings.cmdline_txt
        self.boot_delay_spin.setValue(config.boot_delay)
        self.bootcode_delay_spin.setValue(config.bootcode_delay)
        select_combo_by_data(self.avoid_warnings_combo, config.avoid_warnings)

        if config.memory_limit_mb in (None, 0):
            select_combo_by_data(self.memory_limit_combo, config.memory_limit_mb)
        else:
            select_combo_by_data(self.memory_limit_combo, "custom")
            self.memory_limit_spin.setValue(config.memory_limit_mb)
        if config.gpu_memory_mb in (None, 0):
            select_combo_by_data(self.gpu_memory_combo, config.gpu_memory_mb)
        else:
            select_combo_by_data(self.gpu_memory_combo, "custom")
            self.gpu_memory_spin.setValue(config.gpu_memory_mb)

        select_combo_by_data(self.cpu_turbo_combo, config.cpu_turbo.value)
        self.arm_freq_spin.setValue(config.arm_freq_mhz)
        self.over_voltage_spin.setValue(config.over_voltage)
        self.arm_boost_check.setChecked(config.arm_boost_pi4)
        self.force_hdmi_check.setChecked(config.force_hdmi)
        select_combo_by_data(self.antenna_combo, config.antenna.value)
        self.framethrower_check.setChecked(config.framethrower)
        self.framethrower_boot_check.setChecked(config.framethrower_start_on_boot)
        select_combo_by_data(self.framethrower_scaling_combo, config.framethrower_scaling.value)
        self.framethrower_b_spin.setValue(config.framethrower_b)
        self.framethrower_c_spin.setValue(config.framethrower_c)
        self.extra_config_edit.setPlainText("\n".join(config.extra_lines))

        select_combo_by_data(self.sd_unit_combo, cmdline.sd_unit0.value)
        select_combo_by_data(self.emmc_unit_combo, cmdline.emmc_unit0.value)
        self.sd_low_speed_check.setChecked(cmdline.sd_low_speed)
        self.emmc_low_speed_check.setChecked(cmdline.emmc_low_speed)
        self.sd_clock_spin.setValue(cmdline.sd_clock_mhz or 0)
        self.emmc_clock_spin.setValue(cmdline.emmc_clock_mhz or 0)
        self.vbr_move_check.setChecked(cmdline.vbr_move)
        self.fast_page_zero_check.setChecked(cmdline.fast_page_zero)
        self.chip_slowdown_check.setChecked(cmdline.chip_slowdown)
        self.chip_distance_spin.setValue(cmdline.chip_slowdown_distance)
        self.dbf_slowdown_check.setChecked(cmdline.dbf_slowdown)
        self.blitwait_check.setChecked(cmdline.blitwait)
        self.no_fpu_check.setChecked(cmdline.no_fpu)
        self.limit_2g_check.setChecked(cmdline.limit_2g)
        self.disable_z3_check.setChecked(cmdline.disable_zorro3)
        select_combo_by_data(self.z2_ram_combo, cmdline.z2_ram_size_mb)
        self.vc4_memory_spin.setValue(cmdline.vc4_memory_mb or 0)
        select_combo_by_data(self.swap_df0_combo, cmdline.swap_df0.value)
        select_combo_by_data(self.bus_test_combo, cmdline.bus_test.value)
        self.bus_test_size_spin.setValue(cmdline.bus_test_size_kb)
        self.bus_test_iterations_spin.setValue(cmdline.bus_test_iterations)
        self.extra_cmdline_edit.setText(" ".join(cmdline.extra_tokens))
        self._sync_storage_timing_from_details()
        self._update_custom_fields()
