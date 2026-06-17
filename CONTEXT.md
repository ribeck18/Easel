# Easel

A local-first desktop AI assistant. The user brings their own model access; Easel
talks to language models through a single, swappable interface.

## Language

### Models & Providers

**Provider**:
A named, OpenAI-compatible endpoint the user can talk to: a `{label, base_url, optional api_key,
selected model}`. OpenRouter, OpenAI, and a local Ollama install are each a Provider. Users may
store several and select one as active. Each Provider remembers its own selected model, since model
identifiers are provider-specific.
_Avoid_: backend, service, vendor

**OpenAI SDK / interface standard**:
The OpenAI Python client is the one interface every Provider must speak (the Chat Completions
API shape). It is not itself a Provider — it is the lens through which all Providers are used.
_Avoid_: "OpenAI" when you mean the SDK rather than the company's hosted service

**Active Provider**:
The single Provider currently used for requests. Exactly one is active at a time, and it governs
*all* model calls — foreground chat and background work (memory capture, consolidation, agent loop)
alike.

**Preset**:
A built-in starting template for a common Provider (OpenAI, OpenRouter, Ollama) with its `base_url`
prefilled. The user picks a Preset and fills in the rest, or chooses "Custom" to enter an arbitrary
OpenAI-compatible `base_url`. A Preset is not itself a Provider — it seeds one.

A Provider is identified by its user-given label, so multiple Providers of the same kind (e.g. two
OpenRouter accounts) can coexist.
