#!/usr/bin/env python3
"""Start UCode with the system interpreter: ``python3 run.py``.

There is no packaging and no virtualenv: this file puts ``src`` on the path and hands
over to the application.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ucode.app import main  # noqa: E402 — the path above has to be set up first

if __name__ == "__main__":
    raise SystemExit(main())
