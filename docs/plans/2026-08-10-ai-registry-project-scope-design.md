# AI Registry Project-Scope Configuration Discovery

## Decision

Introduce project-scoped configuration discovery so users get sensible defaults
without listing every file. The built-in provider catalog ships with the
package as data; project-specific providers override it by id; profiles and
aliases are merged into a single project-scope file.

## Configuration layout

```text
<project-root>/
└── .ai-registry/
    ├── providers/          # OPTIONAL — user-customized providers (project scope)
    │   └── my-vllm.yaml
    └── registry.yaml    # REQUIRED — merged profiles + aliases (project scope)
```

Built-in providers ship inside the installed package as package data at
`ai_registry/data/providers/*.yml`.

## Merged registry.yaml

```yaml
profiles:
  - id: uniapi-primary
    provider_id: uniapi
    credential: {env: UNIAPI_PRIMARY_KEY}
    enabled_models: [deepseek-v4-flash]

aliases:
  - id: sol
    deployments:
      - profile_id: uniapi-primary
        model_id: deepseek-v4-flash
```

- `profiles` is required; `aliases` is optional and defaults to empty.
- Legacy profile fields (`api_key_env`, `remark`, `description`) are still
  normalized inside this file.

## Provider scope and merge

- Built-in providers load from package data first.
- Project providers load from `.ai-registry/providers/*.{yaml,yml,json}` when
  the directory exists; a missing directory means built-ins only.
- A project provider with the same id replaces the built-in entirely; unique
  ids add to the catalog. No field-level merge.

## New API

```python
Registry.from_project(
    root: str | Path | None = None,
    *,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

- `root=None` uses the current working directory.
- Discovery merges providers, loads `registry.yaml`, then reuses the
  existing `from_data` validation and reference checks.
- `Registry.from_files` and `Registry.from_data` remain unchanged for explicit
  path control.

## Error handling

- Missing `.ai-registry/registry.yaml` raises an actionable
  `ConfigurationError` telling the user to create it (e.g. by copying the
  example).
- Missing `.ai-registry/` or `.ai-registry/providers/` is not an error for
  providers (built-ins only); the deployments file is still required.

## Packaging and examples

- Move the 4 provider YAMLs to `src/ai_registry/data/providers/` and configure
  uv package data so they ship in the wheel (verified by inspecting the built
  wheel).
- Remove `data/ai/providers/profiles/builtin.yaml` (profiles are project-only).
- Convert `builtin.example.yaml` into `examples/registry.example.yaml`, a
  documented template users copy to `.ai-registry/registry.yaml`.

## Tests and docs

- New tests: built-in-only discovery, project override by id, adding a new
  provider, merged deployments load, missing-file error, example template
  loads, legacy profile fields inside `registry.yaml`.
- Update `README.md`, `docs/overview.md`, `docs/getting-started.md`,
  `docs/configuration.md`, `docs/use-cases.md`, and `docs/api-reference.md` for
  the new layout and `from_project`.
