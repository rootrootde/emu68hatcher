"""Kickstart/Workbench version + Amiga asset directories tab"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
    """workbench version + multi-directory asset configuration"""

    # signal emitted when WB version changes
    version_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rom_scan_worker = None
        self._adf_scan_worker = None
        self._active_scans = 0
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

        #####################
        # asset Directories #
        #####################
        dir_group = QGroupBox("Asset Directories (Kickstart ROMs + Workbench ADFs)")
        dir_layout = QVBoxLayout(dir_group)

        self.dir_list = QListWidget()
        self.dir_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.dir_list.setMinimumHeight(80)
        dir_layout.addWidget(self.dir_list)

        btn_row = QHBoxLayout()
        self.add_dir_btn = QPushButton("Add...")
        self.add_dir_btn.clicked.connect(self._add_directory)
        btn_row.addWidget(self.add_dir_btn)
        self.remove_dir_btn = QPushButton("Remove")
        self.remove_dir_btn.clicked.connect(self._remove_directory)
        btn_row.addWidget(self.remove_dir_btn)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self._fire_scans)
        btn_row.addWidget(self.rescan_btn)
        btn_row.addStretch()
        dir_layout.addLayout(btn_row)

        layout.addWidget(dir_group)

        #################
        # detected files #
        #################
        detected_group = QGroupBox("Detected Files")
        detected_layout = QVBoxLayout(detected_group)

        self.rom_status = QLabel("Add at least one directory above to scan for ROMs and ADFs")
        self.rom_status.setStyleSheet("color: gray;")
        self.rom_status.setWordWrap(True)
        self.rom_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detected_layout.addWidget(self.rom_status)

        # WHDLoad ROM inventory (kick*.* ROMs staged to DEVS:Kickstarts/)
        self.whdload_status = QLabel("")
        self.whdload_status.setStyleSheet("color: gray;")
        self.whdload_status.setWordWrap(True)
        self.whdload_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detected_layout.addWidget(self.whdload_status)

        adf_status_row = QHBoxLayout()
        self.adf_status = QLabel("")
        self.adf_status.setStyleSheet("color: gray;")
        self.adf_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        adf_status_row.addWidget(self.adf_status, 1)
        self._adf_details_btn = QPushButton("Show details…")
        self._adf_details_btn.setEnabled(False)
        self._adf_details_btn.clicked.connect(self._show_details)
        adf_status_row.addWidget(self._adf_details_btn)
        detected_layout.addLayout(adf_status_row)

        # populated by the scan-finished slots so the details dialog can render on demand
        self._rom_rows: list[tuple[str, str, str, str, str]] = []
        self._whdload_rows: list[tuple[str, str, str]] = []
        self._adf_rows: list[tuple[str, str, str, str, bool]] = []
        self._adf_dialog_title: str = ""

        layout.addWidget(detected_group)
        layout.addStretch()

    #####################
    # directory Methods #
    #####################

    def _list_dirs(self) -> list[Path]:
        """current directory entries as Paths"""
        return [Path(self.dir_list.item(i).text()) for i in range(self.dir_list.count())]

    def _set_dirs(self, dirs: list[Path | str]):
        """replace the list, ignoring duplicates and non-string-equal entries"""
        self.dir_list.clear()
        seen: set[str] = set()
        for d in dirs:
            s = str(d)
            if s in seen:
                continue
            seen.add(s)
            self.dir_list.addItem(QListWidgetItem(s))

    def _add_directory(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Add directory containing ROMs / ADFs",
            "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        # dedupe against existing entries
        existing = {self.dir_list.item(i).text() for i in range(self.dir_list.count())}
        if path in existing:
            return
        self.dir_list.addItem(QListWidgetItem(path))
        self._fire_scans()

    def _remove_directory(self):
        row = self.dir_list.currentRow()
        if row < 0:
            return
        self.dir_list.takeItem(row)
        self._fire_scans()

    def _set_scanning(self, started: bool):
        """track active scans and disable controls while any scan is running"""
        if started:
            self._active_scans += 1
        else:
            self._active_scans = max(0, self._active_scans - 1)
        scanning = self._active_scans > 0
        self.version_combo.setEnabled(not scanning)
        self.add_dir_btn.setEnabled(not scanning)
        self.remove_dir_btn.setEnabled(not scanning)
        self.rescan_btn.setEnabled(not scanning)

    def on_version_changed(self):
        """re-scan when version selection changes"""
        self.version_changed.emit(self.get_selected_version())
        self._fire_scans()

    def _fire_scans(self):
        """kick off ROM + ADF scans across the current directory list"""
        dirs = [d for d in self._list_dirs() if d.exists() and d.is_dir()]
        if not dirs:
            self.rom_status.setText("Add at least one directory above to scan for ROMs and ADFs")
            self.rom_status.setStyleSheet("color: gray;")
            self.whdload_status.setText("")
            self.adf_status.setText("")
            self.adf_status.setStyleSheet("color: gray;")
            self._rom_rows = []
            self._whdload_rows = []
            self._adf_rows = []
            self._refresh_details_button()
            return

        # cancel any in-flight workers
        if self._rom_scan_worker and self._rom_scan_worker.isRunning():
            try:
                self._rom_scan_worker.scan_finished.disconnect(self._on_rom_scan_finished)
            except (TypeError, RuntimeError):
                pass
            self._set_scanning(False)
        if self._adf_scan_worker and self._adf_scan_worker.isRunning():
            try:
                self._adf_scan_worker.scan_finished.disconnect(self._on_adf_scan_finished)
            except (TypeError, RuntimeError):
                pass
            self._set_scanning(False)

        self.rom_status.setText("Scanning for ROMs...")
        self.rom_status.setStyleSheet("color: blue;")
        self.adf_status.setText("Scanning for ADFs...")
        self.adf_status.setStyleSheet("color: blue;")

        self._set_scanning(True)
        self._rom_scan_worker = ROMScanWorker(dirs, self)
        self._rom_scan_worker.scan_finished.connect(self._on_rom_scan_finished)
        self._rom_scan_worker.start()

        self._set_scanning(True)
        self._adf_scan_worker = ADFScanWorker(dirs, self)
        self._adf_scan_worker.scan_finished.connect(self._on_adf_scan_finished)
        self._adf_scan_worker.start()

    @Slot(list, bool)
    def _on_rom_scan_finished(self, found_roms: list, truncated: bool = False):
        """handle ROM scan results"""
        self._set_scanning(False)
        from emu68hatcher.data.rom_detection import find_kickstart_for_version

        version = self.get_selected_version()
        dirs = [d for d in self._list_dirs() if d.exists() and d.is_dir()]
        boot_path = find_kickstart_for_version(dirs, version) if found_roms else None

        self._rom_rows = self._build_rom_rows(found_roms, version, boot_path)
        self._update_whdload_status(found_roms)
        self._refresh_details_button()

        if not found_roms:
            if truncated:
                self.rom_status.setText(
                    "No ROMs found (scan stopped - too many files, narrow the directories)"
                )
                self.rom_status.setStyleSheet("color: red;")
            else:
                self.rom_status.setText(
                    "No valid Kickstart ROMs found in the configured directories"
                )
                self.rom_status.setStyleSheet("color: orange;")
            return

        if boot_path:
            for rom in found_roms:
                if rom["path"] == boot_path:
                    self.rom_status.setText(
                        f"Boot ROM: {boot_path.name} - Kickstart {rom['version']} ({rom['model']})"
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

    @staticmethod
    def _build_rom_rows(found_roms: list, version: str, boot_path) -> list[tuple]:
        """(status, filename, version, model, path) per ROM"""
        rows: list[tuple] = []
        for rom in found_roms:
            path = rom["path"]
            if rom.get("excluded"):
                status = "excluded"
            elif boot_path is not None and path == boot_path:
                status = "boot"
            elif rom["version"] == version:
                status = "available"
            else:
                status = "other_version"
            rows.append((status, path.name, rom["version"], rom.get("model", ""), str(path)))
        return rows

    def _update_whdload_status(self, found_roms: list) -> None:
        """show which kick*.* ROMs will be staged for WHDLoad under DEVS:Kickstarts/"""
        from emu68hatcher.data.rom_detection import WHDLOAD_ROM_NAMES

        # path per whdload name; first occurrence wins (matches find_whdload_kickstarts)
        whdload_path: dict[str, str] = {}
        for rom in found_roms:
            name = rom.get("whdload_name")
            if not name or rom.get("excluded"):
                continue
            whdload_path.setdefault(name, str(rom["path"]))

        self._whdload_rows = [
            (
                "found" if name in whdload_path else "missing",
                name,
                whdload_path.get(name, ""),
            )
            for name in WHDLOAD_ROM_NAMES
        ]

        found = sorted(whdload_path.keys())
        missing = [n for n in WHDLOAD_ROM_NAMES if n not in whdload_path]

        if not found:
            self.whdload_status.setText("WHDLoad ROMs → DEVS:Kickstarts/ : none found")
            self.whdload_status.setStyleSheet("color: gray;")
            return

        line = f"WHDLoad ROMs → DEVS:Kickstarts/ ({len(found)}/{len(WHDLOAD_ROM_NAMES)} will be copied)"
        self.whdload_status.setText(line)
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

    @Slot(list, bool)
    def _on_adf_scan_finished(self, found_media: list, truncated: bool = False):
        """handle ADF scan results - build the per-ADF table and a summary."""
        self._set_scanning(False)
        from emu68hatcher.data.install_media import get_required_install_media
        from emu68hatcher.data.package_loader import get_adf_rules_for_version

        # reset the ADF tab data; button stays enabled if other tabs have content
        self._adf_rows = []
        self._refresh_details_button()

        if not found_media:
            if truncated:
                self.adf_status.setText(
                    "No ADFs found (scan stopped - too many files, narrow the directories)"
                )
                self.adf_status.setStyleSheet("color: red;")
            else:
                self.adf_status.setText(
                    "No recognized Workbench ADFs found in the configured directories"
                )
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
        self._adf_dialog_title = f"Detected files for Workbench {wb_version}"
        self._refresh_details_button()

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

    def _refresh_details_button(self):
        has_any = bool(self._rom_rows or self._whdload_rows or self._adf_rows)
        self._adf_details_btn.setEnabled(has_any)

    def _show_details(self):
        if not (self._rom_rows or self._whdload_rows or self._adf_rows):
            return
        from emu68hatcher.gui.dialogs import DetectedFilesDialog

        title = (
            self._adf_dialog_title or f"Detected files for Workbench {self.get_selected_version()}"
        )
        dialog = DetectedFilesDialog(
            title=title,
            rom_rows=self._rom_rows,
            whdload_rows=self._whdload_rows,
            adf_rows=self._adf_rows,
            parent=self,
        )
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
            "wb_version": self.get_selected_version(),
            "asset_directories": [
                self.dir_list.item(i).text() for i in range(self.dir_list.count())
            ],
        }

    def set_config(
        self,
        ks_config: KickstartConfig,
        media_config: InstallMediaConfig,
        asset_directories: list[Path] | None = None,
    ):
        """populate the tab from config objects"""
        # install_media drives the Workbench dropdown; 3.9 maps to 3.1 (same ROM, hidden in UI)
        version_to_set = media_config.version.value
        if version_to_set not in _SELECTABLE_VERSIONS:
            version_to_set = KickstartVersion.V3_1.value
        idx = _SELECTABLE_VERSIONS.index(version_to_set)
        self.version_combo.setCurrentIndex(idx)

        # asset_directories wins; fall back to merging legacy single-dir fields for round-trips
        dirs: list[Path | str] = []
        if asset_directories:
            dirs.extend(asset_directories)
        else:
            if ks_config.rom_directory:
                dirs.append(ks_config.rom_directory)
            if media_config.directory and media_config.directory != ks_config.rom_directory:
                dirs.append(media_config.directory)
        self._set_dirs(dirs)
        if dirs:
            self._fire_scans()
