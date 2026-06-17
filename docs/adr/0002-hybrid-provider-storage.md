# Hybrid Provider storage: secrets in .env, metadata in JSON

A Provider is stored across two files: its API key stays in `.env` (the app's existing secret store,
covered by secret-scrubbing logic), while its non-secret metadata — label, base_url, selected model,
and which Provider is active — lives in a structured `providers.json` in the data dir. Each JSON record
points to its key by env-var name (null for keyless Providers like Ollama).

We chose this over a single `providers.json` holding keys too (keeps secrets out of the metadata file
and consistent with how secrets are already handled) and over namespaced `.env` keys (which model
structured, multi-instance data poorly). The trade-off: a single Provider is now split across two
files, so reads/writes must keep them in sync, and migration must reconcile both.

## Consequences

- Existing installs are auto-migrated: an `OPENROUTER_API_KEY` + `MODEL` already in `.env` is
  synthesized into an active "OpenRouter" Provider on first launch.
