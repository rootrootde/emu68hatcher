"""package selection tab - loads packages from YAML defs"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import NetworkStack, PackageConfig, WifiConfig
from emu68hatcher.data.package_loader import (
    get_bundle_members,
    get_bundles_for_version,
    get_package_by_name,
    get_packages_for_version,
)
from emu68hatcher.data.package_schema import Bundle, Package

# packages controlled by the network stack radio buttons (hidden from checkbox list)
_NETWORK_STACK_PACKAGES = {"roadshow"}


class PackagesTab(QWidget):
    """package selection tab that loads packages from YAML definitions"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkboxes: dict[str, QTreeWidgetItem] = {}
        self.kickstart_version = "3.2.3"  # set a default version
        self._selectables: list[tuple[str, Bundle | Package]] = []
        self._key_to_packages: dict[str, list[str]] = {}
        self.icon_sets: list[dict] = []
        self._load_icon_sets(self.kickstart_version)
        self.setup_ui()

    def _load_icon_sets(self, ks_version: str):
        """load available icon sets from YAML for the given Kickstart version"""
        self.icon_sets = []
        try:
            from emu68hatcher.data.data_manager import load_yaml_data

            for r in load_yaml_data("icon_sets"):
                versions = r.get("versions", [])
                if ks_version not in versions:
                    continue
                self.icon_sets.append(
                    {
                        "name": r.get("name", "Standard"),
                        "description": r.get("description", ""),
                        "default": r.get("default", False),
                    }
                )
        except Exception:
            pass

        if not self.icon_sets:
            self.icon_sets = [
                {"name": "Standard", "description": "Standard Icon set", "default": True},
            ]
            if ks_version.startswith("3.2"):
                self.icon_sets.append(
                    {
                        "name": "GlowIcons",
                        "description": "Glow Icons for high color modes",
                        "default": True,
                    }
                )
                self.icon_sets[0]["default"] = False

    def setup_ui(self):
        """set up the UI layout"""
        layout = QVBoxLayout(self)

        # icon set selection
        icon_group = QGroupBox("Icon Set")
        icon_layout = QHBoxLayout(icon_group)
        icon_layout.addWidget(QLabel("Icons:"))
        self.icon_set_combo = QComboBox()
        self.icon_set_combo.setMinimumWidth(200)
        self.icon_set_combo.setToolTip("GlowIcons recommended for high color displays")
        self._populate_icon_set_combo()
        icon_layout.addWidget(self.icon_set_combo)
        icon_layout.addStretch()
        layout.addWidget(icon_group)

        # network stack selection (radio buttons)
        net_group = QGroupBox("Network Stack")
        net_layout = QVBoxLayout(net_group)
        self.radio_none = QRadioButton("None")
        self.radio_roadshow = QRadioButton("Roadshow")
        self.radio_roadshow.setChecked(True)
        self.radio_none.setToolTip("No network stack - no online connectivity")
        self.radio_roadshow.setToolTip(
            "Roadshow demo - free TCP/IP stack wiht PiStorm network support"
        )
        net_layout.addWidget(self.radio_none)

        # suppress the macOS-style extra layout margins around radio buttons
        self.radio_roadshow.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        roadshow_row = QHBoxLayout()
        roadshow_row.setContentsMargins(0, 0, 0, 0)
        roadshow_row.setSpacing(6)
        roadshow_row.addWidget(self.radio_roadshow)
        roadshow_pkg = get_package_by_name("roadshow")
        if roadshow_pkg and roadshow_pkg.purchase_url:
            demo_label = QLabel(
                f"(Demo version - buy the full version "
                f'<a href="{roadshow_pkg.purchase_url}">here</a>)'
            )
            demo_label.setTextFormat(Qt.TextFormat.RichText)
            demo_label.setOpenExternalLinks(True)
        else:
            demo_label = QLabel("(Demo version)")
        roadshow_row.addWidget(demo_label)
        roadshow_row.addStretch()
        net_layout.addLayout(roadshow_row)

        # WiFi credentials (optional - only shown when a network stack is selected)
        self._wifi_box = QWidget()
        wifi_layout = QHBoxLayout(self._wifi_box)
        wifi_layout.setContentsMargins(0, 0, 0, 0)
        wifi_layout.addWidget(QLabel("WiFi SSID:"))
        self.wifi_ssid = QLineEdit()
        self.wifi_ssid.setPlaceholderText("leave empty to skip")
        self.wifi_ssid.setMaxLength(32)
        wifi_layout.addWidget(self.wifi_ssid)
        wifi_layout.addWidget(QLabel("password:"))
        self.wifi_password = QLineEdit()
        self.wifi_password.setPlaceholderText("min 8 characters")
        self.wifi_password.setMaxLength(63)
        self.wifi_password.setEchoMode(QLineEdit.EchoMode.Password)
        wifi_layout.addWidget(self.wifi_password)

        net_layout.addWidget(self._wifi_box)

        self.radio_none.toggled.connect(self._update_wifi_visibility)
        self._update_wifi_visibility()

        layout.addWidget(net_group)

        # quick action buttons
        btn_layout = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(self.select_all)
        select_none = QPushButton("Select None")
        select_none.clicked.connect(self.select_none)
        defaults = QPushButton("Defaults")
        defaults.clicked.connect(self.select_defaults)
        btn_layout.addWidget(select_all)
        btn_layout.addWidget(select_none)
        btn_layout.addWidget(defaults)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # package tree
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Package", "Description"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)

        # load packages
        self.refresh_packages()

    def refresh_packages(self):
        """reload selectable items (bundles + standalone packages) for current Kickstart version"""
        self.checkboxes.clear()
        self.tree.clear()

        # tree row keys: bundle.id for bundles, package.name for standalones
        self._selectables: list[tuple[str, Bundle | Package]] = []
        self._key_to_packages: dict[str, list[str]] = {}

        # standalone packages (not in a bundle, not mandatory, not a network stack)
        for p in get_packages_for_version(self.kickstart_version):
            if not p.group or p.group == "System":
                continue
            if p.mandatory:
                continue  # installed unconditionally by teh build pipeline
            if p.bundle:
                continue  # surfaced via its bundle
            if p.name in _NETWORK_STACK_PACKAGES:
                continue  # surfaced via the radio buttons
            self._selectables.append((p.name, p))
            self._key_to_packages[p.name] = [p.name]

        # bundles
        for b in get_bundles_for_version(self.kickstart_version):
            members = get_bundle_members(b.id, self.kickstart_version)
            if not members:
                continue
            # bundle id may clash with a package name; prefix on collision
            key = b.id if b.id not in self._key_to_packages else f"bundle:{b.id}"
            self._selectables.append((key, b))
            self._key_to_packages[key] = [m.name for m in members]

        # build UI
        groups: dict[str, list[tuple[str, Bundle | Package]]] = {}
        for key, item in self._selectables:
            groups.setdefault(item.group, []).append((key, item))

        bold_font = QFont()
        bold_font.setBold(True)

        for group_name in sorted(groups.keys()):
            group_item = QTreeWidgetItem(self.tree, [group_name, ""])
            group_item.setFont(0, bold_font)
            group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            group_item.setExpanded(True)

            def _label(item: Bundle | Package) -> str:
                return (
                    item.display_name
                    if isinstance(item, Bundle)
                    else (item.friendly_name or item.name)
                )

            for key, item in sorted(groups[group_name], key=lambda e: _label(e[1]).lower()):
                child = QTreeWidgetItem(group_item, [_label(item), item.description or ""])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(
                    0, Qt.CheckState.Checked if item.default else Qt.CheckState.Unchecked
                )
                self.checkboxes[key] = child

    def set_kickstart_version(self, version: str):
        """update packages + icon sets when Kickstart version changes"""
        if version != self.kickstart_version:
            self.kickstart_version = version
            self.refresh_packages()
            self._load_icon_sets(version)
            self._populate_icon_set_combo()

    def _populate_icon_set_combo(self):
        """fill the icon set dropdown from self.icon_sets, picking the default"""
        self.icon_set_combo.clear()
        default_idx = 0
        for i, icon_set in enumerate(self.icon_sets):
            self.icon_set_combo.addItem(icon_set["name"], icon_set["name"])
            if icon_set["default"]:
                default_idx = i
        self.icon_set_combo.setCurrentIndex(default_idx)

    def get_icon_set(self) -> str:
        """selected icon set name"""
        return self.icon_set_combo.currentData() or "Standard"

    def set_icon_set(self, icon_set_name: str):
        """set the icon set dropdown to a specific value"""
        for i in range(self.icon_set_combo.count()):
            if self.icon_set_combo.itemData(i) == icon_set_name:
                self.icon_set_combo.setCurrentIndex(i)
                return

    def select_all(self):
        """select all packages"""
        for item in self.checkboxes.values():
            item.setCheckState(0, Qt.CheckState.Checked)

    def select_none(self):
        """deselect all packages"""
        for item in self.checkboxes.values():
            item.setCheckState(0, Qt.CheckState.Unchecked)

    def select_defaults(self):
        """reset to default selections"""
        for key, item in self._selectables:
            if key in self.checkboxes:
                self.checkboxes[key].setCheckState(
                    0, Qt.CheckState.Checked if item.default else Qt.CheckState.Unchecked
                )

    def get_network_stack(self) -> NetworkStack | None:
        """get the selected network stack, or None if disabled"""
        if self.radio_none.isChecked():
            return None
        return NetworkStack.ROADSHOW

    def set_network_stack(self, stack: NetworkStack | None):
        """set the network stack radio button"""
        if stack is None:
            self.radio_none.setChecked(True)
        else:
            self.radio_roadshow.setChecked(True)

    def _update_wifi_visibility(self):
        """hide WiFi fields when no network stack is selected"""
        self._wifi_box.setVisible(not self.radio_none.isChecked())

    def get_wifi_config(self) -> WifiConfig | None:
        """get WiFi config from text fields, or None if incomplete"""
        ssid = self.wifi_ssid.text().strip()
        password = self.wifi_password.text().strip()
        if not ssid or len(password) < 8:
            return None
        return WifiConfig(ssid=ssid, password=password)

    def set_wifi_config(self, wifi: WifiConfig | None):
        """populate WiFi fields from config"""
        if wifi:
            self.wifi_ssid.setText(wifi.ssid)
            self.wifi_password.setText(wifi.password)
        else:
            self.wifi_ssid.clear()
            self.wifi_password.clear()

    def get_config(self) -> list:
        """current selections + network stack; bundles expand to member names so persisted config stays flat"""
        result = []
        for key, widget in self.checkboxes.items():
            enabled = widget.checkState(0) == Qt.CheckState.Checked
            for pkg_name in self._key_to_packages.get(key, [key]):
                result.append({"name": pkg_name, "enabled": enabled})

        # add the selected network stack package (if any)
        stack = self.get_network_stack()
        if stack is not None:
            result.append({"name": "roadshow", "enabled": True})
        return result

    def set_config(self, packages: list[PackageConfig]):
        """populate from config; partial bundle state is intentionally collapsed to 'on'"""
        pkg_enabled = {p.name: p.enabled for p in packages}

        # reverse lookup: package name -> checkbox key
        pkg_to_key: dict[str, str] = {}
        for key, pkg_names in self._key_to_packages.items():
            for pkg_name in pkg_names:
                pkg_to_key[pkg_name] = key

        # collapse to per-key state: any member enabled flips the whole bundle on
        key_enabled: dict[str, bool] = {}
        for pkg_name, enabled in pkg_enabled.items():
            key = pkg_to_key.get(pkg_name)
            if key is None:
                continue
            key_enabled[key] = key_enabled.get(key, False) or enabled

        for key, enabled in key_enabled.items():
            if key in self.checkboxes:
                self.checkboxes[key].setCheckState(
                    0, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
                )
