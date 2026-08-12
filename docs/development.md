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
uv run pytest -q --cov          # with coverage
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

Or install the hooks once and let them run automatically:

```bash
uv run pre-commit install
```

The hooks cover ruff, ruff-format, `uv lock`, strict mypy, and a gitleaks scan —
the last because this project rejects literal secrets in configuration, and that
guarantee should not be only schema-deep.

CI additionally runs a job that installs the package with **no extras** and
asserts the dependency closure stayed small. Nothing else proves the core
promise, because the dev group installs Typer.

## Repository layout

```text
.
├── pyproject.toml              # uv project metadata, deps, tool config
├── uv.lock                     # locked dependency graph
├── src/ai_registry/
│   ├── __init__.py             # public API surface
│   ├── py.typed                # PEP 561 marker
│   ├── schemas.py              # Pydantic models + safe serialization
│   ├── config.py               # YAML/JSON loaders + normalization
│   ├── secrets.py              # credential resolution
│   ├── registry.py             # Registry + Resolution + CatalogEntry
│   ├── routing.py              # health-aware deployment selection
│   ├── catalog.py              # third-party catalog import (models.dev)
│   ├── testing.py              # supported test doubles for consumers
│   ├── cli.py                  # optional CLI (cli extra)
│   ├── adapters/               # optional framework adapters
│   ├── errors.py               # public exceptions
│   └── data/providers/         # built-in provider catalog (package data)
├── tests/
│   ├── fixtures/               # provider/account/alias examples
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

- Every account `provider_id` resolves to a configured provider.
- Every enabled model and alias deployment `model_id` exists in the provider's
  catalog and is listed in the account's `enabled_models`.
- Provider, account, alias, and per-provider model IDs are unique.
- Credential references hold exactly one of `env`/`secret_ref`; literal keys
  are rejected.
- Endpoint fields reject credential-bearing URLs.
- Health/routing state never mutates static configuration.

## Testing conventions

- Write tests before implementation (red-green).
- No network calls, ever — including in adapter tests. The optional extras are
  deliberately absent from the dev environment, so the "missing dependency" paths
  are exercised for real, and the "installed" paths run against stub modules
  injected into `sys.modules`. See `tests/test_adapters.py`.
- Optional framework imports must not leak into core tests — there is a
  dedicated integration test asserting the core imports no optional SDKs.
- Deterministic routing tests inject a `random_source` returning values in
  `[0, 1)`; prefer `ai_registry.testing.deterministic_router()`.
- Time-dependent health tests inject a fake `clock` into
  `DeploymentHealthStore` rather than sleeping.
- Prefer `ai_registry.testing.build_registry()` over hand-rolling fixtures. It is
  public API, so exercising it in our own suite keeps it honest.
- Security tests assert that secret-like inputs never appear in
  `str`/`repr`/`args`/structured error output or serialized dumps.
- Use the fixtures under `tests/fixtures/`; represent the built-in
  `ai_registry/data/providers/` shapes in compatibility tests.
- One test module per source module (`tests/test_<module>.py`).

## Versioning and dependencies

- Python `>= 3.11`; runtime dependencies are `pydantic>=2` and `pyyaml`. Adding
  a third runtime dependency needs a strong justification — the small closure is
  a documented security property, not an accident.
- Optional framework adapters ship as extras (`cli`, `openai`, `pydantic-ai`)
  and must never be imported at module import time. There is an integration test
  asserting the core imports no optional SDK.
- Keep `uv.lock` current (`uv lock`) whenever `pyproject.toml` changes.
- The version is `0.x`: breaking changes are allowed but must be listed under
  **Changed** in `CHANGELOG.md` with a migration note.
- Releases are tag-driven (`v*`) and published with PyPI Trusted Publishing; the
  release workflow verifies that the tag matches the `pyproject.toml` version.

## Documentation

- User-facing docs live in `docs/` and are linked from the README.
- Keep the [API reference](api-reference.md) in sync with code changes.
- Update the [configuration](configuration.md) reference whenever the schema
  or loaders change.
