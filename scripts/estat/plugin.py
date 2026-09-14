"""Resolve the external e-Stat catalogue search helper from ESTAT_FILE_SEARCH_SCRIPT."""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "ESTAT_FILE_SEARCH_SCRIPT"


def find_search_script() -> Path:

    value = os.environ.get(ENV_VAR)
    if not value:
        raise FileNotFoundError(f"set {ENV_VAR} to the e-Stat catalogue search.py path")
    path = Path(value).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"{ENV_VAR} does not point to a file: {path}")
    return path
