# Overview

## The problem

Applications that use AI models typically accumulate provider-specific
boilerplate. Every call site needs to know:

- which provider or gateway to talk to,
- the base URL and API key,
- the exact model identifier,
- and how to construct the framework-native client (OpenAI SDK, Pydantic AI,
  LangChain/LangGraph, LlamaIndex, and so on).

When an application has multiple API keys, several deployments of the same
model, self-hosted OpenAI-compatible servers such as vLLM, model aliases, or
multiple client frameworks, that boilerplate stops scaling. Changing a model or
provider requires touching application code everywhere it is used.

A typical integration looks like this today:

```python
OpenAIChatModel(
    "deepseek-v4-flash",
    provider=OpenAIProvider(
        base_url="https://uni-api.example/v1",
        api_key="...",
    ),
)
```

## What `ai-registry` provides

`ai-registry` is a **standalone, framework-independent client factory and
registry**. It owns the parts of integration that are common to every
framework:

- provider and model metadata,
- profile and deployment resolution,
- credential resolution,
- alias resolution,
- and health-aware deployment selection.

It resolves a **logical alias** to a **concrete deployment** and hands your
application everything an adapter needs to build a native client:

```python
from ai_registry import Registry

registry = Registry.from_files(
    provider_files=["catalog.yaml"],
    profile_files=["profiles.yaml"],
    alias_files=["aliases.yaml"],
    secret_resolver=secret_resolver,
)

resolution = registry.resolve("sol")

resolution.profile_id        # -> "uniapi-primary"
resolution.model_id          # -> "deepseek-v4-flash"
resolution.endpoint          # -> "https://uni-api.cstcloud.cn/v1"
resolution.resolve_credential()  # -> resolves the key lazily
```

Your application code refers to stable aliases (`"sol"`, `"ter"`, `"luna"`).
The model, provider, or deployment behind an alias can change in configuration
without any application code changes.

## Core concepts

| Concept | Role |
| --- | --- |
| **Provider** | A provider family or endpoint type plus its model catalog. Contains metadata and safe defaults, never secrets. |
| **Model card** | Describes one model independently of any deployment: type, context limits, capabilities, pricing, embedding dimension. |
| **Profile** | A named deployment configuration: binds a provider to an endpoint and a credential reference, and enables a set of models. |
| **Alias** | A global, stable logical model name pointing to one or more profile/model deployments. |
| **Deployment** | A single `profile_id` + `model_id` pair inside an alias, with routing metadata (priority, weight, enabled). |
| **Credential reference** | A pointer to a secret — an environment variable name or an external `secret_ref` — never a literal key. |
| **Resolution** | The safe result of looking up an alias or direct reference: provider, model, profile, endpoint, and metadata. |

## How resolution works

`Registry.resolve()` follows this order:

1. **Try the complete input as a global alias.** If an alias with that name
   exists, the deployment router picks one eligible deployment from it.
2. **Otherwise parse it as `profile-id/model-id`.** This explicit form is an
   escape hatch only when no alias with that name exists.
3. **Reject unknown references** with an actionable error that never echoes the
   caller's input or any secret.

For example:

```python
registry.resolve("sol")                       # alias-first
registry.resolve("uniapi-primary/deepseek-v4-flash")  # explicit fallback
```

## What it is not

`ai-registry` deliberately does not replace the frameworks:

- It does **not** define a new unified chat, embedding, or reranking interface.
- It does **not** make requests, translate requests, or retry them.
- It does **not** import or emulate LiteLLM, Pydantic AI, or their
  configuration formats.
- It does **not** ship a gateway or proxy service.
- It does **not** put literal API keys in configuration files.

Framework adapters (OpenAI SDK, Pydantic AI, LangGraph, LlamaIndex) are the
intended consumers of a `Resolution` and will be delivered as optional
dependencies. The current release is the framework-independent core that those
adapters are built on.

## Design principles

1. **Framework-independent core.** The base package only depends on Pydantic
   and PyYAML. Optional adapters are separate extras and are never imported at
   module import time.
2. **Aliases are the public contract.** Application code depends on stable
   names, not on any particular provider or model ID.
3. **Secrets stay referenced, not stored.** Configuration contains
   `env:`/`secret_ref:` references. Resolved values exist only transiently at
   the adapter boundary and are excluded from logs, repr output, exceptions,
   and serialized configuration.
4. **Static config stays immutable.** Health state and runtime selection live
   in separate stores so routing never mutates your configuration.
5. **Compatibility-first loading.** The existing `data/ai/providers/*.yml`
   catalog and profile formats load and normalize without migration.

## Architecture

```text
            +---------------------------------------------------+
            |                    ai_registry                    |
            |                                                   |
  YAML/JSON |  config.py  ->  schemas.py (SafeModel)            |
 ---------->|       |                  |                         |
            |       v                  v                         |
            |  normalize  ->  validated objects -> Registry      |
            |                          |                         |
  secrets   |  secrets.py              |   registry.resolve()    |
 ---------->|  env / SecretResolver    |        |                |
            |                          |        v                |
            |                          |   routing.py            |
            |                          |   (health-aware select) |
            |                          |        |                |
            |                          v        v                |
            |                     Resolution (safe, isolated)    |
            +---------------------------------------------------+
                                  |
                     +------------+------------+
                     v            v            v
                OpenAI SDK   Pydantic AI   LangGraph / LlamaIndex
                (future)     (future)      (future optional adapters)
```

The core modules are:

| Module | Responsibility |
| --- | --- |
| `ai_registry.schemas` | Pydantic models, validation, safe serialization. |
| `ai_registry.config` | YAML/JSON readers and compatibility normalization. |
| `ai_registry.secrets` | Credential reference resolution (env + pluggable resolver). |
| `ai_registry.registry` | `Registry` construction and alias/direct resolution. |
| `ai_registry.routing` | Priority/weight/health-aware deployment selection. |
| `ai_registry.errors` | Stable, actionable exception types. |

## Current status

- Version `0.1.0` provides the framework-independent core described above.
- The initial focus is OpenAI-compatible providers (`sdk_type: openai`,
  including UniAPI, vLLM, and gateways). Native Anthropic, Cohere, Gemini, and
  other provider adapters can be added later without changing the registry,
  profile, alias, or credential model.
- OpenAI SDK, Pydantic AI, LangGraph, and LlamaIndex adapters are planned as
  optional extras on top of this core.
