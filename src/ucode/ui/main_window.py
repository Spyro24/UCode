"""The application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMenu, QSplitter, QWidget

from ucode.ui.panel_toggle import PanelToggle
from ucode.ui.right_panel import RightPanel
from ucode.ui.sidebar import SideBar


class MainWindow(QMainWindow):
    """Application window.

    Layout: menu bar on top, tile-wide sidebar on the left, canvas in the middle with a
    one-tile toggle column on its right edge, and the right panel — closed by default,
    five tiles wide when open. The menus and every area are empty for now; contents
    arrive in M2.
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

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.side_bar = SideBar(central)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        # Canvas side of the splitter: the canvas plus the toggle column on its edge,
        # so the toggle sits between the left sidebar and the right panel.
        self.canvas_container = QWidget(self.splitter)
        canvas_layout = QHBoxLayout(self.canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        self.canvas_area = QWidget(self.canvas_container)
        self.canvas_area.setObjectName("canvasArea")
        self.panel_toggle = PanelToggle(self.canvas_container)

        canvas_layout.addWidget(self.canvas_area, 1)
        canvas_layout.addWidget(self.panel_toggle)

        self.right_panel = RightPanel(self.splitter)

        self.splitter.addWidget(self.canvas_container)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        root.addWidget(self.side_bar)
        root.addWidget(self.splitter, 1)

        self.setCentralWidget(central)

        self.panel_toggle.button.clicked.connect(self.toggle_right_panel)

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
            self.panel_toggle.button.setChecked(False)
            return

        self.right_panel.show()
        self.panel_toggle.button.setChecked(True)

        available = self.splitter.width()
        self.splitter.setSizes(
            [max(available - RightPanel.WIDTH, 0), RightPanel.WIDTH]
        )
