# AI Registry Core Design

## Decision

Build the first milestone as a framework-independent registry core with a
normalized Pydantic schema and compatibility loaders for the provider and
profile YAML files already in `data/ai/providers/`. The registry owns
configuration validation, secret-reference resolution, logical model
resolution, and deployment selection. Framework adapters are deferred until
the core contract is stable.

The repository will be managed with `uv` and follow a standard `src/` package
layout. Project metadata, dependency groups, commands, and lockfile will be
defined through `pyproject.toml` and `uv.lock`; development and verification
commands will run through `uv run`.

## Scope

The first implementation provides:

- Pydantic models for providers, model cards, profiles, credentials, aliases,
  deployments, and routing metadata.
- YAML and JSON loading with normalization of the existing provider catalog
  format and profile format into the normalized runtime schema.
- Environment-based credentials and a pluggable `SecretResolver` protocol.
- Alias-first resolution, with `profile-id/model-id` as the explicit fallback.
- Validation of duplicate IDs, unknown providers/models, disabled models,
  invalid deployments, unsupported SDK types, and routing metadata.
- Priority-first selection, weighted selection within the selected priority,
  disabled deployment handling, and health-aware exclusion and recovery.
- Public errors that identify the safe logical reference and remediation while
  never including secret values.

The milestone does not implement OpenAI, Pydantic AI, LangGraph, or LlamaIndex
adapters, a unified response interface, request-time failover wrappers, a
gateway, or literal secret storage.

## Architecture

The package will be organized under `src/ai_registry/`:

- `schemas`: Pydantic configuration and runtime models.
- `config`: YAML/JSON readers and compatibility normalization.
- `secrets`: environment resolver and secret resolver protocol.
- `registry`: validated registry construction and alias/direct resolution.
- `routing`: selection policies and mutable health state.
- `errors`: stable, actionable exception types.

`Registry` will be constructed from loaded configuration and expose safe
resolution results containing the selected provider, canonical model ID,
profile/deployment ID, endpoint metadata, and a resolved credential only to
the adapter boundary. String representations and errors will use redacted
configuration views.

The normalized schema will be the internal and future public contract. Existing
catalog/profile files will be accepted through explicit loaders rather than
making their current shape the long-term API. New examples can use the draft's
provider/profile/alias structure.

## Configuration and Secrets

Provider files describe provider metadata, SDK type, defaults, and model cards.
Profiles bind providers to endpoints, credential references, enabled models,
and routing metadata. Aliases map stable logical names to one or more
profile/model deployments.

Credential references support environment variables and external references
such as `vault://...` through an application-provided resolver. Literal keys
are rejected by default. Credential resolution is lazy during deployment
resolution, with an explicit validation path available later.

## Routing

Selection first excludes disabled and unhealthy deployments, then chooses the
lowest priority value. If multiple deployments remain at that priority, their
weights determine selection. A deterministic injectable random source will be
used in tests. Health state is maintained separately from static configuration
and supports marking failures and recovery without rewriting loaded config.

## Testing

Tests will run with `uv run pytest` and cover schema validation, compatibility
loading, alias/direct resolution, duplicate and unknown references, priority and
weighted selection, health exclusion/recovery, environment and custom secret
resolution, redaction, and custom OpenAI-compatible endpoint metadata. Tests
will not make HTTP calls or import optional framework dependencies.

## Alternatives

Using the draft YAML shape directly would reduce normalization code but make the
existing catalog incompatible and couple the runtime to a configuration shape
that is still evolving. Treating the current YAML as the public schema would
make aliases and deployment routing harder to represent. The normalized schema
with compatibility loaders keeps migration cost localized and preserves the
existing data.
