"""Qt main window"""

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from emu68hatcher import __version__
from emu68hatcher.builder.staging.scripts.generator import render_boot_partition_files
from emu68hatcher.config.boot_models import Emu68BootSettings
from emu68hatcher.config.defaults import create_default_config
from emu68hatcher.config.display_models import CustomScreenMode
from emu68hatcher.config.loader import load_config, save_config
from emu68hatcher.config.schema import (
    CURRENT_CONFIG_VERSION,
    BuildConfig,
)
from emu68hatcher.data.rom_detection import identify_kickstart
from emu68hatcher.gui.dialogs import BuildProgressDialog
from emu68hatcher.gui.tabs import (
    DisplayTab,
    Emu68Tab,
    KickstartTab,
    NetworkTab,
    OutputTab,
    PackagesTab,
    PartitionsTab,
    StartTab,
)


class MainWindow(QMainWindow):
    """main app window"""

    def __init__(self):
        super().__init__()
        self.config = create_default_config()
        self.setup_ui()
        self.resize(1400, 800)

    def setup_ui(self):
        self.setWindowTitle(f"Emu68 Hatcher {__version__}")
        self.setMinimumSize(800, 600)

        # central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # tab widget
        self.tabs = QTabWidget()

        self.start_tab = StartTab()
        self.tabs.addTab(self.start_tab, "Start")

        self.kickstart_tab = KickstartTab()
        self.tabs.addTab(self.kickstart_tab, "Amiga Files")

        self.emu68_tab = Emu68Tab()
        self.tabs.addTab(self.emu68_tab, "Emu68")

        self.display_tab = DisplayTab()
        self.tabs.addTab(self.display_tab, "Display")

        # kickstart + emu68 both gate packages (the resolver filters on both);
        # seed them here so the initial tree is built once, already filtered
        self.packages_tab = PackagesTab(
            kickstart_version=self.kickstart_tab.get_selected_version(),
            emu68_version=self.emu68_tab.get_emu68_version().value,
        )
        self.tabs.addTab(self.packages_tab, "Software")

        self.network_tab = NetworkTab()
        self.tabs.addTab(self.network_tab, "Network")

        self.kickstart_tab.version_changed.connect(self.packages_tab.set_kickstart_version)
        self.emu68_tab.emu68_version_changed.connect(self.packages_tab.set_emu68_version)
        self.emu68_tab.settings_changed.connect(self._refresh_boot_files_preview)
        self.display_tab.settings_changed.connect(self._refresh_boot_files_preview)

        self.output_tab = OutputTab()
        self.tabs.addTab(self.output_tab, "Output")

        self.partitions_tab = PartitionsTab()
        self.tabs.addTab(self.partitions_tab, "Partitions")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # output mode + selected disk drives partition sizing in DEVICE/flash modes
        self.output_tab.target_size_changed.connect(self.partitions_tab.set_auto_disk_size)
        self.output_tab.target_size_cleared.connect(self.partitions_tab.clear_auto_disk_size)
        self.output_tab.target_restore_complete.connect(self._on_output_target_restored)
        self._pending_loaded_partitions = None

        layout.addWidget(self.tabs)

        # bottom buttons
        btn_layout = QHBoxLayout()

        self.load_btn = QPushButton("Load Config...")
        self.load_btn.clicked.connect(self.open_config)
        btn_layout.addWidget(self.load_btn)

        self.save_btn = QPushButton("Save Config...")
        self.save_btn.clicked.connect(self.save_config_file)
        btn_layout.addWidget(self.save_btn)

        btn_layout.addStretch()

        self.build_btn = QPushButton("Build Image")
        self.build_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.build_btn.clicked.connect(self.build_image)
        btn_layout.addWidget(self.build_btn)

        layout.addLayout(btn_layout)

        # status bar
        self.statusBar().showMessage("Ready")
        self._refresh_boot_files_preview()

    def closeEvent(self, event):
        running = []
        for label, tab in (
            ("asset scans", self.kickstart_tab),
            ("disk scan", self.output_tab),
            ("tool download", self.start_tab),
        ):
            if not tab.shutdown_workers():
                running.append(label)
        if running:
            self.statusBar().showMessage("Waiting for " + ", ".join(running))
            event.ignore()
            return
        super().closeEvent(event)

    def open_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Configuration",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            try:
                self.config = load_config(Path(path))
                # populate all tabs from loaded config
                self.kickstart_tab.set_config(
                    self.config.kickstart,
                    self.config.install_media,
                    asset_directories=list(self.config.asset_directories),
                )
                self.display_tab.set_config(self.config.display)
                self.display_tab.set_picasso96_archive(self.config.display.picasso96_archive)
                self.emu68_tab.set_emu68_version(self.config.emu68_version)
                self.emu68_tab.set_settings(self.config.emu68_boot)
                self.display_tab.set_emu68_boot_settings(self.config.emu68_boot)
                self.packages_tab.set_kickstart_version(self.config.kickstart.version.value)
                # set_config above already repopulated the icon list for the loaded version
                self.kickstart_tab.set_icon_set(self.config.icon_set)
                self.network_tab.set_network_stack(self.config.network_stack)
                self.network_tab.set_wifi_config(self.config.wifi)
                self.network_tab.set_roadshow_archive(self.config.roadshow_archive)
                self.network_tab.set_miamidx_key_directory(self.config.miamidx_key_directory)
                self.network_tab.set_network_settings(self.config.network)
                self.packages_tab.set_config(self.config.packages)
                self.kickstart_tab.set_locale(self.config.packages)
                self._pending_loaded_partitions = self.config.partitions
                self.output_tab.set_config(self.config.output)
                self.statusBar().showMessage(f"Loaded: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load config: {e}")

    def _on_output_target_restored(self):
        config = self._pending_loaded_partitions
        self._pending_loaded_partitions = None
        if config is not None:
            self.partitions_tab.set_config(config)

    def save_config_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Configuration",
            "emu68-config.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return  # user cancelled

        try:
            self.collect_config()
            save_config(self.config, Path(path))
            self.statusBar().showMessage(f"Saved: {path}")
        except Exception as e:
            import traceback

            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to save config: {e}")

    def _current_boot_rom_filename(self) -> str:
        for status, _name, _version, _model, path in self.kickstart_tab.asset_panel.results["roms"]:
            if status != "boot":
                continue
            info = identify_kickstart(Path(path))
            if info and info.get("fat32_name"):
                return info["fat32_name"]
            break
        return "kick.rom"

    def _render_boot_files_preview(self) -> dict[str, str]:
        display = self.display_tab.get_config()
        screen_mode = display.get("hdmi_mode") or "1280*720-50"
        custom_cvt = ""
        if screen_mode == "Custom":
            custom_cvt = CustomScreenMode(
                width=display["width"],
                height=display["height"],
                framerate=display["framerate"],
                aspect_ratio=display["aspect_ratio"],
                margins=display["margins"],
                interlace=display["interlace"],
                reduced_blanking=display["reduced_blanking"],
            ).to_cvt_string()

        boot_settings = self._collect_emu68_boot_settings()
        usb_otg = any(
            package["name"] == "poseidon" and package["enabled"]
            for package in self.packages_tab.get_config()
        )
        return render_boot_partition_files(
            screen_mode=screen_mode,
            custom_cvt=custom_cvt,
            rom_filename=self._current_boot_rom_filename(),
            emu68_version=self.emu68_tab.get_emu68_version().value,
            usb_otg=usb_otg,
            boot_settings=boot_settings,
        )

    def _collect_emu68_boot_settings(self) -> Emu68BootSettings:
        settings = self.emu68_tab.get_settings()
        settings["config_txt"].update(self.display_tab.get_emu68_boot_settings())
        return Emu68BootSettings.model_validate(settings)

    def _refresh_boot_files_preview(self):
        try:
            files = self._render_boot_files_preview()
        except Exception as error:
            self.emu68_tab.set_preview_error(f"Preview unavailable:\n{error}")
            return
        self.emu68_tab.set_preview_files(files)

    def _on_tab_changed(self, index: int):
        if self.tabs.widget(index) is self.emu68_tab:
            self._refresh_boot_files_preview()

    def collect_config(self):
        """Validate a fresh config assembled from all tabs."""
        import logging

        logger = logging.getLogger("emu68hatcher")

        ks = self.kickstart_tab.get_config()
        logger.debug(f"Kickstart tab config: {ks}")
        asset_dirs = ks.get("asset_directories", []) or []
        asset_directories = [Path(p) for p in asset_dirs if str(p).strip()]
        logger.debug(f"Asset directories: {asset_directories}")

        disp = self.display_tab.get_config()
        logger.debug(f"Display tab returned: {disp}")
        hdmi_mode = disp.get("hdmi_mode", "1280*720-50")
        custom = None
        if hdmi_mode == "Custom":
            custom = {
                "width": disp["width"],
                "height": disp["height"],
                "framerate": disp.get("framerate", 60),
                "aspect_ratio": disp.get("aspect_ratio", 3),
                "margins": disp.get("margins", False),
                "interlace": disp.get("interlace", False),
                "reduced_blanking": disp.get("reduced_blanking", False),
            }

        pkgs = (
            self.packages_tab.get_config()
            + self.network_tab.extra_package_entries()
            + self.kickstart_tab.get_locale_entries()
        )
        out = self.output_tab.get_config()
        output = None
        if out.get("path"):
            output = {
                "type": out.get("type", "img"),
                "path": out["path"],
                "sparse": out.get("sparse", True),
                "flash_target": out.get("flash_target"),
            }

        wifi = self.network_tab.get_wifi_config()
        network = self.network_tab.get_network_settings()
        partitions = self.partitions_tab.get_config()
        data = {
            "version": CURRENT_CONFIG_VERSION,
            "kickstart": {"version": ks["version"], "rom_directory": None},
            "install_media": {"directory": None},
            "asset_directories": asset_directories,
            "display": {
                "hdmi_mode": hdmi_mode,
                "custom": custom,
                "workbench_mode": disp.get("workbench_mode", "videocore_1280x720"),
                "picasso96_archive": self.display_tab.get_picasso96_archive(),
            },
            "packages": pkgs,
            "icon_set": self.kickstart_tab.get_icon_set(),
            "partitions": partitions.model_dump(mode="python"),
            "output": output,
            "network_stack": self.network_tab.get_network_stack(),
            "roadshow_archive": self.network_tab.get_roadshow_archive(),
            "miamidx_key_directory": self.network_tab.get_miamidx_key_directory(),
            "wifi": wifi.model_dump(mode="python") if wifi else None,
            "network": network.model_dump(mode="python"),
            "emu68_version": self.emu68_tab.get_emu68_version(),
            "emu68_boot": self._collect_emu68_boot_settings().model_dump(mode="python"),
        }
        config = BuildConfig.model_validate(data)
        self.config = config
        return config

    def build_image(self):
        try:
            self.collect_config()
        except Exception as e:
            # config validation (e.g. a malformed static IP) raises here - surface it cleanly
            QMessageBox.warning(self, "Invalid Configuration", str(e))
            return

        # a typed SSID that yields no wifi config means the password was too short to keep
        if self.network_tab.wifi_ssid.text().strip() and self.config.wifi is None:
            QMessageBox.warning(
                self,
                "WiFi Password",
                "Enter a WiFi password of 8-63 characters, or leave it empty for an open network.",
            )
            return

        # validation
        if not self.config.asset_directories:
            QMessageBox.warning(
                self,
                "Missing Asset Directories",
                "Add at least one directory containing Kickstart ROMs and Workbench ADFs.",
            )
            return

        existing_dirs = [Path(d) for d in self.config.asset_directories if Path(d).exists()]
        if not existing_dirs:
            missing = "\n".join(str(d) for d in self.config.asset_directories)
            QMessageBox.warning(
                self, "Directories Not Found", f"None of the asset directories exist:\n{missing}"
            )
            return

        # check if matching ROM exists across the configured dirs
        from emu68hatcher.data.rom_detection import find_kickstart_for_version

        rom_path = find_kickstart_for_version(existing_dirs, self.config.kickstart.version.value)
        if not rom_path:
            dirs_str = "\n  ".join(str(d) for d in existing_dirs)
            QMessageBox.warning(
                self,
                "ROM Not Found",
                f"No Kickstart {self.config.kickstart.version.value} ROM found in:\n  {dirs_str}",
            )
            return

        if not self.config.output or not self.config.output.path:
            QMessageBox.warning(self, "Missing Output", "Please select an output location.")
            return

        # check if HST Imager is available
        from emu68hatcher.utils.host_tools import find_hst_imager

        if not find_hst_imager():
            reply = QMessageBox.question(
                self,
                "Tools Required",
                "HST Imager is required but not installed.\n\nDownload the required tools now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.tabs.setCurrentWidget(self.start_tab)
                self.start_tab.refresh_status()
                self.start_tab.start_download()
            return

        # confirm build
        target_line = ""
        if self.config.output.flash_target:
            target_line = f"Flash target: {self.config.output.flash_target}\n"
        reply = QMessageBox.question(
            self,
            "Start Build",
            f"Ready to build disk image.\n\n"
            f"Output: {self.config.output.path}\n"
            f"{target_line}"
            f"Size: {self.config.partitions.disk_size // (1024**3)} GB\n\n"
            "This may take several minutes. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # launch build dialog; lock the button so a double-click cannot spawn a second worker
        self.build_btn.setEnabled(False)
        try:
            dialog = BuildProgressDialog(self.config, self)
            dialog.start_build()
            dialog.exec()
        finally:
            self.build_btn.setEnabled(True)

        self.statusBar().showMessage(
            "Build complete" if dialog.success else "Build cancelled or failed"
        )


def launch_gui():
    """start the Qt app"""
    app = QApplication(sys.argv)
    app.setApplicationName("Emu68 Hatcher")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    launch_gui()
