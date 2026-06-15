from datetime import datetime
import json
import shutil

from sqlalchemy.orm import Session

from config import (
    Config,
    CORE_MEMORY_BUDGET_CHARS,
    MAX_CONSOLIDATION_ATTEMPTS,
    CoreMemoryDrift,
    CoreMemoryOverBudget,
)
from tools import threat_patterns
from tools.memory import ONBOARD_SECTIONS, _bullet_text, _is_bullet, scrub_secrets
from tools.workspace import resolve_in_workspace, workspace_available
from user_database.chats_database import ChatSession, MemoryEvent, Message, get_engine


def consolidate_chat(chat_id: int) -> None:
    """Promote one chat's onboard memory into core memory and the wiki graph."""
    if not workspace_available():
        return

    if not _claim_chat(chat_id):
        return

    try:
        summary, detail = _write_memory_files(chat_id)
    except Exception as error:
        _record_failure(chat_id, str(error))
        return

    _record_success(chat_id, summary, detail)


def _claim_chat(chat_id: int) -> bool:
    with Session(get_engine()) as session:
        chat = session.get(ChatSession, chat_id)
        if chat is None:
            return False
        if chat.consolidation_status in {"in_progress", "failed"}:
            return False
        chat.consolidation_status = "in_progress"
        chat.consolidation_attempts = (chat.consolidation_attempts or 0) + 1
        session.commit()
        return True


def _write_memory_files(chat_id: int) -> tuple[str, dict]:
    onboard_path = resolve_in_workspace(f"Easel/Onboard/chat-{chat_id}.md")
    if not onboard_path.exists():
        sections = {section: [] for section in ONBOARD_SECTIONS}
    else:
        sections = _parse_onboard(onboard_path.read_text(encoding="utf-8"))

    with Session(get_engine()) as session:
        chat = session.get(ChatSession, chat_id)
        if chat is None:
            raise ValueError(f"Chat {chat_id} does not exist.")
        after_id = chat.last_consolidated_message_id or 0
        messages = (
            session.query(Message)
            .filter(Message.chat_session_id == chat_id, Message.id > after_id)
            .order_by(Message.id)
            .all()
        )
        max_message_id = messages[-1].id if messages else after_id

    # Nothing salient was captured: archive the (empty) onboard file and advance the
    # high-water mark without spending an LLM classification call.
    if not any(sections.values()):
        archived = _archive_onboard(chat_id)
        return (
            "nothing to consolidate",
            {
                "archived_onboard": archived,
                "max_message_id": max_message_id,
                "user_facts": 0,
                "operating_memories": 0,
                "topic_notes": 0,
                "project_notes": 0,
            },
        )

    classified = _classify(sections, _read_index_text(), _existing_slugs())
    today = datetime.utcnow().date().isoformat()

    user_count = _promote_core("user", classified["user"])
    memory_count = _promote_core("memory", classified["memory"])
    topic_paths = [
        _write_wiki_note("topics", entry, chat_id, today)
        for entry in classified["topics"]
    ]
    project_paths = [
        _write_wiki_note("projects", entry, chat_id, today)
        for entry in classified["projects"]
    ]
    _write_index()
    archived = _archive_onboard(chat_id)

    return (
        f"{user_count} user facts, {memory_count} operating memories, "
        f"{len(topic_paths)} topic notes, {len(project_paths)} project notes",
        {
            "archived_onboard": archived,
            "max_message_id": max_message_id,
            "user_facts": user_count,
            "operating_memories": memory_count,
            "topic_notes": len(topic_paths),
            "project_notes": len(project_paths),
            "topics": topic_paths,
            "projects": project_paths,
        },
    )


# --- Classification (one structured LLM call) --------------------------------

_CLASSIFY_PROMPT = """You curate an AI assistant's long-term memory. You are given the
onboard notes captured from one chat, the current knowledge-base index, and the slugs of
existing notes. Classify each item and route it. Return ONLY JSON with this shape:

{
  "user":     ["short bullet about the user", ...],
  "memory":   ["short bullet of durable operating knowledge", ...],
  "topics":   [{"slug": "kebab-slug", "title": "Title", "tags": ["tag"],
               "aliases": [], "bullets": ["fact"], "links": ["other-slug"]}],
  "projects": [{"slug": "kebab-slug", "title": "Title", "tags": ["tag"],
               "aliases": [], "bullets": ["fact"], "links": ["other-slug"]}],
  "discard":  ["item not worth keeping", ...]
}

Rules:
- "user" = durable facts/preferences about the person. "memory" = durable operating
  knowledge for the assistant. Keep both terse; trivia goes to topics or discard.
- A "project" is an ongoing, multi-session effort. A "topic" is an entity, subject, tool,
  or person. Reuse an existing slug from the provided list when the item belongs to it;
  otherwise create a new kebab-case slug.
- "links" are slugs of related notes to cross-link (bidirectional).
- Never include secrets, credentials, API keys, or tokens.
- Output JSON only, no prose, no code fences."""


def _classify(sections: dict, index_text: str, existing_slugs: list[str]) -> dict:
    from ClientModel import ClientModel

    if ClientModel.client is None:
        raise RuntimeError("Memory model is unavailable; cannot classify.")

    payload = json.dumps(
        {
            "onboard": sections,
            "existing_note_slugs": existing_slugs,
            "index": index_text,
        },
        ensure_ascii=True,
    )
    completion = ClientModel.get_client().chat.completions.create(
        model=Config.memory_model(),
        messages=[
            {"role": "system", "content": _CLASSIFY_PROMPT},
            {"role": "user", "content": payload},
        ],
    )
    content = completion.choices[0].message.content or ""
    return _parse_classification(content)


def _parse_classification(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Classifier returned invalid JSON: {error}")
    if not isinstance(raw, dict):
        raise ValueError("Classifier did not return a JSON object.")

    return {
        "user": _string_list(raw.get("user")),
        "memory": _string_list(raw.get("memory")),
        "topics": [_normalize_entry(item) for item in _list(raw.get("topics"))],
        "projects": [_normalize_entry(item) for item in _list(raw.get("projects"))],
        "discard": _string_list(raw.get("discard")),
    }


def _normalize_entry(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    title = str(raw.get("title") or "Untitled").strip()
    slug = str(raw.get("slug") or "").strip() or _slugify(title)
    return {
        "slug": _slugify(slug),
        "title": title,
        "tags": _string_list(raw.get("tags")),
        "aliases": _string_list(raw.get("aliases")),
        "bullets": _string_list(raw.get("bullets")),
        "links": [_slugify(s) for s in _string_list(raw.get("links"))],
    }


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _string_list(value) -> list[str]:
    return [str(item).strip() for item in _list(value) if str(item).strip()]


# --- Core memory promotion (with hard-budget merge/demote) --------------------

def _promote_core(kind: str, items: list[str]) -> int:
    if not items:
        return 0

    current, fingerprint = Config.get_core_memory_with_fingerprint(kind)
    lines = current.splitlines()
    existing = {_bullet_text(line) for line in lines if _is_bullet(line)}
    added = 0
    for item in items:
        text = _bullet_text(item) if _is_bullet(item) else item.strip()
        if text and text not in existing:
            lines.append(f"- {text}")
            existing.add(text)
            added += 1

    if added == 0:
        return 0

    content = "\n".join(lines).strip() + "\n"
    try:
        Config.set_core_memory(kind, content, expected_fingerprint=fingerprint)
    except CoreMemoryOverBudget:
        shrunk, demoted = _shrink_core(content)
        if demoted:
            _append_demoted(kind, demoted)
        # The rejected write left the file unchanged, so the fingerprint still holds.
        Config.set_core_memory(kind, shrunk, expected_fingerprint=fingerprint)
    return added


_SHRINK_PROMPT = """The following core memory exceeds its {limit}-character budget. Merge
duplicates, tighten wording, and move the least durable lines into a "demoted" list so the
kept content fits. Preserve high-value, long-lived facts. Return ONLY JSON:
{{"content": "kept bullets, one per line, under {limit} chars", "demoted": ["moved line"]}}
"""


def _shrink_core(content: str) -> tuple[str, list[str]]:
    from ClientModel import ClientModel

    if ClientModel.client is None:
        raise RuntimeError("Memory model is unavailable; cannot shrink core memory.")

    completion = ClientModel.get_client().chat.completions.create(
        model=Config.memory_model(),
        messages=[
            {
                "role": "system",
                "content": _SHRINK_PROMPT.format(limit=CORE_MEMORY_BUDGET_CHARS),
            },
            {"role": "user", "content": content},
        ],
    )
    raw = (completion.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw.strip("`")
        raw = raw.removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Shrink pass returned invalid JSON: {error}")
    kept = str(data.get("content", "")).strip()
    kept = kept + "\n" if kept else ""
    return kept, _string_list(data.get("demoted"))


def _append_demoted(kind: str, demoted: list[str]) -> None:
    path = resolve_in_workspace("Easel/Wiki/topics/demoted-memory.md")
    today = datetime.utcnow().date().isoformat()
    if path.exists():
        fm, body = _parse_note(path.read_text(encoding="utf-8"))
        title, sections, order = _split_body(body)
    else:
        fm = {
            "tags": _render_list(["topic", "overflow"]),
            "aliases": "[]",
            "created": today,
            "updated": today,
        }
        title = "Demoted memory"
        sections, order = {"Notes": [], "Related": [], "Related conversations": []}, [
            "Notes",
            "Related",
            "Related conversations",
        ]
    _ensure_sections(sections, order)
    _add_bullets(sections["Notes"], [f"({kind}) {line}" for line in demoted])
    fm["updated"] = today
    _safe_write(path, _render_note(fm, _rebuild_body(title or "Demoted memory", sections, order)))


# --- Wiki note writing (topics + projects) -----------------------------------

def _write_wiki_note(category: str, entry: dict, chat_id: int, today: str) -> str:
    root = resolve_in_workspace(f"Easel/Wiki/{category}")
    root.mkdir(parents=True, exist_ok=True)
    slug = entry["slug"]
    path = root / f"{slug}.md"

    if path.exists():
        fm, body = _parse_note(path.read_text(encoding="utf-8"))
        title, sections, order = _split_body(body)
        title = title or entry["title"]
    else:
        fm = {
            "tags": _render_list([category[:-1]] + entry["tags"]),
            "aliases": _render_list(entry["aliases"]),
            "created": today,
            "updated": today,
        }
        title = entry["title"]
        sections, order = {}, []

    _ensure_sections(sections, order)
    _add_bullets(sections["Notes"], entry["bullets"])
    _add_bullets(sections["Related"], [f"[[{link}]]" for link in entry["links"]])
    _add_bullets(sections["Related conversations"], [f"chat {chat_id} · {today}"])
    fm.setdefault("created", today)
    fm.setdefault("tags", _render_list([category[:-1]] + entry["tags"]))
    fm.setdefault("aliases", _render_list(entry["aliases"]))
    fm["updated"] = today

    _safe_write(path, _render_note(fm, _rebuild_body(title, sections, order)))

    for link in entry["links"]:
        if link and link != slug:
            _ensure_reciprocal_link(link, slug, today)

    return path.relative_to(resolve_in_workspace("Easel/Wiki")).as_posix()


def _ensure_reciprocal_link(target_slug: str, source_slug: str, today: str) -> None:
    for category in ("topics", "projects"):
        path = resolve_in_workspace(f"Easel/Wiki/{category}/{target_slug}.md")
        if path.exists():
            fm, body = _parse_note(path.read_text(encoding="utf-8"))
            title, sections, order = _split_body(body)
            _ensure_sections(sections, order)
            _add_bullets(sections["Related"], [f"[[{source_slug}]]"])
            fm["updated"] = today
            _safe_write(
                path,
                _render_note(fm, _rebuild_body(title or target_slug, sections, order)),
            )
            return

    # No note for that slug yet: create a stub topic so the graph still links up.
    root = resolve_in_workspace("Easel/Wiki/topics")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{target_slug}.md"
    fm = {
        "tags": _render_list(["topic"]),
        "aliases": "[]",
        "created": today,
        "updated": today,
    }
    sections, order = {}, []
    _ensure_sections(sections, order)
    _add_bullets(sections["Related"], [f"[[{source_slug}]]"])
    title = target_slug.replace("-", " ").title()
    _safe_write(path, _render_note(fm, _rebuild_body(title, sections, order)))


def _write_index() -> None:
    wiki_root = resolve_in_workspace("Easel/Wiki")
    wiki_root.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Memory index",
        "",
        "| Title | Path | Description | Tags | Updated |",
        "|---|---|---|---|---|",
    ]

    for category in ("topics", "projects"):
        category_root = wiki_root / category
        if not category_root.is_dir():
            continue
        for note in sorted(category_root.glob("*.md")):
            fm, body = _parse_note(note.read_text(encoding="utf-8"))
            title, sections, _ = _split_body(body)
            title = title or note.stem.replace("-", " ").title()
            description = _first_bullet(sections.get("Notes", [])) or title
            tags = fm.get("tags", "").strip("[]") or category[:-1]
            updated = fm.get("updated", "")
            relative = note.relative_to(wiki_root).as_posix()
            lines.append(
                f"| {_cell(title)} | {relative} | {_cell(description)} | "
                f"{_cell(tags)} | {_cell(updated)} |"
            )

    _safe_write(wiki_root / "_index.md", "\n".join(lines) + "\n")


# --- Note format helpers ------------------------------------------------------

_BODY_SECTIONS = ["Notes", "Related", "Related conversations"]


def _parse_note(content: str) -> tuple[dict, str]:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm: dict[str, str] = {}
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    fm[key.strip()] = value.strip()
            return fm, parts[2].lstrip("\n")
    return {}, content


def _render_note(fm: dict, body: str) -> str:
    lines = ["---"]
    for key in ("tags", "aliases", "created", "updated"):
        if key in fm:
            lines.append(f"{key}: {fm[key]}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.rstrip() + "\n"


def _split_body(body: str) -> tuple[str, dict, list]:
    title = ""
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = line[3:].strip()
            if current not in sections:
                sections[current] = []
                order.append(current)
        elif current is not None:
            sections[current].append(line)
    return title, sections, order


def _ensure_sections(sections: dict, order: list) -> None:
    for heading in _BODY_SECTIONS:
        if heading not in sections:
            sections[heading] = []
            order.append(heading)


def _add_bullets(section: list[str], items: list[str]) -> None:
    existing = {_bullet_text(line) for line in section if _is_bullet(line)}
    for item in items:
        text = item.strip()
        if text.startswith("- "):
            text = text[2:].strip()
        if text and text not in existing:
            section.append(f"- {text}")
            existing.add(text)


def _rebuild_body(title: str, sections: dict, order: list) -> str:
    out = [f"# {title}", ""]
    for heading in order:
        content = [line for line in sections.get(heading, []) if line.strip()]
        out.append(f"## {heading}")
        out.extend(content)
        out.append("")
    return "\n".join(out).strip() + "\n"


def _first_bullet(section: list[str]) -> str:
    for line in section:
        if _is_bullet(line):
            return _bullet_text(line)[:80]
    return ""


def _render_list(items: list[str]) -> str:
    seen: list[str] = []
    for item in items:
        clean = str(item).strip()
        if clean and clean not in seen:
            seen.append(clean)
    return "[" + ", ".join(seen) + "]"


def _cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ").strip()


def _safe_write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = threat_patterns.sanitize_for_model(scrub_secrets(content), source="wiki")
    path.write_text(safe, encoding="utf-8")


def _read_index_text() -> str:
    path = resolve_in_workspace("Easel/Wiki/_index.md")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _existing_slugs() -> list[str]:
    slugs: list[str] = []
    for category in ("topics", "projects"):
        root = resolve_in_workspace(f"Easel/Wiki/{category}")
        if root.is_dir():
            slugs.extend(sorted(note.stem for note in root.glob("*.md")))
    return slugs


# --- Bookkeeping (claim / archive / events) ----------------------------------

def _archive_onboard(chat_id: int) -> str | None:
    onboard_path = resolve_in_workspace(f"Easel/Onboard/chat-{chat_id}.md")
    if not onboard_path.exists():
        return None
    archive_root = resolve_in_workspace("Easel/Onboard/_archive")
    archive_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    archive_path = archive_root / f"chat-{chat_id}-{timestamp}.md"
    shutil.move(str(onboard_path), str(archive_path))
    return archive_path.relative_to(resolve_in_workspace("Easel")).as_posix()


def _record_success(chat_id: int, summary: str, detail: dict) -> None:
    with Session(get_engine()) as session:
        chat = session.get(ChatSession, chat_id)
        if chat is None:
            return
        chat.last_consolidated_message_id = detail["max_message_id"]
        chat.consolidated_at = datetime.utcnow()
        chat.consolidation_status = "done"
        chat.consolidation_attempts = 0
        chat.consolidate_after = None
        session.add(
            MemoryEvent(
                chat_session_id=chat_id,
                kind="consolidated",
                summary=summary,
                detail=json.dumps(detail),
            )
        )
        session.commit()

    _append_log(f"consolidated chat {chat_id}: {summary}")


def _record_failure(chat_id: int, message: str) -> None:
    with Session(get_engine()) as session:
        chat = session.get(ChatSession, chat_id)
        if chat is None:
            return
        if (chat.consolidation_attempts or 0) >= MAX_CONSOLIDATION_ATTEMPTS:
            chat.consolidation_status = "failed"
            session.add(
                MemoryEvent(
                    chat_session_id=chat_id,
                    kind="failed",
                    summary=f"Memory consolidation failed for chat {chat_id}.",
                    detail=json.dumps({"error": message}),
                )
            )
        else:
            chat.consolidation_status = "pending"
            chat.consolidate_after = None
        session.commit()

    _append_log(f"failed chat {chat_id}: {message}")


def _append_log(line: str) -> None:
    log_path = resolve_in_workspace("Easel/Memory/_consolidation_log.md")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"- {timestamp} - {line}\n")


def _parse_onboard(content: str) -> dict[str, list[str]]:
    sections = {section: [] for section in ONBOARD_SECTIONS}
    current_section: str | None = None
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current_section = heading if heading in sections else None
        elif current_section and line.strip().startswith("- ") and line.strip() != "- None yet":
            sections[current_section].append(line.strip())
    return sections


def _slugify(title: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in title)
    return "-".join(part for part in slug.split("-") if part) or "note"
