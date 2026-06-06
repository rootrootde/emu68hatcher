"""Emu68 tab - boot config: Emu68 release version + HDMI output mode"""

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import (
    DisplayConfig,
    Emu68Version,
)
from emu68hatcher.gui.widgets import select_combo_by_data


class Emu68Tab(QWidget):
    """Pi-side boot configuration: Emu68 release + HDMI output mode + custom resolution"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hdmi_modes = []
        self.load_screen_modes()
        self.setup_ui()

    def load_screen_modes(self):
        """load HDMI screen modes from YAML"""
        try:
            from emu68hatcher.data.data_manager import load_yaml_data

            modes = load_yaml_data("screen_modes")
            self.hdmi_modes = [
                {
                    "name": r.get("name", ""),
                    "friendly": r.get("friendly_name", r.get("name", "")),
                }
                for r in modes
            ]
            self.hdmi_modes.append({"name": "Custom", "friendly": "Custom Resolution"})
        except Exception:
            # fallback defaults
            self.hdmi_modes = [
                {"name": "Auto", "friendly": "Automatic"},
                {"name": "1280*720-50", "friendly": "720p 50Hz (PAL)"},
                {"name": "1280*720-60", "friendly": "720p 60Hz (NTSC)"},
                {"name": "1920*1080-50", "friendly": "1080p 50Hz"},
                {"name": "1920*1080-60", "friendly": "1080p 60Hz"},
                {"name": "Custom", "friendly": "Custom Resolution"},
            ]

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Emu68 release picker (radios)
        release_group = QGroupBox("Emu68 release")
        release_layout = QVBoxLayout(release_group)

        self.release_button_group = QButtonGroup(self)
        self.release_radio_stable = QRadioButton("1.0.7 (stable)")
        self.release_radio_alpha = QRadioButton("1.1.0-alpha.1")
        self.release_radio_stable.setChecked(True)
        self.release_button_group.addButton(self.release_radio_stable)
        self.release_button_group.addButton(self.release_radio_alpha)
        release_layout.addWidget(self.release_radio_stable)
        release_layout.addWidget(self.release_radio_alpha)

        layout.addWidget(release_group)

        # HDMI output mode (Pi -> monitor, written to config.txt)
        hdmi_group = QGroupBox("HDMI Output Mode (Pi - Monitor)")
        hdmi_layout = QVBoxLayout(hdmi_group)

        hdmi_h = QHBoxLayout()
        hdmi_h.addWidget(QLabel("Output Mode:"))
        self.hdmi_mode_combo = QComboBox()
        for mode in self.hdmi_modes:
            self.hdmi_mode_combo.addItem(mode["friendly"], mode["name"])
        # default to 720p50
        for i, mode in enumerate(self.hdmi_modes):
            if "720" in mode["friendly"] and "50" in mode["friendly"]:
                self.hdmi_mode_combo.setCurrentIndex(i)
                break
        self.hdmi_mode_combo.currentIndexChanged.connect(self.on_hdmi_mode_changed)
        hdmi_h.addWidget(self.hdmi_mode_combo)
        hdmi_h.addStretch()
        hdmi_layout.addLayout(hdmi_h)

        # custom resolution (shown only when Custom selected)
        self.custom_res_widget = QWidget()
        custom_outer = QVBoxLayout(self.custom_res_widget)
        custom_outer.setContentsMargins(0, 0, 0, 0)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Width:"))
        self.hdmi_width_spin = QSpinBox()
        self.hdmi_width_spin.setRange(640, 1920)
        self.hdmi_width_spin.setValue(800)
        size_row.addWidget(self.hdmi_width_spin)
        size_row.addWidget(QLabel("Height:"))
        self.hdmi_height_spin = QSpinBox()
        self.hdmi_height_spin.setRange(480, 1200)
        self.hdmi_height_spin.setValue(600)
        size_row.addWidget(self.hdmi_height_spin)
        size_row.addWidget(QLabel("Hz:"))
        self.hdmi_hz_spin = QSpinBox()
        self.hdmi_hz_spin.setRange(50, 75)
        self.hdmi_hz_spin.setValue(60)
        size_row.addWidget(self.hdmi_hz_spin)
        size_row.addStretch()
        custom_outer.addLayout(size_row)

        cvt_row = QHBoxLayout()
        cvt_row.addWidget(QLabel("Aspect:"))
        self.hdmi_aspect_combo = QComboBox()
        for value, label in (
            (3, "16:9"),
            (1, "4:3"),
            (2, "14:9"),
            (4, "5:4"),
            (5, "16:10"),
            (6, "15:9"),
        ):
            self.hdmi_aspect_combo.addItem(label, value)
        cvt_row.addWidget(self.hdmi_aspect_combo)
        cvt_row.addWidget(QLabel("Margins:"))
        self.hdmi_margins_combo = QComboBox()
        self.hdmi_margins_combo.addItem("Disabled", False)
        self.hdmi_margins_combo.addItem("Enabled", True)
        cvt_row.addWidget(self.hdmi_margins_combo)
        cvt_row.addWidget(QLabel("Scan:"))
        self.hdmi_interlace_combo = QComboBox()
        self.hdmi_interlace_combo.addItem("Progressive", False)
        self.hdmi_interlace_combo.addItem("Interlace", True)
        cvt_row.addWidget(self.hdmi_interlace_combo)
        cvt_row.addWidget(QLabel("Blanking:"))
        self.hdmi_rb_combo = QComboBox()
        self.hdmi_rb_combo.addItem("Normal", False)
        self.hdmi_rb_combo.addItem("Reduced", True)
        cvt_row.addWidget(self.hdmi_rb_combo)
        cvt_row.addStretch()
        custom_outer.addLayout(cvt_row)

        self.custom_res_widget.setVisible(False)
        hdmi_layout.addWidget(self.custom_res_widget)

        layout.addWidget(hdmi_group)

        layout.addStretch()

    def on_hdmi_mode_changed(self, index):
        """show/hide custom resolution controls based on selection"""
        mode_name = self.hdmi_mode_combo.currentData()
        self.custom_res_widget.setVisible(mode_name == "Custom")

    def get_emu68_version(self) -> Emu68Version:
        """which Emu68 release radio is checked"""
        if self.release_radio_alpha.isChecked():
            return Emu68Version.V1_1_0_ALPHA_1
        return Emu68Version.V1_0_7

    def set_emu68_version(self, version: Emu68Version):
        """flip the matching radio when loading a config"""
        if version == Emu68Version.V1_1_0_ALPHA_1:
            self.release_radio_alpha.setChecked(True)
        else:
            self.release_radio_stable.setChecked(True)

    def get_config(self) -> dict:
        """display config (HDMI mode + custom resolution)"""
        hdmi_mode_name = self.hdmi_mode_combo.currentData() or "1280*720-50"
        return {
            "hdmi_mode": hdmi_mode_name,
            "width": self.hdmi_width_spin.value(),
            "height": self.hdmi_height_spin.value(),
            "framerate": self.hdmi_hz_spin.value(),
            "aspect_ratio": self.hdmi_aspect_combo.currentData(),
            "margins": self.hdmi_margins_combo.currentData(),
            "interlace": self.hdmi_interlace_combo.currentData(),
            "reduced_blanking": self.hdmi_rb_combo.currentData(),
        }

    def set_config(self, config: DisplayConfig):
        """populate the HDMI fields from a config object"""
        hdmi_mode = config.hdmi_mode or "1280*720-50"
        select_combo_by_data(self.hdmi_mode_combo, hdmi_mode)
        if config.custom:
            self.hdmi_width_spin.setValue(config.custom.width)
            self.hdmi_height_spin.setValue(config.custom.height)
            self.hdmi_hz_spin.setValue(config.custom.framerate)
            select_combo_by_data(self.hdmi_aspect_combo, config.custom.aspect_ratio)
            select_combo_by_data(self.hdmi_margins_combo, config.custom.margins)
            select_combo_by_data(self.hdmi_interlace_combo, config.custom.interlace)
            select_combo_by_data(self.hdmi_rb_combo, config.custom.reduced_blanking)
