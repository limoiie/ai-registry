# LangChain Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an optional `ai_registry.adapters.langchain` adapter that builds LangChain chat models and embeddings from a `Resolution` (LangGraph consumers get it for free).

**Architecture:** Mirror the existing `pydantic_ai` adapter: a lazy-importing adapter module behind a `langchain` extra, direct class construction (`ChatOpenAI`, `ChatAnthropic`, `OpenAIEmbeddings` — Anthropic offers no embedding API, so anthropic embeddings raise instead), optional dependencies never imported by the core, wiring through `ClientFactory`.

**Tech Stack:** Python 3.11+, LangChain (langchain-openai, langchain-anthropic), pytest with `sys.modules` stubs.

---

### Task 1: Adapter tests (failing)

**Files:**
- Create: `tests/test_langchain.py`

**Step 1: Write the tests**

```python
"""LangChain adapter tests.

The optional extras are deliberately absent from the dev environment, so the
"missing dependency" paths are exercised for real and the "installed" paths run
against stub modules injected into ``sys.modules``, mirroring
``test_adapters.py``.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from ai_registry import MissingDependencyError, UnsupportedProviderError
from ai_registry.adapters import langchain as langchain_adapter
from ai_registry.testing import build_registry, constant_secret_resolver


def resolution(
    *,
    sdk_type: str = "openai",
    model_type: str = "chat",
    endpoint: str | None = "https://provider.test/v1",
    timeout_seconds: float | None = None,
) -> Any:
    registry = build_registry(
        {"chat-default": ["test-account/test-model"]},
        model_type=model_type,
        sdk_type=sdk_type,
        endpoint=endpoint,
        credential="secret_ref:key",
        timeout_seconds=timeout_seconds,
        secret_resolver=constant_secret_resolver("sk-adapter"),
    )
    return registry.resolve("chat-default")


class Recorder:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class ChatOpenAI(Recorder):  # noqa: N801
    pass


class OpenAIEmbeddings(Recorder):  # noqa: N801
    pass


class ChatAnthropic(Recorder):  # noqa: N801
    pass


def install_langchain_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        "langchain_openai": (ChatOpenAI, OpenAIEmbeddings),
        "langchain_anthropic": (ChatAnthropic,),
    }
    for name, classes in modules.items():
        module = types.ModuleType(name)
        for cls in classes:
            setattr(module, cls.__name__, cls)
        monkeypatch.setitem(sys.modules, name, module)


def test_langchain_adapter_reports_the_missing_extra_for_openai() -> None:
    with pytest.raises(MissingDependencyError) as caught:
        langchain_adapter.create_chat_model(resolution())

    assert 'pip install "ai-registry[langchain]"' in str(caught.value)
    assert caught.value.extra == "langchain"
    assert caught.value.package == "langchain-openai"


def test_langchain_adapter_reports_the_missing_extra_for_anthropic() -> None:
    with pytest.raises(MissingDependencyError) as caught:
        langchain_adapter.create_chat_model(resolution(sdk_type="anthropic"))

    assert 'pip install "ai-registry[langchain]"' in str(caught.value)
    assert caught.value.package == "langchain-anthropic"


def test_langchain_adapter_builds_a_chat_openai_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    model = langchain_adapter.create_chat_model(resolution(timeout_seconds=12.5))

    assert isinstance(model, ChatOpenAI)
    assert model.kwargs == {
        "model": "test-model",
        "api_key": "sk-adapter",
        "base_url": "https://provider.test/v1",
        "timeout": 12.5,
    }


def test_langchain_adapter_builds_a_chat_anthropic_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    model = langchain_adapter.create_chat_model(resolution(sdk_type="anthropic"))

    assert isinstance(model, ChatAnthropic)
    assert model.kwargs["api_key"] == "sk-adapter"
    assert model.kwargs["base_url"] == "https://provider.test/v1"


def test_langchain_adapter_builds_openai_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    model = langchain_adapter.create_embeddings(resolution(model_type="embedding"))

    assert isinstance(model, OpenAIEmbeddings)
    assert model.kwargs["model"] == "test-model"
    assert model.kwargs["api_key"] == "sk-adapter"


def test_langchain_adapter_rejects_anthropic_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    with pytest.raises(UnsupportedProviderError, match=r"anthropic"):
        langchain_adapter.create_embeddings(
            resolution(sdk_type="anthropic", model_type="embedding")
        )


def test_langchain_adapter_overrides_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    model = langchain_adapter.create_chat_model(
        resolution(), max_tokens=7, timeout=1.0
    )

    assert model.kwargs["max_tokens"] == 7
    assert model.kwargs["timeout"] == 1.0


def test_langchain_adapter_omits_absent_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)
    registry = build_registry(
        {"chat-default": ["test-account/test-model"]},
        endpoint=None,
        credential=None,
    )

    model = langchain_adapter.create_chat_model(registry.resolve("chat-default"))

    assert model.kwargs == {"model": "test-model"}


def test_langchain_adapter_rejects_non_chat_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    with pytest.raises(UnsupportedProviderError, match=r"embedding"):
        langchain_adapter.create_chat_model(resolution(model_type="embedding"))


def test_langchain_adapter_rejects_non_embedding_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    with pytest.raises(UnsupportedProviderError, match=r"chat"):
        langchain_adapter.create_embeddings(resolution())


def test_langchain_adapter_rejects_unsupported_sdk_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    with pytest.raises(UnsupportedProviderError, match=r"google"):
        langchain_adapter.create_chat_model(resolution(sdk_type="google"))
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_langchain.py -q`
Expected: FAIL — `ModuleNotFoundError` on `ai_registry.adapters.langchain` (import error), since the module does not exist yet.

**Step 3: Commit**

```bash
git add tests/test_langchain.py
git commit -m "test: add langchain adapter tests"
```

---

### Task 2: Adapter module

**Files:**
- Create: `src/ai_registry/adapters/langchain.py`
- Modify: `src/ai_registry/adapters/__init__.py` (add `langchain` to `__all__` and the docstring mention)

**Step 1: Write the adapter**

```python
"""Adapter for LangChain chat models and embeddings.

Install with ``pip install "ai-registry[langchain]"``.

LangChain has no configuration-file registry of its own: a chat model is
``ChatOpenAI``/``ChatAnthropic`` plus explicit credentials, or a convention
string resolved against environment variables. This adapter supplies the first
form from registry configuration, so the alias stays the only name your
application code knows. LangGraph states use these models directly in their
nodes, so this adapter covers LangGraph too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_registry.errors import MissingDependencyError, UnsupportedProviderError
from ai_registry.registry import Resolution
from ai_registry.schemas import ModelType, SDKType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel

__all__ = ["create_chat_model", "create_embeddings"]

_SDK_CLASS: dict[SDKType, dict[ModelType, str]] = {
    SDKType.OPENAI: {
        ModelType.CHAT: "ChatOpenAI",
        ModelType.EMBEDDING: "OpenAIEmbeddings",
    },
    SDKType.ANTHROPIC: {
        ModelType.CHAT: "ChatAnthropic",
    },
}

_SDK_MODULE = {
    SDKType.OPENAI: "langchain_openai",
    SDKType.ANTHROPIC: "langchain_anthropic",
}


def create_chat_model(resolution: Resolution, **overrides: Any) -> BaseChatModel:
    """Build a LangChain chat model for ``resolution``.

    ``overrides`` are forwarded to the model constructor, so request-shaping
    options such as ``max_tokens`` remain available. The returned model is a
    plain LangChain ``BaseChatModel`` and can be passed straight into a
    LangGraph state node.
    """
    if resolution.model.type is not ModelType.CHAT:
        raise UnsupportedProviderError(
            f"model '{resolution.model.id}' is of type "
            f"'{resolution.model.type.value}'; LangChain chat models are chat "
            "models, so resolve a chat alias instead"
        )
    return _build(resolution, ModelType.CHAT, overrides)


def create_embeddings(resolution: Resolution, **overrides: Any) -> Embeddings:
    """Build a LangChain embedding model for ``resolution``.

    Only OpenAI-compatible endpoints serve embeddings; Anthropic offers no
    embedding API, so anthropic resolutions raise ``UnsupportedProviderError``.
    """
    if resolution.model.type is not ModelType.EMBEDDING:
        raise UnsupportedProviderError(
            f"model '{resolution.model.id}' is of type "
            f"'{resolution.model.type.value}'; LangChain embedding models are "
            "embedding models, so resolve an embedding alias instead"
        )
    if resolution.sdk_type is SDKType.ANTHROPIC:
        raise UnsupportedProviderError(
            f"provider '{resolution.provider.id}' resolves to sdk_type "
            "'anthropic'; Anthropic offers no embedding models, so resolve an "
            "OpenAI-compatible embedding endpoint instead"
        )
    return _build(resolution, ModelType.EMBEDDING, overrides)


def _build(
    resolution: Resolution, model_type: ModelType, overrides: dict[str, Any]
) -> Any:
    module = _import_module(resolution)
    kwargs: dict[str, Any] = {"model": resolution.model.id}
    credential = resolution.resolve_credential()
    if credential is not None:
        kwargs["api_key"] = credential
    if resolution.endpoint is not None:
        kwargs["base_url"] = resolution.endpoint
    if resolution.account.timeout_seconds is not None:
        kwargs["timeout"] = resolution.account.timeout_seconds
    class_name = _SDK_CLASS[resolution.sdk_type][model_type]
    return getattr(module, class_name)(**{**kwargs, **overrides})


def _import_module(resolution: Resolution) -> Any:
    import importlib

    module_name = _SDK_MODULE.get(resolution.sdk_type)
    if module_name is None:
        raise UnsupportedProviderError(
            f"provider '{resolution.provider.id}' resolves to sdk_type "
            f"'{resolution.sdk_type.value}', which this adapter does not "
            "build; set sdk_type: openai for an OpenAI-compatible endpoint, or "
            "construct the LangChain client yourself from the resolution"
        )
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        raise MissingDependencyError(
            module_name.replace("_", "-"), "langchain"
        ) from error
```

**Step 2: Wire the package surface**

In `src/ai_registry/adapters/__init__.py`, change `__all__ = ["openai", "pydantic_ai"]` to
`__all__ = ["langchain", "openai", "pydantic_ai"]` (sorted), and add
`from ai_registry.adapters.langchain import create_chat_model, create_embeddings`
to the docstring's import example block.

**Step 3: Run the tests**

Run: `uv run pytest tests/test_langchain.py -q`
Expected: PASS (all 11 tests).

**Step 4: Lint and type-check**

Run: `uv run ruff check src/ai_registry/adapters/langchain.py tests/test_langchain.py` — expected: no errors.
Run: `uv run mypy src/ai_registry/adapters/langchain.py` — expected: no errors (see Task 3 for the mypy override; until then mypy may report missing stubs, which Task 3 fixes).

**Step 5: Commit**

```bash
git add src/ai_registry/adapters/langchain.py src/ai_registry/adapters/__init__.py
git commit -m "feat: add langchain adapter"
```

---

### Task 3: Packaging (extra + mypy)

**Files:**
- Modify: `pyproject.toml` (extras `:38-43`, mypy overrides `:117-120`)

**Step 1: Add the extra**

After the `pydantic-ai` extra, add:

```toml
langchain = ["langchain-openai>=0.2", "langchain-anthropic>=0.2"]
```

Optionally extend the `pydantic-ai` comment above it into a shared comment:

```toml
# OpenAIChatModel (formerly OpenAIModel) and pydantic_ai.providers.* are
# required by the adapter, so the floor is 1.0 rather than the oldest release.
```

Replace with a comment naming both extras alongside. The `0.2` floor for
langchain guarantees the `api_key`/`base_url`/`model` constructor kwargs this
adapter passes.

**Step 2: Extend the mypy override**

Change the adapter overrides block to also ignore the langchain modules:

```toml
[[tool.mypy.overrides]]
# Optional extras are not installed in the default dev environment; the adapters
# import them defensively and are covered by tests using stub modules.
module = [
    "openai",
    "openai.*",
    "pydantic_ai",
    "pydantic_ai.*",
    "langchain_core",
    "langchain_core.*",
    "langchain_openai",
    "langchain_openai.*",
    "langchain_anthropic",
    "langchain_anthropic.*",
]
ignore_missing_imports = true
```

**Step 3: Verify the lockfile and full checks**

Run: `uv lock`
Run: `uv run pytest tests/test_langchain.py tests/test_adapters.py -q` — PASS
Run: `uv run mypy src/ai_registry/adapters/langchain.py` — no errors

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: ship langchain adapter extra"
```

---

### Task 4: Lazy-import guards

**Files:**
- Modify: `tests/test_import.py:16-29` (the subprocess script assertion)

**Step 1: Extend the assertions**

Add one line to the subprocess `-c` script in `test_core_import_does_not_import_adapter_extras`:

```python
assert 'ai_registry.adapters.langchain' not in sys.modules
```

The integration test `test_integration.py:79` already lists `langchain` in
`optional_sdks`, so no change needed there.

**Step 2: Run the tests**

Run: `uv run pytest tests/test_import.py tests/test_integration.py -q`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/test_import.py
git commit -m "test: assert langchain adapter stays lazy"
```

---

### Task 5: ClientFactory wiring

**Files:**
- Modify: `src/ai_registry/factory.py` (TYPE_CHECKING imports `:15-17`, methods after `:85`)
- Modify: `tests/test_factory.py` (add stub installer after `:62`, tests at the end)

**Step 1: Add the factory methods**

Add to the `TYPE_CHECKING` block in `factory.py`:

```python
if TYPE_CHECKING:  # pragma: no cover - typing only
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel
    from openai import AsyncOpenAI, OpenAI
    from pydantic_ai.models import Model
```

Add at the end of the class:

```python
def langchain_chat_model(self, reference: str, **overrides: Any) -> BaseChatModel:
    """Build a LangChain chat model for ``reference``."""
    from ai_registry.adapters.langchain import create_chat_model

    return create_chat_model(self._registry.resolve(reference), **overrides)

def langchain_embeddings(self, reference: str, **overrides: Any) -> Embeddings:
    """Build a LangChain embedding model for ``reference``."""
    from ai_registry.adapters.langchain import create_embeddings

    return create_embeddings(self._registry.resolve(reference), **overrides)
```

**Step 2: Add factory tests**

In `tests/test_factory.py`, add after the pydantic-ai stub installer:

```python
def install_langchain_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    class Recorder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.kwargs = kwargs

    for name, class_names in (
        ("langchain_openai", ("ChatOpenAI", "OpenAIEmbeddings")),
        ("langchain_anthropic", ("ChatAnthropic",)),
    ):
        module = types.ModuleType(name)
        for class_name in class_names:
            setattr(module, class_name, Recorder)
        monkeypatch.setitem(sys.modules, name, module)
```

Add at the end of the file:

```python
def test_langchain_chat_model_resolves_reference_and_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    model = registered_factory().langchain_chat_model("chat-default")

    assert model.kwargs["model"] == "test-model"
    assert model.kwargs["api_key"] == "sk-adapter"


def test_langchain_embeddings_resolves_reference_and_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)
    registry = build_registry(
        {"embed-default": ["test-account/test-model"]},
        model_type="embedding",
        credential="secret_ref:key",
        secret_resolver=constant_secret_resolver("sk-adapter"),
    )

    model = ClientFactory(registry).langchain_embeddings("embed-default")

    assert model.kwargs["model"] == "test-model"


def test_langchain_missing_extra_is_reported_on_first_use() -> None:
    with pytest.raises(MissingDependencyError) as caught:
        registered_factory().langchain_chat_model("chat-default")

    assert 'pip install "ai-registry[langchain]"' in str(caught.value)
```

**Step 3: Run the tests**

Run: `uv run pytest tests/test_factory.py tests/test_langchain.py -q`
Expected: PASS.

**Step 4: Lint and type-check**

Run: `uv run ruff check src/ai_registry/factory.py tests/test_factory.py`
Run: `uv run mypy src/ai_registry/factory.py`
Expected: both clean.

**Step 5: Commit**

```bash
git add src/ai_registry/factory.py tests/test_factory.py
git commit -m "feat: wire langchain adapters into ClientFactory"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (install list `:58-67`, adapter example `:108-125`)
- Modify: `docs/overview.md` (`:141-145`, architecture diagram `:190-198`, table `:212-213`, current status `:214-228`)
- Modify: `CHANGELOG.md` (unreleased `### Added`)

**Step 1: README**

Add to the install block:

```bash
pip install "ai-registry[langchain]"      # + LangChain chat/embeddings adapter
```

Extend the usage example after the pydantic-ai lines:

```python
# A LangChain model — LangGraph states take it directly as a node model:
model = factory.langchain_chat_model("chat-default")
```

**Step 2: docs/overview.md**

- Paragraph at `:141-145`: mention `ai_registry.adapters.langchain` alongside OpenAI/Pydantic AI; change "LangGraph and LlamaIndex are not covered yet" to "LlamaIndex is not covered yet". Note LangGraph works through LangChain models.
- Diagram at `:193-194`: change the consumer line to

```
                 OpenAI SDK   Pydantic AI   LangChain / LangGraph   LlamaIndex
                 [openai]     [pydantic-ai] [langchain]             (your own adapter)
```

- Adapters-table row `:213`: `Optional framework adapters (openai, pydantic-ai, langchain extras).`
- Current status `:219-227`: list the LangChain adapter among the shipped extras; "Not covered yet: LlamaIndex adapter, ...".

**Step 3: CHANGELOG**

Add to the `### Added` list after the pydantic-ai adapter entry:

```text
- Optional LangChain adapter: `ai_registry.adapters.langchain`
  (`create_chat_model`, `create_embeddings`) — chat models for OpenAI-compatible
  and Anthropic providers, embeddings for OpenAI-compatible providers, plus
  `ClientFactory` `langchain_chat_model` / `langchain_embeddings`. Install with
  the `langchain` extra; the models feed straight into LangGraph states.
```

**Step 4: Verify nothing else references the status**

Run: `uv run ruff check` — clean.
Run: `git grep -n "not covered" -- docs README.md` — only LlamaIndex should remain.

**Step 5: Commit**

```bash
git add README.md docs/overview.md CHANGELOG.md
git commit -m "docs: document the langchain adapter"
```

---

### Task 7: Full verification

**Step 1: Run everything**

Run: `uv run pytest -q`
Expected: all tests pass (existing + new).

Run: `uv run mypy src/ai_registry tests`
Expected: no errors.

Run: `uv run ruff check .`
Expected: no errors.

**Step 2: Smoke-test the public docs example**

Run:
```bash
uv run python - <<'PY'
from ai_registry.adapters import langchain as adapter
import inspect
for name in ("create_chat_model", "create_embeddings"):
    func = getattr(adapter, name)
    inspect.signature(func)
PY
```
Expected: prints nothing, exits 0.

**Step 3: Final commit**

Nothing to commit if all steps were committed; confirm with `git status --short` (clean).
