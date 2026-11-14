"""The application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QKeySequence,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QSplitter,
    QWidget,
)

from ucode.core.config import Config
from ucode.core.graph import FileGraph, build_file_graph
from ucode.core.modes import ViewMode
from ucode.ui.file_tree import FileTree
from ucode.ui.panel_toggle import PanelToggle
from ucode.ui.side_panel import SidePanel
from ucode.ui.sidebar import SideBar
from ucode.ui.work_area import WorkArea


class MainWindow(QMainWindow):
    """Application window.

    Layout, left to right: the tile-wide sidebar, the four-tile file selector (hidden
    until a project is open), the work area (workspace over console), the contextual side
    panel and its edge strip. The view mode is presentation only — it never changes which
    project is open.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("UCode")
        self.resize(1280, 800)

        self._split_applied = False
        self.folder: Path | None = None
        self.config = Config.load()
        self.mode: ViewMode = self.config.mode
        self.graph: FileGraph | None = None
        self._graph_framed = False

        self._build_menu_bar()
        self._build_central_area()

        # Both the panel and its edge strip are contextual: neither exists by default.
        self.side_panel.hide()
        self.panel_toggle.hide()

        self._restore_project()

    # -- menus ---------------------------------------------------------
    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        self.file_menu: QMenu = menu_bar.addMenu("&File")
        self.edit_menu: QMenu = menu_bar.addMenu("&Edit")
        self.mode_menu: QMenu = menu_bar.addMenu("&Mode")
        self.run_menu: QMenu = menu_bar.addMenu("&Run")

        self.open_project_action = QAction("Open Project\u2026", self)
        self.open_project_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_project_action.triggered.connect(self.open_folder)
        self.file_menu.addAction(self.open_project_action)

        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_actions: dict[ViewMode, QAction] = {}

        for mode, label in (
            (ViewMode.TEXT, "Text"),
            (ViewMode.NODE_FILES, "Node (Files)"),
            (ViewMode.NODE_CODEFLOW, "Node (Codeflow)"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, m=mode: self.set_mode(m))
            self.mode_group.addAction(action)
            self.mode_menu.addAction(action)
            self.mode_actions[mode] = action

        self.set_mode(self.config.mode, persist=False)

    def set_mode(self, mode: ViewMode, *, persist: bool = True) -> None:
        """Choose how the project is presented, reflect it in the menu, remember it."""
        self.mode = mode
        self.mode_actions[mode].setChecked(True)

        if persist and self.config.mode is not mode:
            self.config.mode = mode
            self._save_config()

        self._sync_graph()

    # -- layout --------------------------------------------------------
    def _build_central_area(self) -> None:
        central = QWidget(self)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.side_bar = SideBar(central)

        self.file_tree = FileTree(central)
        self.file_tree.hide()

        self.splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        self.work_area = WorkArea(self.splitter)
        self.side_panel = SidePanel(self.splitter)

        self.splitter.addWidget(self.work_area)
        self.splitter.addWidget(self.side_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        # The toggle sits outside the splitter so it stays on the window edge while the
        # panel is absent.
        self.panel_toggle = PanelToggle(central)

        root.addWidget(self.side_bar)
        root.addWidget(self.file_tree)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.panel_toggle)

        self.setCentralWidget(central)

        self.panel_toggle.button.clicked.connect(self.toggle_side_panel)
        self.work_area.empty_state.folder_requested.connect(self.open_folder)
        self.side_bar.files_toggled.connect(self.toggle_file_tree)
        self.work_area.canvas.node_moved.connect(self._remember_positions)

    def showEvent(self, event: QShowEvent) -> None:
        """Hand the whole width to the work area once the window has a real size."""
        super().showEvent(event)

        if not self._split_applied:
            self._split_applied = True
            self.splitter.setSizes([self.splitter.width(), 0])

    # -- project -------------------------------------------------------
    def open_folder(self) -> None:
        """Ask for a folder and switch the workspace over to it."""
        start = str(self.folder) if self.folder else ""
        path = QFileDialog.getExistingDirectory(self, "Open Project", start)
        if not path:
            return

        self.set_folder(Path(path))

    def set_folder(self, path: Path) -> None:
        """Open ``path`` as the project: canvas, file selector root, remembered."""
        self.folder = path
        self.file_tree.set_root(path)
        self.file_tree.show()
        self.side_bar.folder_button.setChecked(True)
        self.work_area.show_canvas()

        self.graph = build_file_graph(path)
        self.graph.apply_positions(self.config.positions.get(str(path), {}))
        self._graph_framed = False
        self._sync_graph()

        if self.config.project != str(path):
            self.config.project = str(path)
            self._save_config()

    def _restore_project(self) -> None:
        """Reopen the folder from last time, if it is still there."""
        if not self.config.project:
            return

        candidate = Path(self.config.project)
        if candidate.is_dir():
            self.set_folder(candidate)

    def _sync_graph(self) -> None:
        """Show the file graph only in the view that asks for it."""
        # set_mode runs while the menu is built, before the work area exists.
        if not hasattr(self, "work_area"):
            return

        canvas = self.work_area.canvas
        canvas.set_graph(self.graph if self.mode is ViewMode.NODE_FILES else None)

        if canvas.graph is not None and not self._graph_framed:
            self._graph_framed = True
            canvas.frame_graph()

    def _remember_positions(self) -> None:
        """Keep where the nodes were dropped, in the config, for this project."""
        if self.folder is None or self.graph is None:
            return

        self.config.positions[str(self.folder)] = {
            node.path: node.tile for node in self.graph.nodes
        }
        self._save_config()

    def _save_config(self) -> None:
        try:
            self.config.save()
        except OSError:
            # A read-only config directory must not take the editor down.
            pass

    def toggle_file_tree(self) -> None:
        """The folder button: open the selector, or ask for a folder first."""
        if self.folder is None:
            self.side_bar.folder_button.setChecked(False)
            self.open_folder()
            return

        visible = not self.file_tree.isVisible()
        self.file_tree.setVisible(visible)
        self.side_bar.folder_button.setChecked(visible)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Flush any node edits still sitting in an editor."""
        self.work_area.canvas.save_editors()
        super().closeEvent(event)

    # -- side panel ----------------------------------------------------
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
