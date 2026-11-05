"""Where heavy data lives. Outside git, shared by every worktree (CLAUDE.md, Data layout)."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"


def data_root() -> Path:
    """$RMS_DATA if set and non-empty, else <repo>/../data (= /Users/mac/IGAD/data on this machine)."""
    env = os.environ.get("RMS_DATA", "").strip()
    return Path(env).expanduser().resolve() if env else (REPO_ROOT.parent / "data").resolve()


def raw_dir(area: str) -> Path:
    return data_root() / "raw" / area


def model_dir(area: str) -> Path:
    """processed/<area>/model — written only by the model lead."""
    return data_root() / "processed" / area / "model"
