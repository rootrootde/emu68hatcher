"""Kickstart/Workbench version + Amiga files config tab"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher.config.schema import (
    SUPPORTED_KICKSTARTS,
    InstallMediaConfig,
    KickstartConfig,
    KickstartVersion,
)
from emu68hatcher.gui.workers import ADFScanWorker, ROMScanWorker

# dropdown order follows schema.SUPPORTED_KICKSTARTS (add a version there to expose it here)
_SELECTABLE_VERSIONS: tuple[str, ...] = tuple(v.value for v in SUPPORTED_KICKSTARTS)
_DEFAULT_VERSION: str = KickstartVersion.V3_2_3.value


class KickstartTab(QWidget):
    """workbench version and ROM configuration tab"""

    # signal emitted when WB version changes
    version_changed = Signal(str)

    # debounce textChanged scans (skip per-keystroke worker spawn)
    _SCAN_DEBOUNCE_MS = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rom_scan_worker = None
        self._adf_scan_worker = None
        self._last_rom_dir = ""
        self._last_adf_dir = ""
        self._active_scans = 0

        # debounce timers for the rom/adf path edits
        self._rom_debounce = QTimer(self)
        self._rom_debounce.setSingleShot(True)
        self._rom_debounce.setInterval(self._SCAN_DEBOUNCE_MS)
        self._rom_debounce.timeout.connect(self._fire_rom_scan)

        self._adf_debounce = QTimer(self)
        self._adf_debounce.setSingleShot(True)
        self._adf_debounce.setInterval(self._SCAN_DEBOUNCE_MS)
        self._adf_debounce.timeout.connect(self._fire_adf_scan)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        #####################
        # workbench Version #
        #####################
        version_group = QGroupBox("Workbench Version")
        version_group_layout = QVBoxLayout(version_group)

        version_layout = QHBoxLayout()
        version_layout.addWidget(QLabel("Version:"))
        self.version_combo = QComboBox()
        self.version_combo.addItems(_SELECTABLE_VERSIONS)
        self.version_combo.setCurrentIndex(_SELECTABLE_VERSIONS.index(_DEFAULT_VERSION))
        self.version_combo.currentIndexChanged.connect(self.on_version_changed)
        version_layout.addWidget(self.version_combo)
        version_layout.addStretch()
        version_group_layout.addLayout(version_layout)

        layout.addWidget(version_group)

        #################
        # kickstart ROM #
        #################
        rom_group = QGroupBox("Kickstart ROM")
        rom_layout = QVBoxLayout(rom_group)

        # ROM directory path
        rom_path_layout = QHBoxLayout()
        rom_path_layout.addWidget(QLabel("ROM Directory:"))
        self.rom_dir = QLineEdit()
        self.rom_dir.setPlaceholderText("Directory containing Kickstart ROM files...")
        self.rom_dir.textChanged.connect(lambda _t: self._rom_debounce.start())
        rom_path_layout.addWidget(self.rom_dir)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_rom_directory)
        rom_path_layout.addWidget(self.browse_btn)
        rom_layout.addLayout(rom_path_layout)

        # ROM status - boot ROM line
        self.rom_status = QLabel("Select a directory containing ROM files")
        self.rom_status.setStyleSheet("color: gray;")
        self.rom_status.setWordWrap(True)
        self.rom_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rom_layout.addWidget(self.rom_status)

        # WHDLoad ROM inventory (kick*.* ROMs staged to DEVS:Kickstarts/)
        self.whdload_status = QLabel("")
        self.whdload_status.setStyleSheet("color: gray;")
        self.whdload_status.setWordWrap(True)
        self.whdload_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rom_layout.addWidget(self.whdload_status)

        layout.addWidget(rom_group)

        ################################
        # workbench Installation Media #
        ################################
        wb_group = QGroupBox("Workbench Installation Disks")
        wb_layout = QVBoxLayout(wb_group)

        # ADF directory path
        adf_path_layout = QHBoxLayout()
        adf_path_layout.addWidget(QLabel("ADF Directory:"))
        self.adf_dir = QLineEdit()
        self.adf_dir.setPlaceholderText("Directory containing Workbench ADF files...")
        self.adf_dir.textChanged.connect(lambda _t: self._adf_debounce.start())
        adf_path_layout.addWidget(self.adf_dir)
        self.browse_adf_btn = QPushButton("Browse...")
        self.browse_adf_btn.clicked.connect(self.browse_adf_directory)
        adf_path_layout.addWidget(self.browse_adf_btn)
        wb_layout.addLayout(adf_path_layout)

        # ADF status - one-line summary + button for the detailed table
        adf_status_row = QHBoxLayout()
        self.adf_status = QLabel("Select a directory containing Workbench ADF files")
        self.adf_status.setStyleSheet("color: gray;")
        self.adf_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        adf_status_row.addWidget(self.adf_status, 1)
        self._adf_details_btn = QPushButton("Show details…")
        self._adf_details_btn.setEnabled(False)
        self._adf_details_btn.clicked.connect(self._show_adf_details)
        adf_status_row.addWidget(self._adf_details_btn)
        wb_layout.addLayout(adf_status_row)
        # populated by _on_adf_scan_finished so the dialog can render on demand
        self._adf_rows: list[tuple[str, str, str, str, bool]] = []
        self._adf_dialog_title: str = ""

        layout.addWidget(wb_group)
        layout.addStretch()

    #####################
    # directory Methods #
    #####################

    def browse_rom_directory(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select ROM Directory",
            self.rom_dir.text() or "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.rom_dir.setText(path)
            # auto-populate ADF directory if not set
            if not self.adf_dir.text().strip():
                self.adf_dir.setText(path)

    def browse_adf_directory(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Workbench ADF Directory",
            self.adf_dir.text() or self.rom_dir.text() or "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.adf_dir.setText(path)

    def _set_scanning(self, started: bool):
        """track active scans and disable version combo while any scan is running"""
        if started:
            self._active_scans += 1
        else:
            self._active_scans = max(0, self._active_scans - 1)
        self.version_combo.setEnabled(self._active_scans == 0)

    def on_version_changed(self):
        """re-scan when version selection changes"""
        self.version_changed.emit(self.get_selected_version())
        if self.rom_dir.text():
            self._last_rom_dir = ""  # force rescan
            self._fire_rom_scan()
        if self.adf_dir.text():
            self._last_adf_dir = ""
            self._fire_adf_scan()

    def _fire_rom_scan(self):
        """debounce timer expired - validate the path and start a worker"""
        path = self.rom_dir.text().strip()
        if not path:
            self.rom_status.setText("Select a directory containing ROM files")
            self.rom_status.setStyleSheet("color: gray;")
            return
        if path == self._last_rom_dir:
            return
        self._last_rom_dir = path
        p = Path(path).expanduser().resolve()
        if not p.exists():
            self.rom_status.setText("Directory not found")
            self.rom_status.setStyleSheet("color: red;")
            return
        if not p.is_dir():
            self.rom_status.setText("Path is not a directory")
            self.rom_status.setStyleSheet("color: red;")
            return

        # disconnect any in-flight worker's signal; let it drain and gc on its own
        if self._rom_scan_worker and self._rom_scan_worker.isRunning():
            try:
                self._rom_scan_worker.scan_finished.disconnect(self._on_rom_scan_finished)
            except (TypeError, RuntimeError):
                pass
            self._set_scanning(False)

        self.rom_status.setText("Scanning for ROMs...")
        self.rom_status.setStyleSheet("color: blue;")
        self._set_scanning(True)

        self._rom_scan_worker = ROMScanWorker(p, self)
        self._rom_scan_worker.scan_finished.connect(self._on_rom_scan_finished)
        self._rom_scan_worker.start()

    @Slot(list, bool)
    def _on_rom_scan_finished(self, found_roms: list, truncated: bool = False):
        """handle ROM scan results"""
        self._set_scanning(False)
        from emu68hatcher.data.rom_detection import find_kickstart_for_version

        # always update teh WHDLoad inventory, regardless of boot-ROM outcome
        self._update_whdload_status(found_roms)

        if not found_roms:
            if truncated:
                self.rom_status.setText(
                    "No ROMs found (scan stopped - too many files, pick a smaller folder)"
                )
                self.rom_status.setStyleSheet("color: red;")
            else:
                self.rom_status.setText("No valid Kickstart ROMs found in this directory")
                self.rom_status.setStyleSheet("color: orange;")
            return

        # get selected version
        version = self.get_selected_version()

        # get directory from last scanned path
        p = Path(self._last_rom_dir).expanduser().resolve()

        # check if a ROM exists for the selected version
        rom_path = find_kickstart_for_version(p, version)

        if rom_path:
            # find the info for this ROM
            for rom in found_roms:
                if rom["path"] == rom_path:
                    self.rom_status.setText(
                        f"Boot ROM: {rom_path.name} - Kickstart {rom['version']} ({rom['model']})"
                    )
                    self.rom_status.setStyleSheet("color: green;")
                    return

        # check for an excluded ROM (e.g. encrypted) for this version
        excluded = [r for r in found_roms if r["version"] == version and r.get("excluded")]
        if excluded:
            msg = excluded[0].get("exclude_message", "ROM is not supported")
            self.rom_status.setText(f"ROM found but excluded: {msg}")
            self.rom_status.setStyleSheet("color: red;")
            return

        # no ROM for selected version, show what was found
        versions = sorted({r["version"] for r in found_roms if not r.get("excluded")}, reverse=True)
        self.rom_status.setText(f"No {version} ROM. Available: {', '.join(versions)}")
        self.rom_status.setStyleSheet("color: orange;")

    def _update_whdload_status(self, found_roms: list) -> None:
        """show which kick*.* ROMs will be staged for WHDLoad under DEVS:Kickstarts/"""
        from emu68hatcher.data.rom_detection import WHDLOAD_ROM_NAMES

        found = sorted({r["whdload_name"] for r in found_roms if r.get("whdload_name")})
        missing = [n for n in WHDLOAD_ROM_NAMES if n not in found]

        if not found:
            self.whdload_status.setText(
                "WHDLoad ROMs → DEVS:Kickstarts/ : none found\n"
                f"  (looking for: {', '.join(WHDLOAD_ROM_NAMES)})"
            )
            self.whdload_status.setStyleSheet("color: gray;")
            return

        lines = [
            f"WHDLoad ROMs → DEVS:Kickstarts/ ({len(found)}/{len(WHDLOAD_ROM_NAMES)} will be copied):",
            f"  {', '.join(found)}",
        ]
        if missing:
            lines.append(f"  missing: {', '.join(missing)}")
        self.whdload_status.setText("\n".join(lines))
        self.whdload_status.setStyleSheet("color: green;" if not missing else "color: gray;")

    def get_selected_version(self) -> str:
        """get the selected version from the dropdown"""
        idx = self.version_combo.currentIndex()
        if 0 <= idx < len(_SELECTABLE_VERSIONS):
            return _SELECTABLE_VERSIONS[idx]
        return _DEFAULT_VERSION

    #########################
    # workbench ADF Methods #
    #########################

    def _fire_adf_scan(self):
        """debounce timer expired - validate the path and start a worker"""
        path = self.adf_dir.text().strip()
        if not path:
            self.adf_status.setText("Select a directory containing Workbench ADF files")
            self.adf_status.setStyleSheet("color: gray;")
            return
        if path == self._last_adf_dir:
            return
        self._last_adf_dir = path
        p = Path(path).expanduser().resolve()
        if not p.exists():
            self.adf_status.setText("Directory not found")
            self.adf_status.setStyleSheet("color: red;")
            return
        if not p.is_dir():
            self.adf_status.setText("Path is not a directory")
            self.adf_status.setStyleSheet("color: red;")
            return

        if self._adf_scan_worker and self._adf_scan_worker.isRunning():
            try:
                self._adf_scan_worker.scan_finished.disconnect(self._on_adf_scan_finished)
            except (TypeError, RuntimeError):
                pass
            self._set_scanning(False)

        self.adf_status.setText("Scanning for ADFs...")
        self.adf_status.setStyleSheet("color: blue;")
        self._set_scanning(True)

        self._adf_scan_worker = ADFScanWorker(p, self)
        self._adf_scan_worker.scan_finished.connect(self._on_adf_scan_finished)
        self._adf_scan_worker.start()

    @Slot(list, bool)
    def _on_adf_scan_finished(self, found_media: list, truncated: bool = False):
        """handle ADF scan results - build the per-ADF table and a summary."""
        self._set_scanning(False)
        from emu68hatcher.data.install_media import get_required_install_media
        from emu68hatcher.data.package_loader import get_adf_rules_for_version

        # disable details button until data arrives
        self._adf_rows = []
        self._adf_details_btn.setEnabled(False)

        if not found_media:
            if truncated:
                self.adf_status.setText(
                    "No ADFs found (scan stopped - too many files, pick a smaller folder)"
                )
                self.adf_status.setStyleSheet("color: red;")
            else:
                self.adf_status.setText("No recognized Workbench ADFs found in this directory")
                self.adf_status.setStyleSheet("color: orange;")
            return

        wb_version = self.get_selected_version()

        # expected set: every adf referenced by any rule for this ks version
        expected: set[str] = {r.adf for r in get_adf_rules_for_version(wb_version)}
        required: set[str] = set(get_required_install_media(wb_version))
        # union with required-set so older baselines show even if not in rules
        expected |= required
        # anything NOT required is optional (locales, GlowIcons, modules, ...)
        optional = expected - required

        # found set: hash-matched ADFs, deduped by adf_name
        found_by_name: dict[str, object] = {}
        for m in found_media:
            if m.adf_name not in found_by_name:
                found_by_name[m.adf_name] = m

        req_found = required & found_by_name.keys()
        opt_found = optional & found_by_name.keys()
        req_missing = required - found_by_name.keys()

        # build table rows: (status, adf, friendly, version, required)
        rows = []
        for adf_name in sorted(expected):
            in_required = adf_name in required
            media = found_by_name.get(adf_name)
            if media is not None:
                status = "found"
                friendly = media.friendly_name or adf_name
                version = media.workbench_version or ""
            else:
                status = "missing_required" if in_required else "missing_optional"
                friendly, version = self._infer_adf_labels(adf_name)
            rows.append((status, adf_name, friendly, version, in_required))
        self._adf_rows = rows
        self._adf_dialog_title = f"ADFs for Workbench {wb_version}"
        self._adf_details_btn.setEnabled(True)

        # summary line
        summary = (
            f"Workbench {wb_version} - {len(req_found)}/{len(required)} required, "
            f"{len(opt_found)}/{len(optional)} optional found"
        )
        self.adf_status.setText(summary)
        if req_missing:
            self.adf_status.setStyleSheet("color: orange;")
        else:
            self.adf_status.setStyleSheet("color: green;")

    def _show_adf_details(self):
        """open the details dialog with the per-ADF breakdown."""
        if not self._adf_rows:
            return
        from emu68hatcher.gui.dialogs import ADFDetailsDialog

        dialog = ADFDetailsDialog(self._adf_rows, self._adf_dialog_title, self)
        dialog.exec()

    @staticmethod
    def _infer_adf_labels(adf_name: str) -> tuple[str, str]:
        """split adf_name like 'Workbench3_2_3' into ('Workbench 3.2.3', '3.2.3')"""
        import re

        m = re.match(r"^(.*?)(\d+(?:_\d+)+)$", adf_name)
        if not m:
            return adf_name, ""
        base, ver = m.group(1), m.group(2).replace("_", ".")
        return f"{base} {ver}", ver

    ##################
    # config Methods #
    ##################

    def get_config(self) -> dict:
        return {
            "version": self.get_selected_version(),
            "rom_directory": self.rom_dir.text(),
            "wb_version": self.get_selected_version(),
            "adf_directory": self.adf_dir.text(),
        }

    def set_config(self, ks_config: KickstartConfig, media_config: InstallMediaConfig):
        """populate the tab from config objects"""
        # install_media drives the Workbench dropdown; 3.9 maps to 3.1 (same ROM, hidden in UI)
        version_to_set = media_config.version.value
        if version_to_set not in _SELECTABLE_VERSIONS:
            version_to_set = KickstartVersion.V3_1.value
        idx = _SELECTABLE_VERSIONS.index(version_to_set)
        self.version_combo.setCurrentIndex(idx)

        # set ROM directory
        if ks_config.rom_directory:
            self.rom_dir.setText(str(ks_config.rom_directory))

        # set ADF directory
        if media_config.directory:
            self.adf_dir.setText(str(media_config.directory))
