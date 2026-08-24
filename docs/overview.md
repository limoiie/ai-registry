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
- account and deployment resolution,
- credential resolution,
- alias resolution,
- and health-aware deployment selection.

It resolves a **logical alias** to a **concrete deployment** and hands your
application everything an adapter needs to build a native client:

```python
from ai_registry import Registry

registry = Registry.from_files(
    provider_files=["catalog.yaml"],
    account_files=["accounts.yaml"],
    alias_files=["aliases.yaml"],
    secret_resolver=secret_resolver,
)

resolution = registry.resolve("sol")

resolution.account_id  # -> "uniapi-primary"
resolution.model_id  # -> "deepseek-v4-flash"
resolution.endpoint  # -> "https://uni-api.cstcloud.cn/v1"
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
| **Account** | A named deployment configuration: binds a provider to an endpoint and a credential reference, and enables a set of models. |
| **Alias** | A global, stable logical model name pointing to one or more account/model deployments. |
| **Deployment** | A single `account_id` + `model_id` pair inside an alias, with routing metadata (priority, weight, enabled). |
| **Credential reference** | A pointer to a secret — an environment variable name or an external `secret_ref` — never a literal key. |
| **Resolution** | The safe result of looking up an alias or direct reference: provider, model, account, endpoint, and metadata. |

## How resolution works

`Registry.resolve()` follows this order:

1. **Try the complete input as a global alias.** If an alias with that name
   exists, the deployment router picks one eligible deployment from it.
2. **Otherwise parse it as `account-id/model-id`.** This explicit form is an
   escape hatch only when no alias with that name exists.
3. **Reject unknown references** with an actionable error that never echoes the
   caller's input or any secret.

For example:

```python
registry.resolve("sol")  # alias-first
registry.resolve("uniapi-primary/deepseek-v4-flash")  # explicit fallback
```

## Provider scope and project layout

Providers come from two scopes, merged by provider `id`:

- **Built-in** — the catalog shipped with the package at
  `ai_registry/data/providers/*.yml` (`deepseek`, `uniapi`, `minimax`,
  `openai`, `anthropic`, `gemini`, `moonshot`, `zhipu`,
  `qwen`, `xai`). It is available in every project with no configuration.
- **Project** — optional files under `<project-root>/.ai-registry/providers/`
  (`.yaml`, `.yml`, or `.json`). A project provider with the same `id`
  replaces the built-in provider **entirely**; unique ids add to the catalog.
  There is no field-level merge.

Accounts and aliases are configured in one merged file:

```text
<project-root>/
└── .ai-registry/
    ├── providers/          # OPTIONAL — override or add providers
    ├── registry.yaml    # default — used when no profile requested
    ├── registry.dev.yaml   # OPTIONAL — profile "dev"
    └── registry.prod.yaml  # OPTIONAL — profile "prod"
```

`Registry.from_project(root)` discovers both scopes and loads
`.ai-registry/registry.yaml`, then validates the whole graph with the same
rules as `from_files`/`from_data`. Start from
`examples/registry.example.yaml` when creating the file. Pass `profile="prod"`
(or set `AI_REGISTRY_PROFILE`) to load `registry.prod.yaml` instead; a
requested but missing profile file raises rather than falling back to the
default.

## What it is not

`ai-registry` deliberately does not replace the frameworks:

- It does **not** define a new unified chat, embedding, or reranking interface.
- It does **not** make requests, translate requests, or retry them.
- It does **not** import or emulate LiteLLM, Pydantic AI, or their
  configuration formats.
- It does **not** ship a gateway or proxy service.
- It does **not** put literal API keys in configuration files.

Framework adapters are the intended consumers of a `Resolution`. The OpenAI SDK,
Pydantic AI, and LangChain adapters ship as optional extras
(`ai_registry.adapters.openai`, `ai_registry.adapters.pydantic_ai`,
`ai_registry.adapters.langchain`); LangGraph coverage comes through LangChain
models. LlamaIndex is not covered yet, and `client_kwargs()` gives you what you
need to write your own in a few lines.

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
5. **Built-in catalog, project overrides.** The provider catalog ships with
   the package; project providers under `.ai-registry/providers/` replace
   built-ins by id, and accounts and aliases live in one merged
   `.ai-registry/registry.yaml`. Legacy catalog and account formats still
   load and normalize without migration.
6. **Profile-based selection.** `registry.<profile>.yaml` files are chosen by an
   explicit `profile=` argument or the `AI_REGISTRY_PROFILE` environment
   variable, with a safe default and no silent fallback when a requested
   profile file is missing.

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
                     +------------+------------+------------+
                     v            v            v            v
              OpenAI SDK   Pydantic AI   LangChain / LangGraph   LlamaIndex
              [openai]     [pydantic-ai] [langchain]             (your own adapter)
```

Adapters are optional extras under `ai_registry.adapters`. The core never
imports them, so `pip install ai-registry` still resolves to six packages.

The core modules are:

| Module | Responsibility |
| --- | --- |
| `ai_registry.schemas` | Pydantic models, validation, safe serialization. |
| `ai_registry.config` | YAML/JSON readers and compatibility normalization. |
| `ai_registry.secrets` | Credential reference resolution (env + pluggable resolver). |
| `ai_registry.registry` | `Registry` construction and alias/direct resolution. |
| `ai_registry.routing` | Priority/weight/health-aware deployment selection. |
| `ai_registry.errors` | Stable, actionable exception types. |
| `ai_registry.catalog` | Import third-party catalogs (models.dev) into the provider schema. |
| `ai_registry.testing` | Supported test doubles for consumers. |
| `ai_registry.cli` | Optional command line interface (`cli` extra). |
| `ai_registry.adapters.*` | Optional framework adapters (`openai`, `pydantic-ai`, `langchain` extras). |

## Current status

- The framework-independent core described above is complete: schemas, loaders,
  secret references, resolution, deployment selection with time-based recovery,
  the built-in catalog, and project scopes with profiles.
- OpenAI SDK, Pydantic AI, and LangChain adapters ship as optional extras,
  alongside an optional CLI and a models.dev catalog importer.
- The focus is OpenAI-compatible providers (`sdk_type: openai`, including
  UniAPI, vLLM, and gateways) plus native Anthropic. Cohere, Gemini, and others
  can be added without changing the registry, account, alias, or credential
  model.
- Not covered yet: LlamaIndex adapter, request-time concerns (retries, request
  translation, spend tracking), and any form of context-aware selection that
  would require inspecting the request.
- While the version is `0.x`, minor releases may contain breaking changes; see
  the [changelog](changelog.md).
