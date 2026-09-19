# Changelog

## Forge 3.1.0 — local assessment build

- Removed LM Studio, Ollama, and generic local-model entries from every picker.
- Migrated existing `x-ai/grok-4-fast` pins to live `x-ai/grok-4.6`.
- Verified every listed OpenRouter choice against the official model catalog.
- Interleaved model fallbacks for faster recovery from unavailable endpoints.
- Hardened Kimi K3 drafting and revision recovery by treating it as a thinking
  model, validating raw refusals before marker stitching, and preserving the
  original target across revision turns.
- Routed provider HTTPS through the operating-system certificate store and
  increased transient connection retries across every remote model backend,
  including OpenRouter, Anthropic, Codex streams, and Codex token refresh.
- Added a frozen Linux Qt import gate to prevent backend-less releases.
- Added an independently scrolling API-key list with the same styled scrollbar
  as the model picker, keeping every configured provider accessible.
- Updated desktop, package, build, and future release branding to Forge 3.1.

This build remains local and has not been published.
