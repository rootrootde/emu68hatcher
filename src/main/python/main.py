"""
emu68 Hatcher entry point

dispatches between GUI and CLI based on argv:

- launched with no extra args (Finder double-click, .desktop file, etc.)
  → GUI mode. qt/PySide6 is imported lazily inside this branch so CLI runs
  never pay the ~1-2 s startup cost.

- launched with one or more args → CLI mode via emu68hatcher.cli.main:cli.

works both standalone and with fbs bundling.
"""

import os
import sys


def _augment_path_for_gui_launch():
    """GUI apps launched from Finder inherit a minimal PATH from launchd and
    don't see Homebrew/MacPorts tools like 7z. prepend the common locations
    so shutil.which() and subprocess spawns find them"""
    if sys.platform != "darwin":
        return
    extras = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
        "/opt/local/bin",
        "/opt/local/sbin",
    ]
    current = os.environ.get("PATH", "").split(os.pathsep)
    for p in extras:
        if p not in current:
            current.insert(0, p)
    os.environ["PATH"] = os.pathsep.join(current)


def _run_cli():
    """run the Click CLI with argv[1:]"""
    from emu68hatcher.cli.main import cli
    cli.main(args=sys.argv[1:], prog_name="emu68-hatcher", standalone_mode=True)


def _run_gui():
    """launch the Qt GUI. qt is imported here so CLI mode never loads it"""
    try:
        from fbs_runtime.application_context.PySide6 import ApplicationContext

        class AppContext(ApplicationContext):
            def run(self):
                from emu68hatcher.gui.main_window import MainWindow
                self.window = MainWindow()
                self.window.show()
                return self.app.exec()

        appctxt = AppContext()
        sys.exit(appctxt.run())

    except ImportError:
        # fall back to standalone PySide6 (for development)
        from emu68hatcher.gui.main_window import launch_gui
        launch_gui()


def main():
    _augment_path_for_gui_launch()

    if len(sys.argv) > 1:
        _run_cli()
    else:
        _run_gui()


if __name__ == "__main__":
    main()
