"""Persisted user settings.

The file lives in the platform config directory:
``$XDG_CONFIG_HOME/spyro24/ucode/config.json`` — ``~/.config/spyro24/ucode/config.json``
when ``XDG_CONFIG_HOME`` is unset. Missing, unreadable or malformed settings fall back to
defaults: a broken config must never stop the editor from starting.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ucode.core.modes import ViewMode

VENDOR = "spyro24"
APPLICATION = "ucode"
CONFIG_FILE = "config.json"


def config_dir() -> Path:
    """The directory this application keeps its settings in."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / VENDOR / APPLICATION


def config_path() -> Path:
    return config_dir() / CONFIG_FILE


def _parse_project(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _parse_positions(value: object) -> dict[str, dict[str, tuple[float, float]]]:
    """Node positions per project: ``{project: {node path: (x, y) in tiles}}``."""
    if not isinstance(value, dict):
        return {}

    positions: dict[str, dict[str, tuple[float, float]]] = {}

    for project, nodes in value.items():
        if not isinstance(project, str) or not isinstance(nodes, dict):
            continue

        tiles: dict[str, tuple[float, float]] = {}
        for path, tile in nodes.items():
            if not isinstance(path, str) or not isinstance(tile, (list, tuple)):
                continue
            if len(tile) != 2:
                continue

            x, y = tile
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                tiles[path] = (float(x), float(y))

        if tiles:
            positions[project] = tiles

    return positions


def _parse_mode(value: object) -> ViewMode:
    if isinstance(value, str):
        try:
            return ViewMode(value)
        except ValueError:
            pass
    return ViewMode.TEXT


@dataclass(slots=True)
class Config:
    """Everything remembered between runs."""

    mode: ViewMode = ViewMode.TEXT
    project: str | None = None  # last opened folder
    # Where the user left each node, per project, so the canvas reopens as they left it.
    positions: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    # The same for the folder boxes, which can be dragged independently.
    folders: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        target = config_path() if path is None else path

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()

        if not isinstance(raw, dict):
            return cls()

        return cls(
            mode=_parse_mode(raw.get("mode")),
            project=_parse_project(raw.get("project")),
            positions=_parse_positions(raw.get("positions")),
            folders=_parse_positions(raw.get("folders")),
        )

    def save(self, path: Path | None = None) -> None:
        """Write atomically, so a crash mid-write cannot truncate the config."""
        target = config_path() if path is None else path
        target.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, object] = {"mode": self.mode.value}
        if self.project:
            data["project"] = self.project
        for key, mapping in (("positions", self.positions), ("folders", self.folders)):
            if not mapping:
                continue
            data[key] = {
                project: {
                    name: [round(x, 3), round(y, 3)] for name, (x, y) in tiles.items()
                }
                for project, tiles in mapping.items()
            }
        payload = json.dumps(data, indent=2) + "\n"

        handle = tempfile.NamedTemporaryFile(
            "w",
            dir=target.parent,
            prefix=".config-",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()

        os.replace(handle.name, target)
