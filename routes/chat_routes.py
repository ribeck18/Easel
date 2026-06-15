from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import Config
from services.memory_capture import capture_turn
from services.chat import (
    ensure_chat_session_exists,
    load_chats,
    load_display_history,
    create_new_chat,
)
from services.agent_loop import run_turn, resume_turn
from tools.workspace import (
    WorkspacePathError,
    resolve_in_workspace,
    workspace_available,
)
from user_database.chats_database import ChatSession, get_engine


route = APIRouter()

# Upload size cap for attached text files, mirroring the wiki note read limit.
MAX_UPLOAD_BYTES = 1024 * 1024


class ChatRequest(BaseModel):
    user_message: str
    chat_session_id: int
    attachments: list[str] = []


class ApprovalRequest(BaseModel):
    chat_session_id: int
    tool_call_id: str
    decision: str


@route.post("/api/chat")
async def chat(payload: ChatRequest, background_tasks: BackgroundTasks) -> dict:
    with Session(get_engine()) as s:
        current_chat = ensure_chat_session_exists(
            id=payload.chat_session_id, session=s, user_message=payload.user_message
        )

        if current_chat.status == "awaiting_approval":
            return {
                "status": "awaiting_approval_pending",
                "model_message": "Please approve or reject the pending action first.",
            }

        # Surface uploaded file paths to the model so it can read_file them.
        message_content = payload.user_message
        if payload.attachments:
            listing = ", ".join(payload.attachments)
            message_content = f"[Attached files: {listing}]\n\n{message_content}"

        result = run_turn(
            message_content=message_content,
            chat_session=current_chat,
            session=s,
        )
        s.commit()

    result["user_message"] = payload.user_message
    _schedule_capture(
        background_tasks=background_tasks,
        chat_id=payload.chat_session_id,
        user_message=payload.user_message,
        result=result,
    )
    return result


@route.post("/api/chat/upload")
async def upload(
    chat_session_id: int = Form(...), file: UploadFile = File(...)
) -> dict:
    if not workspace_available():
        return {
            "status": "error",
            "message": "No workspace folder is mounted, so files cannot be saved.",
        }

    name = Path(file.filename or "").name
    if not name:
        return {"status": "error", "message": "The uploaded file has no name."}

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return {
            "status": "error",
            "message": f"File is larger than the {MAX_UPLOAD_BYTES // 1024} KB limit.",
        }
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": "error",
            "message": "Only UTF-8 text files can be attached.",
        }

    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 1
    candidate = name
    try:
        target = resolve_in_workspace(f"Easel/Uploads/{chat_session_id}/{candidate}")
        while target.exists():
            candidate = f"{stem}-{counter}{suffix}"
            target = resolve_in_workspace(
                f"Easel/Uploads/{chat_session_id}/{candidate}"
            )
            counter += 1
    except WorkspacePathError as error:
        return {"status": "error", "message": str(error)}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as error:
        return {"status": "error", "message": f"Could not save file: {error}"}

    return {"status": "ok", "path": f"Easel/Uploads/{chat_session_id}/{candidate}"}


@route.post("/api/chat/approve")
async def approve(payload: ApprovalRequest, background_tasks: BackgroundTasks) -> dict:
    with Session(get_engine()) as s:
        current_chat = (
            s.query(ChatSession)
            .where(ChatSession.id == payload.chat_session_id)
            .first()
        )

        if current_chat is None or current_chat.status != "awaiting_approval":
            return {
                "status": "error",
                "model_message": "There is no pending action to resolve.",
            }

        result = resume_turn(
            chat_session=current_chat, decision=payload.decision, session=s
        )
        s.commit()

    _schedule_capture(
        background_tasks=background_tasks,
        chat_id=payload.chat_session_id,
        user_message="Approved or rejected a pending tool action.",
        result=result,
    )
    return result


@route.post("/api/chat/session")
async def new_session() -> dict[str, int]:
    with Session(get_engine()) as s:
        chat_session = create_new_chat(session=s)
        s.commit()
        session_id = chat_session.id
    return {"chat_session_id": session_id}


@route.get("/api/chat-list")
async def chatlist() -> list[dict]:
    with Session(get_engine()) as s:
        chats = load_chats(s)

        chat_dict_list: list[dict] = []

        for chat in chats:
            chat_dict_list.append({"name": chat.session_name, "id": chat.id})

    return chat_dict_list


@route.get("/api/chat-history")
async def chat_history(current_chat_id: int) -> list[dict]:
    with Session(get_engine()) as s:
        current_chat = (
            s.query(ChatSession).where(ChatSession.id == current_chat_id).first()
        )

        history = load_display_history(current_chat=current_chat, session=s)

    return history


def _schedule_capture(
    background_tasks: BackgroundTasks,
    chat_id: int,
    user_message: str,
    result: dict,
) -> None:
    if not Config.memory_enabled() or result.get("status") != "complete":
        return

    background_tasks.add_task(
        capture_turn,
        chat_id,
        {
            "user_message": user_message,
            "assistant_reply": result.get("model_message", ""),
            "tool_activity": result.get("tool_activity", []),
        },
    )
