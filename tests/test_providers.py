"""Tests for the Provider store and ClientModel resolving from the Active Provider."""

import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import providers as providers_mod  # noqa: E402
import config as config_mod  # noqa: E402
from config import Config  # noqa: E402
from providers import ProviderStore, KEY_ENV_PREFIX, list_presets  # noqa: E402
from ClientModel import ClientModel  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Redirect the Provider store and .env into a temp dir for isolation."""
    env_path = tmp_path / ".env"
    monkeypatch.setattr(providers_mod, "ROOT", tmp_path)
    monkeypatch.setattr(providers_mod, "PROVIDERS_PATH", tmp_path / "providers.json")
    monkeypatch.setattr(providers_mod, "ENV_PATH", env_path)
    # ClientModel reads its own module-level ROOT for the legacy key list; point it at
    # the same temp dir so get_key_names() sees the same .env as the Provider store.
    monkeypatch.setattr(sys.modules["ClientModel"], "ROOT", tmp_path)
    # Config reads/writes MEMORY_MODEL from its own ROOT/ENV_PATH; redirect those too so
    # Config.memory_model() resolves against the same .env + Provider store.
    monkeypatch.setattr(config_mod, "ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "ENV_PATH", env_path)
    # memory_model() uses load_dotenv(override=True); clear these so a prior test's
    # values can't leak in via os.environ (monkeypatch restores them after the test).
    monkeypatch.delenv("MEMORY_MODEL", raising=False)
    monkeypatch.delenv("MEMORY_MODEL_PROVIDER_ID", raising=False)
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


# ── Presets (issue #4) ───────────────────────────────────────────────────────


def test_presets_contents():
    by_key = {p["key"]: p for p in list_presets()}
    assert set(by_key) == {"openai", "openrouter", "ollama"}
    assert by_key["openai"]["base_url"] == "https://api.openai.com/v1"
    assert by_key["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
    assert by_key["ollama"]["base_url"] == "http://localhost:11434/v1"


def test_presets_require_key_flags():
    by_key = {p["key"]: p for p in list_presets()}
    # Hosted providers need a key; the local Ollama endpoint is keyless.
    assert by_key["openai"]["requires_key"] is True
    assert by_key["openrouter"]["requires_key"] is True
    assert by_key["ollama"]["requires_key"] is False


def test_presets_expose_no_secret_fields():
    for p in list_presets():
        assert set(p) == {"key", "label", "base_url", "requires_key"}


def test_list_presets_returns_copies():
    # Mutating the returned data must not corrupt the module-level PRESETS.
    list_presets()[0]["base_url"] = "tampered"
    assert list_presets()[0]["base_url"] != "tampered"


# ── Listing & switching the active Provider (issue #3) ───────────────────────


def test_list_exposes_label_and_model_for_each(store):
    ProviderStore.add_provider("Alpha", "https://a/v1", "model-a", api_key="ka")
    ProviderStore.add_provider("Beta", "https://b/v1", "model-b", api_key=None)
    listed = ProviderStore.list_providers()
    assert [(p["label"], p["model"]) for p in listed] == [
        ("Alpha", "model-a"),
        ("Beta", "model-b"),
    ]


def test_switching_updates_active_client_and_model(store):
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    pid_b = ProviderStore.add_provider("B", "https://b/v1", "model-b", api_key="kb")

    ProviderStore.set_active(pid_b)
    ClientModel.set_client()

    assert ProviderStore.get_active()["id"] == pid_b
    assert ClientModel.get_model() == "model-b"
    assert str(ClientModel.get_client().base_url).rstrip("/") == "https://b/v1"


def _client(store_dir):
    """Bare FastAPI app with only the settings router (no lifespan) for fast route tests."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import settings_routes

    app = FastAPI()
    app.include_router(settings_routes.route)
    return TestClient(app)


def test_route_switches_active_provider(store):
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    pid_b = ProviderStore.add_provider("B", "https://b/v1", "model-b", api_key="kb")

    resp = _client(store).post("/api/providers/active", json={"id": pid_b})
    assert resp.status_code == 200
    assert resp.json() == {"active_id": pid_b, "model": "model-b"}
    assert ProviderStore.get_active()["id"] == pid_b


def test_route_switch_unknown_id_returns_404(store):
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    resp = _client(store).post("/api/providers/active", json={"id": "nope"})
    assert resp.status_code == 404


def test_preset_seeded_save_matches_handtyped(store):
    """A Provider seeded from the keyless Ollama preset is identical to a custom one."""
    ollama = {p["key"]: p for p in list_presets()}["ollama"]
    pid = ProviderStore.add_provider(
        label=ollama["label"], base_url=ollama["base_url"], model="llama3", api_key=None
    )
    record = ProviderStore.get_active()
    assert record["id"] == pid
    assert record["base_url"] == "http://localhost:11434/v1"
    assert record["api_key_env"] is None  # keyless, exactly like a hand-typed one
    ClientModel.set_client()
    assert str(ClientModel.get_client().base_url).rstrip("/") == (
        "http://localhost:11434/v1"
    )


# ── Edit & delete (issue #7) ─────────────────────────────────────────────────


def test_update_metadata_takes_effect(store):
    pid = ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    ProviderStore.update_provider(pid, label="A2", base_url="https://a2/v1", model="model-a2")

    record = ProviderStore.get_active()
    assert (record["label"], record["base_url"], record["model"]) == (
        "A2", "https://a2/v1", "model-a2"
    )
    ClientModel.set_client()
    assert ClientModel.get_model() == "model-a2"
    assert str(ClientModel.get_client().base_url).rstrip("/") == "https://a2/v1"


def test_update_keeps_key_when_unchanged(store):
    pid = ProviderStore.add_provider("A", "https://a/v1", "m", api_key="secret")
    ProviderStore.update_provider(pid, label="A", base_url="https://a/v1", model="m2")
    # Key field omitted -> the existing secret is untouched.
    assert ProviderStore.get_active_api_key() == "secret"


def test_update_replaces_key_in_place(store):
    pid = ProviderStore.add_provider("A", "https://a/v1", "m", api_key="old")
    env_before = ProviderStore.get_active()["api_key_env"]

    ProviderStore.update_provider(pid, label="A", base_url="https://a/v1", model="m", api_key="new")

    # Same env-var name, new value.
    assert ProviderStore.get_active()["api_key_env"] == env_before
    assert ProviderStore.get_active_api_key() == "new"
    assert dotenv_values(store / ".env")[env_before] == "new"


def test_update_adds_key_to_keyless_provider(store):
    pid = ProviderStore.add_provider("Ollama", "http://localhost:11434/v1", "llama3", api_key=None)
    assert ProviderStore.get_active()["api_key_env"] is None

    ProviderStore.update_provider(
        pid, label="Ollama", base_url="http://localhost:11434/v1", model="llama3", api_key="k"
    )
    env_name = ProviderStore.get_active()["api_key_env"]
    assert env_name and env_name.startswith(KEY_ENV_PREFIX)
    assert ProviderStore.get_active_api_key() == "k"


def test_update_unknown_id_raises(store):
    with pytest.raises(ValueError):
        ProviderStore.update_provider("nope", label="x", base_url="y", model="z")


def test_delete_removes_record_and_unsets_its_key(store):
    pid_a = ProviderStore.add_provider("A", "https://a/v1", "ma", api_key="ka")
    ProviderStore.add_provider("B", "https://b/v1", "mb", api_key="kb")
    env_a = ProviderStore.get_active()["api_key_env"]

    ProviderStore.delete_provider(pid_a)

    assert [p["label"] for p in ProviderStore.list_providers()] == ["B"]
    # A's key is gone; B's key remains.
    env = dotenv_values(store / ".env")
    assert env_a not in env
    assert "kb" in env.values()


def test_delete_keyless_leaves_env_untouched(store):
    ProviderStore.add_provider("Keyed", "https://a/v1", "m", api_key="ka")
    pid_keyless = ProviderStore.add_provider(
        "Ollama", "http://localhost:11434/v1", "llama3", api_key=None
    )

    before = dict(dotenv_values(store / ".env"))
    ProviderStore.delete_provider(pid_keyless)  # no error, no env change
    assert dict(dotenv_values(store / ".env")) == before


def test_delete_active_falls_back_to_first_remaining(store):
    pid_a = ProviderStore.add_provider("A", "https://a/v1", "ma", api_key="ka")
    pid_b = ProviderStore.add_provider("B", "https://b/v1", "mb", api_key="kb")
    assert ProviderStore.get_active()["id"] == pid_a  # A added first -> active

    ProviderStore.delete_provider(pid_a)

    assert ProviderStore.get_active()["id"] == pid_b
    ClientModel.refresh_client()
    assert str(ClientModel.get_client().base_url).rstrip("/") == "https://b/v1"


def test_delete_last_provider_clears_active_and_client(store):
    pid = ProviderStore.add_provider("A", "https://a/v1", "ma", api_key="ka")
    ClientModel.set_client()

    ProviderStore.delete_provider(pid)

    assert ProviderStore.get_active() is None
    ClientModel.refresh_client()
    assert ClientModel.client is None


def test_delete_unknown_id_raises(store):
    with pytest.raises(ValueError):
        ProviderStore.delete_provider("nope")


def test_route_edits_provider(store):
    pid = ProviderStore.add_provider("A", "https://a/v1", "ma", api_key="ka")
    resp = _client(store).put(
        "/api/providers/" + pid,
        json={"label": "A2", "base_url": "https://a2/v1", "model": "ma2"},
    )
    assert resp.status_code == 200
    record = ProviderStore.get_active()
    assert (record["label"], record["base_url"], record["model"]) == (
        "A2", "https://a2/v1", "ma2"
    )
    assert ProviderStore.get_active_api_key() == "ka"  # key kept (none sent)


def test_route_edit_unknown_id_returns_404(store):
    resp = _client(store).put(
        "/api/providers/nope", json={"label": "x", "base_url": "y", "model": "z"}
    )
    assert resp.status_code == 404


def test_route_deletes_provider(store):
    ProviderStore.add_provider("A", "https://a/v1", "ma", api_key="ka")
    pid_b = ProviderStore.add_provider("B", "https://b/v1", "mb", api_key="kb")

    resp = _client(store).delete("/api/providers/" + pid_b)
    assert resp.status_code == 200
    assert [p["label"] for p in ProviderStore.list_providers()] == ["A"]


def test_route_delete_unknown_id_returns_404(store):
    resp = _client(store).delete("/api/providers/nope")
    assert resp.status_code == 404


# ── MEMORY_MODEL falls back to the Active Provider's model (issue #6) ─────────


def test_memory_model_blank_uses_active_provider_model(store):
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    assert Config.memory_model() == "model-a"


def test_memory_model_used_when_bound_to_active_provider(store):
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    Config.set_memory_model("cheap-mini")  # bound to the active Provider
    assert Config.memory_model() == "cheap-mini"


def test_memory_model_falls_back_after_provider_switch(store):
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    Config.set_memory_model("openrouter/cheap")  # bound to A while A is active
    pid_b = ProviderStore.add_provider("B", "http://localhost:11434/v1", "llama3", api_key=None)

    ProviderStore.set_active(pid_b)
    # The stale memory model is not valid for B, so fall back to B's own model.
    assert Config.memory_model() == "llama3"


def test_memory_model_falls_back_without_binding(store):
    # Simulate a legacy/upgraded install: MEMORY_MODEL set with no Provider binding.
    ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    from dotenv import set_key
    set_key(store / ".env", "MEMORY_MODEL", "orphan-model")
    assert Config.memory_model() == "model-a"


def test_set_memory_model_blank_clears_binding(store):
    pid = ProviderStore.add_provider("A", "https://a/v1", "model-a", api_key="ka")
    Config.set_memory_model("cheap-mini")
    assert dotenv_values(store / ".env")["MEMORY_MODEL_PROVIDER_ID"] == pid

    Config.set_memory_model("")
    env = dotenv_values(store / ".env")
    assert env["MEMORY_MODEL"] == ""
    assert env["MEMORY_MODEL_PROVIDER_ID"] == ""
    assert Config.memory_model() == "model-a"
