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


def provenance() -> dict:
    """Git commit of the code that is producing an output, and whether pipeline/ or configs/ had uncommitted edits
    (a dirty run cannot be traced to a commit; 06_handoff.py refuses it)."""
    import subprocess
    run = lambda *a: subprocess.run(["git", *a], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {"git_commit": run("rev-parse", "--short", "HEAD"),
            "dirty": bool(run("status", "--porcelain", "--", "pipeline", "configs", "requirements.txt"))}
