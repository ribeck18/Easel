from apscheduler.job import Job
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from apscheduler.jobstores.base import JobLookupError

from services.scheduler import (
    delete_cron_chat_routine,
    list_cron_chat_routines,
    user_create_cron_chat_routine,
)


route = APIRouter()


class CronValues(BaseModel):
    year: str | None
    month: str | None
    day: str | None
    week: str | None
    day_of_week: str | None
    hour: str | None
    minute: str | None
    second: str | None
    # IANA name (e.g. "America/Denver") the cron fields are interpreted in.
    # Sent by the UI from the browser's timezone; optional for compatibility.
    timezone: str | None = None


class CronChatRequest(BaseModel):
    job_name: str
    message: str


@route.post("/api/routine/new")
async def new_routine(cron_values: CronValues, cron_chat: CronChatRequest):
    try:
        job = await user_create_cron_chat_routine(
            name=cron_chat.job_name,
            user_message=cron_chat.message,
            year=cron_values.year,
            month=cron_values.month,
            day=cron_values.day,
            week=cron_values.week,
            day_of_week=cron_values.day_of_week,
            hour=cron_values.hour,
            minute=cron_values.minute,
            second=cron_values.second,
            timezone=cron_values.timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"created_job_id": job.id}


@route.get("/api/routine/list")
async def list_routines() -> list[dict]:
    jobs = await list_cron_chat_routines()

    return jobs


@route.delete("/api/routine/delete")
async def delete_routine(job_id: str):
    try:
        await delete_cron_chat_routine(job_id=job_id)
    except JobLookupError:
        raise HTTPException(
            status_code=404, detail=f"Job with id {job_id} does not exist."
        )

    return {"deleted_job_id": job_id}
