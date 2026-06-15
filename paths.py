"""Filesystem roots for the Easel, resolved from the environment.

Two roots replace the former hardcoded Docker mount points (``/app/data`` and
``/app/workspace``):

* :func:`data_dir` -> machine-internal state (the SQLite databases, ``.env``,
  ``agents.md``). Hidden from the user under
  ``~/Library/Application Support/Easel`` by default. Override with the
  ``EASEL_DATA_DIR`` environment variable (used by the test suite and by the
  Docker image, which sets it to ``/app/data`` to reproduce the old layout).

* :func:`workspace_root` -> the user-chosen, Finder-visible folder the agent reads
  and writes (Memory v2 markdown, wiki, skills, uploads). Supplied by the native
  launcher via the ``EASEL_WORKSPACE`` environment variable. When unset, a path
  that does not exist is returned so :func:`tools.workspace.workspace_available`
  reports "no workspace" -- exactly as the absent ``/app/workspace`` mount did
  under Docker.
"""

import os
from pathlib import Path


# Returned when no workspace is configured. Any non-existent path works; this one is
# clearly labelled so it is obvious in a traceback. ``is_dir()`` is False for it, which
# is how the file tools detect that no workspace is available.
_NO_WORKSPACE = Path("/__easel_no_workspace__")


def data_dir() -> Path:
    """Return the hidden directory for app-internal state, creating it if needed.

    Honors ``EASEL_DATA_DIR`` when set, else defaults to
    ``~/Library/Application Support/Easel``. The directory is created on every call
    (idempotent) so callers never have to guard against its absence.
    """
    override = os.environ.get("EASEL_DATA_DIR")
    base = (
        Path(override)
        if override
        else Path.home() / "Library" / "Application Support" / "Easel"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def workspace_root() -> Path:
    """Return the user-chosen workspace folder, or a non-existent sentinel if unset.

    The sentinel preserves the pre-bundle behavior: with no workspace selected, file
    tools and core memory degrade gracefully instead of erroring.
    """
    configured = os.environ.get("EASEL_WORKSPACE")
    return Path(configured) if configured else _NO_WORKSPACE
