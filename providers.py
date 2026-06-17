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

# Sentinel for ``update_provider``: distinguishes "leave the API key untouched" from
# passing ``None`` (which means "keyless").
_UNCHANGED = object()

# Built-in starting templates for common Providers. A Preset only seeds the Add
# Provider form (prefilling base_url); it is not itself a Provider and adds no field
# to the stored record. ``requires_key`` is False for a local, keyless endpoint
# (Ollama). The UI also offers a "Custom" choice for any other OpenAI-compatible URL.
PRESETS = [
    {
        "key": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "requires_key": True,
    },
    {
        "key": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "requires_key": True,
    },
    {
        "key": "ollama",
        "label": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "requires_key": False,
    },
]


def list_presets() -> list[dict]:
    """Return the built-in Provider presets (no secrets)."""
    return [dict(p) for p in PRESETS]


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

    @staticmethod
    def update_provider(
        provider_id: str,
        label: str,
        base_url: str,
        model: str,
        api_key=_UNCHANGED,
    ) -> None:
        """Edit a stored Provider's fields. Raises ``ValueError`` if the id is unknown.

        ``label``/``base_url``/``model`` are always overwritten. The API key is only
        touched when ``api_key`` is a real value:

        * ``_UNCHANGED`` (default) -> leave the existing key alone.
        * a non-empty string -> write it. Overwrites the value at the record's existing
          ``api_key_env`` (so a migrated ``OPENROUTER_API_KEY`` keeps working); if the
          Provider was keyless, a namespaced ``EASEL_PROVIDER_<id>_KEY`` is created.
        """
        data = ProviderStore._read()
        record = next((p for p in data["providers"] if p["id"] == provider_id), None)
        if record is None:
            raise ValueError(f"No Provider with id {provider_id!r}.")

        record["label"] = label
        record["base_url"] = base_url
        record["model"] = model

        if api_key is not _UNCHANGED and api_key:
            env_name = record.get("api_key_env") or f"{KEY_ENV_PREFIX}{provider_id}_KEY"
            if not ENV_PATH.exists():
                ROOT.mkdir(parents=True, exist_ok=True)
                open(ENV_PATH, "w").close()
            set_key(ENV_PATH, env_name, api_key)
            record["api_key_env"] = env_name

        ProviderStore._write(data)

    @staticmethod
    def delete_provider(provider_id: str) -> None:
        """Remove a Provider, clean up its orphaned ``.env`` key, and fix up ``active_id``.

        Raises ``ValueError`` if the id is unknown. The API key var is only unset when no
        remaining Provider still references that same env-var name. If the deleted Provider
        was active, ``active_id`` falls back to the first remaining Provider (or ``None``
        when none remain).
        """
        data = ProviderStore._read()
        record = next((p for p in data["providers"] if p["id"] == provider_id), None)
        if record is None:
            raise ValueError(f"No Provider with id {provider_id!r}.")

        data["providers"] = [p for p in data["providers"] if p["id"] != provider_id]

        env_name = record.get("api_key_env")
        if env_name and not any(
            p.get("api_key_env") == env_name for p in data["providers"]
        ):
            if ENV_PATH.exists():
                unset_key(ENV_PATH, env_name)

        if data["active_id"] == provider_id:
            data["active_id"] = (
                data["providers"][0]["id"] if data["providers"] else None
            )

        ProviderStore._write(data)

    @staticmethod
    def migrate_legacy_env() -> bool:
        """One-shot upgrade of a pre-Provider install to an active OpenRouter Provider.

        Before Providers existed the app talked to OpenRouter via a hardcoded base_url
        plus ``OPENROUTER_API_KEY`` + ``MODEL`` in ``.env``. On first launch after the
        Provider feature ships, synthesize an active OpenRouter Provider from that config
        so the upgrade is seamless.

        Purely additive: the record points ``api_key_env`` at the existing
        ``OPENROUTER_API_KEY`` var and ``.env`` is never modified. Guarded by the
        existence of ``providers.json`` so it runs at most once and never clobbers an
        already-configured store.

        Returns ``True`` if a Provider was created, ``False`` otherwise (already
        migrated, or nothing to migrate).
        """
        if PROVIDERS_PATH.exists():
            return False

        env = dotenv_values(ENV_PATH)
        api_key = env.get("OPENROUTER_API_KEY")
        model = env.get("MODEL")
        if not api_key or not model:
            return False

        provider_id = uuid.uuid4().hex
        record = {
            "id": provider_id,
            "label": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": model,
            "api_key_env": "OPENROUTER_API_KEY",
        }
        ProviderStore._write({"active_id": provider_id, "providers": [record]})
        return True
