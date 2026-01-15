from __future__ import annotations

import time
from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget, QSizePolicy


class HeartMonitorWidget(QWidget):
    def __init__(self, parent=None, window_sec: float = 10.0, y_min: float = 0.0, y_max: float = 200.0):
        super().__init__(parent)
        self.window_sec = float(window_sec)
        self.y_min = float(y_min)
        self.y_max = float(y_max)
        self._points: List[Tuple[float, float]] = []

        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_points(self, points: List[Tuple[float, float]]):
        self._points = points
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(12, 12, -12, -12)

        # grid
        grid_pen = QPen(Qt.black)
        grid_pen.setWidth(1)
        grid_pen.setStyle(Qt.DotLine)
        painter.setPen(grid_pen)

        for i in range(1, 4):
            y = rect.top() + rect.height() * i / 4.0
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

        if len(self._points) < 2:
            painter.end()
            return

        now = time.time()
        start = now - self.window_sec
        visible = [(t, hr) for (t, hr) in self._points if t >= start]
        if len(visible) < 2:
            painter.end()
            return

        y_min = self.y_min
        y_max = self.y_max
        if y_max - y_min < 1e-6:
            y_max = y_min + 1.0

        line_pen = QPen(Qt.black)
        line_pen.setWidth(3)
        line_pen.setCapStyle(Qt.RoundCap)
        line_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(line_pen)

        def map_x(t: float) -> float:
            return rect.left() + (t - start) / self.window_sec * rect.width()

        def map_y(hr: float) -> float:
            hr = max(y_min, min(y_max, hr))
            return rect.bottom() - (hr - y_min) / (y_max - y_min) * rect.height()

        for i in range(1, len(visible)):
            x1 = map_x(visible[i - 1][0])
            y1 = map_y(visible[i - 1][1])
            x2 = map_x(visible[i][0])
            y2 = map_y(visible[i][1])
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        painter.end()
