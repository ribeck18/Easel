from pathlib import Path

from paths import workspace_root


WORKSPACE_ROOT = workspace_root()


class WorkspacePathError(Exception):
    """Raised when a requested path escapes or cannot be placed in the workspace."""


def workspace_available() -> bool:
    """Return whether a workspace folder is configured and present.

    ``WORKSPACE_ROOT`` is seeded from the ``EASEL_WORKSPACE`` environment variable
    (set by the launcher); when unset it points at a sentinel path that does not exist.

    Returns:
        True if the configured workspace exists and is a directory, else False.
    """
    return WORKSPACE_ROOT.is_dir()


def resolve_in_workspace(user_path: str) -> Path:
    """Resolve a model-supplied path and clamp it inside the workspace.

    The path is joined onto the workspace root and fully resolved (collapsing
    ``..`` segments and following symlinks) before containment is checked, so
    traversal and symlink escapes are both rejected.

    Args:
        user_path: A relative path supplied by the model, e.g. ``"notes/a.md"``.

    Returns:
        The absolute, resolved path, guaranteed to live inside the workspace.

    Raises:
        WorkspacePathError: If the resolved path falls outside the workspace.
    """
    root = WORKSPACE_ROOT.resolve()
    candidate = (root / user_path).resolve()

    if candidate != root and not candidate.is_relative_to(root):
        raise WorkspacePathError(
            f"Path '{user_path}' is outside the workspace and was blocked."
        )

    return candidate
