# AI Registry

A framework-independent core for registering and resolving AI providers,
models, profiles, and deployments. Resolve a **stable alias** to a **concrete,
healthy deployment** — then build any framework-native client from the result.

```python
from ai_registry import Registry

registry = Registry.from_files(
    provider_files=["catalog.yaml"],
    profile_files=["profiles.yaml"],
    alias_files=["aliases.yaml"],
)

resolution = registry.resolve("sol")  # stable logical name

resolution.profile_id  # which profile/key was selected
resolution.model_id  # canonical model id (for requests/logging)
resolution.endpoint  # base URL
resolution.resolve_credential()  # resolved lazily, only at the adapter boundary
```

The underlying model, provider, or endpoint behind `"sol"` can change in
configuration without any application code changes.

## Features

- **Alias-first resolution** with an explicit `profile-id/model-id` fallback.
- **Health-aware routing**: priority, weight, disabled deployments, and a
  runtime health store with recovery.
- **Multiple profiles and keys** for the same or different providers.
- **OpenAI-compatible endpoints** out of the box (UniAPI, vLLM, gateways),
  plus support for other SDK families.
- **Secret references, not secrets**: `env:` / `secret_ref:` credentials,
  lazy resolution, and pluggable `SecretResolver` for Vault/AWS/Kubernetes.
- **Secret-safe by construction**: literal keys are rejected; `repr`, dumps,
  and errors are redacted.
- **Compatibility loaders** for the existing `data/ai/providers/*.yml`
  catalog and profile formats.
- **Framework-independent**: only depends on Pydantic and PyYAML; adapters for
  the OpenAI SDK, Pydantic AI, LangGraph, and LlamaIndex are planned as
  optional extras.

## Install

```bash
pip install ai-registry
# or, from a checkout with uv:
uv sync
```

Requires Python 3.11+.

## Quick start

```python
import os
from ai_registry import Registry
from ai_registry.schemas import Alias, Deployment, ModelCard, Profile, Provider

os.environ["DEEPSEEK_API_KEY"] = "sk-example"

registry = Registry.from_data(
    providers=[
        Provider(
            id="deepseek",
            name="DeepSeek",
            default_base_url="https://api.deepseek.com/v1",
            model_cards=[ModelCard(id="deepseek-chat", type="chat")],
        ),
    ],
    profiles=[
        Profile(
            id="primary",
            provider_id="deepseek",
            credential={"env": "DEEPSEEK_API_KEY"},
            enabled_models=["deepseek-chat"],
        ),
    ],
    aliases=[
        Alias(
            id="chat-default",
            deployments=[Deployment(profile_id="primary", model_id="deepseek-chat")],
        ),
    ],
)

resolution = registry.resolve("chat-default")
print(resolution.endpoint)
print(resolution.resolve_credential())
```

For file-based configuration, see [Getting started](docs/getting-started.md).

## Documentation

| Guide | Audience | Contents |
| --- | --- | --- |
| [Overview](docs/overview.md) | Everyone | The idea, concepts, architecture, goals and non-goals. |
| [Getting started](docs/getting-started.md) | New users | Install, first resolution, loading files, built-in data. |
| [Configuration](docs/configuration.md) | Everyone | Complete data file format: normalized + legacy shapes, field references, validation. |
| [Use cases](docs/use-cases.md) | All users | 12 detailed scenarios: failover, weighted routing, embeddings, custom endpoints, secret resolvers, and more. |
| [API reference](docs/api-reference.md) | Experienced users | Every public class, function, field, and behavior. |
| [Security](docs/security.md) | Everyone | Secret-handling guarantees, redaction rules, endpoint validation, limitations. |
| [Development](docs/development.md) | Contributors | Environment, checks, conventions, testing. |

## Non-goals

This package does not make network requests, define a unified AI response
interface, resolve framework SDK behavior, or ship a gateway. Health-aware
routing applies to deployment selection in the core; request-time failover and
framework adapters are outside the current release.

## License

TBD.
