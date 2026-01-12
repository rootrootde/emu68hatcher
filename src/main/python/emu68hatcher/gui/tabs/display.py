"""
display configuration tab with HDMI output and icon set settings
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QComboBox,
    QSpinBox,
)

from emu68hatcher.config.schema import DisplayConfig


class DisplayTab(QWidget):
    """display configuration tab with HDMI output and icon set settings"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hdmi_modes = []
        self.icon_sets = []  # available icon sets for current KS version
        self._current_ks_version = "3.1"
        self.load_screen_modes()
        self.load_icon_sets()
        self.setup_ui()

    def load_screen_modes(self):
        """load HDMI screen modes from YAML"""
        try:
            from emu68hatcher.data.data_manager import load_yaml_data

            # load HDMI output modes (Pi screen modes)
            modes = load_yaml_data("screen_modes")
            self.hdmi_modes = [
                {
                    "name": r.get("name", ""),
                    "friendly": r.get("friendly_name", r.get("name", "")),
                }
                for r in modes
            ]

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

    def load_icon_sets(self, ks_version: str = "3.1"):
        """load available icon sets from YAML for a specific Kickstart version"""
        self._current_ks_version = ks_version
        self.icon_sets = []

        try:
            from emu68hatcher.data.data_manager import load_yaml_data

            rows = load_yaml_data("icon_sets")
            for r in rows:
                # check if this icon set applies to the current KS version
                versions = r.get("versions", [])
                if ks_version not in versions:
                    continue

                icon_set = {
                    "name": r.get("name", "Standard"),
                    "description": r.get("description", ""),
                    "default": r.get("default", False),
                }
                self.icon_sets.append(icon_set)

        except Exception:
            pass

        # fallback if no sets found
        if not self.icon_sets:
            self.icon_sets = [
                {"name": "Standard", "description": "Standard Icon set", "default": True},
            ]
            # add GlowIcons for 3.2.x
            if ks_version.startswith("3.2"):
                self.icon_sets.append({
                    "name": "GlowIcons",
                    "description": "Glow Icons for high color modes",
                    "default": True,
                })
                self.icon_sets[0]["default"] = False  # standard is not default for 3.2

    def update_icon_sets(self, ks_version: str):
        """update icon set dropdown when Kickstart version changes"""
        self.load_icon_sets(ks_version)

        if hasattr(self, "icon_set_combo"):
            self.icon_set_combo.clear()

            default_idx = 0
            for i, icon_set in enumerate(self.icon_sets):
                self.icon_set_combo.addItem(
                    f"{icon_set['name']} - {icon_set['description']}",
                    icon_set["name"]
                )
                if icon_set["default"]:
                    default_idx = i

            # always use the default for the new version
            self.icon_set_combo.setCurrentIndex(default_idx)

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # =================================================================
        # HDMI Output Mode (Pi's HDMI output to monitor)
        # =================================================================
        hdmi_group = QGroupBox("HDMI Output Mode (Pi → Monitor)")
        hdmi_layout = QVBoxLayout(hdmi_group)

        # HDMI mode dropdown
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
        custom_layout = QHBoxLayout(self.custom_res_widget)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.addWidget(QLabel("Width:"))
        self.hdmi_width_spin = QSpinBox()
        self.hdmi_width_spin.setRange(640, 1920)
        self.hdmi_width_spin.setValue(800)
        custom_layout.addWidget(self.hdmi_width_spin)
        custom_layout.addWidget(QLabel("Height:"))
        self.hdmi_height_spin = QSpinBox()
        self.hdmi_height_spin.setRange(480, 1200)
        self.hdmi_height_spin.setValue(600)
        custom_layout.addWidget(self.hdmi_height_spin)
        custom_layout.addWidget(QLabel("Hz:"))
        self.hdmi_hz_spin = QSpinBox()
        self.hdmi_hz_spin.setRange(50, 75)
        self.hdmi_hz_spin.setValue(60)
        custom_layout.addWidget(self.hdmi_hz_spin)
        custom_layout.addStretch()
        self.custom_res_widget.setVisible(False)
        hdmi_layout.addWidget(self.custom_res_widget)

        layout.addWidget(hdmi_group)

        # =================================================================
        # icon Set
        # =================================================================
        icon_group = QGroupBox("Icon Set")
        icon_layout = QVBoxLayout(icon_group)

        icon_h = QHBoxLayout()
        icon_h.addWidget(QLabel("Icons:"))
        self.icon_set_combo = QComboBox()
        self.icon_set_combo.setMinimumWidth(300)

        # populate with available icon sets
        default_idx = 0
        for i, icon_set in enumerate(self.icon_sets):
            self.icon_set_combo.addItem(
                f"{icon_set['name']} - {icon_set['description']}",
                icon_set["name"]
            )
            if icon_set["default"]:
                default_idx = i
        self.icon_set_combo.setCurrentIndex(default_idx)

        icon_h.addWidget(self.icon_set_combo)
        icon_h.addStretch()
        icon_layout.addLayout(icon_h)

        # info label
        icon_info = QLabel("GlowIcons are recommended for high color displays.")
        icon_info.setStyleSheet("color: gray; font-size: 11px;")
        icon_layout.addWidget(icon_info)

        layout.addWidget(icon_group)

        layout.addStretch()

    def on_hdmi_mode_changed(self, index):
        """show/hide custom resolution controls based on selection"""
        mode_name = self.hdmi_mode_combo.currentData()
        self.custom_res_widget.setVisible(mode_name == "Custom")

    def get_config(self) -> dict:
        """get display configuration as dict"""
        # get HDMI mode
        hdmi_mode_name = self.hdmi_mode_combo.currentData() or "1280*720-50"

        # get custom CVT if needed
        custom_cvt = ""
        if hdmi_mode_name == "Custom":
            custom_cvt = f"{self.hdmi_width_spin.value()} {self.hdmi_height_spin.value()} {self.hdmi_hz_spin.value()}"

        return {
            # HDMI output settings
            "hdmi_mode": hdmi_mode_name,
            "custom_cvt": custom_cvt,
            # icon set
            "icon_set": self.icon_set_combo.currentData() or "Standard",
            # legacy fields for compatibility
            "screen_mode": "PAL" if "50" in hdmi_mode_name else "NTSC",
            "width": self.hdmi_width_spin.value(),
            "height": self.hdmi_height_spin.value(),
        }

    def set_config(self, config: DisplayConfig):
        """populate the tab from config object"""
        # set HDMI mode
        hdmi_mode = config.hdmi_mode or "1280*720-50"
        for i in range(self.hdmi_mode_combo.count()):
            if self.hdmi_mode_combo.itemData(i) == hdmi_mode:
                self.hdmi_mode_combo.setCurrentIndex(i)
                break

        # set custom resolution if applicable
        if config.custom:
            self.hdmi_width_spin.setValue(config.custom.width)
            self.hdmi_height_spin.setValue(config.custom.height)
            self.hdmi_hz_spin.setValue(config.custom.framerate)

    def set_icon_set(self, icon_set_name: str):
        """set the icon set dropdown to a specific value"""
        for i in range(self.icon_set_combo.count()):
            if self.icon_set_combo.itemData(i) == icon_set_name:
                self.icon_set_combo.setCurrentIndex(i)
                return
        # if not found, leave at default
