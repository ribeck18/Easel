from typing import Optional
from openai import OpenAI
from dotenv import dotenv_values, load_dotenv, set_key
from pathlib import Path
import os

from paths import data_dir
from providers import ProviderStore, KEY_ENV_PREFIX


ROOT = data_dir()

# Placeholder key for keyless Providers (e.g. a local Ollama install). The OpenAI
# SDK requires a non-empty api_key even when the endpoint ignores it.
_NO_AUTH_PLACEHOLDER = "sk-no-auth"


class ClientModel:
    client: Optional[OpenAI] = None

    @staticmethod
    def set_client():
        """Build the OpenAI client from the Active Provider (ADR-0001)."""
        active = ProviderStore.get_active()
        if active is None:
            raise ValueError("No Provider is active. Add one in Settings.")

        ClientModel.client = OpenAI(
            base_url=active["base_url"],
            api_key=ProviderStore.get_active_api_key() or _NO_AUTH_PLACEHOLDER,
        )

    @staticmethod
    def refresh_client():
        """Rebuild the client from the active Provider, or drop it if none is active."""
        if ProviderStore.get_active() is not None:
            ClientModel.set_client()
        else:
            ClientModel.client = None

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
        """Return the Active Provider's selected model."""
        active = ProviderStore.get_active()
        if active is None:
            raise ValueError("No Provider is active, so no model is set.")
        return active["model"]

    # Config/settings entries stored in .env that are not API keys and
    # should not be surfaced in the Settings page's API Keys list.
    _NON_KEY_ENV = {
        "MODEL",
        "TOOLS_ENABLED",
        "MEMORY_ENABLED",
        "MEMORY_MODEL",
        "MEMORY_MODEL_PROVIDER_ID",
        "SKILLS_ENABLED",
        "MAX_TOOL_CALLS",
    }

    @staticmethod
    def get_key_names() -> list[str]:
        env_path: Path = Path(ROOT / ".env")
        if not env_path.exists():
            return []
        owned = ProviderStore.key_env_names()
        return [
            k
            for k in dotenv_values(env_path).keys()
            if k.upper() not in ClientModel._NON_KEY_ENV
            and not k.startswith(KEY_ENV_PREFIX)
            and k not in owned
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
