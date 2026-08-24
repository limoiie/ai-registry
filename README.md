# ai-registry

[![PyPI](https://img.shields.io/pypi/v/ai-registry.svg)](https://pypi.org/project/ai-registry/)
[![Python versions](https://img.shields.io/pypi/pyversions/ai-registry.svg)](https://pypi.org/project/ai-registry/)
[![CI](https://github.com/limoiie/ai-registry/actions/workflows/ci.yml/badge.svg)](https://github.com/limoiie/ai-registry/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2a6db2.svg)](https://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Resolve a stable alias to a concrete AI deployment — provider, model,
account, endpoint — and stop there.**

`ai-registry` is the configuration layer under your AI stack, not another client.
It answers one question — *"which provider, which model, whose key, what URL?"* —
and hands the answer to whatever SDK you already use.

It makes **no network requests**, defines **no chat interface**, ships **no
gateway**, and **cannot hold a literal API key**. The runtime dependency closure
is six packages.

```python
from ai_registry import Registry

registry = Registry.from_project()  # reads ./.ai-registry/registry.yaml
resolution = registry.resolve("chat-default")
```

| What you get | Example | Why it matters |
| --- | --- | --- |
| `resolution.provider_id` | `'deepseek'` | Which provider was chosen. |
| `resolution.model_id` | `'deepseek-chat'` | The id to send, and to log. |
| `resolution.account_id` | `'deepseek-primary'` | **Which key** was chosen. |
| `resolution.endpoint` | `'https://api.deepseek.com/anthropic'` | Where to send it. |
| `resolution.model.capabilities` | `tools=True, reasoning=False, …` | What the model can do. |
| `resolution.resolve_credential()` | `'sk-…'` | Resolved lazily, only at the adapter boundary. |

The model, provider, account, or endpoint behind `"chat-default"` can change in
configuration without touching application code.

## Why a resolver instead of a client

Most tools in this space fuse two separate concerns: *deciding what to call* and
*calling it*. Fusing them means you adopt someone's request translation, error
types, retry semantics, and dependency tree in order to get their configuration
model.

That fusion has a well-known failure mode. From
[openai/codex#1370](https://github.com/openai/codex/issues/1370), on Azure
deployment names:

> No logic should inspect the user's deployment name when making assumptions
> about model capabilities.

That is exactly the split this library enforces. A **deployment** is where you
send the request. A **model** is what the model can do. They are different
objects, and `Resolution` gives you both.

## Install

```bash
pip install ai-registry                    # core: pydantic + pyyaml only
pip install "ai-registry[cli]"             # + ai-registry command
pip install "ai-registry[openai]"          # + OpenAI SDK adapter
pip install "ai-registry[pydantic-ai]"     # + Pydantic AI adapter
pip install "ai-registry[langchain]"       # + LangChain chat/embeddings adapter
```

Requires Python 3.11+.

## Configure

Projects keep configuration in `.ai-registry/` at the repository root, resolved
from any subdirectory:

```text
<project-root>/
└── .ai-registry/
    ├── providers/            # OPTIONAL — override or add providers
    ├── registry.yaml         # default
    ├── registry.dev.yaml     # OPTIONAL — profile "dev"
    └── registry.prod.yaml    # OPTIONAL — profile "prod"
```

```yaml
# .ai-registry/registry.yaml
accounts:
  - id: deepseek-primary
    provider_id: deepseek
    credential: env:DEEPSEEK_API_KEY      # a reference, never a key
    enabled_models: [deepseek-chat, deepseek-reasoner]
  - id: uniapi-chat
    provider_id: uniapi
    credential: env:UNIAPI_API_KEY
    enabled_models: [deepseek-v4-flash]

aliases:
  - id: chat-default
    deployments:
      - account_id: deepseek-primary      # preferred
        model_id: deepseek-chat
      - account_id: uniapi-chat           # used when the first is cooling down
        model_id: deepseek-v4-flash
        routing: {priority: 1}
```

Select a profile with `Registry.from_project(profile="prod")` or
`AI_REGISTRY_PROFILE=prod`.

## Use the result

Build a client yourself, or use an optional adapter:

```python
from ai_registry import ClientFactory

factory = ClientFactory.from_project()

# An openai.OpenAI client, pointed at the resolved endpoint and key:
client = factory.openai_client("chat-default")

# A Pydantic AI model — a framework with no config-file registry of its own:
model = factory.pydantic_ai_model("chat-default")

# Registry routing becomes Pydantic AI request-time failover:
model = factory.pydantic_ai_fallback_model("chat-default")

# A LangChain model — LangGraph states take it directly as a node model:
model = factory.langchain_chat_model("chat-default")
```

Or drive failover yourself — `candidates()` returns every healthy deployment in
preference order:

```python
for resolution in factory.registry.candidates("chat-default"):
    try:
        response = call(resolution)
    except TransientError:
        factory.registry.record_failure(resolution)  # cools this target down everywhere
        continue
    factory.registry.record_success(resolution)
    break
```

## Inspect it

```console
$ ai-registry explain chat-default
1. deepseek-primary/deepseek-chat -> https://api.deepseek.com/anthropic (credential: env (ok))
2. uniapi-chat/deepseek-v4-flash -> https://uni-api.cstcloud.cn/v1 (credential: env (unresolved))

$ ai-registry models --type chat --tools --min-context 500000
deepseek	deepseek-v4-flash	chat	1000000	reasoning,structured_output,tools
```

`resolve` and `explain` report whether a credential resolves, never its name or
value.

## Features

- **Alias-first resolution**, with an explicit `account-id/model-id` escape hatch.
- **Multiple accounts and keys** per provider, as reusable first-class objects.
- **Deterministic deployment selection**: priority, weight, disabled, plus a
  health store with time-based cooldown and exponential backoff.
- **Capability-aware catalog queries** — find a chat model with tools and a
  200k window without hardcoding a model id.
- **Secret references, not secrets**: `env:` / `secret_ref:`, resolved lazily,
  with a pluggable `SecretResolver` for Vault, AWS, or Kubernetes.
- **Secret-safe by construction**: literal keys rejected; `repr`, dumps, and
  errors redacted; credential-bearing URLs refused.
- **Bring your own catalog**: `ai_registry.catalog.load_models_dev()` imports a
  models.dev `api.json` so you need not hand-maintain context windows or pricing.
- **Observability built in**: `Resolution.otel_attributes()` emits OpenTelemetry
  GenAI attributes plus which alias and account were selected.
- **Testable**: `ai_registry.testing` ships supported fakes.

## Why not X?

| | Alias layer | Resolution separable from invocation | Multiple keys per provider | In-process | Rejects literal secrets |
|---|---|---|---|---|---|
| **ai-registry** | config file | yes, that's all it does | yes, as `Account` | yes (6 pkgs) | **yes** |
| **LiteLLM Router** | `model_name` groups | yes, via `get_available_deployment()` | yes, by repeating entries | yes (49 pkgs) | no |
| **`llm` (simonw)** | `aliases.json` | yes, `llm.get_model()` | yes, `api_key_name` | yes | no (plaintext `keys.json`) |
| **Pydantic AI** | `'openai:gpt-4o'` string | no — returns a live model | no | yes | n/a |
| **Vercel AI SDK registry** | `customProvider` (code) | no — returns a live model | no | yes (TS) | n/a |
| **Portkey / Helicone / Bifrost / Kong** | gateway config | no | yes | no — network hop | varies |

**Use LiteLLM instead** if you want one `completion()` call across providers,
request translation, retries, spend tracking, or a proxy. It does far more than
this library and does it well.

**Use ai-registry** if you already have SDKs you like and only want the
configuration layer — especially if the dependency footprint of the component
that touches every API key you own is something you care about. For scale: the
resolved closure is 49 packages for `litellm`, 107 for `litellm[proxy]`, and 6
here. In March 2026 two `litellm` releases were
[compromised on PyPI](https://docs.litellm.ai/blog/security-update-march-2026)
with a `.pth` file that harvested cloud credentials on every Python start. Fewer
moving parts near your keys is a real property, not an aesthetic one.

The two are not exclusive: point an `Account` at a LiteLLM proxy and use this to
decide which one.

## Documentation

| Guide | Contents |
| --- | --- |
| [Overview](docs/overview.md) | The idea, concepts, architecture, goals and non-goals. |
| [Getting started](docs/getting-started.md) | Install, first resolution, loading files, built-in data. |
| [Configuration](docs/configuration.md) | Complete file format, field reference, validation. |
| [Use cases](docs/use-cases.md) | Failover, weighted routing, embeddings, custom endpoints, secret resolvers. |
| [API reference](docs/api-reference.md) | Every public class, function, field, and behavior. |
| [Security](docs/security.md) | Secret-handling guarantees, redaction rules, limitations. |
| [Development](docs/development.md) | Environment, checks, conventions, testing. |

## Non-goals

This package does not make network requests, define a unified AI response
interface, translate or retry requests, or ship a gateway. Deployment selection
is deterministic and based on configuration plus recorded health; request-time
concerns belong to the caller or the adapter.

## License

[MIT](LICENSE).
