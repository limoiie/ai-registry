# API reference

This page documents every public symbol in `ai-registry` version `0.1.0`.
Public symbols are stable; anything not listed here is internal and may change
without notice.

## Package surface

```python
import ai_registry

ai_registry.__version__  # "0.1.0"
```

Public names exported from the package root:

| Name | Defined in | Kind |
| --- | --- | --- |
| `Registry` | `ai_registry.registry` | class |
| `ClientFactory` | `ai_registry.factory` | class |
| `DeploymentRouter` | `ai_registry.routing` | class |
| `DeploymentHealthStore` | `ai_registry.routing` | class |
| `SelectedDeployment` | `ai_registry.routing` | dataclass |
| `NoAvailableDeploymentError` | `ai_registry.routing` | exception |
| `__version__` | — | str |

## Errors (`ai_registry.errors`)

All public errors inherit from `RegistryError`. Error messages are actionable
and never contain API keys or resolved secret values.

| Exception | Purpose |
| --- | --- |
| `RegistryError` | Base class for all public registry errors. |
| `ConfigurationError(RegistryError)` | Invalid configuration (duplicates, unknown references, malformed documents, schema violations). |
| `SecretConfigurationError(ConfigurationError)` | A credential is not a safe reference. |
| `SecretResolutionError(SecretConfigurationError)` | A credential reference could not be resolved (defined in `ai_registry.secrets`). |
| `NoAvailableDeploymentError(RegistryError)` | An alias has no enabled, healthy deployment. |

## Registry (`ai_registry.registry`)

### `Registry`

An immutable configuration index for aliases and explicit deployments. Built
from validated configuration and revalidated on construction; the configuration
is deep-copied so caller mutations cannot affect resolution.

#### Construction

```python
Registry(config: RegistryConfig, secret_resolver: SecretResolver | None, router: DeploymentRouter | None = None)
```

Direct constructor from a `RegistryConfig`. `secret_resolver` is required
(positionally) but may be `None` when no account uses a `secret_ref` credential.

#### Class methods

```python
Registry.from_data(
    *,
    providers: Sequence[Provider | Mapping[str, Any]],
    accounts: Sequence[Account | Mapping[str, Any]],
    aliases: Sequence[Alias | Mapping[str, Any]] = (),
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

Build from normalized objects or schema-compatible mappings. Inputs are
revalidated even if they are already `Provider`/`Account`/`Alias` instances.

```python
Registry.from_files(
    provider_files: Sequence[PathSource],
    account_files: Sequence[PathSource],
    alias_files: Sequence[PathSource] = (),
    *,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

Load providers, accounts, and aliases from YAML/JSON paths or streams. Provider
files use the single-provider format (one provider per file); account files
must contain an `accounts` list; alias files must contain an `aliases` list.
Raises `ConfigurationError` on any structural problem.

```python
Registry.from_project(
    root: str | Path | None = None,
    *,
    profile: str | None = None,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

Build a registry from built-in providers plus project configuration discovered
at `root` (or the current working directory when omitted). Loads the merged
accounts/aliases from `<root>/.ai-registry/registry.yaml` (required as the
default file) and project providers from `<root>/.ai-registry/providers/`
(optional). Project providers replace built-ins by `id`; the registry file may
reference any of the merged providers. Raises `ConfigurationError` when the
registry file is missing or invalid.

`profile` selects a named registry file. When set, `from_project` loads
`<root>/.ai-registry/registry.<profile>.yaml` (or `.yml`/`.json`) instead of
the default `registry.yaml`. If `profile` is omitted, the `AI_REGISTRY_PROFILE`
environment variable is used. The explicit `profile` argument takes precedence
over the environment variable. Profile names are restricted to `[A-Za-z0-9_-]`;
invalid names and missing profile files raise `ConfigurationError`. A requested
(but missing) profile file never falls back to the default `registry.yaml`. An
empty or blank profile (argument or environment variable) selects the default
rather than being rejected.

#### Methods

```python
registry.resolve(reference: str) -> Resolution
```

Resolve an alias first, then an explicit `account-id/model-id`. Selection for
aliases goes through the configured `DeploymentRouter` (priority, weight,
health, disabled accounts). Raises:

- `RegistryError` — unknown alias/model reference, or an `account/model`
  reference whose account is unknown or disabled, or whose model is unknown or
  not enabled.
- `NoAvailableDeploymentError` — the alias exists but every deployment is
  disabled, unhealthy, or on a disabled account.

### `Resolution`

A frozen dataclass describing the selected deployment. Every nested value is
deep-copied; mutating the result cannot affect the registry. Its `repr`/`str`
are redacted.

| Attribute / property | Type | Meaning |
| --- | --- | --- |
| `provider` | `Provider` | Deep-copied provider metadata. |
| `model` | `Model` | The selected model. |
| `account` | `Account` | Deep-copied account. |
| `deployment_id` | `str` | The deployment reference used by the resolution layer. |
| `endpoint` | `str | None` | `account.endpoint` or provider `default_base_url` (or the selected endpoint's `base_url` when `endpoint_ref` is set). |
| `sdk_type` | `SDKType` | The resolved SDK type: the provider's, or the selected endpoint's. |
| `mode` | `ModelMode` | The resolved API mode: the selected endpoint's, else `chat`. |
| `endpoint_metadata` | `dict[str, Any]` | Deep-copied account metadata for adapters. |
| `model_id` | `str` | Shorthand for `model.id`. |
| `account_id` | `str` | Shorthand for `account.id`. |

```python
resolution.resolve_credential() -> str | None
```

Resolve the account credential only when an adapter requests it. Returns the
raw secret value, or `None` when the account has no credential. Raises
`SecretResolutionError` for missing/empty environment values or resolver
failures. This is the **only** API that returns a resolved secret.

## Schemas (`ai_registry.schemas`)

### `SafeModel`

Base class for all configuration models. Guarantees secret-safe output:
`repr`, `str`, `model_dump`, `model_dump_json`, and `safe_dump()` redact
credential-bearing fields and sensitive keys recursively (see
[Security](security.md)). `extra="forbid"` rejects unknown fields.
`model_dump_json()` requires JSON-serializable values.

```python
model.safe_dump() -> dict[str, Any]   # JSON-mode dump with None excluded
```

### Enums

```python
class ModelType(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANKING = "reranking"


class SDKType(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    CUSTOM = "custom"


class ModelMode(StrEnum):
    CHAT = "chat"
    RESPONSES = "responses"
```

### `ModelCapabilities`

| Field | Type | Default |
| --- | --- | --- |
| `tools` | bool | `False` |
| `structured_output` | bool | `False` |
| `vision` | bool | `False` |
| `reasoning` | bool | `False` |

### `Model`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | Canonical model ID; allows `- _ . : /`, no whitespace. |
| `type` | `ModelType` | Required. |
| `display_name` | `str | None` | |
| `description` | `str | None` | |
| `released_at` | `date | None` | ISO date. |
| `context_window_tokens` | `int | None` | Must be `>= 1`. |
| `max_output_tokens` | `int | None` | Must be `>= 1`. |
| `embedding_dimension` | `int | None` | Must be `>= 1`. |
| `endpoints` | `list[str] | None` | Endpoint names supporting this model. |
| `capabilities` | `ModelCapabilities` | Accepts alias `abilities`. |
| `metadata` | `dict[str, Any]` | |

### `ProviderEndpoint`

| Field | Type | Notes |
| --- | --- | --- |
| `sdk_type` | `SDKType` | Default `openai`. |
| `base_url` | `str | None` | Endpoint-validated. |
| `mode` | `ModelMode` | Default `chat`. |

### `Provider`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | Identifier. |
| `name` | str | Required. |
| `description` | `str | None` | |
| `sdk_type` | `SDKType` | Default `openai`. Legacy; used only when `endpoints` is empty. |
| `default_base_url` | `str | None` | Endpoint-validated. Legacy; used only when `endpoints` is empty. |
| `endpoints` | `dict[str, ProviderEndpoint]` | Named endpoints selectable per account. |
| `default_endpoint` | `str | None` | Names the default endpoint; must be a declared endpoint. |
| `settings` | `dict[str, Any]` | Adapter settings. |
| `models` | `list[Model]` | |

### `CredentialRef`

| Field | Type | Notes |
| --- | --- | --- |
| `env` | `str | None` | Env var name, min length 1. |
| `secret_ref` | `str | None` | External secret reference, min length 1. |
| `api_key` | `str | None` | Accepted by the shape but **always rejected** by validation. |

Exactly one of `env`/`secret_ref` must be set.

### `Account`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | Identifier. |
| `provider_id` | str | Identifier. |
| `endpoint` | `str | None` | Accepts alias `base_url`. Endpoint-validated. |
| `endpoint_ref` | `str | None` | Selects a named provider endpoint; mutually exclusive with `endpoint`. |
| `credential` | `CredentialRef | None` | Accepts alias `api_key`. |
| `enabled_models` | `list[str]` | Model IDs. |
| `enabled` | bool | Default `True`. |
| `timeout_seconds` | `float | None` | Must be `> 0`. |
| `metadata` | `dict[str, Any]` | |

### `RoutingMetadata`

| Field | Type | Default |
| --- | --- | --- |
| `priority` | int | `0` (must be `>= 0`) |
| `weight` | int | `1` (must be `>= 1`) |
| `enabled` | bool | `True` |
| `timeout_seconds` | `float | None` | must be `> 0` |

### `Deployment`

| Field | Type | Notes |
| --- | --- | --- |
| `account_id` | str | Accepts alias `account`. |
| `model_id` | str | Accepts alias `model`. |
| `routing` | `RoutingMetadata` | Default constructed. |

### `Alias`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | Identifier, unique across aliases. |
| `deployments` | `list[Deployment]` | At least one. |

### `RegistryConfig`

| Field | Type |
| --- | --- |
| `providers` | `list[Provider]` |
| `accounts` | `list[Account]` |
| `aliases` | `list[Alias]` |

Validates uniqueness of provider/account/alias IDs and of model-card IDs within
each provider.

## Configuration loading (`ai_registry.config`)

```python
PathSource = str | pathlib.Path | TextIO
```

| Function | Signature → result |
| --- | --- |
| `load_document(source)` | `PathSource -> dict[str, Any]` — parses one YAML/JSON mapping without resolving secrets. |
| `load_provider_file(source)` | `PathSource -> Provider` — loads and normalizes one provider document (single provider per file). |
| `load_provider_files(sources)` | `list[PathSource] -> list[Provider]` — rejects duplicate provider IDs. |
| `load_account_file(source)` | `PathSource -> list[Account]` — requires an `accounts` list. |
| `load_alias_file(source)` | `PathSource -> list[dict[str, Any]]` — requires an `aliases` list. |
| `load_deployments_file(source)` | `PathSource -> Deployments` — requires an `accounts` list; `aliases` is optional. |
| `discover_builtin_providers()` | `-> list[Provider]` — reads the built-in catalog shipped as package data (`ai_registry/data/providers/*.yml`). |
| `discover_project_providers(root)` | `str | Path -> list[Provider]` — reads `<root>/.ai-registry/providers/`; returns `[]` when the directory is missing. |
| `merge_providers(builtin, project)` | `Sequence[Provider] x Sequence[Provider] -> list[Provider]` — project providers replace built-ins by id; rejects duplicate project ids. |
| `normalize_provider(document, *, source_name=...)` | `dict -> Provider` — normalizes the legacy catalog shape into a `Provider`. |

### `Deployments`

A frozen dataclass returned by `load_deployments_file`:

| Field | Type | Meaning |
| --- | --- | --- |
| `accounts` | `list[Account]` | Normalized accounts from the `accounts` list. |
| `aliases` | `list[dict[str, Any]]` | Raw alias mappings from the `aliases` list (empty when absent). |

Raises `ConfigurationError` for unreadable files, unsupported formats, malformed
documents, and invalid content.

## Secrets (`ai_registry.secrets`)

```python
@runtime_checkable
class SecretResolver(Protocol):
    def resolve(self, reference: str) -> str: ...
```

Application-provided boundary for external secret stores. Implement it to read
from Vault, AWS Secrets Manager, Kubernetes, a keyring, or anything else.
Implementations must return a **non-empty string**; anything else raises
`SecretResolutionError`.

```python
class EnvironmentSecretResolver:
    def resolve(self, reference: str) -> str: ...
```

Resolves a reference as a process environment variable name. Missing or empty
values raise `SecretResolutionError`.

```python
resolve_credential(reference, resolver: SecretResolver | None = None) -> str
```

Resolve one `CredentialRef`:

- `env` — via `EnvironmentSecretResolver`;
- `secret_ref` — via the supplied `resolver` (required, else error);
- anything else — `SecretResolutionError`.

The resolved value is returned transiently and never stored or serialized.

## Routing (`ai_registry.routing`)

### `DeploymentTarget`

The identity a deployment is tracked by, independent of the alias referencing
it.

```python
DeploymentTarget(account_id: str, model_id: str)
```

Health is keyed by this value, which has two consequences worth knowing:

- A target that fails is withheld from **every** alias that references it. An
  account whose quota is exhausted is not "healthy" merely because a different
  alias points at it.
- Reordering deployments in configuration never reassigns health state to a
  different deployment.

`Resolution.target` and `SelectedDeployment.target` both return this value.

### `HealthStore`

A runtime-checkable `Protocol`. Implement it to share health across processes
(for example in Redis) or to hold it fixed in tests.

```python
class HealthStore(Protocol):
    def is_available(self, target: DeploymentTarget) -> bool: ...
    def record_success(self, target: DeploymentTarget) -> None: ...
    def record_failure(self, target: DeploymentTarget) -> None: ...
```

### `DeploymentHealthStore`

The default in-memory, thread-safe implementation, with time-based recovery.

```python
DeploymentHealthStore(
    *,
    cooldown_seconds: float = 60.0,
    max_cooldown_seconds: float = 600.0,
    failure_threshold: int = 1,
    clock: Callable[[], float] = time.monotonic,
)
```

- Unknown state is available (fail-open).
- `record_failure` counts consecutive failures; once `failure_threshold` is
  reached the target is withheld for `cooldown_seconds`.
- When the window elapses the target becomes available again for one half-open
  trial. A success clears the state; a failure cools it down again, doubling the
  window up to `max_cooldown_seconds`.
- `record_success` clears the state immediately.
- `cooldown_remaining(target) -> float` reports seconds until recovery, or `0.0`.

Inject `clock` to test recovery without waiting.

### `DeploymentRouter`

Selects an available deployment from an alias according to priority and weight.

```python
DeploymentRouter(
    health_store: HealthStore | None = None,
    *,
    random_source: Callable[[], float] = random.random,
)
```

`random_source` must return a float in `[0, 1)`; inject a deterministic source
for tests.

```python
router.select(
    alias: Alias,
    *,
    eligible: Callable[[Deployment], bool] | None = None,
) -> SelectedDeployment
```

Selection algorithm:

1. Filter out deployments with `routing.enabled == False`, those for which
   `eligible` returns `False` (the registry uses this to exclude disabled
   accounts), and unhealthy deployments.
2. Take the minimum `priority` among the remaining candidates.
3. Pick weighted-randomly among equal-priority candidates using `weight` and
   `random_source`.
4. Raise `NoAvailableDeploymentError` if nothing is available.

The selected deployment is deep-copied; the alias's static configuration is
never mutated.

```python
router.candidates(
    alias: Alias,
    *,
    eligible: Callable[[Deployment], bool] | None = None,
) -> list[SelectedDeployment]
```

Returns every available deployment in preference order — ascending priority,
and within a priority a weighted shuffle drawn from `random_source`. Returns an
empty list rather than raising when nothing is available, because "nothing to
try" is a normal branch in a retry loop.

### `SelectedDeployment`

| Attribute / property | Type | Meaning |
| --- | --- | --- |
| `alias_id` | str | The alias resolved. |
| `candidate_index` | int | Position of the deployment within `alias.deployments`. |
| `deployment` | `Deployment` | Deep copy of the selected deployment. |
| `metadata` | `dict[str, Any]` | `alias_id`, `candidate_index`, `account_id`, `model_id`, `priority`, `weight`. |
| `target` | `DeploymentTarget` | Health identity of the selection. |

## Testing (`ai_registry.testing`)

Supported test doubles. Importing this module adds no dependency.

```python
build_registry(
    aliases: Mapping[str, Sequence[str]] | None = None,
    *,
    provider_id: str = "test-provider",
    models: Sequence[str | Model] = ("test-model",),
    accounts: Sequence[str] = ("test-account",),
    model_type: ModelType | str = ModelType.CHAT,
    sdk_type: SDKType | str = SDKType.OPENAI,
    endpoint: str | None = "https://provider.test/v1",
    credential: Mapping[str, str] | str | None = "env:TEST_API_KEY",
    timeout_seconds: float | None = None,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

`aliases` maps an alias id to deployments written as `"account-id/model-id"`.

| Helper | Purpose |
| --- | --- |
| `FakeSecretResolver(secrets)` | Dict-backed resolver; records lookups in `.requested`, so you can assert credentials resolve lazily. |
| `constant_secret_resolver(value)` | Answers every reference with one value. The supported way to use a concrete secret in a test without weakening the schema. |
| `ManualHealthStore(unavailable)` | Clock-free health store; records `.successes` and `.failures`. |
| `deterministic_router(pick=0.0, health_store=None)` | Router with a fixed weighted-selection value. |

## Catalog import (`ai_registry.catalog`)

```python
load_models_dev(
    source: PathSource | Mapping[str, Any],
    *,
    provider_ids: Callable[[str], bool] | None = None,
    default_base_url: Mapping[str, str] | None = None,
) -> list[Provider]

models_dev_provider(
    provider_id: str,
    entry: Mapping[str, Any],
    *,
    default_base_url: str | None = None,
) -> Provider
```

Converts a [models.dev](https://models.dev) `api.json` document into providers.
`limit.context` and `limit.output` become the context and output token fields;
`tool_call`, `reasoning` and `structured_output` become capabilities; an `image`
input modality implies `vision`; an `embedding` output modality selects
`ModelType.EMBEDDING`; and `cost`, `modalities`, `knowledge` and related keys are
preserved under the card's `metadata`.

No network access is performed. Vendor the document and refresh it deliberately —
a resolution layer should not change behavior because an upstream file changed
under it.

## Adapters (`ai_registry.adapters`)

Adapters are optional extras and are never imported by the core.

### `ai_registry.adapters.openai`

```python
client_kwargs(resolution) -> dict[str, Any]      # no openai import required
create_client(resolution, **overrides) -> openai.OpenAI
create_async_client(resolution, **overrides) -> openai.AsyncOpenAI
```

`client_kwargs` returns `base_url`, `api_key` and `timeout` when configured.
It resolves the credential, so treat the result as secret. Raises
`UnsupportedProviderError` for a non-`openai` `sdk_type`, and
`MissingDependencyError` when the extra is not installed.

### `ai_registry.adapters.pydantic_ai`

```python
create_model(resolution, **overrides) -> pydantic_ai.models.Model
create_fallback_model(resolutions, **overrides) -> pydantic_ai.models.Model
```

Builds `OpenAIChatModel` + `OpenAIProvider` for `sdk_type: openai`, and
`AnthropicModel` + `AnthropicProvider` for `sdk_type: anthropic`. Pair
`create_fallback_model` with `Registry.candidates()` to turn registry routing into
Pydantic AI request-time failover.

## `ai_registry.factory`

### `ClientFactory`

```python
ClientFactory(registry)
ClientFactory.from_data(*args, **kwargs)
ClientFactory.from_files(*args, **kwargs)
ClientFactory.from_project(*args, **kwargs)
factory.registry -> Registry
factory.openai_client(reference, **overrides) -> openai.OpenAI
factory.openai_async_client(reference, **overrides) -> openai.AsyncOpenAI
factory.pydantic_ai_model(reference, **overrides) -> pydantic_ai.models.Model
factory.pydantic_ai_fallback_model(reference, **overrides) -> pydantic_ai.models.Model
```

The `from_*` classmethods delegate to the matching `Registry` builders and
accept the same arguments, so construction parameters are passed once.
`from_data`'s parameters are keyword-only, mirroring `Registry.from_data`.
Build methods resolve the reference and delegate to the adapter functions; the
adapter extras are imported lazily on first use.

## Command line (`ai-registry`)

Requires the `cli` extra.

| Command | Purpose |
| --- | --- |
| `ai-registry validate` | Load the project configuration and report any problem. |
| `ai-registry aliases` | List aliases and the deployments behind them. |
| `ai-registry models` | List catalog models; `--type`, `--tools`, `--min-context`, `--enabled`. |
| `ai-registry resolve REF` | Resolve a reference and print the selected deployment. |
| `ai-registry explain REF` | Show every candidate in the order routing would try them. |

All commands accept `--root`, `--profile` and `--json`. No command prints a
credential: `resolve` and `explain` report `none`, `env (ok)`,
`env (unresolved)`, or the `secret_ref` equivalent — never the variable name or
the value.
| `deployment_id` | str | Shorthand for `alias_id` (the reference used by the registry resolution layer). |
