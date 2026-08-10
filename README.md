# AI Registry

Framework-independent core for registering and resolving AI providers,
models, profiles, and deployments.

## Development

Install uv, then create the project environment and install the locked
development dependencies:

```bash
uv sync
```

Run the project checks with:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

## Configuration

The core uses normalized provider, profile, and alias objects. Providers have
model cards and SDK-neutral settings; profiles select enabled models and hold
only credential references. Credentials can refer to an environment variable
with `api_key_env` in the current catalog format or the normalized
`credential: {env: NAME}` form. Values are resolved only when an adapter asks
for them.

`load_provider_file`, `load_profile_file`, and `Registry.from_files` load the
current provider and profile files under `data/ai/providers/`, including legacy
fields such as `settings.sdk_type`, `abilities`, `max_dimension`, and
`api_key_env`. New configuration should prefer the normalized shape.

Aliases resolve to deployments such as `chat-default`; callers may also use a
direct `profile-id/model-id` reference. Profile endpoint URLs and other custom
OpenAI-compatible metadata remain available to an adapter without requiring an
OpenAI or other provider SDK.

## Non-goals

This package does not make network requests, resolve provider SDK behavior, or
provide framework integrations. Health-aware routing is limited to the core
deployment state and selection APIs; adapters remain responsible for clients,
request translation, retries, and observability.
