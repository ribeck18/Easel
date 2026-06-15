from tools.workspace import (
    WORKSPACE_ROOT,
    WorkspacePathError,
    resolve_in_workspace,
    workspace_available,
)


MAX_READ_BYTES = 256 * 1024

NO_WORKSPACE_MESSAGE = (
    "Error: no workspace folder is selected, so file tools are unavailable."
)


def read_file(path: str) -> str:
    """Read a UTF-8 text file from the workspace.

    Args:
        path: Workspace-relative path to the file to read.

    Returns:
        The file's text content, or a human-readable error string the model can
        relay to the user (missing workspace, not found, too large, or binary).
    """
    if not workspace_available():
        return NO_WORKSPACE_MESSAGE

    try:
        target = resolve_in_workspace(path)
    except WorkspacePathError as error:
        return f"Error: {error}"

    if not target.is_file():
        return f"Error: no file found at '{path}'."

    if target.stat().st_size > MAX_READ_BYTES:
        return (
            f"Error: '{path}' is larger than the {MAX_READ_BYTES // 1024} KB "
            "read limit."
        )

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: '{path}' is not a UTF-8 text file and cannot be read."
    except OSError as error:
        return f"Error: could not read '{path}': {error}."


def write_file(path: str, content: str) -> str:
    """Create or overwrite a UTF-8 text file in the workspace.

    Parent directories are created as needed.

    Args:
        path: Workspace-relative path to the file to write.
        content: The full text to write to the file.

    Returns:
        A confirmation string, or a human-readable error string.
    """
    if not workspace_available():
        return NO_WORKSPACE_MESSAGE

    try:
        target = resolve_in_workspace(path)
    except WorkspacePathError as error:
        return f"Error: {error}"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        written = target.write_text(content, encoding="utf-8")
    except OSError as error:
        return f"Error: could not write '{path}': {error}."

    return f"Wrote {written} characters to '{path}'."


def search_files(query: str, path: str = ".", max_results: int = 50) -> str:
    """Search workspace files for lines containing a substring.

    Walks ``path`` recursively, scanning UTF-8 text files for case-insensitive
    matches. Binary (non-UTF-8) files and files over the read limit are skipped,
    as are dotfile directories like ``.git``.

    Args:
        query: The substring to look for (case-insensitive).
        path: Workspace-relative directory to search. Defaults to the workspace
            root.
        max_results: Maximum number of matching lines to return (1-500).

    Returns:
        A newline-separated list of ``relative/path:line: text`` hits, a
        "no matches" message, or a human-readable error string.
    """
    if not workspace_available():
        return NO_WORKSPACE_MESSAGE

    if not query:
        return "Error: search query must not be empty."

    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        return "Error: max_results must be an integer."
    max_results = max(1, min(max_results, 500))

    try:
        root = resolve_in_workspace(path)
    except WorkspacePathError as error:
        return f"Error: {error}"

    if not root.is_dir():
        return f"Error: no directory found at '{path}'."

    workspace_root = WORKSPACE_ROOT.resolve()
    needle = query.lower()
    hits: list[str] = []
    truncated = False

    for current in sorted(p for p in root.rglob("*") if p.is_file()):
        if any(part.startswith(".") for part in current.relative_to(root).parts):
            continue
        try:
            if current.stat().st_size > MAX_READ_BYTES:
                continue
            text = current.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        rel = current.relative_to(workspace_root)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append(f"{rel}:{line_number}: {line.strip()}")
                if len(hits) >= max_results:
                    truncated = True
                    break
        if truncated:
            break

    if not hits:
        return f"No matches for '{query}'."

    header = f"Found {len(hits)} match(es)"
    if truncated:
        header += f" (stopped at the {max_results}-result limit)"
    return header + ":\n" + "\n".join(hits)


def edit_file(
    path: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    """Replace an exact substring within an existing workspace file.

    A surgical alternative to ``write_file``: the file is read, ``old_string`` is
    replaced with ``new_string``, and the result is written back. By default
    ``old_string`` must occur exactly once, guarding against accidental mass
    edits; set ``replace_all`` to replace every occurrence.

    Args:
        path: Workspace-relative path to the file to edit.
        old_string: The exact text to find.
        new_string: The text to replace it with.
        replace_all: Replace every occurrence instead of requiring a unique match.

    Returns:
        A confirmation string, or a human-readable error string.
    """
    if not workspace_available():
        return NO_WORKSPACE_MESSAGE

    try:
        target = resolve_in_workspace(path)
    except WorkspacePathError as error:
        return f"Error: {error}"

    if not target.is_file():
        return f"Error: no file found at '{path}'."

    if old_string == new_string:
        return "Error: old_string and new_string are identical."

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: '{path}' is not a UTF-8 text file and cannot be edited."
    except OSError as error:
        return f"Error: could not read '{path}': {error}."

    occurrences = content.count(old_string)
    if occurrences == 0:
        return f"Error: old_string was not found in '{path}'."
    if occurrences > 1 and not replace_all:
        return (
            f"Error: old_string is not unique in '{path}' ({occurrences} matches). "
            "Add surrounding context to make it unique, or set replace_all=true."
        )

    updated = content.replace(old_string, new_string)

    try:
        target.write_text(updated, encoding="utf-8")
    except OSError as error:
        return f"Error: could not write '{path}': {error}."

    return f"Made {occurrences} replacement(s) in '{path}'."


def move_file(source: str, destination: str) -> str:
    """Move or rename a file within the workspace.

    Parent directories of the destination are created as needed. Refuses to
    overwrite an existing destination so data cannot be silently clobbered.

    Args:
        source: Workspace-relative path of the file to move.
        destination: Workspace-relative path to move it to.

    Returns:
        A confirmation string, or a human-readable error string.
    """
    if not workspace_available():
        return NO_WORKSPACE_MESSAGE

    try:
        source_path = resolve_in_workspace(source)
        destination_path = resolve_in_workspace(destination)
    except WorkspacePathError as error:
        return f"Error: {error}"

    if not source_path.is_file():
        return f"Error: no file found at '{source}'."

    if destination_path.exists():
        return (
            f"Error: '{destination}' already exists. Delete it first or choose "
            "another destination."
        )

    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.rename(destination_path)
    except OSError as error:
        return f"Error: could not move '{source}' to '{destination}': {error}."

    return f"Moved '{source}' to '{destination}'."


def delete_file(path: str) -> str:
    """Delete a file from the workspace.

    Only files are removed; directories are refused to avoid recursive deletion.

    Args:
        path: Workspace-relative path of the file to delete.

    Returns:
        A confirmation string, or a human-readable error string.
    """
    if not workspace_available():
        return NO_WORKSPACE_MESSAGE

    try:
        target = resolve_in_workspace(path)
    except WorkspacePathError as error:
        return f"Error: {error}"

    if target.is_dir():
        return f"Error: '{path}' is a directory; only files can be deleted."

    if not target.is_file():
        return f"Error: no file found at '{path}'."

    try:
        target.unlink()
    except OSError as error:
        return f"Error: could not delete '{path}': {error}."

    return f"Deleted '{path}'."


def list_directory(path: str = ".") -> str:
    """List the entries of a workspace directory.

    Args:
        path: Workspace-relative path to the directory. Defaults to the
            workspace root.

    Returns:
        A newline-separated listing with a trailing ``/`` on directories, or a
        human-readable error string.
    """
    if not workspace_available():
        return NO_WORKSPACE_MESSAGE

    try:
        target = resolve_in_workspace(path)
    except WorkspacePathError as error:
        return f"Error: {error}"

    if not target.is_dir():
        return f"Error: no directory found at '{path}'."

    entries = sorted(
        target.iterdir(), key=lambda entry: (entry.is_file(), entry.name.lower())
    )
    if not entries:
        return f"'{path}' is empty."

    lines = [
        entry.name + ("/" if entry.is_dir() else "") for entry in entries
    ]
    return "\n".join(lines)
