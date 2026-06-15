"""Tests for consolidation v2: note format, wiki writers, core promotion, and a full run."""

import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import services.consolidation as cons  # noqa: E402
import tools.workspace as workspace  # noqa: E402
import user_database.chats_database as db  # noqa: E402
from config import Config  # noqa: E402
from user_database.chats_database import ChatSession, MemoryEvent, Message  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # Workspace → temp dir (core memory + wiki land here).
    monkeypatch.setattr(workspace, "WORKSPACE_ROOT", tmp_path)
    # Database → temp file engine, used by consolidation's bookkeeping.
    eng = sa.create_engine(
        f"sqlite:///{tmp_path / 'c.db'}", connect_args={"check_same_thread": False}
    )
    db.base.metadata.create_all(eng)
    monkeypatch.setattr(cons, "get_engine", lambda: eng)
    return tmp_path, eng


def _wiki(tmp_path, *parts):
    return tmp_path / "Easel" / "Wiki" / Path(*parts)


# --- note format helpers ------------------------------------------------------

def test_note_roundtrip():
    fm = {"tags": "[topic, tool]", "aliases": "[]", "created": "2026-06-10",
          "updated": "2026-06-10"}
    body = "# Obsidian\n\n## Notes\n- a note\n\n## Related\n- [[easel]]\n"
    rendered = cons._render_note(fm, body)
    fm2, body2 = cons._parse_note(rendered)
    assert fm2["tags"] == "[topic, tool]"
    title, sections, order = cons._split_body(body2)
    assert title == "Obsidian"
    assert "- a note" in sections["Notes"]


def test_add_bullets_dedups():
    section = ["- one"]
    cons._add_bullets(section, ["one", "- one", "two"])
    assert section == ["- one", "- two"]


# --- wiki note writing --------------------------------------------------------

def test_write_wiki_note_creates_frontmatter_and_sections(env):
    tmp_path, _ = env
    entry = {"slug": "obsidian", "title": "Obsidian", "tags": ["tool"],
             "aliases": [], "bullets": ["great for notes"], "links": []}
    cons._write_wiki_note("topics", entry, chat_id=7, today="2026-06-10")
    note = _wiki(tmp_path, "topics", "obsidian.md").read_text()
    assert note.startswith("---")
    assert "tags: [topic, tool]" in note
    assert "- great for notes" in note
    assert "chat 7 · 2026-06-10" in note


def test_write_wiki_note_is_idempotent(env):
    tmp_path, _ = env
    entry = {"slug": "obsidian", "title": "Obsidian", "tags": ["tool"],
             "aliases": [], "bullets": ["great for notes"], "links": []}
    cons._write_wiki_note("topics", entry, chat_id=7, today="2026-06-10")
    cons._write_wiki_note("topics", entry, chat_id=7, today="2026-06-10")
    note = _wiki(tmp_path, "topics", "obsidian.md").read_text()
    assert note.count("- great for notes") == 1
    assert note.count("chat 7 · 2026-06-10") == 1


def test_reciprocal_link_creates_stub(env):
    tmp_path, _ = env
    entry = {"slug": "easel-memory-v2", "title": "Easel Memory v2", "tags": [],
             "aliases": [], "bullets": ["the plan"], "links": ["obsidian"]}
    cons._write_wiki_note("projects", entry, chat_id=1, today="2026-06-10")
    project = _wiki(tmp_path, "projects", "easel-memory-v2.md").read_text()
    assert "[[obsidian]]" in project
    # A stub topic note for the link target was created with the back-link.
    stub = _wiki(tmp_path, "topics", "obsidian.md").read_text()
    assert "[[easel-memory-v2]]" in stub


def test_write_index_lists_topics_and_projects(env):
    tmp_path, _ = env
    cons._write_wiki_note("topics", {"slug": "obsidian", "title": "Obsidian",
                                     "tags": ["tool"], "aliases": [],
                                     "bullets": ["notes app"], "links": []}, 1, "2026-06-10")
    cons._write_wiki_note("projects", {"slug": "easel", "title": "Easel",
                                       "tags": [], "aliases": [],
                                       "bullets": ["the app"], "links": []}, 1, "2026-06-09")
    cons._write_index()
    index = _wiki(tmp_path, "_index.md").read_text()
    assert "topics/obsidian.md" in index
    assert "projects/easel.md" in index
    assert "2026-06-10" in index and "2026-06-09" in index  # per-note updated dates


# --- core promotion -----------------------------------------------------------

def test_promote_core_dedups(env):
    assert cons._promote_core("user", ["likes tea", "likes tea"]) == 1
    assert cons._promote_core("user", ["likes tea"]) == 0  # already present
    assert "likes tea" in Config.get_core_memory("user")


def test_promote_core_shrinks_on_overflow(env, monkeypatch):
    monkeypatch.setattr(config, "CORE_MEMORY_BUDGET_CHARS", 40)
    monkeypatch.setattr(
        cons, "_shrink_core", lambda content: ("- kept\n", ["dropped one", "dropped two"])
    )
    added = cons._promote_core("memory", ["x" * 100])
    assert added == 1
    assert Config.get_core_memory("memory").strip() == "- kept"
    demoted = _wiki(env[0], "topics", "demoted-memory.md").read_text()
    assert "dropped one" in demoted and "dropped two" in demoted


# --- full consolidate_chat run ------------------------------------------------

def test_full_consolidation(env, monkeypatch):
    tmp_path, eng = env

    # Seed a chat with messages.
    with Session(eng) as s:
        chat = ChatSession(session_name="Memory chat")
        s.add(chat)
        s.flush()
        chat_id = chat.id
        s.add_all([
            Message(chat_session_id=chat_id, role="user", message="I use Obsidian daily"),
            Message(chat_session_id=chat_id, role="assistant", message="Noted!"),
        ])
        s.commit()

    # Onboard file with captured content.
    onboard = tmp_path / "Easel" / "Onboard" / f"chat-{chat_id}.md"
    onboard.parent.mkdir(parents=True, exist_ok=True)
    onboard.write_text(
        "# Onboard\n\n## User facts/preferences\n- uses Obsidian daily\n\n"
        "## Topics & entities\n- Obsidian\n",
        encoding="utf-8",
    )

    # Stub the LLM classifier.
    monkeypatch.setattr(cons, "_classify", lambda sections, idx, slugs: {
        "user": ["uses Obsidian daily"],
        "memory": [],
        "topics": [{"slug": "obsidian", "title": "Obsidian", "tags": ["tool"],
                    "aliases": [], "bullets": ["the user's note app"], "links": []}],
        "projects": [],
        "discard": [],
    })

    cons.consolidate_chat(chat_id)

    # Core memory updated.
    assert "uses Obsidian daily" in Config.get_core_memory("user")
    # Topic note + index written.
    assert _wiki(tmp_path, "topics", "obsidian.md").exists()
    assert "topics/obsidian.md" in _wiki(tmp_path, "_index.md").read_text()
    # Onboard archived (moved out of the active path).
    assert not onboard.exists()
    assert list((tmp_path / "Easel" / "Onboard" / "_archive").glob("*.md"))

    # Chat marked done + success event + high-water mark advanced.
    with Session(eng) as s:
        chat = s.get(ChatSession, chat_id)
        assert chat.consolidation_status == "done"
        assert chat.last_consolidated_message_id is not None
        events = s.query(MemoryEvent).filter_by(chat_session_id=chat_id).all()
        assert any(e.kind == "consolidated" for e in events)


def test_classifier_failure_is_recorded(env, monkeypatch):
    tmp_path, eng = env
    with Session(eng) as s:
        chat = ChatSession(session_name="bad")
        s.add(chat)
        s.flush()
        chat_id = chat.id
        s.add(Message(chat_session_id=chat_id, role="user", message="hi"))
        s.commit()

    onboard = tmp_path / "Easel" / "Onboard" / f"chat-{chat_id}.md"
    onboard.parent.mkdir(parents=True, exist_ok=True)
    onboard.write_text("## User facts/preferences\n- something\n", encoding="utf-8")

    def boom(*a, **k):
        raise ValueError("classifier exploded")

    monkeypatch.setattr(cons, "_classify", boom)
    # Imported by-name into the consolidation module, so patch it there.
    monkeypatch.setattr(cons, "MAX_CONSOLIDATION_ATTEMPTS", 1)

    cons.consolidate_chat(chat_id)

    with Session(eng) as s:
        chat = s.get(ChatSession, chat_id)
        assert chat.consolidation_status == "failed"
        # Onboard left intact for retry/inspection.
    assert onboard.exists()
