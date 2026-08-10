# Profile-Based Registry Selection

## Decision

Allow users to select between multiple project registry files for
environment/tenant-specific configuration. The primary use case is choosing a
different registry at deploy/config time (dev/staging/prod, or per tenant) that
stays fixed for the process lifetime.

Adopt Approach 1: named registry files selected by a profile, with both an
explicit argument and an environment-variable fallback.

## Layout

```text
.ai-registry/
├── providers/
├── registry.yaml          # default (no profile)
├── registry.dev.yaml      # profile "dev"
└── registry.prod.yaml     # profile "prod"
```

## API

```python
Registry.from_project(
    root: str | Path | None = None,
    *,
    profile: str | None = None,
    secret_resolver: SecretResolver | None = None,
    router: DeploymentRouter | None = None,
) -> Registry
```

## Selection precedence

1. Explicit `profile=` argument, if given.
2. Else the `AI_REGISTRY_PROFILE` environment variable, if set.
3. Else the default `.ai-registry/registry.yaml`.

Once a profile is determined, the loader looks for
`.ai-registry/registry.<profile>.yaml` (also accepting `.yml`/`.json`).

## Behavior and error handling

- **No silent fallback.** If a profile is requested (argument or env var) but
  its file is missing, raise an actionable `ConfigurationError` naming the
  expected file. Do not fall back to the default — that could mask a prod
  misconfiguration.
- **Safe profile names.** The profile is interpolated into a file path, so
  reject values containing path separators or traversal (`/`, `\`, `..`, NUL)
  with a clear error.
- **Empty/blank profile** is treated as "no profile" → the default file.
- The example template `examples/registry.example.yaml` remains the default;
  docs show copying it to `registry.<env>.yaml` for each environment.

## Docs

Update `configuration.md`, `api-reference.md`, `getting-started.md`,
`use-cases.md`, `overview.md`, and `README.md` to document the named files,
`profile=` argument, and `AI_REGISTRY_PROFILE` env var.

## Tests

- Default (no profile) loads `registry.yaml`.
- `profile=` loads `registry.<profile>.yaml`.
- Env var fallback loads `registry.<env>.yaml`.
- Explicit `profile=` overrides the env var.
- Missing profile file → actionable error, no fallback.
- Unsafe profile name (path traversal) → rejected.
- `.yml`/`.json` variants still work.