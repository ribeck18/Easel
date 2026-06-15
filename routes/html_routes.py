from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


route = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def render_page(request: Request, template_name: str, title: str, active_page: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"title": title, "active_page": active_page},
    )


@route.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/chat")


@route.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    return render_page(request, "chat.html", "Easel | Chat", "chat")


@route.get("/routines", response_class=HTMLResponse)
async def routines_page(request: Request) -> HTMLResponse:
    return render_page(request, "routines.html", "Easel | Routines", "routines")


@route.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    return render_page(request, "skills.html", "Easel | Skills", "skills")


@route.get("/memory", response_class=HTMLResponse)
async def memory_page(request: Request) -> HTMLResponse:
    return render_page(request, "memory.html", "Easel | Memory", "memory")


@route.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return render_page(request, "settings.html", "Easel | Settings", "settings")
