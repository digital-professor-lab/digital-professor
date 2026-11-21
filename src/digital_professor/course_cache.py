"""Keep published courses across restarts of the local demo.

Off by default. With ``DP_KEEP_COURSES=1`` each published course is saved under ``.cache/courses/`` and
loaded again when the app starts, so a developer does not have to upload the files after every restart.
The folder is git-ignored: course files stay on the machine they were uploaded to.

The saved file is a pickle written by this process on this machine. It is never read from anywhere else.
"""

from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)


def enabled() -> bool:
    return os.getenv("DP_KEEP_COURSES") == "1"


def _folder() -> Path:
    return Path(os.getenv("DP_COURSE_CACHE", ".cache/courses"))


def remember(workspace: Any) -> None:
    """Save a published course. A failure is logged and never stops the publication."""
    if not enabled():
        return
    try:
        folder = _folder()
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f"{workspace.course_id}.tmp"
        temporary.write_bytes(pickle.dumps(workspace))
        temporary.replace(folder / f"{workspace.course_id}.pkl")
    except Exception as error:      # pragma: no cover - depends on the local disk
        log.warning("Could not save course %s: %s", getattr(workspace, "course_id", "?"), error)


def saved_courses() -> Iterator[Any]:
    """The courses saved by earlier runs. A file that no longer loads is skipped."""
    if not enabled() or not _folder().is_dir():
        return
    for path in sorted(_folder().glob("*.pkl")):
        try:
            yield pickle.loads(path.read_bytes())
        except Exception as error:
            log.warning("Skipping saved course %s: %s", path.name, error)
