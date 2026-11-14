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
from dataclasses import dataclass
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

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        target = config_path() if path is None else path

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()

        if not isinstance(raw, dict):
            return cls()

        return cls(mode=_parse_mode(raw.get("mode")))

    def save(self, path: Path | None = None) -> None:
        """Write atomically, so a crash mid-write cannot truncate the config."""
        target = config_path() if path is None else path
        target.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps({"mode": self.mode.value}, indent=2) + "\n"

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
