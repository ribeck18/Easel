from uuid import uuid4
from zoneinfo import ZoneInfo


def create_routine(
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
    """
    Create a recurring (or one-off) scheduled routine that re-prompts the agent on a cron schedule.

    Registers a cron-triggered job with the scheduler. When the schedule fires,
    `run_scheduled_turn` is invoked with `user_message`, causing the agent to act
    as if the user had sent that message at that time. Use this to set up reminders,
    recurring check-ins, or any task that should run automatically on a calendar
    schedule (e.g. "every weekday at 8am", "the 1st of every month").

    Schedule fields follow cron/APScheduler semantics: each one constrains *when*
    the job runs, and any field left as None is treated as a wildcard (every value).
    At least one schedule field must be provided, otherwise the job would fire every
    second. Fields accept cron-style expressions, not just single numbers:
      - "5"        -> exactly that value (e.g. hour="5" means 05:00)
      - "*/15"     -> every 15 units (e.g. minute="*/15" -> :00, :15, :30, :45)
      - "1-5"      -> a range (e.g. day_of_week="mon-fri" or "0-4")
      - "1,15"     -> a list of specific values
    `day_of_week` also accepts names ("mon", "tue", ...). Omitting smaller units
    (minute, second) defaults them to 0, so hour="9" alone fires once at 09:00:00.

    Args:
        name: Human-readable label for the routine (shown in listings; not unique).
        user_message: The text fed to the agent when the schedule fires. Write it
            as if you (the user) were sending the instruction at that moment.
        year: 4-digit year, e.g. "2026". None = every year.
        month: Month 1-12. None = every month.
        day: Day of month 1-31. None = every day.
        week: ISO week number 1-53. None = every week.
        day_of_week: 0-6 (0=Mon) or names like "mon", "fri", "mon-fri".
            None = every day of the week.
        hour: Hour 0-23. None = every hour.
        minute: Minute 0-59. None = every minute.
        second: Second 0-59. None = every second.
        timezone: IANA timezone name (e.g. "America/Boise") in which the cron
            fields are interpreted, so hour="16" means 16:00 local, not UTC.
            None = the scheduler's default timezone.

    Returns:
        The created APScheduler Job object. Its `id` is a generated UUID, and
        `job.next_run_time` reports when it will next fire.

    Raises:
        ValueError: If no schedule field is set, or if `timezone` is not a valid
            IANA timezone name.

    Examples:
        Every weekday at 8:00 AM Mountain time:
            create_routine(
                name="Morning standup nudge",
                user_message="Remind me to post my standup update.",
                hour="8", minute="0",
                day_of_week="mon-fri",
                timezone="America/Boise",
            )

        First of every month at midnight:
            create_routine(
                name="Monthly report",
                user_message="Generate the monthly project summary.",
                day="1", hour="0", minute="0",
            )
    """
    # Imported lazily inside the function to avoid a circular import: this module
    # is loaded (via tools.executor) while services.scheduler is still
    # initializing, so its names aren't bound at module-import time. By call time
    # the scheduler module is fully loaded.
    from services.scheduler import run_scheduled_turn, scheduler

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

    return f"{job.name} routine created with id {job.id}. Next run: {job.next_run_time}"

