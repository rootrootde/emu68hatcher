"""start tab - welcome screen and required-tool setup"""

import os
import stat
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


_TOOL_ROWS = [
    ("HST-Imager", "Disk image creation and manipulation"),
    ("HST-Amiga", "Amiga filesystem tools"),
    ("7z", "Archive extraction (p7zip)"),
]


class StartTab(QWidget):
    """welcome screen with tool-status table and download button"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._row_widgets: dict[str, tuple[QLabel, QLabel]] = {}
        self._setup_ui()
        self.refresh_status()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # welcome header
        title = QLabel("Welcome to Emu68 Hatcher")
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(title)

        subtitle = QLabel(
            "Create bootable SD card images for PiStorm/Emu68 Amiga systems.<br>"
            "Configure your build using the tabs above and click "
            "<b>Build Image</b> when ready."
        )
        subtitle.setWordWrap(True)
        subtitle.setTextFormat(Qt.TextFormat.RichText)
        subtitle.setStyleSheet("color: #aaa;")
        subtitle.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(subtitle)

        # horizontal divider between welcome area and tool status
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(divider)
        layout.addSpacing(8)

        # tool status group
        tools_group = QGroupBox("Required Tools")
        tools_layout = QVBoxLayout(tools_group)
        tools_layout.setSpacing(12)

        for name, description in _TOOL_ROWS:
            row = QHBoxLayout()
            row.setSpacing(10)

            status_label = QLabel("…")
            status_label.setFixedWidth(24)
            status_label.setAlignment(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
            )

            text_col = QVBoxLayout()
            text_col.setSpacing(2)

            name_label = QLabel(f"<b>{name}</b> - {description}")
            name_label.setTextFormat(Qt.TextFormat.RichText)
            name_label.setWordWrap(True)

            path_label = QLabel("")
            path_label.setStyleSheet("color: #888; font-size: 11px;")
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )

            text_col.addWidget(name_label)
            text_col.addWidget(path_label)

            row.addWidget(status_label)
            row.addLayout(text_col, 1)
            tools_layout.addLayout(row)

            self._row_widgets[name] = (status_label, path_label)

        # buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_status)
        btn_row.addWidget(self.refresh_btn)

        self.download_btn = QPushButton("Download Missing Tools…")
        self.download_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold;"
        )
        self.download_btn.clicked.connect(self.start_download)
        btn_row.addWidget(self.download_btn)

        tools_layout.addLayout(btn_row)
        layout.addWidget(tools_group)

        # download progress group (hidden until a download starts)
        self.progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(self.progress_group)

        self.progress_status = QLabel("")
        progress_layout.addWidget(self.progress_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(self.progress_group)
        self.progress_group.setVisible(False)

        # CLI helper (frozen builds only - source checkouts already have the
        # `emu68-hatcher` entry point via `pip install -e`)
        if getattr(sys, "frozen", False) and sys.platform in ("darwin", "linux"):
            cli_group = QGroupBox("Command Line Interface")
            cli_layout = QVBoxLayout(cli_group)

            cli_desc = QLabel(
                "Install a <code>emu68-hatcher</code> helper to "
                "<code>~/.local/bin/</code> so you can drive builds from the "
                "terminal. Useful for scripting and advanced workflows."
            )
            cli_desc.setWordWrap(True)
            cli_desc.setTextFormat(Qt.TextFormat.RichText)
            cli_desc.setStyleSheet("color: #aaa;")
            cli_layout.addWidget(cli_desc)

            cli_btn_row = QHBoxLayout()
            cli_btn_row.addStretch()
            self.install_cli_btn = QPushButton("Install CLI helper…")
            self.install_cli_btn.clicked.connect(self._install_cli_helper)
            cli_btn_row.addWidget(self.install_cli_btn)
            cli_layout.addLayout(cli_btn_row)

            layout.addWidget(cli_group)

        layout.addStretch()

    # ------------------------------------------------------------------
    # tool status
    # ------------------------------------------------------------------

    @Slot()
    def refresh_status(self):
        """re-query tool install state and repaint the rows"""
        from emu68hatcher.builder.tools import check_tools, get_tool_path

        status = check_tools()
        any_missing = False

        for name, _ in _TOOL_ROWS:
            installed = status.get(name, False)
            status_label, path_label = self._row_widgets[name]
            if installed:
                path = get_tool_path(
                    "7z" if name == "7z" else name.lower()
                )
                status_label.setText("✅")
                path_label.setText(str(path) if path else "installed")
            else:
                status_label.setText("❌")
                path_label.setText("not installed")
                any_missing = True

        self.download_btn.setEnabled(any_missing)
        self.download_btn.setText(
            "Download Missing Tools…" if any_missing else "All Tools Installed"
        )

    # ------------------------------------------------------------------
    # download flow
    # ------------------------------------------------------------------

    @Slot()
    def start_download(self):
        from emu68hatcher.gui.workers import ToolDownloadWorker

        if self._worker and self._worker.isRunning():
            return

        self.download_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.progress_group.setVisible(True)
        self.progress_status.setText("Preparing download…")
        self.progress_bar.setValue(0)

        self._worker = ToolDownloadWorker(self)
        self._worker.tool_started.connect(self._on_tool_started)
        self._worker.tool_progress.connect(self._on_tool_progress)
        self._worker.tool_finished.connect(self._on_tool_finished)
        self._worker.download_finished.connect(self._on_download_finished)
        self._worker.start()

    @Slot(str)
    def _on_tool_started(self, tool_name: str):
        self.progress_status.setText(f"Downloading {tool_name}…")
        self.progress_bar.setValue(0)

    @Slot(str, int, int)
    def _on_tool_progress(self, tool_name: str, downloaded: int, total: int):
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(min(pct, 100))
            mb_down = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.progress_status.setText(
                f"Downloading {tool_name} - {mb_down:.1f} / {mb_total:.1f} MB"
            )
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate
            self.progress_status.setText(f"Downloading {tool_name}…")

    @Slot(str, bool)
    def _on_tool_finished(self, tool_name: str, success: bool):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)

    @Slot(bool, list)
    def _on_download_finished(self, success: bool, failed: list):
        self.refresh_btn.setEnabled(True)
        self.refresh_status()

        if success:
            self.progress_status.setText("All tools downloaded successfully.")
            self.progress_bar.setValue(100)
        else:
            failed_list = ", ".join(failed) if failed else "one or more tools"
            hint = ""
            if "7z" in failed:
                hint = " (macOS: install with <code>brew install p7zip</code>)"
            self.progress_status.setText(
                f"Failed to download: {failed_list}.{hint}"
            )
            self.progress_status.setTextFormat(Qt.TextFormat.RichText)

    # ------------------------------------------------------------------
    # CLI helper install
    # ------------------------------------------------------------------

    @Slot()
    def _install_cli_helper(self):
        """write ~/.local/bin/emu68-hatcher shell wrapper that execs the
        frozen binary. shows install result and PATH hint if needed
        """
        binary = Path(sys.executable).resolve()
        bin_dir = Path.home() / ".local" / "bin"
        target = bin_dir / "emu68-hatcher"

        try:
            bin_dir.mkdir(parents=True, exist_ok=True)
            script = (
                "#!/bin/sh\n"
                "# Emu68 Hatcher CLI helper - generated by the GUI.\n"
                f'exec "{binary}" "$@"\n'
            )
            target.write_text(script)
            target.chmod(
                target.stat().st_mode
                | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Install Failed",
                f"Could not write {target}:\n\n{exc}",
            )
            return

        path_env = os.environ.get("PATH", "")
        on_path = str(bin_dir) in path_env.split(os.pathsep)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("CLI Helper Installed")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(f"Installed <code>emu68-hatcher</code> to <code>{target}</code>.")
        if on_path:
            msg.setInformativeText(
                "You can now run <code>emu68-hatcher --help</code> in a new "
                "terminal window."
            )
        else:
            shell = Path(os.environ.get("SHELL", "/bin/zsh")).name
            rc_file = {
                "zsh": "~/.zshrc",
                "bash": "~/.bashrc",
                "fish": "~/.config/fish/config.fish",
            }.get(shell, "your shell rc file")
            export_line = 'export PATH="$HOME/.local/bin:$PATH"'
            msg.setInformativeText(
                f"<b>~/.local/bin is not on your PATH.</b> Add this line to "
                f"<code>{rc_file}</code> and open a new terminal:<br><br>"
                f"<code>{export_line}</code>"
            )
        msg.exec()

    # ------------------------------------------------------------------
    # config hooks (Start tab doesn't touch config, but keeps the API)
    # ------------------------------------------------------------------

    def set_config(self, _config):
        return

    def get_config(self):
        return None
