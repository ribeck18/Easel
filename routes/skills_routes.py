import mimetypes

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from config import Config
from tools import skills
from tools.workspace import WorkspacePathError, workspace_available


route = APIRouter()


class ToggleRequest(BaseModel):
    enabled: bool


@route.get("/api/settings/skills")
async def get_skills_setting() -> dict:
    return {"enabled": Config.skills_enabled()}


@route.post("/api/settings/skills")
async def set_skills_setting(enabled: bool) -> None:
    Config.set_skills_enabled(enabled)


@route.get("/api/skills")
async def list_skills() -> dict:
    return {"workspace": workspace_available(), "skills": skills.list_skills()}


@route.get("/api/skills/{slug}")
async def get_skill(slug: str) -> JSONResponse:
    detail = skills.skill_detail(slug)
    if detail is None:
        return JSONResponse(status_code=404, content={"error": "No such skill."})
    return JSONResponse(content=detail)


@route.get("/api/skills/{slug}/reference")
async def get_skill_reference(slug: str, path: str):
    resolved = skills.reference_path(slug, path)
    if resolved is None:
        return JSONResponse(status_code=404, content={"error": "No such reference."})
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return FileResponse(resolved, media_type=media_type, filename=resolved.name)


@route.post("/api/skills/{slug}/toggle")
async def toggle_skill(slug: str, payload: ToggleRequest) -> JSONResponse:
    try:
        enabled = skills.set_skill_enabled(slug, payload.enabled)
    except WorkspacePathError as error:
        return JSONResponse(status_code=409, content={"error": str(error)})
    return JSONResponse(content={"slug": slug, "enabled": enabled})
