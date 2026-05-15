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
from emu68hatcher.config.defaults import create_default_config
from emu68hatcher.config.loader import load_config, save_config
from emu68hatcher.config.schema import (
    CustomScreenMode,
    OutputConfig,
    PackageConfig,
)
from emu68hatcher.gui.dialogs import BuildProgressDialog
from emu68hatcher.gui.tabs import (
    Emu68Tab,
    KickstartTab,
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

        self.packages_tab = PackagesTab()
        self.tabs.addTab(self.packages_tab, "Software")

        # connect version changes - packages tab now also owns the icon set selector
        self.kickstart_tab.version_changed.connect(self.packages_tab.set_kickstart_version)

        # initialize packages tab with current kickstart version (default is 3.2.3)
        initial_version = self.kickstart_tab.get_selected_version()
        self.packages_tab.set_kickstart_version(initial_version)

        self.output_tab = OutputTab()
        self.tabs.addTab(self.output_tab, "Output")

        self.partitions_tab = PartitionsTab()
        self.tabs.addTab(self.partitions_tab, "Partitions")

        # output mode + selected disk drives partition sizing in DEVICE/flash modes
        self.output_tab.target_size_changed.connect(self.partitions_tab.set_auto_disk_size)
        self.output_tab.target_size_cleared.connect(self.partitions_tab.clear_auto_disk_size)

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

    def open_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Configuration",
            "",
            "JSON Files (*.json);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
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
                self.emu68_tab.set_config(self.config.display)
                self.emu68_tab.set_emu68_version(self.config.emu68_version)
                self.packages_tab.set_kickstart_version(self.config.kickstart.version.value)
                self.packages_tab.set_icon_set(self.config.icon_set)
                self.packages_tab.set_network_stack(self.config.network_stack)
                self.packages_tab.set_wifi_config(self.config.wifi)
                self.packages_tab.set_roadshow_archive(self.config.roadshow_archive)
                self.packages_tab.set_config(self.config.packages)
                self.partitions_tab.set_config(self.config.partitions)
                self.output_tab.set_config(self.config.output)
                self.statusBar().showMessage(f"Loaded: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load config: {e}")

    def save_config_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Configuration",
            "emu68-config.json",
            "JSON Files (*.json);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
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

    def collect_config(self):
        """pull config from all tabs into self.config"""
        import logging

        from emu68hatcher.config.schema import KickstartVersion

        logger = logging.getLogger("emu68hatcher")

        ks = self.kickstart_tab.get_config()
        logger.debug(f"Kickstart tab config: {ks}")
        self.config.kickstart.version = KickstartVersion(ks["version"])
        # legacy single-dir fields go away in favour of asset_directories
        self.config.kickstart.rom_directory = None

        # str-enum constructs from the raw version; fall back to 3.1 on unknown
        try:
            self.config.install_media.version = KickstartVersion(ks.get("wb_version", "3.1"))
        except ValueError:
            self.config.install_media.version = KickstartVersion.V3_1
        self.config.install_media.directory = None

        # asset_directories is the single source of truth - scanned for both ROMs and ADFs
        asset_dirs = ks.get("asset_directories", []) or []
        self.config.asset_directories = [Path(p) for p in asset_dirs if str(p).strip()]
        logger.debug(f"Asset directories: {self.config.asset_directories}")

        disp = self.emu68_tab.get_config()
        logger.debug(f"Emu68 tab returned: {disp}")

        # set HDMI output mode
        hdmi_mode = disp.get("hdmi_mode", "1280*720-50")
        self.config.display.hdmi_mode = hdmi_mode

        # store custom HDMI resolution if applicable
        if hdmi_mode == "Custom":
            self.config.display.custom = CustomScreenMode(
                width=disp["width"],
                height=disp["height"],
                framerate=disp.get("framerate", 60),
            )

        # selected Emu68 release
        self.config.emu68_version = self.emu68_tab.get_emu68_version()

        # icon set
        self.config.icon_set = self.packages_tab.get_icon_set()

        pkgs = self.packages_tab.get_config()
        self.config.packages = [PackageConfig(name=p["name"], enabled=p["enabled"]) for p in pkgs]
        self.config.network_stack = self.packages_tab.get_network_stack()
        self.config.wifi = self.packages_tab.get_wifi_config()
        self.config.roadshow_archive = self.packages_tab.get_roadshow_archive()

        out = self.output_tab.get_config()
        if out.get("path"):
            self.config.output = OutputConfig(
                type=out.get("type", "img"),
                path=Path(out["path"]),
                sparse=out.get("sparse", True),
                flash_target=out.get("flash_target"),
            )
        else:
            # device / flash mode without a selected disk - clear stale config
            self.config.output = None

        self.config.partitions = self.partitions_tab.get_config()

    def build_image(self):
        self.collect_config()

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
        reply = QMessageBox.question(
            self,
            "Start Build",
            f"Ready to build disk image.\n\n"
            f"Output: {self.config.output.path}\n"
            f"Size: {self.config.partitions.disk_size // (1024**3)} GB\n\n"
            "This may take several minutes. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # launch build dialog; lock the button so a double-click cant spawn a second worker
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
