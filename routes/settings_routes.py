from fastapi import APIRouter
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


@route.get("/api/keys")
async def get_keys() -> list[str]:
    return ClientModel.get_key_names()


@route.post("/api/setkey")
async def edit_env(key_name: str, key: str) -> None:
    ClientModel.add_env_var(key_name=key_name, key=key)
    # The active Provider is the source of truth for the client; only (re)build it
    # here if one already exists, so adding a legacy key doesn't error pre-Provider.
    if ProviderStore.get_active() is not None:
        ClientModel.set_client()


@route.post("/api/setmodel")
async def set_model(model: str) -> None:
    ClientModel.set_model(model=model)

    chosen_model = ClientModel.get_model()

    # for debug
    print(chosen_model)


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
