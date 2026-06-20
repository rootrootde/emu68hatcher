"""package selection tab - loads packages from YAML defs"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import PackageConfig
from emu68hatcher.data.package_loader import (
    get_bundle_members,
    get_bundles_for_version,
    get_packages_for_version,
)
from emu68hatcher.data.package_schema import Bundle, Package

# packages controlled by the network stack radio (Network tab), hidden from the tree
_NETWORK_STACK_PACKAGES = {"roadshow"}

# groups not shown in the tree: System is mandatory infra (mui handled specially);
# Locale is the language grid on the Amiga Files tab
_HIDDEN_GROUPS = {"System", "Locale"}


class PackagesTab(QWidget):
    """package selection tab that loads packages from YAML definitions"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkboxes: dict[str, QTreeWidgetItem] = {}
        self.kickstart_version = "3.2.3"  # set a default version
        self._selectables: list[tuple[str, Bundle | Package]] = []
        self._key_to_packages: dict[str, list[str]] = {}
        self._updating = False  # reentrancy guard for the mui mutual-exclusion handler
        self.setup_ui()

    def setup_ui(self):
        """set up the UI layout"""
        layout = QVBoxLayout(self)

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
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        # load packages
        self.refresh_packages()

    def refresh_packages(self):
        """reload selectable items (bundles + standalone packages) for current Kickstart version"""
        # silence the mui handler while the tree is rebuilt (setCheckState fires itemChanged)
        self._updating = True
        try:
            self._refresh_packages()
        finally:
            self._updating = False

    def _refresh_packages(self):
        self.checkboxes.clear()
        self.tree.clear()

        # tree row keys: bundle.id for bundles, package.name for standalones
        self._selectables: list[tuple[str, Bundle | Package]] = []
        self._key_to_packages: dict[str, list[str]] = {}

        # standalone packages (not in a bundle, not mandatory, not a network stack)
        for p in get_packages_for_version(self.kickstart_version):
            if not p.group or p.group in _HIDDEN_GROUPS:
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

        self._add_mui_group(bold_font)

    def _add_mui_group(self, bold_font: QFont):
        """mui38/mui5 as two mutually-exclusive rows (they're group:System, so not in the tree)"""
        from emu68hatcher.data.package_loader import get_package_by_name

        group_item = QTreeWidgetItem(self.tree, ["MUI Toolkit", "pick one MUI version"])
        group_item.setFont(0, bold_font)
        group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        group_item.setExpanded(True)
        for name, label in (("mui38", "MUI 3.8"), ("mui5", "MUI 5.0")):
            pkg = get_package_by_name(name)
            child = QTreeWidgetItem(group_item, [label, pkg.description if pkg else ""])
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # mui38 default-checked; exactly one is always on (the radio's old invariant)
            on = name == "mui38"
            child.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self.checkboxes[name] = child
            self._key_to_packages[name] = [name]

    def _on_item_changed(self, item, column):
        """keep exactly one of mui38/mui5 checked (a radio built from two checkboxes)"""
        if self._updating or column != 0:
            return
        mui38 = self.checkboxes.get("mui38")
        mui5 = self.checkboxes.get("mui5")
        if item is not mui38 and item is not mui5:
            return
        self._updating = True
        try:
            if item.checkState(0) == Qt.CheckState.Checked:
                other = mui5 if item is mui38 else mui38
                other.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                # can't leave zero selected - re-check the one the user just unticked
                item.setCheckState(0, Qt.CheckState.Checked)
        finally:
            self._updating = False

    def set_kickstart_version(self, version: str):
        """reload the package tree when the Kickstart version changes"""
        if version != self.kickstart_version:
            self.kickstart_version = version
            self.refresh_packages()

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

    def get_config(self) -> list:
        """tree selections; bundles expand to member names so persisted config stays flat"""
        result = []
        for key, widget in self.checkboxes.items():
            enabled = widget.checkState(0) == Qt.CheckState.Checked
            for pkg_name in self._key_to_packages.get(key, [key]):
                result.append({"name": pkg_name, "enabled": enabled})
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

        # guard so applying the saved mui state doesn't trip the mutual-exclusion handler
        self._updating = True
        try:
            for key, enabled in key_enabled.items():
                if key in self.checkboxes:
                    self.checkboxes[key].setCheckState(
                        0, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
                    )
            # a config with neither mui recorded (or both off) falls back to mui38
            mui38 = self.checkboxes.get("mui38")
            mui5 = self.checkboxes.get("mui5")
            if mui38 is not None and mui5 is not None:
                m38 = mui38.checkState(0) == Qt.CheckState.Checked
                m5 = mui5.checkState(0) == Qt.CheckState.Checked
                if m38 == m5:  # both on or both off -> normalise to mui38
                    mui38.setCheckState(0, Qt.CheckState.Checked)
                    mui5.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._updating = False
