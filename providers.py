"""Provider storage: secrets in ``.env``, metadata in ``providers.json``.

A *Provider* is a named, OpenAI-compatible endpoint the user can talk to. Per
ADR-0002 the secret (the API key) lives in the app's ``.env`` -- the existing
secret store -- while the non-secret metadata (label, base_url, selected model,
which Provider is active, and a pointer to the key's env-var name) lives in a
structured ``providers.json`` alongside it. A keyless Provider (e.g. a local
Ollama install) has ``api_key_env`` set to ``None``.
"""

from pathlib import Path
import json
import os
import uuid

from dotenv import dotenv_values, set_key, unset_key

from paths import data_dir


ROOT = data_dir()
ENV_PATH = ROOT / ".env"
PROVIDERS_PATH = ROOT / "providers.json"

# Env-var prefix under which Provider API keys are stored in ``.env``. Lets the
# legacy "API Keys" settings list filter these out so Provider secrets are not
# surfaced as standalone keys.
KEY_ENV_PREFIX = "EASEL_PROVIDER_"


class ProviderStore:
    """Static-accessor store for Providers, mirroring ``ClientModel``/``Config``."""

    @staticmethod
    def _read() -> dict:
        if not PROVIDERS_PATH.exists():
            return {"active_id": None, "providers": []}
        try:
            data = json.loads(PROVIDERS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"active_id": None, "providers": []}
        data.setdefault("active_id", None)
        data.setdefault("providers", [])
        return data

    @staticmethod
    def _write(data: dict) -> None:
        """Atomically replace ``providers.json`` (temp file + ``os.replace``)."""
        ROOT.mkdir(parents=True, exist_ok=True)
        temp_path = PROVIDERS_PATH.with_suffix(PROVIDERS_PATH.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temp_path, PROVIDERS_PATH)

    @staticmethod
    def add_provider(
        label: str, base_url: str, model: str, api_key: str | None = None
    ) -> str:
        """Add a Provider and return its id. Marks it active if none is active yet.

        The ``api_key`` (when given) is written to ``.env`` under a generated
        env-var name; the metadata record only stores that name. A blank/``None``
        key produces a keyless Provider (``api_key_env`` is ``None``).
        """
        provider_id = uuid.uuid4().hex

        api_key_env: str | None = None
        if api_key:
            api_key_env = f"{KEY_ENV_PREFIX}{provider_id}_KEY"
            if not ENV_PATH.exists():
                ROOT.mkdir(parents=True, exist_ok=True)
                open(ENV_PATH, "w").close()
            set_key(ENV_PATH, api_key_env, api_key)

        record = {
            "id": provider_id,
            "label": label,
            "base_url": base_url,
            "model": model,
            "api_key_env": api_key_env,
        }

        data = ProviderStore._read()
        data["providers"].append(record)
        if data["active_id"] is None:
            data["active_id"] = provider_id
        ProviderStore._write(data)

        return provider_id

    @staticmethod
    def list_providers() -> list[dict]:
        """Return public Provider info (no secret values)."""
        return [
            {
                "id": p["id"],
                "label": p["label"],
                "base_url": p["base_url"],
                "model": p["model"],
                "has_key": p.get("api_key_env") is not None,
            }
            for p in ProviderStore._read()["providers"]
        ]

    @staticmethod
    def get_active() -> dict | None:
        """Return the full active Provider record, or ``None`` if none is active."""
        data = ProviderStore._read()
        active_id = data["active_id"]
        if active_id is None:
            return None
        for p in data["providers"]:
            if p["id"] == active_id:
                return p
        return None

    @staticmethod
    def get_active_api_key() -> str | None:
        """Resolve the active Provider's API key from ``.env``, or ``None``."""
        active = ProviderStore.get_active()
        if active is None or active.get("api_key_env") is None:
            return None
        return dotenv_values(ENV_PATH).get(active["api_key_env"])

    @staticmethod
    def set_active(provider_id: str) -> None:
        """Mark a stored Provider as active. Raises if the id is unknown."""
        data = ProviderStore._read()
        if not any(p["id"] == provider_id for p in data["providers"]):
            raise ValueError(f"No Provider with id {provider_id!r}.")
        data["active_id"] = provider_id
        ProviderStore._write(data)
