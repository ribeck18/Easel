"""Tests for the chat-history FTS5 index and query helpers.

Uses a temporary on-disk SQLite database (FTS5 needs a real file connection) and
monkeypatches ``get_engine`` so the query helpers target it.
"""

import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import user_database.chats_database as db  # noqa: E402
from user_database.chats_database import ChatSession, Message  # noqa: E402


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    path = tmp_path / "fts.db"
    eng = sa.create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )
    db.base.metadata.create_all(eng)
    with eng.begin() as connection:
        for statement in db._FTS_STATEMENTS:
            connection.execute(text(statement))
    monkeypatch.setattr(db, "get_engine", lambda: eng)
    monkeypatch.setattr(db, "_FTS_AVAILABLE", True)
    return eng


def _seed(eng):
    with Session(eng) as s:
        alpha = ChatSession(id=1, session_name="Alpha")
        beta = ChatSession(id=2, session_name="Beta")
        s.add_all([alpha, beta])
        s.flush()
        s.add_all(
            [
                Message(id=1, chat_session_id=1, role="user",
                        message="I love the Obsidian vault workflow"),
                Message(id=2, chat_session_id=1, role="assistant",
                        message="Sure, Obsidian is great for notes"),
                Message(id=3, chat_session_id=2, role="user",
                        message="Tell me about the database schema"),
                # A tool row that must NOT be indexed even though it says "obsidian".
                Message(id=4, chat_session_id=2, role="tool", tool_name="read_file",
                        message="huge tool output mentioning obsidian"),
                # An assistant row with no text content must not be indexed.
                Message(id=5, chat_session_id=2, role="assistant", message=None),
            ]
        )
        s.commit()


def test_insert_trigger_indexes_only_user_and_assistant(engine):
    _seed(engine)
    hits = db.search_messages("obsidian")
    assert {h["chat_session_id"] for h in hits} == {1}
    assert all(h["role"] in ("user", "assistant") for h in hits)
    assert len(hits) == 2


def test_exclude_current_chat(engine):
    _seed(engine)
    assert db.search_messages("obsidian", exclude_chat_id=1) == []


def test_punctuation_query_does_not_error(engine):
    _seed(engine)
    # FTS5 operators/punctuation must be neutralized, not raise a syntax error.
    hits = db.search_messages("schema (database)")
    assert [h["id"] for h in hits] == [3]
    # A query that is pure punctuation must also be safe (no match, no crash).
    assert db.search_messages("-- * (")  == []


def test_snippet_present(engine):
    _seed(engine)
    hits = db.search_messages("schema")
    assert "schema" in hits[0]["snippet"].lower()


def test_fetch_messages_around(engine):
    _seed(engine)
    around = db.fetch_messages_around(1, 2, context=2)
    assert [m["id"] for m in around] == [1, 2]
    # A chat with no qualifying messages at/before the anchor → empty.
    assert db.fetch_messages_around(99, 5, context=2) == []
    # A high anchor harmlessly returns the chat's tail (context window).
    assert [m["id"] for m in db.fetch_messages_around(1, 999, context=2)] == [1, 2]


def test_delete_trigger_keeps_index_in_sync(engine):
    _seed(engine)
    with Session(engine) as s:
        s.delete(s.get(Message, 1))
        s.commit()
    hits = db.search_messages("obsidian")
    assert [h["id"] for h in hits] == [2]


def test_fts_query_escaping():
    assert db._fts_match_query("hello world") == '"hello" "world"'
    assert db._fts_match_query('say "hi"') == '"say" """hi"""'
    assert db._fts_match_query("   ") == ""


def test_unavailable_returns_empty(engine, monkeypatch):
    _seed(engine)
    monkeypatch.setattr(db, "_FTS_AVAILABLE", False)
    assert db.search_messages("obsidian") == []
