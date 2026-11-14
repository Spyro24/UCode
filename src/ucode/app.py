"""Application bootstrap: build the Qt application, show the window, run the loop."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ucode.ui.main_window import MainWindow
from ucode.ui.theme import apply_dark_theme

APP_NAME = "UCode"


def main(argv: list[str] | None = None) -> int:
    """Start UCode and return the process exit code."""
    args = list(sys.argv if argv is None else argv)

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    apply_dark_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()
