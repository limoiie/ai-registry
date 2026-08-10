# Use cases

This page shows detailed, real-world ways to use `ai-registry`. Each use case
builds on the [configuration](configuration.md) reference.

## 1. Stable aliases over a changing backend

The core benefit: application code depends on alias names, so the model,
provider, or deployment behind an alias can change without code changes.

```python
# v1: behind "sol" there is DeepSeek
aliases:
  - id: sol
    deployments:
      - profile_id: uniapi-primary
        model_id: deepseek-v4-flash
```

```python
# v2: swap to a local vLLM without touching application code
aliases:
  - id: sol
    deployments:
      - profile_id: local-vllm
        model_id: Qwen/Qwen3-32B
```

```python
resolution = registry.resolve("sol")
```

Application code always calls `registry.resolve("sol")`. Tracing, usage
accounting, and logging can still read `resolution.model_id` and
`resolution.profile_id` to report the canonical identifiers behind the alias.

## 2. Multiple API keys for the same provider

Profile a shared gateway with several keys and let routing balance across them.

```yaml
profiles:
  - id: uniapi-primary
    provider_id: uniapi
    credential: {env: UNIAPI_PRIMARY_KEY}
    enabled_models: [deepseek-v4-flash]
  - id: uniapi-secondary
    provider_id: uniapi
    credential: {env: UNIAPI_SECONDARY_KEY}
    enabled_models: [deepseek-v4-flash]

aliases:
  - id: chat-default
    deployments:
      - profile_id: uniapi-primary
        model_id: deepseek-v4-flash
        routing: {priority: 0, weight: 3}
      - profile_id: uniapi-secondary
        model_id: deepseek-v4-flash
        routing: {priority: 0, weight: 1}
```

Equal priority + weights of `3` and `1` means the primary key handles about
75% of resolutions. Inject a `DeploymentRouter` with a deterministic random
source to test the split.

## 3. Priority-based primary/backup failover

Give the primary deployment a lower `priority` number. It is always selected
while available; the backup is used only when the primary is unhealthy.

```yaml
aliases:
  - id: chat-default
    deployments:
      - profile_id: uniapi-primary
        model_id: deepseek-v4-flash
        routing: {priority: 0, weight: 1}
      - profile_id: local-vllm
        model_id: Qwen/Qwen3-32B
        routing: {priority: 1, weight: 1}
```

With default (healthy) state, `resolve("chat-default")` always returns
`uniapi-primary`. After `mark_failure("chat-default", 0)`, it returns the vLLM
backup.

## 4. Health-aware routing with recovery

`DeploymentHealthStore` and `DeploymentRouter` work together. Health identity is
`(alias_id, candidate_index)`, so it is independent of routing metadata and
works even with duplicate deployments.

```python
from ai_registry import DeploymentHealthStore, DeploymentRouter, Registry

health = DeploymentHealthStore()
router = DeploymentRouter(health)

registry = Registry.from_data(
    providers=[...],
    profiles=[...],
    aliases=[...],
    router=router,
)

# Application adapter reports a failure for candidate 0
health.mark_failure("chat-default", 0)

resolution = registry.resolve("chat-default")  # fails over to backup

# After the deployment recovers, restore it
health.mark_success("chat-default", 0)
```

The health store is separate from static configuration, so marking a failure
or recovery never mutates your YAML-defined config. Unknown health state is
healthy, so the system fails open by default.

## 5. Disabling a deployment or profile

- `routing.enabled: false` removes a deployment from selection permanently.
- `enabled: false` on a profile excludes it from both alias routing and direct
  references.

```yaml
profiles:
  - id: old-key
    provider_id: uniapi
    credential: {env: UNIAPI_OLD_KEY}
    enabled_models: [deepseek-v4-flash]
    enabled: false
```

## 6. Embedding and reranking models

Model cards carry `type`, so chat, embedding, and reranking models coexist and
resolve through the same API. `embedding_dimension` is preserved for adapters.

```python
resolution = registry.resolve("embed-default")
assert resolution.model.type.value == "embedding"
assert resolution.model.embedding_dimension == 1024

resolution = registry.resolve("rerank-default")
assert resolution.model.type.value == "reranking"
```

Direct references work for models that are not aliased:

```python
registry.resolve("uniapi-primary/bge-large-zh:latest")
```

## 7. Custom OpenAI-compatible endpoints (vLLM, gateways)

Profile an internal vLLM server or a gateway. `endpoint` overrides the
provider default, and arbitrary adapter metadata rides along in
`endpoint_metadata`.

```yaml
profiles:
  - id: local-vllm
    provider_id: vllm-local
    endpoint: http://vllm.internal:8000/v1
    credential: {env: VLLM_API_KEY}
    enabled_models: [Qwen/Qwen3-32B]
    metadata:
      provider_name: internal-vllm
      supports_json_mode: true

  - id: gateway
    provider_id: deepseek
    endpoint: https://gateway.example/v1
    credential: {env: GATEWAY_API_KEY}
    enabled_models: [deepseek-chat]
```

```python
resolution = registry.resolve("gateway")
resolution.endpoint  # "https://gateway.example/v1"
resolution.endpoint_metadata  # {"provider_name": ..., "supports_json_mode": ...}
```

Provider `default_base_url` supplies the endpoint when a profile does not set
one.

## 8. Custom secret resolver

Integrate Vault, AWS Secrets Manager, Kubernetes, or a local keyring by
implementing the `SecretResolver` protocol. References use `secret_ref`:

```yaml
profiles:
  - id: production
    provider_id: uniapi
    credential:
      secret_ref: vault://production/ai/uniapi-primary
    enabled_models: [deepseek-v4-flash]
```

```python
# from_files — explicit paths, when you want full control of the files
from ai_registry import Registry
from ai_registry.secrets import SecretResolver


class VaultResolver:
    """Thin example; use a real Vault client."""

    def resolve(self, reference: str) -> str:
        # reference == "vault://production/ai/uniapi-primary"
        token = vault_client.read(reference)
        if not token:
            raise LookupError("missing secret")
        return token


registry = Registry.from_files(
    provider_files=["catalog.yaml"],
    profile_files=["profiles.yaml"],
    alias_files=["aliases.yaml"],
    secret_resolver=VaultResolver(),
)

resolution = registry.resolve("sol")
token = resolution.resolve_credential()  # only now is the secret fetched
```

Resolvers must return a non-empty string. Failures are wrapped in a safe
`SecretResolutionError` that does not expose the underlying exception.

## 9. Direct references as an escape hatch

When no alias matches, `Registry.resolve()` falls back to `profile-id/model-id`.
This is useful for operational tooling and one-off model access:

```python
registry.resolve("uniapi-primary/deepseek-v4-flash")
```

References that are neither an alias nor a `profile/model` pair are rejected
with an actionable error.

## 10. Programmatic construction

You do not have to use files at all. Build `Registry.from_data` from objects or
plain dicts — useful for tests, config systems, or dynamically assembled
configurations.

```python
registry = Registry.from_data(
    providers=[provider],
    profiles=[{"id": "p", "provider_id": "provider", "enabled_models": ["chat"]}],
    aliases=[{"id": "chat", "deployments": [{"profile_id": "p", "model_id": "chat"}]}],
)
```

## 11. Inspecting what was selected

`Resolution` gives adapters everything they need and nothing more:

```python
resolution.provider.id  # provider family
resolution.model.id  # canonical model ID for requests/logging
resolution.profile.id  # which profile/key was used
resolution.endpoint  # base URL
resolution.endpoint_metadata  # adapter-specific settings
```

`str(resolution)` / `repr(resolution)` are redacted, so they are safe to log.

## 12. Connecting to framework adapters (roadmap)

The current release is the core. The intended adapter pattern resolves an alias
and builds a framework-native object from the `Resolution`:

```python
# Conceptual — adapters are not yet shipped.
resolution = registry.resolve("sol")
client = openai_adapter.build_client(resolution)  # AsyncOpenAI / OpenAI
model = pydantic_ai_adapter.chat_model(resolution)  # PydanticAIModel
chat = langchain_adapter.chat_model(resolution)  # BaseChatModel
llm = llama_index_adapter.llm(resolution)  # LLM
embedding = llama_index_adapter.embedding(resolution)  # Embedding
```

Adapters receive the selected deployment and call
`resolution.resolve_credential()` at client construction time. Optional
dependency errors should point at the relevant extra, e.g.
`pip install ai-registry[pydantic-ai]`.

## 13. Project-scoped configuration (`from_project`)

Keep configuration in a `.ai-registry/` directory and let the registry
discover it. The built-in provider catalog ships with the package, so a fresh
project only needs a merged deployments file:

```text
<project-root>/
└── .ai-registry/
    ├── providers/          # OPTIONAL — override or add providers
    └── registry.yaml    # REQUIRED — merged profiles + aliases
```

```yaml
# .ai-registry/registry.yaml
profiles:
  - id: uniapi-primary
    provider_id: uniapi
    credential: {env: UNIAPI_PRIMARY_KEY}
    enabled_models: [deepseek-v4-flash, bge-large-zh:latest]

aliases:
  - id: sol
    deployments:
      - profile_id: uniapi-primary
        model_id: deepseek-v4-flash
```

```python
from ai_registry import Registry

registry = Registry.from_project()  # discovers ./.ai-registry/

resolution = registry.resolve("sol")
```

Override a built-in provider by dropping a file with the same `id` under
`.ai-registry/providers/`; the override replaces the provider entirely, so
omitted fields fall back to schema defaults. Start from
`examples/registry.example.yaml`, and use `Registry.from_files` (use case 8)
when you need explicit path control instead.
