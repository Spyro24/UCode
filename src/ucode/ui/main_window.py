"""The application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QSplitter,
    QWidget,
)

from ucode.ui.panel_toggle import PanelToggle
from ucode.ui.side_panel import SidePanel
from ucode.ui.sidebar import SideBar
from ucode.ui.work_area import WorkArea


class MainWindow(QMainWindow):
    """Application window.

    Layout, left to right: the tile-wide sidebar, the work area (workspace over console),
    the contextual side panel, and the tile-wide toggle strip on the far right edge that
    closes it again. Panel and strip are absent by default — they appear together only
    when something asks for the panel. The menus and every area are empty for now.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("UCode")
        self.resize(1280, 800)

        self._split_applied = False
        self.folder: Path | None = None

        self._build_menu_bar()
        self._build_central_area()

        # Both the panel and its edge strip are contextual: neither exists by default.
        self.side_panel.hide()
        self.panel_toggle.hide()

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

        self.work_area = WorkArea(self.splitter)
        self.side_panel = SidePanel(self.splitter)

        self.splitter.addWidget(self.work_area)
        self.splitter.addWidget(self.side_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        # The toggle sits outside the splitter so it stays on the window edge and remains
        # visible while the panel is absent.
        self.panel_toggle = PanelToggle(central)

        root.addWidget(self.side_bar)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.panel_toggle)

        self.setCentralWidget(central)

        self.panel_toggle.button.clicked.connect(self.toggle_side_panel)
        self.work_area.empty_state.folder_requested.connect(self.open_folder)

    def showEvent(self, event: QShowEvent) -> None:
        """Hand the whole width to the work area once the window has a real size."""
        super().showEvent(event)

        if not self._split_applied:
            self._split_applied = True
            self.splitter.setSizes([self.splitter.width(), 0])

    def open_side_panel(self) -> None:
        """Show the side panel at its default five tiles, with its edge strip."""
        self.panel_toggle.show()
        self.side_panel.show()
        self.panel_toggle.button.setChecked(True)

        available = self.splitter.width()
        self.splitter.setSizes(
            [max(available - SidePanel.WIDTH, 0), SidePanel.WIDTH]
        )

    def close_side_panel(self) -> None:
        """Remove the side panel and its strip; the work area takes the width back."""
        self.side_panel.hide()
        self.panel_toggle.button.setChecked(False)
        self.panel_toggle.hide()

    def toggle_side_panel(self) -> None:
        if self.side_panel.isVisible():
            self.close_side_panel()
        else:
            self.open_side_panel()

    def open_folder(self) -> None:
        """Ask for a folder and switch the workspace over to it."""
        path = QFileDialog.getExistingDirectory(self, "Open Folder")
        if not path:
            return

        self.folder = Path(path)
        self.work_area.show_canvas()
