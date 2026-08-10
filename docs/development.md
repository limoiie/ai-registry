# Development

Guidelines for contributors to the `ai-registry` repository.

## Environment

The repository is managed with [uv](https://docs.astral.sh/uv/). Install uv,
then sync the locked environment:

```bash
uv sync
```

This creates a `.venv` with the package (editable) and the dev dependencies
(pytest, ruff, mypy).

## Running checks

All checks are invoked through uv:

```bash
uv run pytest -q                # unit + integration tests
uv run ruff check .             # lint
uv run ruff format --check .    # formatting
uv run mypy src tests           # strict type checking
uv lock --check                 # lockfile is up to date
uv build                        # build sdist + wheel
```

A typical pre-commit verification:

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
```

## Repository layout

```text
.
├── pyproject.toml              # uv project metadata, deps, tool config
├── uv.lock                     # locked dependency graph
├── src/ai_registry/
│   ├── __init__.py             # public API surface
│   ├── schemas.py              # Pydantic models + safe serialization
│   ├── config.py               # YAML/JSON loaders + normalization
│   ├── secrets.py              # credential resolution
│   ├── registry.py             # Registry + Resolution
│   ├── routing.py              # health-aware deployment selection
│   ├── errors.py               # public exceptions
│   └── data/providers/         # built-in provider catalog (package data)
├── tests/
│   ├── fixtures/               # provider/profile/alias examples
│   └── test_*.py               # one module per source module
├── examples/                   # config templates (registry.example.yaml)
└── docs/                       # this documentation set
```

## Public API discipline

- The package root (`ai_registry/__init__.py`) is the public surface. Exported
  names are stable.
- Anything not exported or not documented in [API reference](api-reference.md)
  is internal and may change.
- `SafeModel`/`Resolution` redaction is a security contract. New serialization
  paths must route through the redaction logic and must be tested.

## Configuration invariants

These invariants are enforced and must be preserved by changes:

- Every profile `provider_id` resolves to a configured provider.
- Every enabled model and alias deployment `model_id` exists in the provider's
  catalog and is listed in the profile's `enabled_models`.
- Provider, profile, alias, and per-provider model IDs are unique.
- Credential references hold exactly one of `env`/`secret_ref`; literal keys
  are rejected.
- Endpoint fields reject credential-bearing URLs.
- Health/routing state never mutates static configuration.

## Testing conventions

- Write tests before implementation (red-green).
- No network calls. HTTP behavior, when adapters arrive, must be mocked.
- Optional framework imports must not leak into core tests — there is a
  dedicated integration test asserting the core imports no optional SDKs.
- Deterministic routing tests inject a `random_source` returning values in
  `[0, 1)`.
- Security tests assert that secret-like inputs never appear in
  `str`/`repr`/`args`/structured error output or serialized dumps.
- Use the fixtures under `tests/fixtures/`; represent the built-in
  `ai_registry/data/providers/` shapes in compatibility tests.

## Versioning and dependencies

- Python `>= 3.11`; runtime dependencies are `pydantic>=2` and `pyyaml`.
- Optional framework adapters will ship as extras and must never be imported at
  module import time.
- Keep `uv.lock` current (`uv lock`) whenever `pyproject.toml` changes.

## Documentation

- User-facing docs live in `docs/` and are linked from the README.
- Keep the [API reference](api-reference.md) in sync with code changes.
- Update the [configuration](configuration.md) reference whenever the schema
  or loaders change.
