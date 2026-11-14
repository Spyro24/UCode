"""How the project is presented in the workspace."""

from __future__ import annotations

from enum import Enum


class ViewMode(str, Enum):
    """The three views the editor offers."""

    TEXT = "text"  # plain text editing
    NODE_FILES = "node-files"  # one node per file
    NODE_CODEFLOW = "node-codeflow"  # nodes follow the code's flow
