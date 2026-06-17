from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ClientModel import ClientModel
from config import Config
from providers import ProviderStore, list_presets


route = APIRouter()


class AgentsRequest(BaseModel):
    content: str


class ProviderRequest(BaseModel):
    label: str
    base_url: str
    model: str
    api_key: str | None = None


class ActiveProviderRequest(BaseModel):
    id: str


@route.get("/api/providers/presets")
async def get_provider_presets() -> list[dict]:
    return list_presets()


@route.get("/api/providers")
async def get_providers() -> dict:
    return {
        "active_id": (ProviderStore.get_active() or {}).get("id"),
        "providers": ProviderStore.list_providers(),
    }


@route.post("/api/providers")
async def add_provider(payload: ProviderRequest) -> dict:
    provider_id = ProviderStore.add_provider(
        label=payload.label,
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
    )
    ClientModel.set_client()
    return {"id": provider_id}


@route.post("/api/providers/active")
async def set_active_provider(payload: ActiveProviderRequest) -> dict:
    try:
        ProviderStore.set_active(payload.id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown provider")
    ClientModel.set_client()
    return {"active_id": payload.id, "model": ClientModel.get_model()}


@route.put("/api/providers/{provider_id}")
async def update_provider(provider_id: str, payload: ProviderRequest) -> dict:
    # A blank api_key means "keep the current key"; only set it when one is supplied.
    kwargs = {"api_key": payload.api_key} if payload.api_key else {}
    try:
        ProviderStore.update_provider(
            provider_id,
            label=payload.label,
            base_url=payload.base_url,
            model=payload.model,
            **kwargs,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown provider")
    active = ProviderStore.get_active()
    if active is not None and active["id"] == provider_id:
        ClientModel.set_client()
    return {"id": provider_id}


@route.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str) -> dict:
    try:
        ProviderStore.delete_provider(provider_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown provider")
    ClientModel.refresh_client()
    return {"active_id": (ProviderStore.get_active() or {}).get("id")}


@route.get("/api/settings/tools")
async def get_tools_setting() -> dict:
    return {
        "enabled": Config.tools_enabled(),
        "max_tool_calls": Config.max_tool_calls(),
    }


@route.post("/api/settings/tools")
async def set_tools_setting(enabled: bool) -> None:
    Config.set_tools_enabled(enabled)


@route.get("/api/agents")
async def get_agents() -> dict:
    return {"content": Config.get_agents_md()}


@route.post("/api/agents")
async def set_agents(payload: AgentsRequest) -> None:
    Config.set_agents_md(payload.content)
