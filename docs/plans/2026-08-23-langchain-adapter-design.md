# LangChain Adapter Design

Date: 2026-08-23
Status: approved

## Problem

`ai-registry` ships adapters for the OpenAI SDK and Pydantic AI, but not for
LangChain. Since LangGraph composes LangChain chat models in its nodes, a
LangChain adapter covers both frameworks. The docs list LangGraph/LlamaIndex as
"not covered yet" (docs/overview.md).

## Chosen approach

A dedicated optional adapter module, `ai_registry.adapters.langchain`,
mirroring the existing `pydantic_ai` adapter exactly. LangGraph receives
coverage for free: graph nodes take LangChain chat models.

Rejected alternatives:

- `langchain.chat_models.create_chat_model` with convention strings — requires
  the full `langchain` package (heavy) and embedding models need explicit
  classes anyway.
- A kwargs-only helper (like `client_kwargs`) — neither validates the model
  type nor builds the client, which is the point of an adapter here.

## API

`src/ai_registry/adapters/langchain.py`:

- `create_chat_model(resolution, **overrides)` — requires
  `ModelType.CHAT`; builds `ChatOpenAI` (SDKType.OPENAI) or
  `ChatAnthropic` (SDKType.ANTHROPIC).
- `create_embeddings(resolution, **overrides)` — requires
  `ModelType.EMBEDDING`; builds `OpenAIEmbeddings` for OpenAI-compatible
  `sdk_type` (SDKType.OPENAI). Anthropic provides no embedding API and
  `langchain-anthropic` ships no embeddings class, so an anthropic
  resolution raises `UnsupportedProviderError` with a remedy instead.

`overrides` win on constructor conflict. The credential is resolved exactly
once and never returned. Missing optional extras raise
`MissingDependencyError`; wrong sdk_type or wrong model type raise
`UnsupportedProviderError` with messages in the existing style
(openai.py:53, pydantic_ai.py:69).

## Mapping

From the `Resolution`:

| Resolution field | Constructor kwarg |
| --- | --- |
| `model.id` | `model` |
| `resolve_credential()` | `api_key` (omitted when None) |
| `endpoint` | `base_url` (omitted when None) |
| `account.timeout_seconds` | `timeout` (omitted when None) |

## Packaging

- `pyproject.toml` extra:
  `langchain = ["langchain-openai>=0.2", "langchain-anthropic>=0.2"]`.
  The 0.2 floor guarantees the `api_key`/`base_url`/`model` kwargs, in the
  same style as the comment for the `pydantic-ai` extra.
- mypy override: `langchain_openai`, `langchain_openai.*`,
  `langchain_anthropic`, `langchain_anthropic.*` → `ignore_missing_imports`.

## Wiring

- `ClientFactory.langchain_chat_model(reference, **overrides)` and
  `ClientFactory.langchain_embeddings(reference, **overrides)`, lazily
  importing the adapter.
- `adapters/__init__.py`: add `langchain` to `__all__` and the docstring.
- `tests/test_import.py`: core import must not import the langchain adapter.

## Testing

`tests/test_langchain.py`, mirroring `test_adapters.py`:

- stub modules for `langchain_openai`/`langchain_anthropic` injected into
  `sys.modules`, recording constructor kwargs;
- missing-extra paths run against the real environment (extra not installed);
- chat and embedding construction for both sdk_types;
- overrides win;
- rejects wrong model type and unsupported sdk_type.

All tests are network-free and SDK-free.

## Documentation

- README: add `langchain` extra to the install list and the adapter mention.
- docs/overview.md: adapters are now openai, pydantic-ai, langchain; remove
  LangGraph from the "not covered" list; update the architecture diagram.
- CHANGELOG: new entry.
