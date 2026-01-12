"""
emu68 Hatcher Qt GUI - Main Window
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QPushButton,
    QFileDialog,
    QMessageBox,
)

from emu68hatcher.config.schema import (
    CustomScreenMode,
    NetworkStack,
    WorkbenchModeType,
    PackageConfig,
    OutputConfig,
    OutputType,
    ScreenModeType,
)
from emu68hatcher.config.defaults import create_default_config
from emu68hatcher.config.loader import save_config, load_config

from emu68hatcher.gui.dialogs import BuildProgressDialog
from emu68hatcher.gui.tabs import (
    StartTab,
    KickstartTab,
    DisplayTab,
    PackagesTab,
    PartitionsTab,
    OutputTab,
)


class MainWindow(QMainWindow):
    """main application window"""

    def __init__(self):
        super().__init__()
        self.config = create_default_config()
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Emu68 Hatcher")
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
        self.tabs.addTab(self.kickstart_tab, "Kickstart")

        self.display_tab = DisplayTab()
        self.tabs.addTab(self.display_tab, "Display")

        self.packages_tab = PackagesTab()
        self.tabs.addTab(self.packages_tab, "Packages")

        # connect version changes to packages tab and display tab
        self.kickstart_tab.version_changed.connect(self.packages_tab.set_kickstart_version)
        self.kickstart_tab.version_changed.connect(self.display_tab.update_icon_sets)

        # initialize display tab with current kickstart version (default is 3.2.3)
        initial_version = self.kickstart_tab.get_selected_version()
        self.display_tab.update_icon_sets(initial_version)
        self.packages_tab.set_kickstart_version(initial_version)

        self.partitions_tab = PartitionsTab()
        self.tabs.addTab(self.partitions_tab, "Partitions")

        self.output_tab = OutputTab()
        self.tabs.addTab(self.output_tab, "Output")

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

    def new_config(self):
        self.config = create_default_config()
        # reset all tabs to default state
        self.kickstart_tab.set_config(self.config.kickstart, self.config.install_media)
        self.display_tab.update_icon_sets(self.config.kickstart.version.value)
        self.display_tab.set_config(self.config.display)
        self.display_tab.set_icon_set(self.config.icon_set)
        self.packages_tab.set_network_stack(self.config.network_stack)
        self.packages_tab.set_config(self.config.packages)
        self.partitions_tab.set_config(self.config.partitions)
        self.output_tab.set_config(self.config.output)
        self.statusBar().showMessage("New configuration created")

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
                self.kickstart_tab.set_config(self.config.kickstart, self.config.install_media)
                self.display_tab.update_icon_sets(self.config.kickstart.version.value)
                self.display_tab.set_config(self.config.display)
                self.display_tab.set_icon_set(self.config.icon_set)
                self.packages_tab.set_network_stack(self.config.network_stack)
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
        """collect configuration from all tabs"""
        from emu68hatcher.config.schema import KickstartVersion, WorkbenchVersion as WBVersion
        import logging
        logger = logging.getLogger("emu68hatcher")

        ks = self.kickstart_tab.get_config()
        logger.debug(f"Kickstart tab config: {ks}")
        self.config.kickstart.version = KickstartVersion(ks["version"])
        self.config.kickstart.rom_directory = Path(ks["rom_directory"]) if ks["rom_directory"] else None

        # workbench install media settings
        wb_version_map = {
            "3.1": WBVersion.V3_1,
            "3.2": WBVersion.V3_2,
            "3.2.2.1": WBVersion.V3_2_2_1,
            "3.2.3": WBVersion.V3_2_3,
            "3.9": WBVersion.V3_9,
        }
        self.config.install_media.version = wb_version_map.get(ks.get("wb_version", "3.1"), WBVersion.V3_1)
        adf_dir = ks.get("adf_directory", "")
        logger.debug(f"ADF directory from GUI: '{adf_dir}' (truthy={bool(adf_dir)})")
        self.config.install_media.directory = Path(adf_dir) if adf_dir else None
        logger.debug(f"Set install_media.directory to: {self.config.install_media.directory}")

        disp = self.display_tab.get_config()
        logger.debug(f"Display tab returned: {disp}")

        # set HDMI output mode
        hdmi_mode = disp.get("hdmi_mode", "1280*720-50")
        self.config.display.hdmi_mode = hdmi_mode

        # also set legacy screen_mode for compatibility
        if "50" in hdmi_mode:
            self.config.display.screen_mode = ScreenModeType.PAL
        elif "60" in hdmi_mode:
            self.config.display.screen_mode = ScreenModeType.NTSC
        elif hdmi_mode == "Custom":
            self.config.display.screen_mode = ScreenModeType.CUSTOM

        # store custom HDMI resolution if applicable
        if hdmi_mode == "Custom":
            self.config.display.custom = CustomScreenMode(
                width=disp["width"],
                height=disp["height"],
                framerate=60,
            )

        # store Workbench display settings (use RTG defaults)
        self.config.display.workbench.mode_type = WorkbenchModeType.RTG
        self.config.display.workbench.screen_mode = "VideoCore:1280x720 32bit BGRA"
        self.config.display.workbench.mode_id = ""
        self.config.display.workbench.width = 1280
        self.config.display.workbench.height = 720
        self.config.display.workbench.color_depth = 24
        self.config.display.workbench.backdrop = True

        # store icon set selection
        self.config.icon_set = disp.get("icon_set", "Standard")

        pkgs = self.packages_tab.get_config()
        self.config.packages = [
            PackageConfig(name=p["name"], enabled=p["enabled"])
            for p in pkgs
        ]
        self.config.network_stack = self.packages_tab.get_network_stack()

        out = self.output_tab.get_config()
        if out["path"]:
            self.config.output = OutputConfig(
                type=OutputType.DISK if out["type"] == "disk" else OutputType.IMG,
                path=Path(out["path"]),
            )

        # partition config from editor
        self.config.partitions = self.partitions_tab.get_config()

    def build_image(self):
        self.collect_config()

        # validation
        if not self.config.kickstart.rom_directory:
            QMessageBox.warning(self, "Missing ROM Directory", "Please select a directory containing Kickstart ROM files.")
            return

        rom_dir = Path(self.config.kickstart.rom_directory)
        if not rom_dir.exists():
            QMessageBox.warning(self, "Directory Not Found", f"ROM directory not found:\n{rom_dir}")
            return

        # check if a matching ROM exists
        from emu68hatcher.data.rom_detection import find_kickstart_for_version
        rom_path = find_kickstart_for_version(rom_dir, self.config.kickstart.version.value)
        if not rom_path:
            QMessageBox.warning(
                self,
                "ROM Not Found",
                f"No Kickstart {self.config.kickstart.version.value} ROM found in:\n{rom_dir}"
            )
            return

        if not self.config.output or not self.config.output.path:
            QMessageBox.warning(self, "Missing Output", "Please select an output location.")
            return

        # check if HST Imager is available
        from emu68hatcher.utils.platform import find_hst_imager
        if not find_hst_imager():
            reply = QMessageBox.question(
                self,
                "Tools Required",
                "HST Imager is required but not installed.\n\n"
                "Download the required tools now?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
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
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        # launch build dialog
        dialog = BuildProgressDialog(self.config, self)
        dialog.start_build()
        dialog.exec()

        # show result
        if dialog.worker and not dialog.worker.isRunning():
            self.statusBar().showMessage("Build complete" if dialog.progress_bar.value() == 100 else "Build cancelled or failed")

    def show_about(self):
        QMessageBox.about(
            self,
            "About Emu68 Hatcher",
            "Emu68 Hatcher\n\n"
            "Create bootable Amiga disk images for PiStorm/Emu68.\n\n"
            "Version 0.1.0\n"
            "https://github.com/mja65/Emu68-Hatcher-Software"
        )


def launch_gui():
    """launch the Qt GUI application"""
    app = QApplication(sys.argv)
    app.setApplicationName("Emu68 Hatcher")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    launch_gui()
