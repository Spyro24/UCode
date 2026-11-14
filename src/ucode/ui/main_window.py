"""The application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMenu, QSplitter, QWidget

from ucode.ui.right_panel import RightPanel
from ucode.ui.sidebar import SideBar


class MainWindow(QMainWindow):
    """Application window.

    Layout: menu bar on top, tile-wide sidebar on the left, canvas in the middle and a
    right panel that is closed by default and opens five tiles wide. The menus, the
    sidebar, the canvas and the panel are all empty for now — their contents arrive in M2.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("UCode")
        self.resize(1280, 800)

        self._split_applied = False

        self._build_menu_bar()
        self._build_central_area()

        self.right_panel.hide()

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        self.file_menu: QMenu = menu_bar.addMenu("&File")
        self.edit_menu: QMenu = menu_bar.addMenu("&Edit")

    def _build_central_area(self) -> None:
        central = QWidget(self)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.side_bar = SideBar(central)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        self.canvas_area = QWidget(self.splitter)
        self.canvas_area.setObjectName("canvasArea")
        self.right_panel = RightPanel(self.splitter)

        self.splitter.addWidget(self.canvas_area)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        layout.addWidget(self.side_bar)
        layout.addWidget(self.splitter, 1)

        self.setCentralWidget(central)

    def showEvent(self, event: QShowEvent) -> None:
        """Hand the canvas the full width once the window has a real size."""
        super().showEvent(event)

        if not self._split_applied:
            self._split_applied = True
            self.splitter.setSizes([self.splitter.width(), 0])

    def toggle_right_panel(self) -> None:
        """Open or close the right panel; opening gives it its default five tiles."""
        if self.right_panel.isVisible():
            self.right_panel.hide()
            return

        self.right_panel.show()
        available = self.splitter.width()
        self.splitter.setSizes(
            [max(available - RightPanel.WIDTH, 0), RightPanel.WIDTH]
        )
