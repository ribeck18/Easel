from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Boolean,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
    Engine,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
    declarative_base,
)
from datetime import datetime
from pathlib import Path
import re

from paths import data_dir


# Set to False if the SQLite build lacks the FTS5 module (see _setup_fts). The
# chat-history tools check this and degrade to a clear "unavailable" message.
_FTS_AVAILABLE = True


def get_engine() -> Engine:

    connection_string = f"sqlite:///{data_dir() / 'chat_history.db'}"

    engine = create_engine(connection_string, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


base = declarative_base()


class Message(base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_sessions.id"), nullable=False
    )
    # Nullable: assistant rows that only request a tool carry no text content.
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    # Raw tool_calls array (JSON) on an assistant row that requests a tool.
    tool_calls: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set on a tool-result row to answer a specific assistant tool call.
    tool_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_datetime: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    chat_session: Mapped["ChatSession"] = relationship(
        "ChatSession", back_populates="messages"
    )


class ChatSession(base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_name: Mapped[str] = mapped_column(String, nullable=True)
    # Loop state for the tool-calling pause: "idle" | "awaiting_approval".
    status: Mapped[str] = mapped_column(String, default="idle")
    created_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consolidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_consolidated_message_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    consolidation_status: Mapped[str] = mapped_column(String, default="none")
    consolidation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    consolidate_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # When set, write tools run without pausing for approval for this chat.
    auto_approve_writes: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="chat_session"
    )


class MemoryEvent(base):
    __tablename__ = "memory_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chat_sessions.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)


# Columns added after the initial release, keyed by table name. create_all only
# creates missing tables, so existing databases are patched with ALTER TABLE.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "messages": {
        "tool_calls": "TEXT",
        "tool_call_id": "VARCHAR",
        "tool_name": "VARCHAR",
    },
    "chat_sessions": {
        "status": "VARCHAR DEFAULT 'idle'",
        "last_activity_at": "DATETIME",
        "consolidated_at": "DATETIME",
        "last_consolidated_message_id": "INTEGER",
        "consolidation_status": "VARCHAR DEFAULT 'none'",
        "consolidation_attempts": "INTEGER DEFAULT 0",
        "consolidate_after": "DATETIME",
        "auto_approve_writes": "BOOLEAN DEFAULT 0",
    },
}


def _migrate(engine: Engine) -> None:
    """Add columns introduced after the first release to an existing database.

    SQLAlchemy's ``create_all`` creates missing tables but never alters an
    existing one, so a database created before tool calling lacks the new
    columns. This issues an idempotent ``ALTER TABLE ... ADD COLUMN`` for any
    expected column that is not already present.

    Args:
        engine: The SQLAlchemy engine connected to the SQLite database.
    """
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    with engine.begin() as connection:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                    )


def create_database():
    engine = get_engine()
    base.metadata.create_all(engine)
    _migrate(engine)
    _setup_fts(engine)


# --- Full-text search over chat history (Memory v2) --------------------------
#
# An external-content FTS5 table mirrors user/assistant message text, kept in sync by
# triggers so it stays correct no matter who inserts (ORM today, raw SQL tomorrow). Tool
# rows and empty assistant rows are deliberately excluded — they are large, low-signal,
# and the most likely carriers of injected content.

_FTS_STATEMENTS = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
        message,
        content='messages',
        content_rowid='id'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages
    WHEN new.role IN ('user','assistant') AND new.message IS NOT NULL BEGIN
        INSERT INTO messages_fts(rowid, message) VALUES (new.id, new.message);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages
    WHEN old.role IN ('user','assistant') AND old.message IS NOT NULL BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, message)
        VALUES ('delete', old.id, old.message);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_au_del AFTER UPDATE ON messages
    WHEN old.role IN ('user','assistant') AND old.message IS NOT NULL BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, message)
        VALUES ('delete', old.id, old.message);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_au_ins AFTER UPDATE ON messages
    WHEN new.role IN ('user','assistant') AND new.message IS NOT NULL BEGIN
        INSERT INTO messages_fts(rowid, message) VALUES (new.id, new.message);
    END
    """,
]

_FTS_BACKFILL = """
    INSERT INTO messages_fts(rowid, message)
    SELECT id, message FROM messages
    WHERE role IN ('user','assistant') AND message IS NOT NULL
      AND id NOT IN (SELECT rowid FROM messages_fts)
"""


def _setup_fts(engine: Engine) -> None:
    """Create the FTS5 table/triggers and backfill existing rows (idempotent)."""
    global _FTS_AVAILABLE
    try:
        with engine.begin() as connection:
            for statement in _FTS_STATEMENTS:
                connection.execute(text(statement))
            connection.execute(text(_FTS_BACKFILL))
        _FTS_AVAILABLE = True
    except Exception as error:  # pragma: no cover - depends on SQLite build
        _FTS_AVAILABLE = False
        print(f"FTS5 unavailable; chat-history search disabled: {error}")


def fts_available() -> bool:
    """Return whether full-text chat-history search is usable."""
    return _FTS_AVAILABLE


def _fts_match_query(query: str) -> str:
    """Turn a natural-language query into a safe FTS5 MATCH expression.

    Each whitespace token is wrapped in double quotes (escaping internal quotes), so FTS5
    operators and punctuation in ordinary prose cannot raise a syntax error. Tokens are
    implicitly AND-ed.
    """
    tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    quoted = ['"' + t.replace('"', '""') + '"' for t in tokens]
    return " ".join(q for q in quoted if q != '""')


def search_messages(
    query: str, exclude_chat_id: int | None = None, limit: int = 10
) -> list[dict]:
    """Full-text search user/assistant messages, best matches first.

    Args:
        query: Natural-language search text.
        exclude_chat_id: Chat to omit (the current conversation, already in context).
        limit: Maximum hits to return.

    Returns:
        A list of dicts with id, chat_session_id, session_name, role, created_datetime,
        and a highlighted snippet. Empty if FTS is unavailable or nothing matched.
    """
    if not _FTS_AVAILABLE:
        return []
    match = _fts_match_query(query)
    if not match:
        return []

    sql = text(
        """
        SELECT m.id AS id,
               m.chat_session_id AS chat_session_id,
               c.session_name AS session_name,
               m.role AS role,
               m.created_datetime AS created_datetime,
               snippet(messages_fts, 0, '«', '»', '…', 12) AS snippet
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        JOIN chat_sessions c ON c.id = m.chat_session_id
        WHERE messages_fts MATCH :match
          AND (:exclude IS NULL OR m.chat_session_id != :exclude)
        ORDER BY bm25(messages_fts)
        LIMIT :limit
        """
    )
    with get_engine().connect() as connection:
        rows = connection.execute(
            sql, {"match": match, "exclude": exclude_chat_id, "limit": limit}
        ).mappings().all()
    return [dict(row) for row in rows]


def fetch_messages_around(
    chat_id: int, around_message_id: int, context: int = 6
) -> list[dict]:
    """Return user/assistant messages around an anchor, in chronological order.

    Counts messages (not id-distance): up to ``context`` before and ``context`` after the
    anchor, plus the anchor itself. Empty if the anchor is not a user/assistant message in
    the given chat.
    """
    before_sql = text(
        """
        SELECT id, role, message, created_datetime FROM messages
        WHERE chat_session_id = :chat AND role IN ('user','assistant')
          AND message IS NOT NULL AND id <= :anchor
        ORDER BY id DESC LIMIT :n
        """
    )
    after_sql = text(
        """
        SELECT id, role, message, created_datetime FROM messages
        WHERE chat_session_id = :chat AND role IN ('user','assistant')
          AND message IS NOT NULL AND id > :anchor
        ORDER BY id ASC LIMIT :n
        """
    )
    with get_engine().connect() as connection:
        before = connection.execute(
            before_sql, {"chat": chat_id, "anchor": around_message_id, "n": context + 1}
        ).mappings().all()
        after = connection.execute(
            after_sql, {"chat": chat_id, "anchor": around_message_id, "n": context}
        ).mappings().all()

    if not before:
        return []
    ordered = list(reversed([dict(row) for row in before])) + [dict(row) for row in after]
    return ordered
