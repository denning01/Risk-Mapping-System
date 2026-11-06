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


def refuse_if_posted(area: str, allow: bool) -> None:
    """Operator ruling 2026-11-06: rasters named by a POSTED hand-off are being read (and snapshotted) by exposure.
    Never rewrite them unless the operator was told "about to rewrite <area> rasters" (then pass --rewrite-posted),
    and re-post the hand-off right after. A WITHDRAWN hand-off names nothing."""
    import sys
    f = REPO_ROOT.parent / "rms-audit" / "handoffs" / f"flood-{area}.md"
    if f.exists() and "WITHDRAWN" not in f.read_text()[:200] and not allow:
        sys.exit(f"REFUSED: {f} names the {area} rasters this run would overwrite. Send the operator "
                 f"'about to rewrite {area} rasters' first, then re-run with --rewrite-posted, then re-post the hand-off.")
