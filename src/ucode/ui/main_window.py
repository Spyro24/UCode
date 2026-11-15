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
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QWidget,
)

from typing import Callable

from ucode.core import disasm, elf, run
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
        # A single file opened on its own: what it is, and how to build its view again.
        self.file_path: Path | None = None
        self._view_factory: Callable[[], FileGraph | None] | None = None

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
        self.misc_menu: QMenu = menu_bar.addMenu("&Misc")

        self.relayout_action = QAction("Recompute Best Layout", self)
        self.relayout_action.triggered.connect(self.recompute_layout)
        self.misc_menu.addAction(self.relayout_action)

        self.open_project_action = QAction("Open Project\u2026", self)
        self.open_project_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_project_action.triggered.connect(self.open_folder)
        self.file_menu.addAction(self.open_project_action)

        self.open_file_action = QAction("Open File\u2026", self)
        self.open_file_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.open_file_action.triggered.connect(self.open_file)
        self.file_menu.addAction(self.open_file_action)

        self.run_action = QAction("Run", self)
        self.run_action.setShortcut(QKeySequence("Ctrl+R"))
        self.run_action.triggered.connect(lambda: self.run_current())
        self.run_menu.addAction(self.run_action)

        self.debug_action = QAction("Debug (Live)", self)
        self.debug_action.setShortcut(QKeySequence("F5"))
        self.debug_action.triggered.connect(lambda: self.run_current(debug=True))
        self.run_menu.addAction(self.debug_action)

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
        self.work_area.console.live_line.connect(self._show_live_line)
        self.work_area.console.live_idle.connect(self._clear_live_line)
        self.work_area.console.live_stopped.connect(self._clear_live_line)
        self.work_area.canvas.node_moved.connect(self._remember_positions)
        self.work_area.canvas.folder_moved.connect(self._remember_positions)

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

    # -- single file ---------------------------------------------------
    def open_file(self) -> None:
        """Ask for one file and open it on its own."""
        start = str(self.folder) if self.folder else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open File", start)
        if not path:
            return

        self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        """Show ``path`` alone; a binary has to be told how to present itself."""
        path = path.resolve()
        if not path.is_file():
            return

        view = "text"
        if elf.is_elf(path):
            view = self._ask_elf_view(path)
            if view is None:
                return

        self.show_file(path, view)

    def _ask_elf_view(self, path: Path) -> str | None:
        """Which of the three viewers an ELF binary should open in."""
        info = elf.header(path)
        box = QMessageBox(self)
        box.setWindowTitle("ELF binary")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{path.name} is an ELF binary.")
        box.setInformativeText(
            (info.summary(path) if info is not None else "ELF binary")
            + "\n\nHow do you want to open it?"
        )
        text_button = box.addButton("Text editor", QMessageBox.ButtonRole.AcceptRole)
        hex_button = box.addButton("Hex editor", QMessageBox.ButtonRole.AcceptRole)
        disasm_button = box.addButton(
            "Disassembly", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(text_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked is text_button:
            return "text"
        if clicked is hex_button:
            return "hex"
        if clicked is disasm_button:
            return "disasm"
        return None

    def _ask_architecture(self, path: Path) -> str | None:
        """Which machine objdump should read the binary as; None when cancelled."""
        detected = self._detected_architecture(path)
        labels = [label for label, _target, _id in disasm.ARCHITECTURES]
        # Mark the one the header claims, so overriding it is a deliberate choice.
        names = [
            f"{label}   (from the ELF header)" if label == detected else label
            for label in labels
        ]
        current = labels.index(detected) if detected in labels else 0

        choice, accepted = QInputDialog.getItem(
            self,
            "Disassembly",
            f"Architecture to read {path.name} as:",
            names,
            current,
            False,
        )
        if not accepted:
            return None

        return disasm.ARCHITECTURES[names.index(choice)][1]

    @staticmethod
    def _detected_architecture(path: Path) -> str | None:
        """The architecture the ELF header claims, as one of the listed names."""
        info = elf.header(path)
        if info is None:
            return None

        for label, _target, machine_id in disasm.ARCHITECTURES:
            if machine_id != info.machine_id:
                continue
            if machine_id == 243:  # RISC-V 32 and 64 share e_machine
                return "RISC-V 64" if info.bits == 64 else "RISC-V 32"
            return label

        return None

    def show_file(self, path: Path, view: str) -> None:
        """Open a lone file in the view that was chosen for it."""
        note = ""
        if view == "disasm":
            machine = self._ask_architecture(path)
            if machine is None:
                return
            graph, note = disasm.build_graph(path, machine)
            if graph is None:
                QMessageBox.warning(self, "Disassembly", note)
                return
            factory = lambda: disasm.build_graph(path, machine)[0]  # noqa: E731
        elif view == "hex":
            graph = elf.build_hex_graph(path)
            factory = lambda: elf.build_hex_graph(path)  # noqa: E731
        else:
            graph = elf.build_text_graph(path)
            factory = lambda: elf.build_text_graph(path)  # noqa: E731

        if self.folder is not None:
            # A file opens on its own, so the project's file selector steps aside.
            self.file_tree.hide()
            self.side_bar.folder_button.setChecked(False)

        self.file_path = path
        self._view_factory = factory
        self.work_area.console.set_project(path.parent)
        self.work_area.show_canvas()
        self.set_mode(ViewMode.NODE_FILES, persist=False)
        self._show_graph(graph)
        title = f"UCode \u2014 {path.name}"
        if note:
            title += f" \u2014 {note}"
        self.setWindowTitle(title)

    def _show_graph(self, graph: FileGraph) -> None:
        """Put a freshly built graph on the canvas, with any remembered positions."""
        self.graph = graph
        key = self._view_key()
        self.graph.apply_positions(self.config.positions.get(key, {}))
        self.graph.apply_folder_positions(self.config.folders.get(key, {}))
        self._graph_framed = False
        self._sync_graph()

    def _view_key(self) -> str:
        """What remembered positions for the current view are filed under."""
        if self.file_path is not None:
            return str(self.file_path)
        return str(self.folder)

    def set_folder(self, path: Path) -> None:
        """Open ``path`` as the project: canvas, file selector root, remembered."""
        self.folder = path
        self.file_path = None
        self._view_factory = None
        self.setWindowTitle("UCode")
        self.work_area.console.set_project(path)
        self.file_tree.set_root(path)
        self.file_tree.show()
        self.side_bar.folder_button.setChecked(True)
        self.work_area.show_canvas()

        self.graph = build_file_graph(path)
        self.graph.apply_positions(self.config.positions.get(str(path), {}))
        self.graph.apply_folder_positions(self.config.folders.get(str(path), {}))
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
        show = self.mode is ViewMode.NODE_FILES or self.file_path is not None
        canvas.set_graph(self.graph if show else None)

        if canvas.graph is not None and not self._graph_framed:
            self._graph_framed = True
            canvas.frame_graph()

    # -- running -------------------------------------------------------
    def run_current(self, *, debug: bool = False) -> None:
        """Run (or live-debug) the file in front of the user, in the console."""
        self.work_area.canvas.save_editors()

        console = self.work_area.console
        target = self._run_target()
        if target is None:
            # No main.py, nothing in focus: let the user point at the file to run.
            target = self._choose_run_target()
            if target is None:
                return

        # The process runs in the file's folder, so it must get an absolute path.
        target = target.resolve()
        if not target.is_file():
            console.notice(f"{target} does not exist", error=True)
            return

        if debug:
            args = run.debug_command(target)
            if not args:
                console.notice(
                    f"live debugging runs Python scripts; {target.name} is not one",
                    error=True,
                )
                return
            title = f"debug \u00b7 {target.name}"
        else:
            args = run.command(target)
            if not args:
                console.notice(
                    f"{target.name} is neither a Python script nor an executable",
                    error=True,
                )
                return
            title = f"run \u00b7 {target.name}"

        console.run_program(args, cwd=target.parent, title=title, live=debug)

    def _show_live_line(self, path: str, line: int) -> None:
        """Mark the line the live session is on, inside the node that holds the file."""
        key = self._node_key(path)
        if key is not None:
            self.work_area.canvas.set_active_line(key, line)

    def _clear_live_line(self) -> None:
        """The session moved on or ended: no line is being executed any more."""
        self.work_area.canvas.set_active_line(None, None)

    def _node_key(self, path: str) -> str | None:
        """The graph key for a file path, when the file is a node in this view."""
        if not path or self.graph is None:
            return None

        nodes = self.graph.by_path()
        if path in nodes:
            return path

        root = self.graph.root
        if root is None:
            return None

        try:
            relative = Path(path).resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            return None

        key = relative.as_posix()
        return key if key in nodes else None

    def _run_target(self) -> Path | None:
        """The file the Run menu should execute."""
        if self.file_path is not None:
            return self.file_path

        focused = self._focused_file()
        if focused is not None:
            return focused

        remembered = self._remembered_run_target()
        if remembered is not None:
            return remembered

        return run.entry_point(self.folder)

    def _run_key(self) -> str | None:
        """What the chosen run target is remembered under."""
        if self.file_path is not None:
            return str(self.file_path)
        if self.folder is not None:
            return str(self.folder)
        return None

    def _remembered_run_target(self) -> Path | None:
        """The file chosen last time for this project, while it still exists."""
        key = self._run_key()
        if key is None:
            return None

        stored = self.config.runs.get(key)
        if not stored:
            return None

        path = Path(stored)
        return path if path.is_file() else None

    def _choose_run_target(self) -> Path | None:
        """Ask which file to run, and remember it for this project."""
        start = str(self.folder) if self.folder is not None else str(Path.home())
        chosen, _filter = QFileDialog.getOpenFileName(
            self,
            "Select the file to run",
            start,
            "Python files (*.py);;All files (*)",
        )

        if not chosen:
            self.work_area.console.notice(
                "no file was chosen, so nothing was run", error=False
            )
            return None

        path = Path(chosen).resolve()
        key = self._run_key()
        if key is not None:
            self.config.runs[key] = str(path)
            self._save_config()

        return path

    def _focused_file(self) -> Path | None:
        """The node whose editor has the keyboard focus, if one does."""
        widget = QApplication.focusWidget()
        while widget is not None:
            path = getattr(widget, "path", None)
            if isinstance(path, str) and path:
                candidate = Path(path)
                if not candidate.is_absolute() and self.folder is not None:
                    candidate = self.folder / candidate
                if candidate.is_file():
                    return candidate
            widget = widget.parentWidget()

        return None

    def recompute_layout(self) -> None:
        """Throw away the hand-placed arrangement and lay the view out afresh."""
        key = self._view_key()
        self.config.positions.pop(key, None)
        self.config.folders.pop(key, None)
        self._save_config()

        if self.folder is not None and self.file_path is None:
            self.graph = build_file_graph(self.folder)
        elif self._view_factory is not None:
            rebuilt = self._view_factory()
            if rebuilt is None:
                return
            self.graph = rebuilt
        else:
            return

        self._graph_framed = False
        self._sync_graph()

    def _remember_positions(self) -> None:
        """Keep where the nodes were dropped, in the config, for this view."""
        if self.graph is None:
            return
        if self.folder is None and self.file_path is None:
            return

        key = self._view_key()
        self.config.positions[key] = {
            node.path: node.tile for node in self.graph.nodes
        }
        self.config.folders[key] = {
            box.folder: box.tile for box in self.graph.folders
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
        self.work_area.console.shutdown()
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
