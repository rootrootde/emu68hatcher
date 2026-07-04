"""network tab - stack selection, per-interface IP (dhcp/static), gateway, DNS, wifi creds"""

import re
from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import (
    InterfaceIp,
    IpMode,
    NetworkSettings,
    NetworkStack,
    WifiConfig,
)
from emu68hatcher.data.package_loader import get_package_by_name

# permissive dotted-quad: lets the field be typed; the schema does the real IPv4 check
_IP_RE = QRegularExpression(r"^(\d{1,3})(\.\d{1,3}){0,3}$")


# a fixed label-column width so every group's fields start at the same x and end up equal length
_LABEL_W = 78


def _ip_field(placeholder: str = "") -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setValidator(QRegularExpressionValidator(_IP_RE))
    edit.setMinimumWidth(160)
    return edit


def _flabel(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setMinimumWidth(_LABEL_W)
    return lbl


def _grow_form(group: QGroupBox) -> QFormLayout:
    """a form whose fields fill the available width (macOS defaults to staying at size hint)"""
    form = QFormLayout(group)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


class NetworkTab(QWidget):
    """TCP/IP stack + per-interface address config for ethernet and wifi"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # network stack selection
        net_group = QGroupBox("Network Stack")
        net_layout = QVBoxLayout(net_group)
        self.radio_none = QRadioButton("None")
        self.radio_roadshow = QRadioButton("Roadshow")
        self.radio_roadshow.setChecked(True)
        self.radio_none.setToolTip("No network stack - no online connectivity")
        self.radio_roadshow.setToolTip("Roadshow demo - free TCP/IP stack with PiStorm support")
        net_layout.addWidget(self.radio_none)

        self.radio_roadshow.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        roadshow_row = QHBoxLayout()
        roadshow_row.setContentsMargins(0, 0, 0, 0)
        roadshow_row.setSpacing(6)
        roadshow_row.addWidget(self.radio_roadshow)
        roadshow_pkg = get_package_by_name("roadshow")
        if roadshow_pkg and roadshow_pkg.purchase_url:
            self._roadshow_status_label = QLabel(
                f'(Demo version - buy the full version <a href="{roadshow_pkg.purchase_url}">here</a>)'
            )
            self._roadshow_status_label.setTextFormat(Qt.TextFormat.RichText)
            self._roadshow_status_label.setOpenExternalLinks(True)
        else:
            self._roadshow_status_label = QLabel("(Demo version)")
        roadshow_row.addWidget(self._roadshow_status_label)
        roadshow_row.addStretch()
        net_layout.addLayout(roadshow_row)

        # full-version archive picker: empty -> bundled demo
        self._roadshow_full_box = QWidget()
        full_layout = QHBoxLayout(self._roadshow_full_box)
        full_layout.setContentsMargins(20, 0, 0, 0)
        full_layout.setSpacing(6)
        full_layout.addWidget(QLabel("Full version archive:"))
        self.roadshow_archive_edit = QLineEdit()
        self.roadshow_archive_edit.setPlaceholderText("Roadshow.lha (leave empty for demo)")
        self.roadshow_archive_edit.setReadOnly(True)
        full_layout.addWidget(self.roadshow_archive_edit, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_roadshow_archive)
        full_layout.addWidget(browse_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_roadshow_archive)
        full_layout.addWidget(clear_btn)
        net_layout.addWidget(self._roadshow_full_box)
        layout.addWidget(net_group)

        # all four groups are siblings in the main layout so they share one consistent gap
        # (hidden together when no stack is selected). these are meaningful only with a stack.
        self._iface_groups = [
            self._build_ethernet_group(),
            self._build_wifi_group(),
            self._build_routing_group(),
        ]
        for g in self._iface_groups:
            layout.addWidget(g)
        layout.addStretch()

        self.radio_none.toggled.connect(self._update_net_visibility)
        self._update_net_visibility()
        self._update_static_enabled()  # grey the IP fields - both interfaces default to DHCP

    def _build_ethernet_group(self) -> QGroupBox:
        group = QGroupBox("Ethernet (genet)")
        form = _grow_form(group)
        self.eth_dhcp = QRadioButton("DHCP")
        self.eth_static = QRadioButton("Static")
        self.eth_dhcp.setChecked(True)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.eth_dhcp)
        mode_row.addWidget(self.eth_static)
        mode_row.addStretch()
        form.addRow(_flabel("Address:"), mode_row)
        self.eth_addr = _ip_field("192.168.1.50")
        self.eth_mask = _ip_field("255.255.255.0")
        form.addRow(_flabel("IP:"), self.eth_addr)
        form.addRow(_flabel("Netmask:"), self.eth_mask)
        self.eth_static.toggled.connect(self._update_static_enabled)
        return group

    def _build_wifi_group(self) -> QGroupBox:
        group = QGroupBox("WiFi (wifipi)")
        form = _grow_form(group)
        self.wifi_ssid = QLineEdit()
        self.wifi_ssid.setPlaceholderText("leave empty to skip wifi")
        self.wifi_ssid.setMaxLength(32)
        form.addRow(_flabel("SSID:"), self.wifi_ssid)
        self.wifi_password = QLineEdit()
        self.wifi_password.setPlaceholderText("empty = open network")
        self.wifi_password.setMaxLength(63)
        self.wifi_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_flabel("Password:"), self.wifi_password)
        self.wifi_dhcp = QRadioButton("DHCP")
        self.wifi_static = QRadioButton("Static")
        self.wifi_dhcp.setChecked(True)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.wifi_dhcp)
        mode_row.addWidget(self.wifi_static)
        mode_row.addStretch()
        form.addRow(_flabel("Address:"), mode_row)
        self.wifi_addr = _ip_field("192.168.1.51")
        self.wifi_mask = _ip_field("255.255.255.0")
        form.addRow(_flabel("IP:"), self.wifi_addr)
        form.addRow(_flabel("Netmask:"), self.wifi_mask)
        self.wifi_static.toggled.connect(self._update_static_enabled)
        return group

    def _build_routing_group(self) -> QGroupBox:
        # one default route + one resolver list are global in roadshow, not per-interface
        # && renders a literal ampersand (a single & is a Qt mnemonic)
        group = QGroupBox("Routing && DNS (shared)")
        form = _grow_form(group)
        self.gw_edit = _ip_field("192.168.1.1")
        form.addRow(_flabel("Gateway:"), self.gw_edit)
        self.dns_edit = QLineEdit()
        self.dns_edit.setPlaceholderText("8.8.8.8 1.1.1.1 (space-separated)")
        form.addRow(_flabel("DNS servers:"), self.dns_edit)
        return group

    def _update_net_visibility(self):
        on = not self.radio_none.isChecked()
        self._roadshow_full_box.setVisible(on)
        for g in self._iface_groups:
            g.setVisible(on)

    def _update_static_enabled(self):
        self.eth_addr.setEnabled(self.eth_static.isChecked())
        self.eth_mask.setEnabled(self.eth_static.isChecked())
        self.wifi_addr.setEnabled(self.wifi_static.isChecked())
        self.wifi_mask.setEnabled(self.wifi_static.isChecked())

    # --- network stack ---
    def get_network_stack(self) -> NetworkStack | None:
        return None if self.radio_none.isChecked() else NetworkStack.ROADSHOW

    def set_network_stack(self, stack: NetworkStack | None):
        if stack is None:
            self.radio_none.setChecked(True)
        else:
            self.radio_roadshow.setChecked(True)

    def extra_package_entries(self) -> list[dict]:
        """the network-stack package the tree doesn't carry"""
        if self.get_network_stack() is not None:
            return [{"name": "roadshow", "enabled": True}]
        return []

    # --- per-interface settings ---
    def get_network_settings(self) -> NetworkSettings:
        # only read the IP fields in static mode, so a stale/half-typed value left in a
        # dhcp-mode field never reaches (and fails) schema validation
        def _iface(static: QRadioButton, addr: QLineEdit, mask: QLineEdit) -> InterfaceIp:
            if not static.isChecked():
                return InterfaceIp(mode=IpMode.DHCP)
            return InterfaceIp(
                mode=IpMode.STATIC,
                address=addr.text().strip() or None,
                netmask=mask.text().strip() or None,
            )

        eth = _iface(self.eth_static, self.eth_addr, self.eth_mask)
        wifi = _iface(self.wifi_static, self.wifi_addr, self.wifi_mask)
        dns = [s for s in re.split(r"[\s,]+", self.dns_edit.text().strip()) if s]
        return NetworkSettings(
            ethernet=eth, wifi=wifi, gateway=self.gw_edit.text().strip() or None, dns_servers=dns
        )

    def set_network_settings(self, net: NetworkSettings):
        def _apply(static_rb, dhcp_rb, addr, mask, iface):
            static_rb.setChecked(iface.mode == IpMode.STATIC)
            dhcp_rb.setChecked(iface.mode != IpMode.STATIC)
            addr.setText(iface.address or "")
            mask.setText(iface.netmask or "")

        _apply(self.eth_static, self.eth_dhcp, self.eth_addr, self.eth_mask, net.ethernet)
        _apply(self.wifi_static, self.wifi_dhcp, self.wifi_addr, self.wifi_mask, net.wifi)
        self.gw_edit.setText(net.gateway or "")
        self.dns_edit.setText(" ".join(net.dns_servers))
        self._update_static_enabled()

    # --- roadshow archive ---
    def _browse_roadshow_archive(self):
        from PySide6.QtWidgets import QFileDialog

        start = self.roadshow_archive_edit.text() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Roadshow archive",
            start,
            "Roadshow archive (*.lha *.LHA);;All files (*.*)",
        )
        if path:
            self.roadshow_archive_edit.setText(path)
            self._refresh_roadshow_status()

    def _clear_roadshow_archive(self):
        self.roadshow_archive_edit.clear()
        self._refresh_roadshow_status()

    def _refresh_roadshow_status(self):
        path = self.roadshow_archive_edit.text().strip()
        if path:
            self._roadshow_status_label.setTextFormat(Qt.TextFormat.PlainText)
            self._roadshow_status_label.setText(f"(Full version: {Path(path).name})")
        else:
            roadshow_pkg = get_package_by_name("roadshow")
            if roadshow_pkg and roadshow_pkg.purchase_url:
                self._roadshow_status_label.setTextFormat(Qt.TextFormat.RichText)
                self._roadshow_status_label.setText(
                    f"(Demo version - buy the full version "
                    f'<a href="{roadshow_pkg.purchase_url}">here</a>)'
                )
            else:
                self._roadshow_status_label.setTextFormat(Qt.TextFormat.PlainText)
                self._roadshow_status_label.setText("(Demo version)")

    def get_roadshow_archive(self) -> Path | None:
        text = self.roadshow_archive_edit.text().strip()
        return Path(text) if text else None

    def set_roadshow_archive(self, archive: Path | str | None):
        self.roadshow_archive_edit.setText(str(archive) if archive else "")
        self._refresh_roadshow_status()

    # --- wifi creds ---
    def get_wifi_config(self) -> WifiConfig | None:
        """wifi creds, or None when no SSID; empty password means an open network"""
        ssid = self.wifi_ssid.text().strip()
        if not ssid:
            return None
        password = self.wifi_password.text().strip()
        if password and len(password) < 8:
            return None  # WPA needs >=8; treat a too-short password as incomplete
        return WifiConfig(ssid=ssid, password=password)

    def set_wifi_config(self, wifi: WifiConfig | None):
        if wifi:
            self.wifi_ssid.setText(wifi.ssid)
            self.wifi_password.setText(wifi.password)
        else:
            self.wifi_ssid.clear()
            self.wifi_password.clear()
