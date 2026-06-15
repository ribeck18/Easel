from datetime import datetime
from pathlib import Path
import difflib
import re

from tools import threat_patterns
from tools.workspace import (
    WorkspacePathError,
    resolve_in_workspace,
    workspace_available,
)


ONBOARD_SECTIONS = [
    "User facts/preferences",
    "Decisions",
    "Topics & entities",
    "Open tasks/follow-ups",
    "Notable outcomes",
]
MAX_SEARCH_RESULTS = 12
MAX_NOTE_BYTES = 256 * 1024
MAX_CHAT_HISTORY_RESULTS = 10
MAX_CHAT_MESSAGE_CHARS = 1000


def _sanitize_for_recall(text: str) -> str:
    """Credential-scrub then injection-sanitize stored text before the model sees it."""
    return threat_patterns.sanitize_for_model(scrub_secrets(text), source="recall")


def _format_recall_date(value) -> str:
    """Render a stored created_datetime (str or datetime) as YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10] if value else "unknown date"


def scrub_secrets(text: str) -> str:
    """Redact common credential shapes before memory text is written."""
    patterns = [
        r"sk-[A-Za-z0-9_\-]{16,}",
        r"AKIA[0-9A-Z]{16}",
        r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}",
        r"(?i)(password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^'\"\s]+",
        r"\b[A-Fa-f0-9]{48,}\b",
    ]
    scrubbed = text
    for pattern in patterns:
        scrubbed = re.sub(pattern, "<redacted secret>", scrubbed)
    return scrubbed


def write_onboard(chat_id: int, sections: dict[str, list[str]]) -> None:
    """Merge captured turn notes into the chat's onboard memory file."""
    if not workspace_available():
        return

    path = _onboard_path(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    merged = _parse_onboard(existing)

    for section in ONBOARD_SECTIONS:
        for item in sections.get(section, []):
            bullet = _normalize_bullet(item)
            if bullet and bullet not in merged[section]:
                merged[section].append(bullet)

    rendered = scrub_secrets(_render_onboard(chat_id, merged))
    rendered = threat_patterns.sanitize_for_model(rendered, source="onboard")
    path.write_text(rendered, encoding="utf-8")


def search_memory(query: str) -> str:
    """Search wiki memory notes by case-insensitive substring."""
    if not workspace_available():
        return "Error: no workspace folder is mounted, so memory search is unavailable."

    query = query.strip().lower()
    if not query:
        return "Error: search_memory requires a non-empty query."

    wiki_root = _wiki_root()
    if not wiki_root.is_dir():
        return "No wiki memory has been created yet."

    results: list[str] = []
    for note in sorted(wiki_root.rglob("*.md")):
        try:
            relative_path = note.relative_to(wiki_root).as_posix()
            for line_number, line in enumerate(note.read_text(encoding="utf-8").splitlines(), 1):
                if query in line.lower():
                    snippet = _sanitize_for_recall(line.strip())
                    results.append(f"{relative_path}:{line_number} - {snippet}")
                    break
        except UnicodeDecodeError:
            continue
        if len(results) >= MAX_SEARCH_RESULTS:
            break

    if not results:
        return "No matching memory notes found."
    return "\n".join(results)


def read_wiki_note(path: str) -> str:
    """Read one note under Easel/Wiki."""
    if not workspace_available():
        return "Error: no workspace folder is mounted, so wiki notes are unavailable."

    try:
        note = _resolve_wiki_path(path)
    except WorkspacePathError as error:
        return f"Error: {error}"

    if not note.is_file():
        return f"Error: no wiki note found at '{path}'."
    if note.stat().st_size > MAX_NOTE_BYTES:
        return f"Error: '{path}' is larger than the {MAX_NOTE_BYTES // 1024} KB read limit."

    try:
        return _sanitize_for_recall(note.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return f"Error: '{path}' is not a UTF-8 text file and cannot be read."
    except OSError as error:
        return f"Error: could not read '{path}': {error}."


def search_chat_history(query: str, current_chat_id: int | None = None) -> str:
    """Search prior conversations (not the current one) by full-text keyword.

    ``current_chat_id`` is injected server-side by the executor, never by the model, so
    the active conversation — already visible in context — is excluded from results.
    """
    from user_database.chats_database import fts_available, search_messages

    if not fts_available():
        return "Error: chat history search is unavailable on this server."
    query = (query or "").strip()
    if not query:
        return "Error: search_chat_history requires a non-empty query."

    hits = search_messages(
        query, exclude_chat_id=current_chat_id, limit=MAX_CHAT_HISTORY_RESULTS
    )
    if not hits:
        return "No past conversations matched."

    lines: list[str] = []
    for hit in hits:
        date = _format_recall_date(hit["created_datetime"])
        name = hit["session_name"] or "untitled"
        snippet = _sanitize_for_recall(hit["snippet"] or "").strip()
        lines.append(
            f'chat {hit["chat_session_id"]} "{name}" · {date} · {hit["role"]} · '
            f'msg {hit["id"]}\n  …{snippet}…'
        )
    lines.append(
        "\nUse read_chat_history(chat_id, around_message_id) to see surrounding messages."
    )
    return "\n".join(lines)


def read_chat_history(
    chat_id: int, around_message_id: int, context: int = 6
) -> str:
    """Return the messages surrounding a search_chat_history hit, in order."""
    from user_database.chats_database import fetch_messages_around

    try:
        chat_id = int(chat_id)
        around_message_id = int(around_message_id)
        context = max(1, min(int(context), 20))
    except (TypeError, ValueError):
        return "Error: chat_id, around_message_id, and context must be integers."

    rows = fetch_messages_around(chat_id, around_message_id, context)
    if not rows:
        return (
            f"Error: no readable messages found in chat {chat_id} "
            f"around message {around_message_id}."
        )

    blocks: list[str] = []
    for row in rows:
        date = _format_recall_date(row["created_datetime"])
        body = _sanitize_for_recall((row["message"] or "")[:MAX_CHAT_MESSAGE_CHARS])
        blocks.append(f"[{row['role']} · {date}] {body}")
    return "\n\n".join(blocks)


def memory(
    action: str,
    target: str,
    content: str = "",
    old_text: str = "",
    chat_id: int | None = None,
) -> str:
    """Immediately add, replace, or remove a bullet in core memory.

    Each entry is one top-level ``- `` bullet line. ``replace``/``remove`` locate the
    entry by case-insensitive substring of ``old_text`` and refuse ambiguous matches.
    Writes go through the same hardened path as the consolidator (atomic, drift-checked,
    scrubbed/scanned, hard-budget-enforced).
    """
    from config import (
        Config,
        CORE_MEMORY_BUDGET_CHARS,
        CoreMemoryDrift,
        CoreMemoryOverBudget,
        CoreMemoryUnavailable,
    )

    if not workspace_available():
        return "Error: no workspace is mounted, so memory is unavailable."
    if target not in ("memory", "user"):
        return "Error: target must be 'memory' or 'user'."
    if action not in ("add", "replace", "remove"):
        return "Error: action must be 'add', 'replace', or 'remove'."

    current, fingerprint = Config.get_core_memory_with_fingerprint(target)
    lines = current.splitlines()

    if action == "add":
        new_bullet = _normalize_bullet(content)
        if not new_bullet:
            return "Error: add requires non-empty content."
        if any(
            _is_bullet(line) and _bullet_text(line) == _bullet_text(new_bullet)
            for line in lines
        ):
            return "Already present — no duplicate added."
        new_lines = lines + [new_bullet]
        change_label = _bullet_text(new_bullet)
    else:
        if not old_text.strip():
            return f"Error: {action} requires old_text identifying the entry."
        needle = old_text.strip().lower()
        matches = [
            i
            for i, line in enumerate(lines)
            if _is_bullet(line) and needle in _bullet_text(line).lower()
        ]
        if not matches:
            return (
                f"Error: no entry matched '{old_text}'. Nearest entries:\n"
                + _nearest_bullets(lines, needle)
            )
        if len(matches) > 1:
            preview = "\n".join(lines[i] for i in matches)
            return (
                f"Error: '{old_text}' matched {len(matches)} entries. Use a more specific "
                f"old_text. Matches:\n{preview}"
            )
        index = matches[0]
        if action == "remove":
            change_label = _bullet_text(lines[index])
            new_lines = lines[:index] + lines[index + 1 :]
        else:
            new_bullet = _normalize_bullet(content)
            if not new_bullet:
                return "Error: replace requires non-empty content."
            change_label = _bullet_text(new_bullet)
            new_lines = lines[:index] + [new_bullet] + lines[index + 1 :]

    new_text = "\n".join(new_lines).strip()
    new_text = new_text + "\n" if new_text else ""

    try:
        Config.set_core_memory(target, new_text, expected_fingerprint=fingerprint)
    except CoreMemoryOverBudget as error:
        return (
            f"Memory is at {error.current}/{error.limit} chars and this change doesn't "
            "fit. Use replace or remove to consolidate existing entries, or move details "
            "into a wiki note, then retry."
        )
    except CoreMemoryDrift:
        return (
            "The memory file was edited outside this chat; the previous version was "
            "backed up. Re-read memory and retry."
        )
    except CoreMemoryUnavailable:
        return "Error: no workspace is mounted, so memory is unavailable."

    _record_memory_write(chat_id, target, action, change_label)
    usage = len(Config.get_core_memory(target))
    file_name = "USER.md" if target == "user" else "MEMORY.md"
    verb = {"add": "Saved", "replace": "Updated", "remove": "Removed"}[action]
    return f"{verb}. {file_name} now at {usage}/{CORE_MEMORY_BUDGET_CHARS} chars."


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^\s*-\s+", line))


def _bullet_text(line: str) -> str:
    return re.sub(r"^\s*-\s+", "", line).strip()


def _nearest_bullets(lines: list[str], needle: str, count: int = 3) -> str:
    bullets = [_bullet_text(line) for line in lines if _is_bullet(line)]
    if not bullets:
        return "(memory is currently empty)"
    ranked = sorted(
        bullets,
        key=lambda b: difflib.SequenceMatcher(None, needle, b.lower()).ratio(),
        reverse=True,
    )
    return "\n".join(f"- {b}" for b in ranked[:count])


def _record_memory_write(
    chat_id: int | None, target: str, action: str, change_label: str
) -> None:
    """Best-effort MemoryEvent so agent-driven writes show in the Memory activity feed."""
    from user_database.chats_database import MemoryEvent, get_engine
    from sqlalchemy.orm import Session

    clipped = change_label if len(change_label) <= 80 else change_label[:79] + "…"
    try:
        with Session(get_engine()) as session:
            session.add(
                MemoryEvent(
                    chat_session_id=chat_id,
                    kind="memory_write",
                    summary=f"{target}: {action} '{clipped}'",
                )
            )
            session.commit()
    except Exception as error:  # pragma: no cover - logging must never fail the tool
        print(f"Could not record memory write event: {error}")


def _parse_onboard(content: str) -> dict[str, list[str]]:
    sections = {section: [] for section in ONBOARD_SECTIONS}
    current_section: str | None = None

    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current_section = heading if heading in sections else None
            continue
        if current_section and line.strip().startswith("- "):
            bullet = _normalize_bullet(line)
            if bullet and bullet not in sections[current_section]:
                sections[current_section].append(bullet)

    return sections


def _render_onboard(chat_id: int, sections: dict[str, list[str]]) -> str:
    lines = [f"# Onboard memory for chat {chat_id}", ""]
    for section in ONBOARD_SECTIONS:
        lines.extend([f"## {section}"])
        items = sections.get(section, [])
        if items:
            lines.extend(items)
        else:
            lines.append("- None yet")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _normalize_bullet(item: str) -> str:
    stripped = item.strip()
    if not stripped or stripped == "- None yet":
        return ""
    if stripped.startswith("- "):
        return stripped
    return f"- {stripped}"


def _onboard_path(chat_id: int) -> Path:
    return resolve_in_workspace(f"Easel/Onboard/chat-{chat_id}.md")


def _wiki_root() -> Path:
    return resolve_in_workspace("Easel/Wiki")


def _resolve_wiki_path(path: str) -> Path:
    wiki_root = _wiki_root().resolve()
    candidate = (wiki_root / path).resolve()
    if candidate != wiki_root and not candidate.is_relative_to(wiki_root):
        raise WorkspacePathError(f"Path '{path}' is outside Easel/Wiki and was blocked.")
    return candidate
