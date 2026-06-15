from typing import Optional
from openai import OpenAI
from dotenv import dotenv_values, load_dotenv, set_key
from pathlib import Path
import os

from paths import data_dir


ROOT = data_dir()


class ClientModel:
    api_key_name: Optional[str] = "OPENROUTER_API_KEY"
    client: Optional[OpenAI] = None

    @staticmethod
    def set_client():
        ClientModel.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=ClientModel.get_api_key(),
            # base_url="http://localhost:11434/v1",
            # api_key="ollama",
        )

    @staticmethod
    def get_client():
        if ClientModel.client is None:
            raise ValueError("Client has not been initalized.")

        return ClientModel.client

    @staticmethod
    def set_model(model: str):
        env_path: Path = Path(ROOT / ".env")

        if not env_path.exists():
            open(env_path, "w").close()

        set_key(env_path, "MODEL", model)

    @staticmethod
    def get_model() -> str:
        load_dotenv(ROOT / ".env", override=True)
        model = os.getenv("MODEL")

        if model is None:
            raise ValueError("No model set.")

        return model

    @staticmethod
    def get_api_key():
        if ClientModel.api_key_name is None:
            raise ValueError("No API key was found. Make sure you have set one.")

        load_dotenv(ROOT / ".env", override=True)
        api_key = os.getenv(ClientModel.api_key_name)

        if api_key is None:
            raise ValueError("API key could not be found.")

        return api_key

    # Config/settings entries stored in .env that are not API keys and
    # should not be surfaced in the Settings page's API Keys list.
    _NON_KEY_ENV = {
        "MODEL",
        "TOOLS_ENABLED",
        "MEMORY_ENABLED",
        "MEMORY_MODEL",
        "SKILLS_ENABLED",
        "MAX_TOOL_CALLS",
    }

    @staticmethod
    def get_key_names() -> list[str]:
        env_path: Path = Path(ROOT / ".env")
        if not env_path.exists():
            return []
        return [
            k
            for k in dotenv_values(env_path).keys()
            if k.upper() not in ClientModel._NON_KEY_ENV
        ]

    @staticmethod
    def add_env_var(key_name: str, key: str) -> None:
        env_path: Path = Path(ROOT / ".env")

        if not env_path.exists():
            open(env_path, "w").close()

        exisiting_keys = dotenv_values(env_path)

        if key_name in exisiting_keys:
            print(f"Key '{key_name}' exists - replacing.")
        else:
            print(f"Key '{key_name}' does not exist - adding to env.")

        set_key(env_path, key_name, key)
