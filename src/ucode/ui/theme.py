"""The dark theme: one place that defines every colour the UI uses.

Widgets import the tokens instead of hard-coding values, so switching theme later means
changing this file rather than hunting through the widgets.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

# -- surfaces ---------------------------------------------------------
BG_CHROME = "#0e1015"  # menu bar, sidebar, edge strip — the frame around the work
BG_WINDOW = "#15171c"  # window background
BG_SURFACE = "#1b1e24"  # the workspace itself
BG_PANEL = "#191c22"  # side panel
BG_CONSOLE = "#15181d"  # console

# -- controls ---------------------------------------------------------
BG_CONTROL = "#232730"
BG_CONTROL_HOVER = "#2b303a"
BG_CONTROL_PRESSED = "#313743"

# -- lines and text ---------------------------------------------------
BORDER = "#272b34"
BORDER_STRONG = "#333a46"
# -- node graph -------------------------------------------------------
GRAPH_FOLDER = "#1c2027"
GRAPH_FOLDER_BORDER = "#2c3340"
GRAPH_NODE = "#252b35"
GRAPH_NODE_BORDER = "#3a4352"
GRAPH_EDGE = "#4c5768"
GRAPH_ARROW = "#6f7d92"
GRAPH_IMPORT = "#1e2a33"
GRAPH_IMPORT_BORDER = "#3a5a68"
GRAPH_IMPORT_TEXT = "#7fb6cc"
GRAPH_IMPORT_EDGE = "#3f6272"
BG_NODE_EDITOR = "#20252e"

# -- syntax -----------------------------------------------------------
SYNTAX_KEYWORD = "#c678dd"
SYNTAX_NUMBER = "#d19a66"
SYNTAX_STRING = "#98c379"
SYNTAX_COMMENT = "#6b7482"
SYNTAX_FUNCTION = "#61afef"
SYNTAX_DECORATOR = "#e5c07b"
SYNTAX_PREPROCESSOR = "#56b6c2"

TEXT = "#d7dce5"
TEXT_MUTED = "#8b93a1"
ACCENT = "#4c8dff"


def build_palette() -> QPalette:
    """A dark palette, so unstyled widgets follow the theme too."""
    palette = QPalette()

    colours = {
        QPalette.ColorRole.Window: BG_WINDOW,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: BG_SURFACE,
        QPalette.ColorRole.AlternateBase: BG_PANEL,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: BG_CONTROL,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: BG_CONTROL,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_MUTED,
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: BORDER_STRONG,
    }

    for role, value in colours.items():
        palette.setColor(role, value)

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, TEXT_MUTED)

    return palette


STYLESHEET = f"""
QMenuBar {{
    background-color: {BG_CHROME};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background-color: {BG_CONTROL_HOVER}; }}
QMenu {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
}}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{ background-color: {BG_CONTROL_HOVER}; }}
QStatusBar {{ background-color: {BG_CHROME}; color: {TEXT_MUTED}; }}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Fusion gives a palette a predictable look on every platform."""
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setStyleSheet(STYLESHEET)
