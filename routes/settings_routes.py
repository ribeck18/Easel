from fastapi import APIRouter
from pydantic import BaseModel

from ClientModel import ClientModel
from config import Config


route = APIRouter()


class AgentsRequest(BaseModel):
    content: str


@route.get("/api/keys")
async def get_keys() -> list[str]:
    return ClientModel.get_key_names()


@route.post("/api/setkey")
async def edit_env(key_name: str, key: str) -> None:
    ClientModel.add_env_var(key_name=key_name, key=key)
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
