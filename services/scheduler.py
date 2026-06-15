from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.job import Job
from sqlalchemy.orm import Session
from uuid import uuid4
from zoneinfo import ZoneInfo

from config import Config
from services.chat import create_new_chat, ensure_chat_session_exists
from services.agent_loop import run_turn
from services.memory_capture import capture_turn
from user_database.chats_database import get_engine
from paths import data_dir


jobstores = {
    "default": SQLAlchemyJobStore(url=f"sqlite:///{data_dir() / 'cron_jobs.db'}")
}

scheduler = BackgroundScheduler(jobstores=jobstores)


async def user_create_cron_chat_routine(
    name: str,
    user_message: str,
    year: str | None = None,
    month: str | None = None,
    day: str | None = None,
    week: str | None = None,
    day_of_week: str | None = None,
    hour: str | None = None,
    minute: str | None = None,
    second: str | None = None,
    timezone: str | None = None,
):
    cron_list = [
        ("year", year),
        ("month", month),
        ("day", day),
        ("week", week),
        ("day_of_week", day_of_week),
        ("hour", hour),
        ("minute", minute),
        ("second", second),
    ]
    cron_kwargs = {}
    for field, value in cron_list:
        if value is not None:
            cron_kwargs[field] = value

    if not cron_kwargs:
        raise ValueError(
            "A routine needs at least one schedule field set (year, month, day, "
            "week, day_of_week, hour, minute, or second)."
        )

    # The cron fields are interpreted in this timezone, so "hour=16" means
    # 16:00 where the user is, not 16:00 in the server's (UTC) timezone. When
    # omitted, APScheduler falls back to the scheduler's default timezone.
    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except Exception as exc:
            raise ValueError(f"Unknown timezone: {timezone!r}") from exc
        cron_kwargs["timezone"] = timezone

    job_id = str(uuid4())

    job = scheduler.add_job(
        func=run_scheduled_turn,
        trigger="cron",
        id=job_id,
        name=name,
        kwargs={"message": user_message},
        misfire_grace_time=600,
        replace_existing=True,
        **cron_kwargs,
    )

    return job


def run_scheduled_turn(message: str) -> None:
    """Start a fresh chat and run one turn for a scheduled routine.

    Called directly by the scheduler job — no HTTP round-trip back into the
    app. Runs synchronously because ``BackgroundScheduler`` executes jobs in a
    worker thread with no event loop, so the job function must not be a
    coroutine.

    Args:
        message: The user message to send into the newly created chat.
    """
    with Session(get_engine()) as session:
        chat_session = create_new_chat(session=session)
        session.commit()
        chat_session = ensure_chat_session_exists(chat_session.id, message, session)
        result = run_turn(message, chat_session, session)
        session.commit()
        chat_id = chat_session.id

    if Config.memory_enabled() and result.get("status") == "complete":
        capture_turn(
            chat_id,
            {
                "user_message": message,
                "assistant_reply": result.get("model_message", ""),
                "tool_activity": result.get("tool_activity", []),
            },
        )


async def list_cron_chat_routines() -> list[dict]:
    jobs_list: list[Job] = scheduler.get_jobs()

    jobs = []
    for job in jobs_list:
        job_dict = {}
        job_dict["name"] = job.name
        job_dict["id"] = job.id
        job_dict["trigger"] = str(job.trigger)
        job_dict["next_run_time"] = job.next_run_time
        job_dict["message"] = job.kwargs.get("message")
        job_dict["timezone"] = str(getattr(job.trigger, "timezone", None) or "") or None

        jobs.append(job_dict)

    return jobs


async def delete_cron_chat_routine(job_id: str):
    scheduler.remove_job(job_id)


async def edit_cron_chat_routine(job_id: str):
    pass


async def pause_cron_chat_routine(job_id: str):
    pass


async def resume_cron_chat_routine():
    pass
