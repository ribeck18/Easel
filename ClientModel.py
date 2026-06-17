from typing import Optional
from openai import OpenAI

from providers import ProviderStore


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
    def get_model() -> str:
        """Return the Active Provider's selected model."""
        active = ProviderStore.get_active()
        if active is None:
            raise ValueError("No Provider is active, so no model is set.")
        return active["model"]
