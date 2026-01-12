"""
kickstart/Workbench version and Amiga files configuration tab
"""

from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QFileDialog,
)

from emu68hatcher.config.schema import KickstartConfig, InstallMediaConfig
from emu68hatcher.gui.workers import ROMScanWorker, ADFScanWorker


class KickstartTab(QWidget):
    """workbench version and ROM configuration tab"""

    # signal emitted when Kickstart/Workbench version changes
    version_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rom_scan_worker = None
        self._adf_scan_worker = None
        self._last_rom_dir = ""
        self._last_adf_dir = ""
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # =================================================================
        # workbench Version
        # =================================================================
        version_group = QGroupBox("Workbench Version")
        version_group_layout = QVBoxLayout(version_group)

        version_layout = QHBoxLayout()
        version_layout.addWidget(QLabel("Version:"))
        self.version_combo = QComboBox()
        # only show versions we can currently test (3.9 hidden for now)
        self.version_combo.addItems(["3.1", "3.2", "3.2.2.1", "3.2.3"])
        self.version_combo.setCurrentIndex(3)  # 3.2.3 default (latest)
        self.version_combo.currentIndexChanged.connect(self.on_version_changed)
        version_layout.addWidget(self.version_combo)
        version_layout.addStretch()
        version_group_layout.addLayout(version_layout)

        # hidden combo for internal use (synced with version_combo)
        self.wb_version_combo = QComboBox()
        self.wb_version_combo.addItems(["3.1", "3.2", "3.2.2.1", "3.2.3"])
        self.wb_version_combo.setCurrentIndex(3)
        self.wb_version_combo.hide()

        layout.addWidget(version_group)

        # =================================================================
        # kickstart ROM
        # =================================================================
        rom_group = QGroupBox("Kickstart ROM")
        rom_layout = QVBoxLayout(rom_group)

        # ROM directory path
        rom_path_layout = QHBoxLayout()
        rom_path_layout.addWidget(QLabel("ROM Directory:"))
        self.rom_dir = QLineEdit()
        self.rom_dir.setPlaceholderText("Directory containing Kickstart ROM files...")
        self.rom_dir.textChanged.connect(self.scan_rom_directory)
        rom_path_layout.addWidget(self.rom_dir)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_rom_directory)
        rom_path_layout.addWidget(self.browse_btn)
        rom_layout.addLayout(rom_path_layout)

        # ROM status
        self.rom_status = QLabel("Select a directory containing ROM files")
        self.rom_status.setStyleSheet("color: gray;")
        rom_layout.addWidget(self.rom_status)

        layout.addWidget(rom_group)

        # =================================================================
        # workbench Installation Media
        # =================================================================
        wb_group = QGroupBox("Workbench Installation Disks")
        wb_layout = QVBoxLayout(wb_group)

        # ADF directory path
        adf_path_layout = QHBoxLayout()
        adf_path_layout.addWidget(QLabel("ADF Directory:"))
        self.adf_dir = QLineEdit()
        self.adf_dir.setPlaceholderText("Directory containing Workbench ADF files...")
        self.adf_dir.textChanged.connect(self.scan_adf_directory)
        adf_path_layout.addWidget(self.adf_dir)
        self.browse_adf_btn = QPushButton("Browse...")
        self.browse_adf_btn.clicked.connect(self.browse_adf_directory)
        adf_path_layout.addWidget(self.browse_adf_btn)
        wb_layout.addLayout(adf_path_layout)

        # ADF status
        self.adf_status = QLabel("Select a directory containing Workbench ADF files")
        self.adf_status.setStyleSheet("color: gray;")
        wb_layout.addWidget(self.adf_status)

        layout.addWidget(wb_group)
        layout.addStretch()

    # =========================================================================
    # directory Methods
    # =========================================================================

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

    def on_version_changed(self):
        """re-scan when version selection changes and sync hidden wb_version_combo"""
        # sync the hidden wb_version_combo with the main version_combo
        self.wb_version_combo.setCurrentIndex(self.version_combo.currentIndex())

        # emit version changed signal for other tabs (e.g., packages)
        self.version_changed.emit(self.get_selected_version())

        # re-scan ROM directory
        if self.rom_dir.text():
            self._last_rom_dir = ""  # reset to force rescan
            self.scan_rom_directory(self.rom_dir.text())

        # re-scan ADF directory
        if self.adf_dir.text():
            self._last_adf_dir = ""  # reset to force rescan
            self.scan_adf_directory(self.adf_dir.text())

    def scan_rom_directory(self, path: str):
        """scan directory for ROMs using a background thread"""
        # strip whitespace from path
        path = path.strip()

        if not path:
            self.rom_status.setText("Select a directory containing ROM files")
            self.rom_status.setStyleSheet("color: gray;")
            return

        # avoid rescanning the same directory
        if path == self._last_rom_dir:
            return
        self._last_rom_dir = path

        # expand ~ and resolve to absolute path
        p = Path(path).expanduser().resolve()
        if not p.exists():
            self.rom_status.setText("Directory not found")
            self.rom_status.setStyleSheet("color: red;")
            return

        if not p.is_dir():
            self.rom_status.setText("Path is not a directory")
            self.rom_status.setStyleSheet("color: red;")
            return

        # cancel any running scan
        if self._rom_scan_worker and self._rom_scan_worker.isRunning():
            self._rom_scan_worker.terminate()
            self._rom_scan_worker.wait()

        # show scanning status
        self.rom_status.setText("Scanning for ROMs...")
        self.rom_status.setStyleSheet("color: blue;")

        # start background scan
        self._rom_scan_worker = ROMScanWorker(p, self)
        self._rom_scan_worker.scan_finished.connect(self._on_rom_scan_finished)
        self._rom_scan_worker.start()

    @Slot(list)
    def _on_rom_scan_finished(self, found_roms: list):
        """handle ROM scan results"""
        from emu68hatcher.data.rom_detection import find_kickstart_for_version

        if not found_roms:
            self.rom_status.setText("No valid Kickstart ROMs found in this directory")
            self.rom_status.setStyleSheet("color: orange;")
            return

        # get selected version
        version = self.get_selected_version()

        # get directory from last scanned path
        p = Path(self._last_rom_dir).expanduser().resolve()

        # check if we have a ROM for the selected version
        rom_path = find_kickstart_for_version(p, version)

        if rom_path:
            # find the info for this ROM
            for rom in found_roms:
                if rom["path"] == rom_path:
                    self.rom_status.setText(
                        f"ROM: Kickstart {rom['version']} ({rom['model']})"
                    )
                    self.rom_status.setStyleSheet("color: green;")
                    return

        # no ROM for selected version, show what we found
        versions = sorted(set(r["version"] for r in found_roms), reverse=True)
        self.rom_status.setText(
            f"No {version} ROM. Available: {', '.join(versions)}"
        )
        self.rom_status.setStyleSheet("color: orange;")

    def get_selected_version(self) -> str:
        """get the selected version from the dropdown"""
        # version dropdown order: 3.1, 3.2, 3.2.2.1, 3.2.3 (3.9 hidden for now)
        version_map = {0: "3.1", 1: "3.2", 2: "3.2.2.1", 3: "3.2.3"}
        return version_map.get(self.version_combo.currentIndex(), "3.2.3")

    # =========================================================================
    # workbench ADF Methods
    # =========================================================================

    def get_selected_wb_version(self) -> str:
        """get the selected Workbench version (same as ROM version now)"""
        # uses the main version_combo since both are now unified
        return self.get_selected_version()

    def scan_adf_directory(self, path: str):
        """scan directory for Workbench ADFs using a background thread"""
        # strip whitespace from path
        path = path.strip()

        if not path:
            self.adf_status.setText("Select a directory containing Workbench ADF files")
            self.adf_status.setStyleSheet("color: gray;")
            return

        # avoid rescanning the same directory
        if path == self._last_adf_dir:
            return
        self._last_adf_dir = path

        # expand ~ and resolve to absolute path
        p = Path(path).expanduser().resolve()
        if not p.exists():
            self.adf_status.setText("Directory not found")
            self.adf_status.setStyleSheet("color: red;")
            return

        if not p.is_dir():
            self.adf_status.setText("Path is not a directory")
            self.adf_status.setStyleSheet("color: red;")
            return

        # cancel any running scan
        if self._adf_scan_worker and self._adf_scan_worker.isRunning():
            self._adf_scan_worker.terminate()
            self._adf_scan_worker.wait()

        # show scanning status
        self.adf_status.setText("Scanning for ADFs...")
        self.adf_status.setStyleSheet("color: blue;")

        # start background scan
        self._adf_scan_worker = ADFScanWorker(p, self)
        self._adf_scan_worker.scan_finished.connect(self._on_adf_scan_finished)
        self._adf_scan_worker.start()

    @Slot(list)
    def _on_adf_scan_finished(self, found_media: list):
        """handle ADF scan results"""
        from emu68hatcher.extractor.adf import (
            check_install_media_complete,
            get_required_install_media,
        )

        if not found_media:
            self.adf_status.setText("No recognized Workbench ADFs found in this directory")
            self.adf_status.setStyleSheet("color: orange;")
            return

        # get selected Workbench version
        wb_version = self.get_selected_wb_version()

        # check if we have a complete set for the selected version
        complete, missing = check_install_media_complete(found_media, wb_version)

        if complete:
            # count all disks compatible with selected version
            # for 3.2.x updates, include base 3.2 disks and intermediate versions
            compatible_versions = {wb_version}
            if wb_version == "3.2.2.1":
                compatible_versions.update(["3.2", "3.2.2"])  # base + 3.2.2 update disks
            elif wb_version == "3.2.3":
                compatible_versions.add("3.2")  # base 3.2 disks

            # count unique adf_names (user may have multiple copies with different hashes)
            compatible_disks = {m.adf_name for m in found_media
                               if m.workbench_version in compatible_versions}
            self.adf_status.setText(
                f"Complete set for {wb_version}: {len(compatible_disks)} disk(s) found"
            )
            self.adf_status.setStyleSheet("color: green;")
        else:
            # show what versions we have
            versions_found = sorted(set(m.workbench_version for m in found_media))
            if missing:
                self.adf_status.setText(
                    f"Incomplete {wb_version} set. Missing: {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}"
                )
            else:
                self.adf_status.setText(
                    f"No {wb_version} disks found. Available: {', '.join(versions_found)}"
                )
            self.adf_status.setStyleSheet("color: orange;")

    # =========================================================================
    # config Methods
    # =========================================================================

    def get_config(self) -> dict:
        return {
            "version": self.get_selected_version(),
            "rom_directory": self.rom_dir.text(),
            "wb_version": self.get_selected_wb_version(),
            "adf_directory": self.adf_dir.text(),
        }

    def set_config(self, ks_config: KickstartConfig, media_config: InstallMediaConfig):
        """populate the tab from config objects"""
        # use install_media version as the primary version (user selects "Workbench Version")
        # version dropdown order: 3.1, 3.2, 3.2.2.1, 3.2.3 (3.9 hidden for now)
        version_map = {"3.1": 0, "3.2": 1, "3.2.2.1": 2, "3.2.3": 3}
        # default to the install media version, fallback to kickstart version if 3.9
        version_to_set = media_config.version.value
        if version_to_set == "3.9":
            version_to_set = "3.1"  # 3.9 uses 3.1 ROMs, but 3.9 is hidden for now
        self.version_combo.setCurrentIndex(version_map.get(version_to_set, 3))

        # sync hidden wb_version_combo
        self.wb_version_combo.setCurrentIndex(self.version_combo.currentIndex())

        # set ROM directory
        if ks_config.rom_directory:
            self.rom_dir.setText(str(ks_config.rom_directory))

        # set ADF directory
        if media_config.directory:
            self.adf_dir.setText(str(media_config.directory))
