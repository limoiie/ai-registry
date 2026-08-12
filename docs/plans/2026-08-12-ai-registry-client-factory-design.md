# ClientFactory Design

**Goal:** Give users a single entry point that constructs a `Registry` once and
builds framework-native clients from it, so call sites stop threading a
`Registry` around. Today every call is `create_client_for(registry, "ref")`; the
factory turns that into `factory.openai_client("ref")`.

**Architecture:** A `ClientFactory` class in the core package holding a
`Registry`. Classmethods mirror `Registry.from_project` / `from_files` /
`from_data` so construction params (profile, secret resolver, router) are passed
once. Instance methods lazily import the adapter modules and delegate to the
low-level `create_*` functions. The optional extras stay optional: importing the
core never imports `openai` or `pydantic_ai`.

## Naming

- Class: `ClientFactory`, re-exported from `ai_registry` top level.
- Construction: `ClientFactory(registry)`, `ClientFactory.from_project(...)`,
  `ClientFactory.from_files(...)`, `ClientFactory.from_data(...)`.
- Build methods (noun form):
  - `openai_client(reference, **overrides)`
  - `openai_async_client(reference, **overrides)`
  - `pydantic_ai_model(reference, **overrides)`
  - `pydantic_ai_fallback_model(reference, **overrides)`
- `registry` property exposing the underlying `Registry` for failover
  (`candidates()`, `record_success()`, `record_failure()`) and introspection.

## API surface removed

The one-call helpers `create_client_for`, `create_async_client_for`,
`create_model_for`, `create_fallback_model_for` are removed from the adapters —
the factory subsumes them. They have not been released (still Unreleased), so no
migration note is needed.

The low-level `create_client`, `create_async_client`, `create_model`,
`create_fallback_model` (Resolution-based) and `client_kwargs` stay. They serve
per-Resolution construction in failover loops and framework integration, and the
factory delegates to them.

## Data flow

```
ClientFactory.from_project(profile="prod")
    -> Registry.from_project(profile="prod")
    -> ClientFactory(registry)
    -> openai_client("chat-default")
        -> lazy import ai_registry.adapters.openai
        -> create_client(registry.resolve("chat-default"))
            -> openai.OpenAI(**client_kwargs(resolution))
```

## Error handling

Unchanged from the existing functions: `MissingDependencyError` on first use of
an uninstalled extra, `UnsupportedProviderError` / `RegistryError` pass through
from `create_*` and `Registry.resolve`.

## Type annotations

Build methods are annotated with the SDK types under `TYPE_CHECKING`, matching
the adapter modules. `openai` / `pydantic_ai.*` imports are guarded by
`ignore_missing_imports` in mypy config.

## Testing

- Mirror `tests/test_adapters.py`: inject stub modules into `sys.modules`, verify
  delegation (kwargs/args reaching the stub constructors) and lazy import.
- Test each `from_*` classmethod delegates to the matching `Registry` builder
  (e.g. `from_data` with a custom router resolves the same reference).
- Test `.registry` exposes `candidates()` / `record_success()`.
- Test missing-extra path raises `MissingDependencyError` with the right extra.