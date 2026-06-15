from contextlib import asynccontextmanager
from pathlib import Path
import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from routes import (
    chat_routes,
    html_routes,
    memory_routes,
    routine_routes,
    settings_routes,
    skills_routes,
)
from ClientModel import ClientModel
from services.memory_sweeper import run_memory_sweeper
from services.scheduler import scheduler
from user_database.chats_database import create_database


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = TEMPLATES_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_database()
    if ClientModel.get_key_names():
        ClientModel.set_client()
    if not scheduler.running:
        scheduler.start()
    sweeper_task = asyncio.create_task(run_memory_sweeper())
    yield
    sweeper_task.cancel()
    try:
        await sweeper_task
    except asyncio.CancelledError:
        pass
    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(html_routes.route)
app.include_router(chat_routes.route)
app.include_router(memory_routes.route)
app.include_router(routine_routes.route)
app.include_router(settings_routes.route)
app.include_router(skills_routes.route)


@app.get("/healthz")
async def healthz():
    """Liveness probe the native launcher hits to detect an already-running instance."""
    return {"status": "ok", "app": "easel"}


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    excluded = ["/settings", "/api/setkey", "/api/setmodel", "/api/keys", "/static", "/healthz"]
    if ClientModel.client is None and not any(
        request.url.path.startswith(path) for path in excluded
    ):
        return RedirectResponse(url="/settings")
    return await call_next(request)
