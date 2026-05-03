"""GUI entry point"""

import sys


def run():
    try:  # frozen builds use fbs ApplicationContext
        from fbs_runtime.application_context.PySide6 import ApplicationContext

        class AppContext(ApplicationContext):
            def run(self):
                from emu68hatcher.gui.main_window import MainWindow

                self.window = MainWindow()
                self.window.show()
                return self.app.exec()

        sys.exit(AppContext().run())
    except ImportError:
        from emu68hatcher.gui.main_window import launch_gui

        launch_gui()
