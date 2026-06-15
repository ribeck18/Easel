import asyncio
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ClientModel import ClientModel
from config import (
    Config,
    IDLE_TIMEOUT_MINUTES,
    MAX_CONSOLIDATION_ATTEMPTS,
    STALE_IN_PROGRESS_MINUTES,
    SWEEPER_INTERVAL_SECONDS,
)
from services.consolidation import consolidate_chat
from tools.workspace import workspace_available
from user_database.chats_database import ChatSession, Message, get_engine


_CONSOLIDATION_LOCK = asyncio.Lock()


async def run_memory_sweeper() -> None:
    """Run the background memory sweeper until cancelled."""
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Memory sweeper tick failed: {error}")
        await asyncio.sleep(SWEEPER_INTERVAL_SECONDS)


async def sweep_once() -> None:
    """Find eligible chats and consolidate them one at a time."""
    if not Config.memory_enabled() or not workspace_available():
        return
    if ClientModel.client is None:
        return

    _reclaim_stale_runs()
    for chat_id in _eligible_chat_ids():
        async with _CONSOLIDATION_LOCK:
            await asyncio.to_thread(consolidate_chat, chat_id)


def _reclaim_stale_runs() -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_IN_PROGRESS_MINUTES)
    with Session(get_engine()) as session:
        chats = (
            session.query(ChatSession)
            .filter(ChatSession.consolidation_status == "in_progress")
            .all()
        )
        for chat in chats:
            last_activity = chat.last_activity_at or chat.created_date
            if last_activity <= cutoff:
                chat.consolidation_status = "pending"
                chat.consolidate_after = None
        session.commit()


def _eligible_chat_ids() -> list[int]:
    now = datetime.utcnow()
    idle_cutoff = now - timedelta(minutes=IDLE_TIMEOUT_MINUTES)
    eligible: list[int] = []

    with Session(get_engine()) as session:
        chats = session.query(ChatSession).all()
        for chat in chats:
            if chat.consolidation_status in {"in_progress", "failed"}:
                continue
            if (chat.consolidation_attempts or 0) >= MAX_CONSOLIDATION_ATTEMPTS:
                continue

            last_message = (
                session.query(Message)
                .filter(Message.chat_session_id == chat.id)
                .order_by(Message.id.desc())
                .first()
            )
            if last_message is None:
                continue
            if last_message.id <= (chat.last_consolidated_message_id or 0):
                continue

            ready_pending = (
                chat.consolidation_status == "pending"
                and (
                    chat.consolidate_after is None
                    or chat.consolidate_after <= now
                )
            )
            ready_idle = (chat.last_activity_at or chat.created_date) <= idle_cutoff
            if ready_pending or ready_idle:
                eligible.append(chat.id)

    return eligible
