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
(positionally) but may be `None` when no profile uses a `secret_ref` credential.

#### Class methods

```python
Registry.from_data(
    *,
    providers: Sequence[Provider | Mapping[str, Any]],
    profiles: Sequence[Profile | Mapping[str, Any]],
    aliases: Sequence[Alias | Mapping[str, Any]] = (),
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

Build from normalized objects or schema-compatible mappings. Inputs are
revalidated even if they are already `Provider`/`Profile`/`Alias` instances.

```python
Registry.from_files(
    provider_files: Sequence[PathSource],
    profile_files: Sequence[PathSource],
    alias_files: Sequence[PathSource] = (),
    *,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

Load providers, profiles, and aliases from YAML/JSON paths or streams. Provider
files use the single-provider format (one provider per file); profile files
must contain a `profiles` list; alias files must contain an `aliases` list.
Raises `ConfigurationError` on any structural problem.

```python
Registry.from_project(
    root: str | Path | None = None,
    *,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

Build a registry from built-in providers plus project configuration discovered
at `root` (or the current working directory when omitted). Loads the merged
profiles/aliases from `<root>/.ai-registry/registry.yaml` (required) and
project providers from `<root>/.ai-registry/providers/` (optional). Project
providers replace built-ins by `id`; the deployments file may reference any of
the merged providers. Raises `ConfigurationError` when the deployments file is
missing or invalid.

#### Methods

```python
registry.resolve(reference: str) -> Resolution
```

Resolve an alias first, then an explicit `profile-id/model-id`. Selection for
aliases goes through the configured `DeploymentRouter` (priority, weight,
health, disabled profiles). Raises:

- `RegistryError` — unknown alias/model reference, or a `profile/model`
  reference whose profile is unknown or disabled, or whose model is unknown or
  not enabled.
- `NoAvailableDeploymentError` — the alias exists but every deployment is
  disabled, unhealthy, or on a disabled profile.

### `Resolution`

A frozen dataclass describing the selected deployment. Every nested value is
deep-copied; mutating the result cannot affect the registry. Its `repr`/`str`
are redacted.

| Attribute / property | Type | Meaning |
| --- | --- | --- |
| `provider` | `Provider` | Deep-copied provider metadata. |
| `model` | `ModelCard` | The selected model card. |
| `profile` | `Profile` | Deep-copied profile. |
| `deployment_id` | `str` | The deployment reference used by the resolution layer. |
| `endpoint` | `str | None` | `profile.endpoint` or provider `default_base_url`. |
| `endpoint_metadata` | `dict[str, Any]` | Deep-copied profile metadata for adapters. |
| `model_id` | `str` | Shorthand for `model.id`. |
| `profile_id` | `str` | Shorthand for `profile.id`. |

```python
resolution.resolve_credential() -> str | None
```

Resolve the profile credential only when an adapter requests it. Returns the
raw secret value, or `None` when the profile has no credential. Raises
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
```

### `ModelCapabilities`

| Field | Type | Default |
| --- | --- | --- |
| `tools` | bool | `False` |
| `structured_output` | bool | `False` |
| `vision` | bool | `False` |
| `reasoning` | bool | `False` |

### `ModelCard`

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
| `capabilities` | `ModelCapabilities` | Accepts alias `abilities`. |
| `metadata` | `dict[str, Any]` | |

### `Provider`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | Identifier. |
| `name` | str | Required. |
| `description` | `str | None` | |
| `sdk_type` | `SDKType` | Default `openai`. |
| `default_base_url` | `str | None` | Endpoint-validated. |
| `settings` | `dict[str, Any]` | Adapter settings. |
| `model_cards` | `list[ModelCard]` | |

### `CredentialRef`

| Field | Type | Notes |
| --- | --- | --- |
| `env` | `str | None` | Env var name, min length 1. |
| `secret_ref` | `str | None` | External secret reference, min length 1. |
| `api_key` | `str | None` | Accepted by the shape but **always rejected** by validation. |

Exactly one of `env`/`secret_ref` must be set.

### `Profile`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | Identifier. |
| `provider_id` | str | Identifier. |
| `endpoint` | `str | None` | Accepts alias `base_url`. Endpoint-validated. |
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
| `profile_id` | str | Accepts alias `profile`. |
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
| `profiles` | `list[Profile]` |
| `aliases` | `list[Alias]` |

Validates uniqueness of provider/profile/alias IDs and of model-card IDs within
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
| `load_profile_file(source)` | `PathSource -> list[Profile]` — requires a `profiles` list. |
| `load_alias_file(source)` | `PathSource -> list[dict[str, Any]]` — requires an `aliases` list. |
| `load_deployments_file(source)` | `PathSource -> Deployments` — requires a `profiles` list; `aliases` is optional. |
| `discover_builtin_providers()` | `-> list[Provider]` — reads the built-in catalog shipped as package data (`ai_registry/data/providers/*.yml`). |
| `discover_project_providers(root)` | `str | Path -> list[Provider]` — reads `<root>/.ai-registry/providers/`; returns `[]` when the directory is missing. |
| `merge_providers(builtin, project)` | `Sequence[Provider] x Sequence[Provider] -> list[Provider]` — project providers replace built-ins by id; rejects duplicate project ids. |
| `normalize_provider(document, *, source_name=...)` | `dict -> Provider` — normalizes the legacy catalog shape into a `Provider`. |

### `Deployments`

A frozen dataclass returned by `load_deployments_file`:

| Field | Type | Meaning |
| --- | --- | --- |
| `profiles` | `list[Profile]` | Normalized profiles from the `profiles` list. |
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

### `DeploymentHealthStore`

Mutable runtime health state kept separate from static configuration. Health
identity is `(alias_id, candidate_index)`, which is stable even if routing
fields mutate and distinguishes duplicate deployments. Unknown health state is
healthy (fail-open).

```python
store = DeploymentHealthStore()
store.mark_failure(alias_id, candidate_index)
store.mark_success(alias_id, candidate_index)
store.is_healthy(alias_id, candidate_index)  # -> bool
```

### `DeploymentRouter`

Selects an available deployment from an alias according to priority and weight.

```python
DeploymentRouter(
    health_store: DeploymentHealthStore | None = None,
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
   profiles), and unhealthy deployments.
2. Take the minimum `priority` among the remaining candidates.
3. Pick weighted-randomly among equal-priority candidates using `weight` and
   `random_source`.
4. Raise `NoAvailableDeploymentError` if nothing is available.

The selected deployment is deep-copied; the alias's static configuration is
never mutated.

### `SelectedDeployment`

| Attribute / property | Type | Meaning |
| --- | --- | --- |
| `alias_id` | str | The alias resolved. |
| `candidate_index` | int | Position of the deployment within `alias.deployments`. |
| `deployment` | `Deployment` | Deep copy of the selected deployment. |
| `metadata` | `dict[str, Any]` | `alias_id`, `candidate_index`, `profile_id`, `model_id`, `priority`, `weight`. |
| `deployment_id` | str | Shorthand for `alias_id` (the reference used by the registry resolution layer). |
