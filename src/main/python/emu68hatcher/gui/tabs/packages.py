"""
package selection tab - loads packages dynamically from YAML definitions
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QCheckBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QFrame,
    QLabel,
)
from PySide6.QtCore import Qt

from emu68hatcher.config.schema import NetworkStack, PackageConfig
from emu68hatcher.data.package_loader import get_packages_for_version
from emu68hatcher.data.package_schema import Package

# packages controlled by the network stack radio buttons (hidden from checkbox list)
_NETWORK_STACK_PACKAGES = {"roadshow"}


class PackagesTab(QWidget):
    """package selection tab that loads packages from YAML definitions"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkboxes: dict[str, QCheckBox] = {}
        self.kickstart_version = "3.2.3"
        self._packages: list[Package] = []
        self.setup_ui()

    def setup_ui(self):
        """set up the UI layout"""
        layout = QVBoxLayout(self)

        # network stack selection (radio buttons)
        net_group = QGroupBox("Network Stack")
        net_layout = QVBoxLayout(net_group)
        net_layout.addWidget(QLabel("TCP/IP stack for online connectivity:"))
        self.radio_none = QRadioButton("None")
        self.radio_roadshow = QRadioButton("Roadshow (demo, recommended)")
        self.radio_roadshow.setChecked(True)
        self.radio_none.setToolTip("No network stack - no online connectivity")
        self.radio_roadshow.setToolTip("Roadshow demo - free TCP/IP stack with PiStorm network support")
        net_layout.addWidget(self.radio_none)
        net_layout.addWidget(self.radio_roadshow)
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

        # scrollable area for packages
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll)

        # load packages
        self.refresh_packages()

    def refresh_packages(self):
        """reload packages for current Kickstart version"""
        # clear existing checkboxes
        self.checkboxes.clear()

        # clear layout
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # load packages for version from YAML definitions
        all_packages = get_packages_for_version(self.kickstart_version)

        # skip "System" group (mandatory, not user-selectable)
        # skip network stack packages (controlled by radio buttons above)
        # group packages that share a friendly_name under one checkbox
        self._packages = []
        # maps display_name -> list of package names that share that checkbox
        self._display_to_packages: dict[str, list[str]] = {}

        for p in all_packages:
            if not p.group or p.group == "System":
                continue
            if p.name in _NETWORK_STACK_PACKAGES:
                continue
            self._packages.append(p)
            display_name = p.friendly_name or p.name
            if display_name not in self._display_to_packages:
                self._display_to_packages[display_name] = []
            self._display_to_packages[display_name].append(p.name)

        # build UI - one checkbox per unique display_name
        groups: dict[str, list[tuple[str, Package]]] = {}
        seen_display: set[str] = set()
        for pkg in self._packages:
            display_name = pkg.friendly_name or pkg.name
            if display_name in seen_display:
                continue
            seen_display.add(display_name)
            if pkg.group not in groups:
                groups[pkg.group] = []
            groups[pkg.group].append((display_name, pkg))

        for group_name in sorted(groups.keys()):
            entries = groups[group_name]

            group_box = QGroupBox(group_name)
            group_layout = QVBoxLayout(group_box)

            for display_name, pkg in sorted(entries, key=lambda e: e[0]):
                cb = QCheckBox(display_name)
                cb.setChecked(pkg.default)

                if pkg.description:
                    cb.setToolTip(pkg.description)

                # store checkbox under display_name (not pkg.name)
                self.checkboxes[display_name] = cb
                group_layout.addWidget(cb)

            self.scroll_layout.addWidget(group_box)

        self.scroll_layout.addStretch()

    def set_kickstart_version(self, version: str):
        """update packages when Kickstart version changes"""
        if version != self.kickstart_version:
            self.kickstart_version = version
            self.refresh_packages()

    def select_all(self):
        """select all packages"""
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def select_none(self):
        """deselect all packages"""
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def select_defaults(self):
        """reset to default selections"""
        seen = set()
        for pkg in self._packages:
            display_name = pkg.friendly_name or pkg.name
            if display_name in seen:
                continue
            seen.add(display_name)
            if display_name in self.checkboxes:
                self.checkboxes[display_name].setChecked(pkg.default)

    def get_network_stack(self) -> Optional[NetworkStack]:
        """get the selected network stack, or None if disabled"""
        if self.radio_none.isChecked():
            return None
        return NetworkStack.ROADSHOW

    def set_network_stack(self, stack: Optional[NetworkStack]):
        """set the network stack radio button"""
        if stack is None:
            self.radio_none.setChecked(True)
        else:
            self.radio_roadshow.setChecked(True)

    def get_config(self) -> list:
        """get current package selections, including the selected network stack

        expands display-name checkboxes back to individual package names,
        so packages like DirectoryOpus (dopus418 + dopusedit +
        directoryopus_cfg) all get enabled/disabled together.
        """
        result = []
        for display_name, cb in self.checkboxes.items():
            enabled = cb.isChecked()
            pkg_names = self._display_to_packages.get(display_name, [display_name])
            for pkg_name in pkg_names:
                result.append({"name": pkg_name, "enabled": enabled})

        # add the selected network stack package (if any)
        stack = self.get_network_stack()
        if stack is not None:
            result.append({"name": "roadshow", "enabled": True})
        return result

    def set_config(self, packages: list[PackageConfig]):
        """populate the tab from config object"""
        pkg_enabled = {p.name: p.enabled for p in packages}

        # reverse lookup: find the display_name for each package name
        pkg_to_display = {}
        for display_name, pkg_names in self._display_to_packages.items():
            for pkg_name in pkg_names:
                pkg_to_display[pkg_name] = display_name

        for pkg_name, enabled in pkg_enabled.items():
            display_name = pkg_to_display.get(pkg_name, pkg_name)
            if display_name in self.checkboxes:
                self.checkboxes[display_name].setChecked(enabled)
