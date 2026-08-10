# AI Registry Package Design

## Context

The application needs to use AI models from multiple providers and deployments
without spreading provider-specific API keys, base URLs, and client construction
through application code.

Current provider integrations commonly require code such as:

```python
OpenAIChatModel(
    "deepseek-v4-flash",
    provider=OpenAIProvider(
        base_url="https://uni-api.example/v1",
        api_key="...",
    ),
)
```

This does not scale when the application has multiple API keys, several
deployments of the same model, self-hosted OpenAI-compatible servers such as
vLLM, model aliases, or multiple client frameworks.

The package described here is a standalone client factory and registry. It
owns model/provider metadata, profile and deployment resolution, credential
resolution, alias resolution, and deployment selection. It does not replace
Pydantic AI, the OpenAI SDK, LangGraph, or LlamaIndex. Those remain native
execution frameworks exposed through optional adapters.

## Goals

- Resolve a logical model alias to one or more configured deployments.
- Construct native clients for the OpenAI SDK, Pydantic AI, LangGraph-compatible
  chat models, and LlamaIndex.
- Support multiple profiles and multiple API keys for identical or different
  providers.
- Support custom providers and arbitrary sets of models.
- Support OpenAI-compatible hosted and self-hosted endpoints, including UniAPI
  and vLLM.
- Keep aliases stable while allowing their underlying models and deployments to
  change in configuration.
- Support priority, weight, and health-aware deployment selection.
- Support optional secret-manager integrations through a pluggable resolver.
- Keep framework dependencies optional through extras.
- Avoid exposing credentials in logs, exceptions, repr output, or serialized
  configuration.

## Non-goals

- Do not define a new unified chat, embedding, or reranking interface.
- Do not import or emulate LiteLLM, Pydantic AI, or other existing
  configuration formats.
- Do not make LiteLLM a required runtime dependency.
- Do not make LangGraph the model abstraction. LangGraph consumes model objects
  supplied by the application.
- Do not provide a gateway or proxy service in the initial package.
- Do not put literal API keys in catalog/profile files by default.

## Package Boundaries

The base package must remain framework-independent and contain only:

- Pydantic schemas
- YAML/JSON loading
- Provider, model, profile, deployment, and alias validation
- Credential reference resolution
- Alias and direct-reference resolution
- Deployment selection policies
- Health state and routing metadata
- Common package errors

Optional adapters construct framework-native objects:

- `openai`: OpenAI `AsyncOpenAI` and/or `OpenAI` clients
- `pydantic-ai`: Pydantic AI `Model` objects
- `langgraph`: LangChain `BaseChatModel` objects usable by LangGraph
- `llama-index`: LlamaIndex LLM and embedding objects

LangGraph has no separate model-client abstraction. Its adapter therefore
returns the native LangChain model object that a LangGraph graph consumes.

## Optional Dependencies

Suggested extras:

```toml
[project.optional-dependencies]
openai = ["openai"]
pydantic-ai = ["pydantic-ai"]
langgraph = ["langgraph", "langchain-openai"]
llama-index = [
    "llama-index-core",
    "llama-index-llms-openai-like",
    "llama-index-embeddings-openai-like",
]
all = [
    "ai-registry[openai,pydantic-ai,langgraph,llama-index]",
]
```

The package should not import optional frameworks at module import time. An
adapter should raise an actionable error when its dependency is unavailable,
including the relevant installation command.

## Core Concepts

### Provider

A provider describes a provider family or endpoint type and its model catalog.
It contains metadata and safe defaults, not secrets.

Example fields:

- `provider_id`
- `name`
- `sdk_type`
- `default_base_url`
- model cards
- provider-specific adapter settings

The initial implementation should prioritize `sdk_type: openai`, allowing
OpenAI, UniAPI, vLLM, gateways, and other OpenAI-compatible services to use the
same adapter path. Native provider adapters can be added later.

### Model Card

A model card describes a model independently of a deployment:

- Canonical model ID
- Display name and description
- Model type: chat, embedding, or reranking
- Context and output limits
- Embedding dimension
- Pricing metadata
- Capability metadata such as tools, structured output, vision, and reasoning
- Framework-specific compatibility/profile overrides where required

### Profile / Deployment

A profile is a named deployment configuration. It binds a provider to an
endpoint and credentials and enables a set of models.

Multiple profiles may point to the same provider and model while using
different API keys or base URLs.

Example:

```yaml
profiles:
  uniapi-primary:
    provider: uniapi
    api_key:
      env: UNIAPI_PRIMARY_KEY
    models:
      - deepseek-v4-flash

  uniapi-secondary:
    provider: uniapi
    api_key:
      env: UNIAPI_SECONDARY_KEY
    models:
      - deepseek-v4-flash

  local-vllm:
    provider: vllm-local
    base_url: http://vllm.internal:8000/v1
    api_key:
      env: VLLM_API_KEY
    models:
      - Qwen/Qwen3-32B
```

Profiles should support priority, weight, availability, timeout, and
adapter-specific settings for routing.

### Global Alias

Aliases are the primary public API. They are global logical model names and
are not scoped to a profile.

An alias points to one or more profile/model deployments:

```yaml
aliases:
  sol:
    deployments:
      - profile: uniapi-primary
        model: deepseek-v4-flash
      - profile: uniapi-secondary
        model: deepseek-v4-flash
      - profile: local-vllm
        model: Qwen/Qwen3-32B

  ter:
    deployments:
      - profile: uniapi-primary
        model: qwen3.5
      - profile: local-vllm
        model: Qwen/Qwen3-32B
```

Application code uses stable aliases:

```python
registry.openai.client("sol")
registry.pydantic_ai.chat("ter")
registry.langgraph.chat_model("luna")
registry.llama_index.embedding("embedding-default")
```

Changing the model or provider behind `sol` must not require application code
changes.

The explicit `profile/model` form is an escape hatch only when no alias with
that name exists:

```python
registry.openai.client("uniapi-primary/deepseek-v4-flash")
```

Resolution order:

1. Try the complete input as a global alias.
2. If no alias exists, parse it as `profile-id/model-id`.
3. Reject unknown references with an actionable error.

Canonical model IDs remain available for provider requests, logging, tracing,
usage accounting, and configuration migration even when callers use aliases.

## Public API

The intended entry point is:

```python
from ai_registry import Registry

registry = Registry.from_files(
    catalog="catalog.yaml",
    profiles="profiles.yaml",
    secrets=secret_resolver,
)

openai_client = registry.openai.client("sol")
pydantic_model = registry.pydantic_ai.chat("ter")
langgraph_model = registry.langgraph.chat_model("luna")
llama_index_llm = registry.llama_index.llm("sol")
llama_index_embedding = registry.llama_index.embedding("embedding-default")
```

The exact synchronous/asynchronous client methods may be split explicitly if
the target frameworks require it, but the logical model argument must remain
the same across adapters.

## Credential Resolution

Profiles contain references rather than secret values:

```yaml
api_key:
  env: UNIAPI_PRIMARY_KEY
```

The package provides an environment resolver. It also accepts a protocol for
external secret systems:

```python
class SecretResolver(Protocol):
    def resolve(self, reference: str) -> str: ...
```

Example:

```yaml
api_key:
  secret_ref: vault://production/ai/uniapi-primary
```

Vault, AWS Secrets Manager, Kubernetes, and similar integrations should be
separate optional packages or application-provided implementations.

Literal keys should be rejected or explicitly disabled by default. Secret
references and resolved values must never appear in logs, repr output, or
errors.

## Adapter Behavior

Native framework clients are returned. The registry does not expose a common
cross-framework response abstraction.

### OpenAI SDK

The adapter constructs an OpenAI client bound to one selected deployment:

- `base_url`
- resolved API key
- model is supplied to request methods by the caller or through a small model
  binding helper if needed

Because an OpenAI client is endpoint-bound, the initial adapter performs
deployment selection when the client is created.

### Pydantic AI

The adapter constructs a native Pydantic AI model using the provider and model
appropriate to the resolved deployment. For OpenAI-compatible endpoints this
uses `OpenAIProvider(base_url=..., api_key=...)` and `OpenAIChatModel`.

Where Pydantic AI supports a compatible fallback model, the adapter may build a
fallback chain. Generic weighted request-time routing is not required for the
first release.

### LangGraph

The adapter returns a native LangChain chat model usable as a LangGraph node.
The first implementation can use `ChatOpenAI` with the resolved base URL and
API key for OpenAI-compatible deployments.

### LlamaIndex

The adapter returns native LlamaIndex LLM and embedding objects, using the
OpenAI-like integrations for OpenAI-compatible endpoints. Reranking support
may be added after chat and embeddings if the selected LlamaIndex integration
does not provide an adequate native adapter.

## Routing and Failover

An alias can contain multiple deployments. Deployment selection should support:

- Priority ordering
- Weighted selection
- Disabled/unavailable deployments
- Health state
- Adapter-specific timeout and retry metadata

Native clients are generally bound to one endpoint. Therefore:

- OpenAI, Pydantic AI, LangChain/LangGraph, and LlamaIndex adapters initially
  select one deployment at client creation time.
- LiteLLM is not an initial required adapter, but its native `Router` can be
  added later and naturally supports request-time routing across deployments.
- Generic request-time failover across every framework would require a custom
  wrapper or proxy and is outside the first release.

The registry should make the selected deployment observable without exposing
credentials.

## Validation and Errors

Load-time validation should detect:

- Duplicate provider, profile, or alias IDs
- Unknown providers
- Unknown models
- Models not enabled by a profile
- Invalid alias deployments
- Invalid routing metadata
- Unsupported provider SDK types

Credential existence may be validated lazily when a deployment is resolved, or
eagerly through an explicit validation operation.

Errors should identify the logical alias/profile/model and the required
remediation. They must not include API keys or resolved secret values.

Missing optional dependencies should identify the adapter and installation
extra, for example `pip install ai-registry[pydantic-ai]`.

## Testing Requirements

The first release should test:

- YAML parsing and Pydantic schema validation
- Global alias resolution
- Explicit `profile/model` fallback resolution
- Multiple deployments for one alias
- Priority and weighted deployment selection
- Health-aware exclusion and recovery
- Environment secret resolution
- Custom secret resolver behavior
- Optional dependency error messages
- Native client construction for every adapter
- Custom OpenAI-compatible endpoints
- UniAPI and vLLM-style configurations
- Provider/model capability validation
- No secret leakage in errors, repr output, or logs

HTTP calls should be mocked in unit tests. Integration tests against real
providers should be optional and separately configured.

## Recommended Initial Scope

Implement the following first:

1. Core Pydantic schemas and YAML loading.
2. Environment and pluggable secret resolution.
3. Provider/profile/model/alias validation.
4. Alias-first and direct-reference resolution.
5. Priority/weight/health-aware deployment selection.
6. OpenAI SDK adapter.
7. Pydantic AI adapter.
8. LangGraph-compatible LangChain adapter.
9. LlamaIndex LLM and embedding adapters.
10. Documentation and mocked adapter tests.

The package should initially focus on OpenAI-compatible providers. Native
Anthropic, Cohere, Gemini, and other provider adapters can be added later
without changing the registry, profile, alias, or credential model.

## Alternatives Considered

### LiteLLM-centered

LiteLLM Router provides strong deployment routing, retries, aliases, and
failover. It is useful as an optional adapter or future gateway integration,
but making it the core would couple the package to LiteLLM’s runtime and
configuration model.

### Framework-specific registries

Having each adapter independently resolve profiles would duplicate validation,
secret loading, routing, and health behavior. This is rejected.

### Unified response abstraction

A package-owned response interface would duplicate existing framework APIs and
make native integration less useful. This is rejected.
