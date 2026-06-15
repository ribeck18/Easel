from datetime import datetime, timezone
import json

from sqlalchemy.orm import Session

from user_database.chats_database import ChatSession, Message
from ClientModel import ClientModel
from config import Config
from tools import executor
from tools.definitions import build_tool_specs, requires_approval
from services.chat import (
    ask_model_name_chat,
    build_system_prompt,
    load_history,
    save_message,
)


def run_turn(message_content: str, chat_session: ChatSession, session: Session) -> dict:
    """Run one user turn: persist the message and drive the tool-calling loop.

    If this is the first message in the session, the model is also asked for a
    short title and ``chat_name`` is included in the result.

    Args:
        message_content: The raw text typed by the user.
        chat_session: The active ChatSession to attach messages to.
        session: SQLAlchemy database session used for all DB operations.

    Returns:
        A response dict (see ``_run_loop``) describing either a completed reply
        or a write paused for approval.
    """
    is_first: bool = (
        session.query(Message).filter_by(chat_session_id=chat_session.id).count() == 0
    )
    chat_session.last_activity_at = datetime.utcnow()
    if chat_session.consolidated_at is not None or (
        chat_session.consolidation_status == "failed"
    ):
        chat_session.consolidated_at = None
        chat_session.consolidation_status = "none"
        chat_session.consolidation_attempts = 0

    save_message(
        message=message_content, role="user", chat=chat_session, session=session
    )

    result = _run_loop(chat_session=chat_session, session=session)

    if is_first:
        ask_model_name_chat(chat_session=chat_session, user_message=message_content)
        result["chat_name"] = chat_session.session_name

    return result


def resume_turn(chat_session: ChatSession, decision: str, session: Session) -> dict:
    """Resume a paused turn after the user approves or rejects a tool call.

    The tool call waiting at the end of the history is answered using the
    arguments stored on the server (never resent by the client), then the loop
    continues until the next pause or a final reply.

    Args:
        chat_session: The ChatSession whose tool call is awaiting approval.
        decision: ``"approve"`` to run the write, ``"approve_always"`` to run it
            and auto-approve future writes for this chat, anything else declines.
        session: SQLAlchemy database session used for all DB operations.

    Returns:
        A response dict (see ``_run_loop``); ``tool_activity`` for the resolved
        write is prepended so the UI can render it.
    """
    pending = _pending_tool_call(chat_session=chat_session, session=session)
    if pending is None:
        return _complete_result(
            text="There is no pending action to resume.", activity=[]
        )

    tool_call_id, tool_name, arguments_json = pending

    if decision in ("approve", "approve_always"):
        if decision == "approve_always":
            chat_session.auto_approve_writes = True
        result_text = executor.execute(
            tool_name, arguments_json, context={"chat_id": chat_session.id}
        )
        status = "approved"
    else:
        result_text = "The user declined to run this tool."
        status = "declined"

    save_message(
        message=result_text,
        role="tool",
        chat=chat_session,
        session=session,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )
    chat_session.status = "idle"

    activity = [
        {
            "tool_name": tool_name,
            "arguments": arguments_json,
            "result": result_text,
            "status": status,
        }
    ]

    result = _run_loop(chat_session=chat_session, session=session)
    result["tool_activity"] = activity + result["tool_activity"]
    return result


def _run_loop(chat_session: ChatSession, session: Session) -> dict:
    """Call the model repeatedly, auto-running reads until a reply or a pause.

    Read and list tools auto-execute and the loop continues; a write tool stops
    the loop and persists ``awaiting_approval`` state for the next request leg.
    The loop is capped at ``Config.max_tool_calls`` auto-executed calls.

    Args:
        chat_session: The active ChatSession.
        session: SQLAlchemy database session used for all DB operations.

    Returns:
        A ``complete`` result with the final reply, or an ``awaiting_approval``
        result carrying the pending write, each including ``tool_activity``.
    """
    tools_enabled = Config.tools_enabled()
    memory_enabled = Config.memory_enabled()
    skills_enabled = Config.skills_enabled()
    max_tool_calls = Config.max_tool_calls()
    system_prompt = build_system_prompt(
        tools_enabled=tools_enabled,
        memory_enabled=memory_enabled,
        skills_enabled=skills_enabled,
    )
    tool_specs = build_tool_specs(
        memory_enabled=memory_enabled,
        tools_enabled=tools_enabled,
        skills_enabled=skills_enabled,
    )
    activity: list[dict] = []
    executed = 0

    while True:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(load_history(session=session, current_chat=chat_session))

        request: dict = {"model": ClientModel.get_model(), "messages": messages}
        if tools_enabled or memory_enabled or skills_enabled:
            request["tools"] = tool_specs
            request["tool_choice"] = "auto"
            request["parallel_tool_calls"] = False

        completion = ClientModel.get_client().chat.completions.create(**request)
        reply = completion.choices[0].message

        if not reply.tool_calls:
            text = reply.content or ""
            save_message(
                message=text, role="assistant", chat=chat_session, session=session
            )
            chat_session.status = "idle"
            return _complete_result(text=text, activity=activity)

        # parallel_tool_calls is disabled, so there is exactly one call.
        call = reply.tool_calls[0]
        save_message(
            message=reply.content,
            role="assistant",
            chat=chat_session,
            session=session,
            tool_calls=json.dumps([call.model_dump()]),
        )

        if requires_approval(call.function.name) and not chat_session.auto_approve_writes:
            chat_session.status = "awaiting_approval"
            return {
                "status": "awaiting_approval",
                "time": _now(),
                "tool_activity": activity,
                "pending": {
                    "tool_call_id": call.id,
                    "tool_name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }

        if executed >= max_tool_calls:
            text = (
                f"Stopped after reaching the limit of {max_tool_calls} tool calls "
                "in one turn."
            )
            save_message(
                message=text,
                role="tool",
                chat=chat_session,
                session=session,
                tool_call_id=call.id,
                tool_name=call.function.name,
            )
            chat_session.status = "idle"
            return _complete_result(text=text, activity=activity)

        result_text = executor.execute(
            call.function.name,
            call.function.arguments,
            context={"chat_id": chat_session.id},
        )
        executed += 1
        save_message(
            message=result_text,
            role="tool",
            chat=chat_session,
            session=session,
            tool_call_id=call.id,
            tool_name=call.function.name,
        )
        activity.append(
            {
                "tool_name": call.function.name,
                "arguments": call.function.arguments,
                "result": result_text,
                "status": "ok",
            }
        )


def _pending_tool_call(
    chat_session: ChatSession, session: Session
) -> tuple[str, str, str] | None:
    """Return the (id, name, arguments) of the write awaiting approval, if any.

    The pending call is the assistant tool-request row left dangling at the end
    of the history when the loop paused.

    Args:
        chat_session: The ChatSession to inspect.
        session: SQLAlchemy database session used for the query.

    Returns:
        A ``(tool_call_id, tool_name, arguments_json)`` tuple, or None if the
        last message is not a dangling tool request.
    """
    last = (
        session.query(Message)
        .filter_by(chat_session_id=chat_session.id)
        .order_by(Message.id.desc())
        .first()
    )
    if last is None or last.role != "assistant" or last.tool_calls is None:
        return None

    call = json.loads(last.tool_calls)[0]
    return call["id"], call["function"]["name"], call["function"]["arguments"]


def _complete_result(text: str, activity: list[dict]) -> dict:
    return {
        "status": "complete",
        "model_message": text,
        "time": _now(),
        "tool_activity": activity,
    }


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)
