from datetime import datetime, timedelta
import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import (
    Config,
    CoreMemoryOverBudget,
    CoreMemoryUnavailable,
    LEAVE_GRACE_MINUTES,
)
from tools.memory import read_wiki_note
from tools.workspace import WorkspacePathError, resolve_in_workspace, workspace_available
from user_database.chats_database import ChatSession, MemoryEvent, Message, get_engine


route = APIRouter()


class LeaveRequest(BaseModel):
    chat_session_id: int


class RetryRequest(BaseModel):
    chat_session_id: int


class SeenRequest(BaseModel):
    event_ids: list[int]


class CoreMemoryRequest(BaseModel):
    content: str


@route.post("/api/memory/leave")
async def leave_chat(payload: LeaveRequest) -> dict:
    with Session(get_engine()) as session:
        chat = session.get(ChatSession, payload.chat_session_id)
        if chat is None:
            return {"status": "missing"}
        if chat.consolidation_status in {"in_progress", "failed"}:
            return {"status": chat.consolidation_status}

        last_message = (
            session.query(Message)
            .filter(Message.chat_session_id == chat.id)
            .order_by(Message.id.desc())
            .first()
        )
        if last_message is None or last_message.id <= (
            chat.last_consolidated_message_id or 0
        ):
            return {"status": "no_changes"}

        chat.consolidation_status = "pending"
        chat.consolidate_after = datetime.utcnow() + timedelta(
            minutes=LEAVE_GRACE_MINUTES
        )
        session.commit()

    return {"status": "pending"}


@route.get("/api/settings/memory")
async def get_memory_setting() -> dict:
    return {"enabled": Config.memory_enabled(), "model": Config.get_memory_model_setting()}


@route.post("/api/settings/memory")
async def set_memory_setting(enabled: bool, model: str = "") -> None:
    Config.set_memory_enabled(enabled)
    Config.set_memory_model(model)


@route.get("/api/memory/core")
async def get_core_memory(kind: str) -> dict:
    return {"content": Config.get_core_memory(kind)}


@route.post("/api/memory/core")
async def set_core_memory(kind: str, payload: CoreMemoryRequest):
    # The Settings save is a deliberate user edit, so it skips drift detection
    # (expected_fingerprint=None) but is still budget- and workspace-checked.
    try:
        Config.set_core_memory(kind, payload.content)
    except CoreMemoryUnavailable:
        return JSONResponse(
            status_code=409,
            content={"error": "No workspace is mounted, so core memory is unavailable."},
        )
    except CoreMemoryOverBudget as error:
        return JSONResponse(
            status_code=422,
            content={
                "error": "over_budget",
                "current": error.current,
                "limit": error.limit,
            },
        )
    return {"status": "ok"}


@route.get("/api/memory/wiki")
async def list_wiki() -> dict:
    if not workspace_available():
        return {"notes": []}
    try:
        index_path = resolve_in_workspace("Easel/Wiki/_index.md")
    except WorkspacePathError:
        return {"notes": []}
    if not index_path.exists():
        return {"notes": []}
    return {"notes": _parse_index(index_path.read_text(encoding="utf-8"))}


@route.get("/api/memory/wiki/note")
async def get_wiki_note(path: str) -> dict:
    return {"content": read_wiki_note(path)}


@route.get("/api/memory/events")
async def list_events(unseen: bool = False) -> dict:
    with Session(get_engine()) as session:
        query = session.query(MemoryEvent).order_by(MemoryEvent.created_at.desc())
        if unseen:
            query = query.filter(MemoryEvent.seen == False)
        events = query.limit(50).all()
        failed_chats = (
            session.query(ChatSession)
            .filter(ChatSession.consolidation_status == "failed")
            .all()
        )
        return {
            "events": [
                {
                    "id": event.id,
                    "chat_session_id": event.chat_session_id,
                    "kind": event.kind,
                    "summary": event.summary,
                    "detail": _decode_detail(event.detail),
                    "created_at": event.created_at.isoformat(),
                    "seen": event.seen,
                }
                for event in events
            ],
            "failed_chats": [
                {"id": chat.id, "name": chat.session_name}
                for chat in failed_chats
            ],
        }


@route.post("/api/memory/events/seen")
async def mark_events_seen(payload: SeenRequest) -> None:
    with Session(get_engine()) as session:
        events = session.query(MemoryEvent).filter(MemoryEvent.id.in_(payload.event_ids))
        for event in events:
            event.seen = True
        session.commit()


@route.post("/api/memory/retry")
async def retry_chat(payload: RetryRequest) -> dict:
    with Session(get_engine()) as session:
        chat = session.get(ChatSession, payload.chat_session_id)
        if chat is None:
            return {"status": "missing"}
        chat.consolidation_status = "pending"
        chat.consolidation_attempts = 0
        chat.consolidate_after = None
        session.commit()
    return {"status": "pending"}


def _parse_index(content: str) -> list[dict]:
    notes: list[dict] = []
    for line in content.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "Path" in line:
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        notes.append(
            {
                "title": parts[0],
                "path": parts[1],
                "description": parts[2],
                "tags": parts[3],
                "updated": parts[4],
            }
        )
    return notes


def _decode_detail(detail: str | None) -> dict | None:
    if detail is None:
        return None
    try:
        return json.loads(detail)
    except json.JSONDecodeError:
        return {"raw": detail}
