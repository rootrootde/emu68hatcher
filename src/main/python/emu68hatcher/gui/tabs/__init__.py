"""GUI tab widgets for the main window"""

from emu68hatcher.gui.tabs.emu68 import Emu68Tab
from emu68hatcher.gui.tabs.kickstart import KickstartTab
from emu68hatcher.gui.tabs.output import OutputTab
from emu68hatcher.gui.tabs.packages import PackagesTab
from emu68hatcher.gui.tabs.partitions import PartitionsTab
from emu68hatcher.gui.tabs.start import StartTab

__all__ = [
    "StartTab",
    "KickstartTab",
    "Emu68Tab",
    "PackagesTab",
    "PartitionsTab",
    "OutputTab",
]
