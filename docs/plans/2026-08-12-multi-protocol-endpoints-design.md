# Multi-protocol provider endpoints design

Date: 2026-08-12

## Problem

A provider can expose several upstream API formats at once. DeepSeek, for
example, offers an OpenAI-compatible chat endpoint, an OpenAI Responses API
endpoint (currently only for `deepseek-v4-flash`), and an Anthropic-compatible
endpoint. Today the schema models a provider with exactly one `sdk_type` and one
`default_base_url`, so a single provider cannot describe multiple protocols, and
an account cannot choose which protocol to talk over.

## Goals

- Let a provider declare several named endpoints, each bundling `sdk_type`
  (protocol), `base_url`, and an optional `mode` (`chat` vs `responses`).
- Let an account select one of those endpoints by name (`endpoint_ref`).
- Surface the effective `sdk_type` and `mode` on `Resolution` so adapters pick
  the right SDK call (chat completions vs responses).
- Keep the existing single-endpoint shape working unchanged (backward
  compatible): providers without `endpoints` behave exactly as today.
- Validate model availability per endpoint (Responses API only supports
  `deepseek-v4-flash` for now).

## Non-goals

- Not introducing provider-specific request shaping beyond the endpoint
  selection.
- Not adding new SDK integrations.

## Design

### Provider endpoints

```yaml
id: deepseek
name: DeepSeek
endpoints:
  openai-chat:
    sdk_type: openai
    base_url: https://api.deepseek.com
    mode: chat                 # chat completions (default)
  openai-responses:
    sdk_type: openai
    base_url: https://api.deepseek.com
    mode: responses            # Responses API
  anthropic:
    sdk_type: anthropic
    base_url: https://api.deepseek.com/anthropic
    mode: chat
model_cards:
  - id: deepseek-v4-flash
    ...
    endpoints: [openai-chat, openai-responses, anthropic]
  - id: deepseek-v4-pro
    ...
    endpoints: [openai-chat, anthropic]
```

- `endpoints` is an optional map on the provider. Keys are endpoint ids, values
  bundle `sdk_type` + `base_url` + optional `mode`.
- `mode` defaults to `chat`; `responses` is only meaningful for
  `sdk_type: openai`.
- When `endpoints` is absent, the provider keeps its current single
  `sdk_type` + `default_base_url` behavior (mode `chat`).

### Account selection

```yaml
accounts:
  - id: deepseek-v4-primary
    provider_id: deepseek
    endpoint_ref: openai-responses
    credential: {env: DEEPSEEK_API_KEY}
    enabled_models: [deepseek-v4-flash]
```

- New `endpoint_ref` field on `Account` names a provider endpoint.
- `endpoint_ref` and the existing `endpoint` (raw URL override) are mutually
  exclusive; setting both is rejected.
- Unset → legacy behavior: `account.endpoint` override, else provider
  `default_base_url`, protocol = provider `sdk_type`, mode `chat`.

### Resolution

- `Resolution` carries effective `sdk_type` and `mode` for the deployment,
  resolved from the selected endpoint (or the legacy provider values).
- `Resolution.endpoint` resolves to the selected endpoint's `base_url` (or the
  legacy path).
- Adapters switch on `resolution.sdk_type`/`resolution.mode` instead of
  `resolution.provider.sdk_type`.

### Model availability

- A model card may declare `endpoints: [...]` naming which provider endpoints
  support it. Omitted means all provider endpoints.
- Validation: an account whose `endpoint_ref` is not in the model's supported
  set fails at resolve/config time with a clear message.

## Schema changes

- `schemas.py`:
  - `ProviderEndpoint` model: `sdk_type`, `base_url`, `mode` (default `chat`).
  - `Provider.endpoints: dict[str, ProviderEndpoint] | None`.
  - `Account.endpoint_ref: str | None`.
  - `ModelCard.endpoints: list[str] | None` (optional supported-set).
- `config.py`:
  - Normalize `endpoints`; validate `endpoint_ref` against provider endpoint
    names; reject `endpoint_ref` + `endpoint` together; keep legacy
    `proxy_url.placeholder` → `default_base_url` mapping.
- `registry.py`:
  - Resolve effective `sdk_type`, `mode`, `endpoint` at `_resolution`.
  - Validate model availability against the selected endpoint.
- `adapters/openai.py`, `adapters/pydantic_ai.py`:
  - Read `resolution.sdk_type` + `resolution.mode`; use the responses call when
    mode is `responses`.

## Testing

- Unit tests for schema validation (`endpoint_ref` + `endpoint` conflict,
  unknown endpoint ref, unknown mode).
- Config normalization tests for the new `endpoints` shape and legacy
  compatibility.
- Registry resolution tests: selecting an endpoint by name, effective
  sdk_type/mode, model-availability rejection.
- Adapter tests: chat vs responses mode routing.
- Fixture: a deepseek provider with `endpoints` exercising openai-chat,
  openai-responses, and anthropic.