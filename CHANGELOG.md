# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is `0.x`, minor releases may contain breaking changes; they
are always listed under **Changed** with a migration note.

## [Unreleased]

## [0.2.0] - 2026-08-24

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
- Optional adapters: `ai_registry.adapters.openai` (`create_client`,
  `create_async_client`, `client_kwargs`) and `ai_registry.adapters.pydantic_ai`
  (`create_model`, `create_fallback_model`). Install with the `openai` or
  `pydantic-ai` extras.
- Optional LangChain adapter: `ai_registry.adapters.langchain`
  (`create_chat_model`, `create_embeddings`) — chat models for OpenAI-compatible
  and Anthropic providers, embeddings for OpenAI-compatible providers, plus
  `ClientFactory` `langchain_chat_model` / `langchain_embeddings`. Install with
  the `langchain` extra; the models feed straight into LangGraph states.
- `ClientFactory`: a core facade that builds a registry once (`from_project` /
  `from_files` / `from_data`) and builds framework clients from references
  (`openai_client`, `openai_async_client`, `pydantic_ai_model`,
  `pydantic_ai_fallback_model`). Adapter extras are imported lazily.
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
- Providers can declare multiple named upstream endpoints (`endpoints` map),
  each bundling `sdk_type`, `base_url`, and `mode` (`chat` vs `responses`).
  Accounts select one by name with `endpoint_ref`; `Resolution` surfaces the
  effective `sdk_type`/`mode`/`endpoint`, and adapters route on them. Model
  cards can declare which endpoints support them, and resolution validates the
  selection. The `endpoints` map is the single source of truth: a provider
  designates its default endpoint with `default_endpoint` (or uses its only
  endpoint), and the top-level `sdk_type`/`default_base_url` are honored only
  for legacy providers that declare no `endpoints`.
- **Model cards are now called `Model`, and the provider `model_cards` list is
  now `models` in both the schema and the YAML catalog files.** The legacy
  `model_cards` key is still accepted by the loader.
  *Migration*: rename `model_cards:` → `models:` in provider files and use
  `Model`/`Provider.models` in code; the old names still load.
- The built-in provider catalog now declares explicit `endpoints` maps for every
  provider, and DeepSeek's `openai-responses` endpoint is marked as supporting
  only `deepseek-v4-flash`.
- The Uni API built-in catalog is aligned with the gateway's current model list:
  models retired upstream are removed (`spark-x1:70b`, `qwen2.5-vl:72b`,
  `qwq:32b`, the `deepseek-r1` family, `qwen3:235b`, `deepseek-v4-pro`), models
  are renamed to their upstream ids (`s1-base-lite:s1-8b` → `S1-Base-Lite`,
  `s1-base-pro:s1-32b` → `S1-Base-Pro`, `s1-base-ultra:s1-671b` →
  `S1-Base-Ultra`, `s1-citationcalculate` → `S1-CitationCalculate`,
  `gte-qwen2-7b` → `gte-qwen2:7b`), and `deepseek-v3.2` is added. The
  reranking models (`bge-reranker-v2-m3`, `qwen3-reranker:8b`) move into the
  `uniapi` provider, and the separate `uniapi-rerankers` provider is removed.
  *Migration*: point accounts that referenced `uniapi-rerankers` at `uniapi`
  instead, and update references to the renamed model ids.

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
- The Uni API provider's OpenAI-compatible base URL now includes the `/v1`
  prefix. Previously clients posted to the portal's bare domain, which returned
  404 with an HTML body instead of reaching the API gateway.
- The built-in provider catalog is corrected against official sources: release
  dates, `context_window_tokens`, and `max_output_tokens` are aligned for
  Anthropic, OpenAI, Google, DeepSeek, Moonshot, Qwen, Zhipu, xAI, MiniMax, and
  Uni API models. Entries that never existed are removed (`glm-5-code`) or
  renamed to their real IDs (`MiniMax-M2-Stable` → `MiniMax-M2`,
  `kimi-k2.7` → `kimi-k2.7-code`), and models retired upstream
  (`deepseek-chat`, `deepseek-reasoner`, `kimi-latest`,
  `kimi-thinking-preview`, `kimi-k2-thinking`, `kimi-k2-turbo-preview`,
  `grok-3`, `grok-4`, `grok-4-latest`) are marked `deprecated`.

## [0.1.0]

### Added

- Initial framework-independent core: provider/account/alias schemas, YAML and
  JSON loaders with compatibility normalization, secret-reference resolution,
  alias and `account-id/model-id` resolution, priority/weight/health-aware
  deployment selection, a built-in provider catalog, and project-scoped
  configuration with profiles.
