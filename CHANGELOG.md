# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is `0.x`, minor releases may contain breaking changes; they
are always listed under **Changed** with a migration note.

## [Unreleased]

### Added

- `Registry.candidates()` returns every available deployment for a reference in
  routing order, so callers can implement request-time failover without a
  router.
- `Registry.record_success()` / `record_failure()` report the outcome of an
  attempt back into the health store.
- Catalog queries: `Registry.list_models()` (filter by type, provider,
  capability, minimum context window, and whether an enabled account exposes the
  model), `list_aliases()`, `list_accounts()`, `list_providers()`,
  `get_provider()`, `get_account()`.
- `Resolution.otel_attributes()` emits OpenTelemetry GenAI attributes
  (`gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.operation.name`) plus
  `ai_registry.*` attributes recording which alias and account were selected.
- `ai_registry.testing` ships supported test doubles: `build_registry`,
  `FakeSecretResolver`, `constant_secret_resolver`, `ManualHealthStore`, and
  `deterministic_router`.
- `ai_registry.catalog.load_models_dev()` imports a models.dev `api.json`
  document into providers, so context windows, pricing and capabilities need not
  be maintained by hand. No network access is performed.
- Optional adapters: `ai_registry.adapters.openai` (`build_client`,
  `build_async_client`, `client_kwargs`) and `ai_registry.adapters.pydantic_ai`
  (`build_model`, `build_fallback_model`). Install with the `openai` or
  `pydantic-ai` extras.
- Optional CLI (`pip install "ai-registry[cli]"`): `ai-registry validate`,
  `aliases`, `models`, `resolve`, and `explain`. No command prints a credential.
- Credential references accept string shorthands: `env:NAME`, `env.NAME`,
  `${env:NAME}`, `${NAME}`, `os.environ/NAME`, and `secret_ref:REF`. Literal
  keys are still rejected.
- `py.typed` marker, so downstream type checkers use the package's annotations.
- Structured error types: `AdapterError`, `MissingDependencyError`,
  `UnsupportedProviderError`.
- `DeploymentHealthStore.cooldown_remaining()` and the `HealthStore` protocol,
  allowing a shared or persistent store to be substituted.

### Changed

- **Health state is now keyed by `DeploymentTarget(account_id, model_id)`**
  instead of `(alias_id, candidate_index)`. A target that fails is withheld from
  every alias that references it, and reordering deployments in configuration no
  longer reassigns health state to a different deployment.
  *Migration*: replace `store.mark_failure(alias_id, index)` with
  `store.record_failure(DeploymentTarget(account_id, model_id))` — or use
  `Registry.record_failure(resolution)`.
- **Health recovery is now time-based.** A failure cools a target down for
  `cooldown_seconds` (default 60), after which one half-open trial is allowed;
  repeated failures back off exponentially up to `max_cooldown_seconds`
  (default 600). Previously a failure was permanent until an explicit success.
- `DeploymentHealthStore` is thread-safe.
- `Registry.from_project()` walks up from the starting directory to the nearest
  ancestor containing `.ai-registry/`, so resolution works from any
  subdirectory. Pass `search_parents=False` for the previous behavior.
- The package root re-exports the schema, error, and secret-resolver types that
  the documentation already treated as public.

### Fixed

- Provider catalogs that declare tool support as `function_call` (the shape used
  by every built-in provider file) no longer lose it. Previously *all* built-in
  model cards reported `capabilities.tools == False`. Capability spellings from
  models.dev (`tool_call`) and LiteLLM (`supports_function_calling`) are also
  recognized.
- Built-in providers resolve to a real endpoint. Their base URL is declared under
  `settings.proxy_url.placeholder`, which was ignored, so every resolution from
  the documented quick-start returned `endpoint = None` and adapters silently
  fell back to their own default host.

## [0.1.0]

### Added

- Initial framework-independent core: provider/account/alias schemas, YAML and
  JSON loaders with compatibility normalization, secret-reference resolution,
  alias and `account-id/model-id` resolution, priority/weight/health-aware
  deployment selection, a built-in provider catalog, and project-scoped
  configuration with profiles.
