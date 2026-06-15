"""Test-suite-wide setup.

Importing ``config`` / ``ClientModel`` / ``user_database.chats_database`` /
``services.scheduler`` resolves :func:`paths.data_dir` at import time, which would
otherwise create and use the real ``~/Library/Application Support/Easel`` directory on
the developer's machine. Setting ``EASEL_DATA_DIR`` here -- before pytest imports any
test module, and therefore before those app modules load -- redirects all app-internal
state (the SQLite databases, ``.env``, ``agents.md``) into a throwaway temp directory for
the duration of the run.

``setdefault`` means a caller who already exported ``EASEL_DATA_DIR`` (e.g. to inspect
the artifacts) is respected.
"""

import os
import tempfile

os.environ.setdefault(
    "EASEL_DATA_DIR", tempfile.mkdtemp(prefix="easel-test-data-")
)
