"""custom Qt widgets reused across tabs"""

from PySide6.QtWidgets import QComboBox


def select_combo_by_data(combo: QComboBox, value) -> None:
    """pick the combo item whose data() == value; no-op if not found"""
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return
