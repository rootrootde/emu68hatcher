"""partition bar - horizontal disk-layout viz with drag-resize"""

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QToolTip, QWidget

from emu68hatcher.config.defaults import MIN_AMIGA_PARTITION_SIZE
from emu68hatcher.config.partition_helpers import round_to_cylinder

BOOT_COLOR = QColor("#546E7A")  # blue-gray
AMIGA_COLORS = [
    QColor("#009688"),  # teal
    QColor("#FF9800"),  # orange
    QColor("#4CAF50"),  # green
    QColor("#9C27B0"),  # purple
    QColor("#F44336"),  # red
    QColor("#3F51B5"),  # indigo
]
FREE_COLOR = QColor("#424242")  # dark gray
SELECTED_BORDER = QColor("#FFEB3B")  # yellow highlight


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024**3:
        return f"{size_bytes / (1024**3):.1f} GB"
    return f"{size_bytes // (1024**2)} MB"


class PartitionBar(QWidget):
    """horizontal bar - proportional partition sizes with drag-resize"""

    GRAB_ZONE = 5  # pixels from border edge that activate resize
    partition_clicked = Signal(int)  # amiga partition index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMaximumHeight(70)
        self.setMouseTracking(True)
        self._segments: list[tuple[str, int, str, QColor, bool]] = []
        self._rects: list[tuple[QRect, str]] = []
        self._on_resize_callback = None  # callable(left_idx, left_size, right_idx, right_size)
        # drag state
        self._borders: list[tuple[int, int, int]] = []
        self._dragging = False
        self._drag_border_idx = -1
        self._drag_start_x = 0
        self._bytes_per_pixel = 1.0
        self._amiga_partitions = []
        self._free_space = 0

    def set_data(
        self, disk_size: int, boot_size: int, amiga_partitions, free_space: int, selected: int = -1
    ):
        self._amiga_partitions = list(amiga_partitions)
        self._free_space = free_space
        self._segments = []
        self._segments.append(("EMU68BOOT", boot_size, "FAT32", BOOT_COLOR, False))
        for i, p in enumerate(amiga_partitions):
            color = AMIGA_COLORS[i % len(AMIGA_COLORS)]
            star = " *" if p.bootable else ""
            sublabel = f"{p.filesystem.value}{star}"
            self._segments.append((p.volume, p.size, sublabel, color, i == selected))
        if free_space > 0:
            self._segments.append(("free", free_space, "", FREE_COLOR, False))
        self.update()

    def _resizable_border(self, seg_idx: int) -> bool:
        """true for amiga|amiga and amiga|free; boot|first-amiga (0|1) is locked"""
        # seg 0 = boot. amiga partitions start at seg 1
        left = seg_idx
        right = seg_idx + 1
        if right >= len(self._segments):
            return False
        if left == 0:
            return False  # boot border not resizable
        return True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w = self.width() - 2
        h = self.height() - 2
        x = 1

        total = sum(s[1] for s in self._segments)
        if total <= 0:
            painter.end()
            return

        self._bytes_per_pixel = total / w if w > 0 else 1.0
        self._rects = []
        self._borders = []
        name_font = QFont()
        name_font.setPointSize(9)
        name_font.setBold(True)
        sub_font = QFont()
        sub_font.setPointSize(8)

        for idx, (label, size, sublabel, color, selected) in enumerate(self._segments):
            seg_w = max(2, int((size / total) * w))
            if x + seg_w > self.width() - 1:
                seg_w = self.width() - 1 - x
            rect = QRect(x, 1, seg_w, h)
            self._rects.append((rect, f"{label}\n{_format_size(size)}\n{sublabel}"))

            painter.fillRect(rect, QBrush(color))

            if selected:
                pen = QPen(SELECTED_BORDER, 2)
                painter.setPen(pen)
                painter.drawRect(rect.adjusted(1, 1, -1, -1))

            painter.setPen(QPen(QColor("#222222"), 1))
            painter.drawRect(rect)

            painter.setPen(QColor("#FFFFFF"))
            text_rect = rect.adjusted(4, 2, -4, -2)
            if seg_w > 80:
                painter.setFont(name_font)
                painter.drawText(
                    text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label
                )
                painter.setFont(sub_font)
                painter.drawText(
                    text_rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                    f"{_format_size(size)}  {sublabel}",
                )
            elif seg_w > 40:
                painter.setFont(sub_font)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

            x += seg_w

            # remember border position for drag detection
            if idx < len(self._segments) - 1 and self._resizable_border(idx):
                self._borders.append((x, idx, idx + 1))

        # drag handles
        arrow = 4
        gap = 2
        mid_y = self.height() // 2
        for bx, _, _ in self._borders:
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
            painter.drawLine(bx, 4, bx, self.height() - 5)

            painter.setBrush(QBrush(QColor("#FFFFFF")))
            painter.setPen(QPen(QColor("#222222"), 1))
            painter.drawPolygon(
                QPolygon(
                    [
                        QPoint(bx - gap, mid_y),
                        QPoint(bx - gap - arrow, mid_y - arrow),
                        QPoint(bx - gap - arrow, mid_y + arrow),
                    ]
                )
            )
            painter.drawPolygon(
                QPolygon(
                    [
                        QPoint(bx + gap, mid_y),
                        QPoint(bx + gap + arrow, mid_y - arrow),
                        QPoint(bx + gap + arrow, mid_y + arrow),
                    ]
                )
            )

        painter.end()

    def _border_at(self, x: int) -> int:
        """index into self._borders near x, else -1"""
        for i, (bx, _, _) in enumerate(self._borders):
            if abs(x - bx) <= self.GRAB_ZONE:
                return i
        return -1

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()

        if self._dragging:
            dx = pos.x() - self._drag_start_x
            delta_bytes = round_to_cylinder(int(dx * self._bytes_per_pixel))
            if delta_bytes == 0:
                return
            _, left_seg, right_seg = self._borders[self._drag_border_idx]
            # left_seg and right_seg are segment indices (0=boot, 1+=amiga, last=free)
            left_amiga = left_seg - 1  # index into amiga_partitions
            right_amiga = right_seg - 1

            left_is_amiga = 0 <= left_amiga < len(self._amiga_partitions)
            right_is_free = (
                right_seg == len(self._segments) - 1 and self._segments[right_seg][0] == "free"
            )
            right_is_amiga = 0 <= right_amiga < len(self._amiga_partitions)

            if left_is_amiga and (right_is_amiga or right_is_free):
                left_size = self._amiga_partitions[left_amiga].size
                if right_is_amiga:
                    right_size = self._amiga_partitions[right_amiga].size
                else:
                    right_size = self._free_space

                new_left = left_size + delta_bytes
                new_right = right_size - delta_bytes

                min_size = round_to_cylinder(MIN_AMIGA_PARTITION_SIZE)
                if right_is_free:
                    # free space can go to 0
                    if new_left < min_size or new_right < 0:
                        return
                else:
                    if new_left < min_size or new_right < min_size:
                        return

                self._amiga_partitions[left_amiga].size = new_left
                if right_is_amiga:
                    self._amiga_partitions[right_amiga].size = new_right

                self._drag_start_x = pos.x()
                if self._on_resize_callback:
                    self._on_resize_callback(
                        left_amiga, new_left, right_amiga if right_is_amiga else -1, new_right
                    )
            return

        # not dragging - update cursor + tooltip
        bi = self._border_at(pos.x())
        if bi >= 0:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            QToolTip.hideText()
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            for rect, tip in self._rects:
                if rect.contains(pos):
                    gpos = (
                        event.globalPosition().toPoint()
                        if hasattr(event, "globalPosition")
                        else self.mapToGlobal(pos)
                    )
                    QToolTip.showText(gpos, tip, self, rect)
                    return
            QToolTip.hideText()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        bi = self._border_at(pos.x())
        if bi >= 0:
            self._dragging = True
            self._drag_border_idx = bi
            self._drag_start_x = pos.x()
            return
        for seg_idx, (rect, _) in enumerate(self._rects):
            if rect.contains(pos):
                amiga_idx = seg_idx - 1
                if 0 <= amiga_idx < len(self._amiga_partitions):
                    self.partition_clicked.emit(amiga_idx)
                return

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._drag_border_idx = -1
