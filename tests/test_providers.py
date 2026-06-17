"""Tests for the Provider store and ClientModel resolving from the Active Provider."""

import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import providers as providers_mod  # noqa: E402
from providers import ProviderStore, KEY_ENV_PREFIX  # noqa: E402
from ClientModel import ClientModel  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Redirect the Provider store and .env into a temp dir for isolation."""
    monkeypatch.setattr(providers_mod, "ROOT", tmp_path)
    monkeypatch.setattr(providers_mod, "PROVIDERS_PATH", tmp_path / "providers.json")
    monkeypatch.setattr(providers_mod, "ENV_PATH", tmp_path / ".env")
    # ClientModel reads its own module-level ROOT for the legacy key list; point it at
    # the same temp dir so get_key_names() sees the same .env as the Provider store.
    monkeypatch.setattr(sys.modules["ClientModel"], "ROOT", tmp_path)
    ClientModel.client = None
    return tmp_path


def _write_legacy_env(store_dir, **vars):
    """Write the given key=value pairs into the temp .env."""
    (store_dir / ".env").write_text(
        "".join(f'{k}="{v}"\n' for k, v in vars.items()), encoding="utf-8"
    )


def test_add_provider_roundtrip(store):
    pid = ProviderStore.add_provider(
        label="My OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-4o",
        api_key="sk-secret-123",
    )

    # First Provider becomes active.
    active = ProviderStore.get_active()
    assert active["id"] == pid
    assert active["base_url"] == "https://openrouter.ai/api/v1"
    assert active["model"] == "openai/gpt-4o"

    # The key lives in .env under the record's pointer, not in the JSON metadata.
    assert active["api_key_env"] == f"{KEY_ENV_PREFIX}{pid}_KEY"
    assert dotenv_values(store / ".env")[active["api_key_env"]] == "sk-secret-123"
    assert ProviderStore.get_active_api_key() == "sk-secret-123"


def test_list_providers_exposes_no_secret(store):
    ProviderStore.add_provider("P", "https://x/v1", "m", api_key="sk-shh")
    listed = ProviderStore.list_providers()
    assert len(listed) == 1
    entry = listed[0]
    assert entry["label"] == "P"
    assert entry["has_key"] is True
    # No secret value or env-var name leaks through the public listing.
    assert "api_key" not in entry
    assert "api_key_env" not in entry
    assert "sk-shh" not in str(entry)


def test_client_resolves_from_active_provider(store):
    ProviderStore.add_provider(
        "OR", "https://openrouter.ai/api/v1", "openai/gpt-4o", api_key="sk-1"
    )
    ClientModel.set_client()

    assert ClientModel.get_model() == "openai/gpt-4o"
    assert str(ClientModel.get_client().base_url).rstrip("/") == (
        "https://openrouter.ai/api/v1"
    )


def test_switching_active_changes_model_and_client(store):
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    pid_b = ProviderStore.add_provider("B", "https://b/v1", "model-b", api_key="kb")

    # B was added second, so A is still active.
    assert ClientModel.get_model() == "model-a"

    ProviderStore.set_active(pid_b)
    ClientModel.set_client()
    assert ClientModel.get_model() == "model-b"
    assert str(ClientModel.get_client().base_url).rstrip("/") == "https://b/v1"


def test_keyless_provider(store):
    pid = ProviderStore.add_provider(
        "Ollama", "http://localhost:11434/v1", "llama3", api_key=None
    )
    active = ProviderStore.get_active()
    assert active["id"] == pid
    assert active["api_key_env"] is None
    assert ProviderStore.get_active_api_key() is None

    # set_client still succeeds (placeholder key) for a keyless endpoint.
    ClientModel.set_client()
    assert str(ClientModel.get_client().base_url).rstrip("/") == (
        "http://localhost:11434/v1"
    )


def test_no_active_provider_errors(store):
    assert ProviderStore.get_active() is None
    with pytest.raises(ValueError):
        ClientModel.get_model()
    with pytest.raises(ValueError):
        ClientModel.set_client()


def test_set_active_unknown_id_raises(store):
    ProviderStore.add_provider("A", "https://a/v1", "m", api_key="k")
    with pytest.raises(ValueError):
        ProviderStore.set_active("does-not-exist")


# ── Legacy migration (issue #5) ──────────────────────────────────────────────


def test_migrates_legacy_env(store):
    _write_legacy_env(store, OPENROUTER_API_KEY="sk-old", MODEL="openai/gpt-4o")
    assert not (store / "providers.json").exists()

    assert ProviderStore.migrate_legacy_env() is True

    active = ProviderStore.get_active()
    assert active["label"] == "OpenRouter"
    assert active["base_url"] == "https://openrouter.ai/api/v1"
    assert active["model"] == "openai/gpt-4o"
    # Points at the existing env var; the secret is not duplicated.
    assert active["api_key_env"] == "OPENROUTER_API_KEY"
    assert ProviderStore.get_active_api_key() == "sk-old"

    # The migrated install boots into a working client.
    ClientModel.set_client()
    assert ClientModel.get_model() == "openai/gpt-4o"
    assert str(ClientModel.get_client().base_url).rstrip("/") == (
        "https://openrouter.ai/api/v1"
    )


def test_migration_is_additive_and_hides_key_from_legacy_list(store):
    _write_legacy_env(store, OPENROUTER_API_KEY="sk-old", MODEL="m")
    ProviderStore.migrate_legacy_env()

    # .env is untouched: the key still lives there...
    assert dotenv_values(store / ".env")["OPENROUTER_API_KEY"] == "sk-old"
    # ...but it is now owned by a Provider, so it drops out of the legacy key list.
    assert "OPENROUTER_API_KEY" not in ClientModel.get_key_names()


def test_migration_noop_when_providers_exist(store):
    pid = ProviderStore.add_provider("Existing", "https://x/v1", "mx", api_key="kx")
    _write_legacy_env(store, OPENROUTER_API_KEY="sk-old", MODEL="m")

    assert ProviderStore.migrate_legacy_env() is False
    # The existing store is not clobbered.
    assert ProviderStore.get_active()["id"] == pid
    assert len(ProviderStore.list_providers()) == 1


def test_migration_noop_on_fresh_install(store):
    assert ProviderStore.migrate_legacy_env() is False
    assert ProviderStore.get_active() is None
    assert ProviderStore.list_providers() == []


def test_migration_requires_both_key_and_model(store):
    _write_legacy_env(store, OPENROUTER_API_KEY="sk-old")  # no MODEL
    assert ProviderStore.migrate_legacy_env() is False
    assert ProviderStore.get_active() is None

    _write_legacy_env(store, MODEL="m")  # key only / now no key
    assert ProviderStore.migrate_legacy_env() is False
    assert ProviderStore.get_active() is None


def test_migration_is_idempotent(store):
    _write_legacy_env(store, OPENROUTER_API_KEY="sk-old", MODEL="m")
    assert ProviderStore.migrate_legacy_env() is True
    assert ProviderStore.migrate_legacy_env() is False
    assert len(ProviderStore.list_providers()) == 1
