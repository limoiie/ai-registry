# Getting started

This guide walks through installing `ai-registry` and resolving your first
model. It assumes you already have a small catalog, profile, and alias file.

## Prerequisites

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) (recommended for development), or any
  standard Python tooling (pip, venv)

## Install

From a local checkout, `uv` installs the locked development environment:

```bash
uv sync
```

To use the package as a library in your own project:

```bash
uv add ai-registry
# or
pip install ai-registry
```

## A minimal example

The fastest way to use the registry is to build it directly from Python
objects. No YAML files are required.

```python
from ai_registry import Registry
from ai_registry.schemas import Alias, Deployment, ModelCard, Profile, Provider

provider = Provider(
    id="deepseek",
    name="DeepSeek",
    default_base_url="https://api.deepseek.com/v1",
    model_cards=[
        ModelCard(id="deepseek-chat", type="chat"),
    ],
)

profile = Profile(
    id="primary",
    provider_id="deepseek",
    credential={"env": "DEEPSEEK_API_KEY"},
    enabled_models=["deepseek-chat"],
)

alias = Alias(
    id="chat-default",
    deployments=[Deployment(profile_id="primary", model_id="deepseek-chat")],
)

registry = Registry.from_data(
    providers=[provider],
    profiles=[profile],
    aliases=[alias],
)
```

With `DEEPSEEK_API_KEY` exported in your environment, resolve the alias:

```python
import os

os.environ["DEEPSEEK_API_KEY"] = "sk-example"

resolution = registry.resolve("chat-default")

print(resolution.profile_id)  # "primary"
print(resolution.model_id)  # "deepseek-chat"
print(resolution.endpoint)  # "https://api.deepseek.com/v1"
print(resolution.resolve_credential())  # "sk-example"
```

`resolve_credential()` is the only API that ever returns the raw secret. It is
meant for the adapter boundary and is not invoked until you call it (lazy).

## Discover from your project

The registry can discover a project's configuration from a `.ai-registry/`
directory at the project root. Providers are optional there — the built-in
catalog ships with the package — but a registry file is required and holds
merged profiles and aliases. By default that is `registry.yaml`; profile-named
files (see [Select by environment](#select-by-environment) below) are also
accepted:

```text
<project-root>/
└── .ai-registry/
    ├── providers/          # OPTIONAL — override or add providers
    └── registry.yaml    # default — merged profiles + aliases
```

Copy `examples/registry.example.yaml`, which references the built-in
`deepseek`, `uniapi`, and `uniapi-rerankers` providers:

```yaml
profiles:
  - id: deepseek-primary
    provider_id: deepseek
    credential: {env: DEEPSEEK_API_KEY}
    enabled_models: [deepseek-chat, deepseek-reasoner]

aliases:
  - id: chat-default
    deployments:
      - profile_id: deepseek-primary
        model_id: deepseek-chat
```

```python
import os

from ai_registry import Registry

os.environ["DEEPSEEK_API_KEY"] = "sk-example"

registry = Registry.from_project()  # uses the current directory

resolution = registry.resolve("chat-default")
print(resolution.model_id)  # "deepseek-chat"
```

Pass a `root` path to discover from another directory. A project provider
under `.ai-registry/providers/` with the same `id` as a built-in replaces it
entirely — there is no deep merge.

### Select by environment

To keep separate registries per environment, copy the example to a
profile-named file and select it. Copy `examples/registry.example.yaml` to
`.ai-registry/registry.prod.yaml` (adjusting the contents for production), then
select the `prod` profile either by argument or by environment variable:

```python
from ai_registry import Registry

registry = Registry.from_project(profile="prod")  # loads registry.prod.yaml
```

```bash
export AI_REGISTRY_PROFILE=prod
python -c "from ai_registry import Registry; Registry.from_project()"
```

The file is named `registry.<profile>.yaml` under `.ai-registry/`. Without a
profile, the default `registry.yaml` is used. An explicit `profile=` argument
overrides the `AI_REGISTRY_PROFILE` environment variable. If a requested
profile file is missing, `from_project` raises instead of silently falling back
to the default. An empty or blank profile selects the default rather than being
rejected. See [Configuration](configuration.md) for full details.

## Loading from files explicitly (`from_files`)

`Registry.from_files` loads configuration from explicit paths. It accepts
paths, `pathlib.Path`, or open file objects, in YAML or JSON.

Given these three documents:

`deepseek.yaml` — a single provider (one provider per file):

```yaml
id: deepseek
name: DeepSeek
default_base_url: https://api.deepseek.com/v1
model_cards:
  - id: deepseek-chat
    type: chat
```

`profiles.yaml` — one or more profiles:

```yaml
profiles:
  - id: primary
    provider_id: deepseek
    credential:
      env: DEEPSEEK_API_KEY
    enabled_models:
      - deepseek-chat
```

`aliases.yaml` — one or more aliases:

```yaml
aliases:
  - id: chat-default
    deployments:
      - profile_id: primary
        model_id: deepseek-chat
```

Build the registry:

```python
from ai_registry import Registry

registry = Registry.from_files(
    provider_files=["deepseek.yaml"],
    profile_files=["profiles.yaml"],
    alias_files=["aliases.yaml"],
)

resolution = registry.resolve("chat-default")
```

Notes:

- **One provider per file.** To use several providers, list each provider file
  in `provider_files`. Profile files, in contrast, contain a `profiles` list.
- Profile and alias documents may be combined in a single file that has both a
  `profiles` list and an `aliases` list. Pass that file to both
  `profile_files` and `alias_files`.
- If you already have a file shaped like `providers: [...]`, split it into one
  file per provider, or iterate it with `normalize_provider()` and build the
  registry with `Registry.from_data` (see
  [Configuration](configuration.md)).

## Built-in provider catalog

The package ships a built-in provider catalog at
`ai_registry/data/providers/*.yml` (`deepseek`, `uniapi`, `minimax`,
`uniapi-rerankers`). These use the legacy provider-catalog format (top-level
`url`, `settings.sdk_type`, and `abilities` on model cards), which the loader
normalizes automatically.

`Registry.from_project` loads the built-ins automatically and lets project
providers override them by id, so most projects never list a provider file:

```python
from ai_registry.config import discover_builtin_providers

providers = discover_builtin_providers()  # -> list[Provider]
```

Use `Registry.from_files` with explicit paths when you keep your own provider,
profile, and alias files instead.

See [Configuration](configuration.md) for the full file format reference and
[Use cases](use-cases.md) for more realistic setups.

## What happens on errors

Configuration mistakes fail fast at construction time with actionable
messages. Unknown references fail at resolution time. For example:

```python
registry.resolve("nope")  # RegistryError: unknown alias or model reference
```

Errors identify the logical alias/profile/model and the required remediation.
They never include API keys or resolved secret values. See
[Security](security.md) for the guarantees.

## Next steps

- [Overview](overview.md) — the ideas and architecture
- [Configuration](configuration.md) — the complete data file format
- [Use cases](use-cases.md) — detailed, real-world examples
- [API reference](api-reference.md) — every public symbol
- [Security](security.md) — the secret-handling model
- [Development](development.md) — contributing and running checks
