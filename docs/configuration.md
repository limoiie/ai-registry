# Configuration

This reference documents every data format `ai-registry` understands: the
**normalized** shape (recommended) and the **legacy compatibility** shape used
by the built-in provider catalog shipped at `ai_registry/data/providers/*.yml`.

## Document types

Configuration is plain YAML or JSON. There are four document kinds:

| Document | Contents | Loaded by |
| --- | --- | --- |
| Provider document | **One provider mapping** per file. | `load_provider_file`, `load_provider_files`, `Registry.from_files(provider_files=...)`, `Registry.from_project` |
| Account document | A top-level `accounts` list. | `load_account_file`, `Registry.from_files(account_files=...)` |
| Alias document | A top-level `aliases` list. | `load_alias_file`, `Registry.from_files(alias_files=...)` |
| Deployments document | A top-level `accounts` list plus optional `aliases` list. | `load_deployments_file`, `Registry.from_project` |

Notes:

- **Providers are one-per-file.** `Registry.from_files` treats each entry of
  `provider_files` as a single provider document (see below). To use several
  providers, list several files. Account and alias files, by contrast, contain
  lists of many entries.
- Account and alias documents can be the same file when it contains both lists;
  that is exactly the merged deployments document (see
  [Project layout](#project-layout)).
- A file shaped like `providers: [...]` is **not** accepted directly by
  `load_provider_file`/`from_files`. Either split it into one file per provider,
  or iterate it with `normalize_provider()` and build the registry with
  `Registry.from_data`.

The loader accepts a file path (`str` or `pathlib.Path`) or any text stream
(`io.StringIO`, open file). Format is chosen by suffix: `.json` parses as JSON;
`.yaml`, `.yml`, and unnamed streams parse as YAML.

No secrets are resolved while loading. Credential references are validated for
shape but resolved lazily at the adapter boundary.

## Project layout

Projects keep configuration under a `.ai-registry/` directory:

```text
<project-root>/
└── .ai-registry/
    ├── providers/          # OPTIONAL — override or add providers
    └── registry.yaml    # default — merged accounts + aliases (no profile)
```

- `registry.yaml` is the default registry file, used when no profile is
  requested. It is a single document with a required `accounts` list and an
  optional `aliases` list (see [Registry file](#registry-file)). Profile-named
  files (`registry.<env>.yaml`) follow the same shape; see
  [Profile selection](#profile-selection).
- `providers/` holds project provider documents (one provider per file, any of
  `.yaml`, `.yml`, `.json`). When the directory is missing, only the built-in
  catalog is used.
- `Registry.from_project(root)` discovers both, merges the providers, and
  loads `registry.yaml` with the same validation as the explicit loaders.

### Profile selection

`Registry.from_project` can select among several registry files by **profile**
(typically one per environment or tenant). The active file is named
`registry.<profile>.yaml` (or `.yml`/`.json`) instead of the default
`registry.yaml`:

```text
<project-root>/
└── .ai-registry/
    ├── providers/           # OPTIONAL — override or add providers
    ├── registry.yaml        # default (no profile)
    ├── registry.dev.yaml    # profile "dev"
    └── registry.prod.yaml   # profile "prod"
```

The profile is chosen by precedence — the first that applies wins:

1. **Explicit argument** — `Registry.from_project(root, profile="prod")`.
2. **Environment variable** — `AI_REGISTRY_PROFILE` set to the profile name.
3. **Default** — no profile, so `registry.yaml` (or `.yml`/`.json`).

An explicit `profile=` always overrides the environment variable. Profile names
are restricted to `[A-Za-z0-9_-]`; anything else (including path separators and
`.`/`..`) is rejected with a `ConfigurationError`.

**There is no silent fallback.** Once a profile is requested — by argument or
environment variable — the matching file must exist. If
`registry.<profile>.yaml`/`.yml`/`.json` is missing, `from_project` raises a
`ConfigurationError` naming the expected file; it never falls back to the
default `registry.yaml`. The default is only used when no profile is requested
at all. An empty or blank profile (an empty `profile=` value or an unset/empty
`AI_REGISTRY_PROFILE`) is treated as "no profile" and selects the default
rather than being rejected.

### Provider scope and override

Providers come from two scopes and are merged by `id`:

- **Built-in** — `deepseek`, `uniapi`, `minimax`, `uniapi-rerankers` ship with
  the package as package data at `ai_registry/data/providers/*.yml`.
- **Project** — files under `.ai-registry/providers/`.

A project provider with the same `id` **replaces the built-in provider
entirely** — there is no deep merge, so fields omitted from the override fall
back to schema defaults, not to the built-in values. Unique ids are added to
the catalog, and duplicate project ids are rejected.

## Provider

A provider describes a provider family or endpoint type and its model catalog.
It contains metadata and safe defaults, never secrets.

### Normalized form

```yaml
id: uniapi
name: Uni API
description: OpenAI-compatible gateway
sdk_type: openai            # openai | anthropic | google | custom
default_base_url: https://uni-api.cstcloud.cn/v1
settings:
  region: cn-east
model_cards:
  - id: deepseek-v4-flash
    type: chat
```

### Field reference

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | identifier | yes | `[A-Za-z0-9_.-]`, no spaces. |
| `name` | string | yes | Display name. |
| `description` | string | no | Free text. |
| `sdk_type` | enum | no | `openai` (default), `anthropic`, `google`, `custom`. |
| `default_base_url` | URL string | no | Validated endpoint (see [Endpoint validation](#endpoint-validation)). |
| `settings` | mapping | no | Provider-specific adapter settings; forwarded as-is. |
| `model_cards` | list | no | The provider's model catalog. |

### SDK types

`ai-registry` is provider-adapter-agnostic at the core. The current release
focuses on OpenAI-compatible endpoints, but the schema records the SDK family
so adapters can be chosen later:

| Value | Meaning |
| --- | --- |
| `openai` | OpenAI-compatible: OpenAI, UniAPI, vLLM, gateways. |
| `anthropic` | Anthropic-compatible endpoints. |
| `google` | Gemini/Google endpoints. |
| `custom` | Anything else; adapter-specific handling. |

### Model cards

A model card describes a model independently of any deployment.

```yaml
model_cards:
  - id: deepseek-v4-flash
    display_name: DeepSeek V4 Flash
    type: chat                    # chat | embedding | reranking
    description: Fast, cost-effective MoE model.
    released_at: "2026-04-24"
    context_window_tokens: 1000000
    max_output_tokens: 384000
    capabilities:
      tools: true
      structured_output: true
      reasoning: true
      vision: false
    metadata:
      notes: internal
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | model id | yes | The canonical model identifier. May contain `- _ . : /`, no whitespace (e.g. `bge-large-zh:latest`, `Qwen/Qwen3-32B`). |
| `type` | enum | yes | `chat`, `embedding`, or `reranking`. |
| `display_name` | string | no | Human-friendly name. |
| `description` | string | no | Free text. |
| `released_at` | date | no | ISO `YYYY-MM-DD`. |
| `context_window_tokens` | positive int | no | Context limit. |
| `max_output_tokens` | positive int | no | Output limit. |
| `embedding_dimension` | positive int | no | For embedding models. |
| `capabilities` | mapping | no | Also accepted as `abilities` (see [legacy compatibility](#provider-catalog-compatibility)). |
| `metadata` | mapping | no | Arbitrary adapter metadata. |

`capabilities` supports the keys `tools`, `structured_output`, `vision`, and
`reasoning` (all optional booleans, default `false`).

## Registry file

`registry.yaml` merges accounts and aliases into one document:

```yaml
accounts:
  - id: uniapi-primary
    provider_id: uniapi
    credential: {env: UNIAPI_PRIMARY_KEY}
    enabled_models: [deepseek-v4-flash]

aliases:
  - id: sol
    deployments:
      - account_id: uniapi-primary
        model_id: deepseek-v4-flash
```

`accounts` is required; `aliases` is optional and defaults to empty. Legacy
account fields (`api_key_env`, `remark`, `description`) are normalized inside
this file exactly as in a standalone account document. Loaded by
`load_deployments_file` and `Registry.from_project`.

## Account

An account is a named deployment configuration. It binds a provider to an
endpoint and a credential reference, and enables a set of models. Multiple
accounts may point to the same provider and model with different API keys or
base URLs.

### Normalized form

```yaml
accounts:
  - id: uniapi-primary
    provider_id: uniapi
    endpoint: https://uni-api.cstcloud.cn/v1   # optional override
    credential:
      env: UNIAPI_PRIMARY_KEY
    enabled_models:
      - deepseek-v4-flash
    enabled: true
    timeout_seconds: 30
    metadata:
      owner: platform
```

### Field reference

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | identifier | yes | Unique across accounts. |
| `provider_id` | identifier | yes | Must reference a configured provider. |
| `endpoint` | URL string | no | Overrides the provider `default_base_url`. Also accepted as `base_url`. |
| `credential` | credential ref | no | Exactly one of `env` or `secret_ref` (see [Credentials](#credentials)). Also accepted as `api_key` for the shape, but literal keys are rejected. |
| `enabled_models` | list of model ids | no | The models this account exposes. Resolution rejects models not listed here. |
| `enabled` | bool | no | Default `true`. Disabled accounts are excluded from aliases and direct resolution. |
| `timeout_seconds` | positive number | no | Adapter-facing metadata. |
| `metadata` | mapping | no | Arbitrary adapter metadata, e.g. `provider_name`, `supports_json_mode`. |

## Alias

Aliases are the primary public API. They are **global** logical model names and
are not scoped to an account. An alias points to one or more account/model
deployments; the router selects one when the alias is resolved.

```yaml
aliases:
  - id: sol
    deployments:
      - account_id: uniapi-primary
        model_id: deepseek-v4-flash
        routing:
          priority: 0
          weight: 3
      - account_id: uniapi-secondary
        model_id: deepseek-v4-flash
        routing:
          priority: 1
          weight: 1
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | identifier | yes | Unique across aliases. |
| `deployments` | list | yes | At least one deployment. |

### Deployment

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `account_id` | identifier | yes | Also accepted as `account`. |
| `model_id` | model id | yes | Also accepted as `model`. |
| `routing` | routing metadata | no | Defaults to priority `0`, weight `1`, enabled `true`. |

### Routing metadata

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `priority` | non-negative int | `0` | Lower values are tried first. |
| `weight` | positive int | `1` | Relative weight among equal-priority deployments. |
| `enabled` | bool | `true` | `false` permanently excludes the deployment. |
| `timeout_seconds` | positive number | none | Adapter-facing metadata. |

## Credentials

Accounts contain **references** rather than secret values:

```yaml
credential:
  env: UNIAPI_PRIMARY_KEY
```

or, for an external secret system:

```yaml
credential:
  secret_ref: vault://production/ai/uniapi-primary
```

| Field | Constraints |
| --- | --- |
| `env` | Exactly one of `env`/`secret_ref` must be set. The value names a process environment variable. |
| `secret_ref` | Resolved by an application-provided `SecretResolver` (Vault, AWS Secrets Manager, Kubernetes, ...). |
| `api_key` | Schema field exists for shape compatibility but **literal API keys are always rejected**. |

### String shorthands

A credential may also be written as a single string. These are all equivalent to
`{env: UNIAPI_PRIMARY_KEY}`:

```yaml
credential: env:UNIAPI_PRIMARY_KEY        # canonical shorthand
credential: env.UNIAPI_PRIMARY_KEY        # BAML / Bifrost spelling
credential: ${env:UNIAPI_PRIMARY_KEY}     # VS Code / MCP spelling
credential: ${UNIAPI_PRIMARY_KEY}         # Docker Compose spelling
credential: os.environ/UNIAPI_PRIMARY_KEY # LiteLLM spelling
```

External references use `secret_ref:REF` or `${secret_ref:REF}`.

The point of accepting several spellings is to remove a migration papercut, not
to weaken the rule: a string that matches none of these prefixes is treated as a
literal key and rejected. The error never echoes the value.

```yaml
credential: sk-live-abcdef   # ConfigurationError: literal API keys are rejected
```

Empty `env` or `secret_ref` strings are invalid. Missing or empty environment
variables and empty resolver results raise a safe `SecretResolutionError` at
resolution time. See [Security](security.md).

## Endpoint validation

`default_base_url` (provider) and `endpoint`/`base_url` (account) are validated
at load time. The following are rejected:

- URLs with userinfo, e.g. `https://user:pass@host/v1`;
- query or fragment parameters whose names look credential-bearing, e.g.
  `?api_key=...`, `?access_token=...`, `?x-api-key=...`,
  `?aws_access_key_id=...`, `?connection_string=...` — including `;` as an
  additional separator (`?x=y;api_key=...`);
- empty query parameter names, e.g. `?=x`.

Use a `credential` reference instead of embedding secrets in URLs.

## Validation rules

`Registry` construction validates the whole configuration graph:

- **Duplicate IDs** are rejected: provider IDs, account IDs, alias IDs, and
  model-card IDs within a provider.
- **Unknown providers**: every account `provider_id` must exist.
- **Unknown models**: every `enabled_models` entry and every alias deployment
  `model_id` must exist in the referenced provider's catalog.
- **Models not enabled**: resolution rejects a model that is not listed in the
  account's `enabled_models`.
- **Invalid alias deployments**: alias deployments must reference existing
  accounts and enabled models.
- **Unsupported SDK types**: values outside `openai`/`anthropic`/`google`/`custom`
  are rejected.
- **Invalid routing metadata**: negative priority, zero weight, and so on are
  rejected.

These checks run when the `Registry` is constructed, so mistakes fail fast
instead of at request time.

## Legacy compatibility format

The built-in provider catalog (`ai_registry/data/providers/*.yml`) and legacy
account documents use an older shape. The loader normalizes it to the schema
above automatically. **New configuration should prefer the normalized shape.**

### Provider catalog compatibility

```yaml
id: uniapi
name: Uni API
description: OpenAI-compatible gateway
url: https://www.cstcloud.cn        # moved into settings.url
check_model: deepseek-r1:32b        # moved into settings.check_model
models_url: https://uni-api.cstcloud.cn/doc/llm/models  # moved into settings.models_url
settings:
  sdk_type: openai
  show_model_fetcher: true
model_cards:
  - id: deepseek-r1:32b
    type: chat
    abilities:                       # mapped to capabilities
      function_call: true
      reasoning: true
    pricing: {...}                   # preserved in metadata.pricing
    deprecated: true                 # preserved in metadata.deprecated
    max_dimension: 1024              # mapped to embedding_dimension + metadata.max_dimension
```

Normalization rules:

- `url`, `check_model`, `models_url` are copied into `settings`.
- `sdk_type` may appear at top level or inside `settings`. Legacy `uniapi` is
  normalized to `openai`. Conflicting `sdk_type` declarations are rejected.
- `abilities` maps known capability keys (`reasoning`, `structured_output`,
  `vision`, `tools`) to `capabilities`; `function_call` is preserved in
  metadata for adapter use.
- `pricing`, `deprecated`, `settings`, and leftover `abilities` are preserved
  under `metadata`.
- `max_dimension` maps to `embedding_dimension`.
- A `context_window_tokens` of `0` (unknown) is recorded in metadata and the
  schema field is left unset.

### Account compatibility

```yaml
accounts:
  - id: builtin-uniapi
    provider_id: uniapi
    remark: builtin                     # preserved in metadata.remark
    description: Built-in Uni API account  # preserved in metadata.description
    api_key_env: UNIAPI_API_KEY         # converted to credential: {env: UNIAPI_API_KEY}
    enabled_models:
      - deepseek-v4-flash
```

Normalization rules:

- `api_key_env` is converted to `credential: {env: NAME}`.
- Defining both `api_key_env` and `credential` is rejected.
- `remark` and `description` are preserved under `metadata`.
- Any explicit `metadata` mapping is preserved.

## Putting it all together

A realistic multi-provider setup (one provider per file):

```yaml
# uniapi.yaml
id: uniapi
name: Uni API
sdk_type: openai
default_base_url: https://uni-api.cstcloud.cn/v1
model_cards:
  - id: deepseek-v4-flash
    type: chat
    context_window_tokens: 1000000
  - id: bge-large-zh:latest
    type: embedding
    embedding_dimension: 1024
  - id: bge-reranker-v2-m3
    type: reranking
```

```yaml
# accounts.yaml
accounts:
  - id: uniapi-primary
    provider_id: uniapi
    credential: {env: UNIAPI_PRIMARY_KEY}
    enabled_models: [deepseek-v4-flash, bge-large-zh:latest, bge-reranker-v2-m3]
  - id: uniapi-secondary
    provider_id: uniapi
    credential: {env: UNIAPI_SECONDARY_KEY}
    enabled_models: [deepseek-v4-flash]
```

```yaml
# aliases.yaml
aliases:
  - id: chat-default
    deployments:
      - account_id: uniapi-primary
        model_id: deepseek-v4-flash
        routing: {priority: 0, weight: 3}
      - account_id: uniapi-secondary
        model_id: deepseek-v4-flash
        routing: {priority: 0, weight: 1}
  - id: embed-default
    deployments:
      - account_id: uniapi-primary
        model_id: bge-large-zh:latest
  - id: rerank-default
    deployments:
      - account_id: uniapi-primary
        model_id: bge-reranker-v2-m3
```

```python
registry = Registry.from_files(
    provider_files=["uniapi.yaml"],
    account_files=["accounts.yaml"],
    alias_files=["aliases.yaml"],
)
```
