# OpenAI SDK as the universal Provider interface

To let users choose between model services (OpenRouter, OpenAI, a local Ollama install, and any
other OpenAI-compatible endpoint), we standardize on the OpenAI Python SDK as the single interface
every Provider must speak — the Chat Completions API shape. A Provider is just a `{base_url, api_key}`
the SDK is pointed at; OpenRouter and Ollama are already used this way today.

We deliberately rejected per-provider adapters / a provider-abstraction layer. The OpenAI Chat
Completions shape is the de-facto standard that the providers we care about already implement, so an
abstraction would add indirection without buying compatibility we don't already get for free. The
cost: a Provider that is *not* OpenAI-compatible cannot be supported without revisiting this decision.
