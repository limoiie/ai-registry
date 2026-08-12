# ClientFactory Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `ClientFactory` facade to the core package that constructs a `Registry` once and builds clients from references, and remove the now-redundant `create_*_for` adapter helpers.

**Architecture:** `ClientFactory` holds a `Registry`; classmethods `from_project`/`from_files`/`from_data` delegate to the matching `Registry` builders; instance methods `openai_client`/`openai_async_client`/`pydantic_ai_model`/`pydantic_ai_fallback_model` are lazy imports of the adapter modules that delegate to the low-level `create_*` functions. The core stays light: no SDK is imported at module import time.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, mypy, uv.

**Design doc:** `docs/plans/2026-08-12-ai-registry-client-factory-design.md`

---

### Task 1: Remove the `create_*_for` helpers

The `ClientFactory` subsumes these one-call helpers. They are Unreleased, so no migration note.

**Files:**
- Modify: `src/ai_registry/adapters/openai.py`
- Modify: `src/ai_registry/adapters/pydantic_ai.py`
- Modify: `tests/test_adapters.py`

**Step 1: Remove the `_for` tests from `tests/test_adapters.py`**

Delete the `registered_registry()` helper and these five tests:
- `test_create_client_for_resolves_alias_then_builds`
- `test_create_async_client_for_resolves_alias_then_builds`
- `test_create_client_for_forwards_overrides`
- `test_create_model_for_resolves_alias_then_builds`
- `test_create_fallback_model_for_resolves_candidates`

**Step 2: Remove the `_for` functions from `src/ai_registry/adapters/openai.py`**

Delete `create_client_for` and `create_async_client_for` (lines 57-75). Change `__all__` to:

```python
__all__ = ["client_kwargs", "create_async_client", "create_client"]
```

Remove `Registry` from the import on line 11 (it becomes unused): `from ai_registry.registry import Resolution`.

**Step 3: Remove the `_for` functions from `src/ai_registry/adapters/pydantic_ai.py`**

Delete `create_model_for` and `create_fallback_model_for` (lines 102-128). Change `__all__` to:

```python
__all__ = ["create_fallback_model", "create_model"]
```

Remove `Registry` from the import on line 17: `from ai_registry.registry import Resolution`.

**Step 4: Run the adapter tests**

Run: `uv run pytest tests/test_adapters.py -q`
Expected: PASS (18 tests; the 5 `_for` tests are gone).

**Step 5: Commit**

```bash
git add src/ai_registry/adapters/openai.py src/ai_registry/adapters/pydantic_ai.py tests/test_adapters.py
git commit -m "refactor: fold create_*_for helpers into ClientFactory later"
```

---

### Task 2: Create `ClientFactory` with delegation methods (TDD)

**Files:**
- Create: `src/ai_registry/factory.py`
- Create: `tests/test_factory.py`

**Step 1: Write the failing tests**

Create `tests/test_factory.py`:

```python
"""ClientFactory tests.

The optional SDKs are absent from the dev environment, so the "missing
dependency" path is real and the "installed" paths run against stub modules
injected into ``sys.modules``, mirroring ``test_adapters.py``.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from ai_registry import ClientFactory, MissingDependencyError
from ai_registry.testing import build_registry, constant_secret_resolver


class RecordingClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def install_openai_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("openai")
    module.OpenAI = RecordingClient  # type: ignore[attr-defined]
    module.AsyncOpenAI = RecordingClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)


def install_pydantic_ai_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("pydantic_ai", "pydantic_ai.models", "pydantic_ai.providers"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    models_openai = types.ModuleType("pydantic_ai.models.openai")
    providers_openai = types.ModuleType("pydantic_ai.providers.openai")
    models_anthropic = types.ModuleType("pydantic_ai.models.anthropic")
    providers_anthropic = types.ModuleType("pydantic_ai.providers.anthropic")
    fallback = types.ModuleType("pydantic_ai.models.fallback")

    class Recorder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    models_openai.OpenAIChatModel = Recorder  # type: ignore[attr-defined]
    providers_openai.OpenAIProvider = Recorder  # type: ignore[attr-defined]
    models_anthropic.AnthropicModel = Recorder  # type: ignore[attr-defined]
    providers_anthropic.AnthropicProvider = Recorder  # type: ignore[attr-defined]
    fallback.FallbackModel = Recorder  # type: ignore[attr-defined]

    for name, module in (
        ("pydantic_ai.models.openai", models_openai),
        ("pydantic_ai.providers.openai", providers_openai),
        ("pydantic_ai.models.anthropic", models_anthropic),
        ("pydantic_ai.providers.anthropic", providers_anthropic),
        ("pydantic_ai.models.fallback", fallback),
    ):
        monkeypatch.setitem(sys.modules, name, module)


def registered_factory() -> ClientFactory:
    registry = build_registry(
        {"chat-default": ["test-account/test-model"]},
        credential="secret_ref:key",
        secret_resolver=constant_secret_resolver("sk-adapter"),
    )
    return ClientFactory(registry)


def test_openai_client_resolves_reference_and_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_openai_stub(monkeypatch)

    client = registered_factory().openai_client("chat-default")

    assert client.kwargs["base_url"] == "https://provider.test/v1"
    assert client.kwargs["api_key"] == "sk-adapter"


def test_openai_async_client_resolves_reference_and_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_openai_stub(monkeypatch)

    client = registered_factory().openai_async_client("chat-default")

    assert client.kwargs["api_key"] == "sk-adapter"


def test_openai_client_forwards_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    install_openai_stub(monkeypatch)

    client = registered_factory().openai_client("chat-default", max_retries=7)

    assert client.kwargs["max_retries"] == 7


def test_pydantic_ai_model_resolves_reference_and_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)

    model = registered_factory().pydantic_ai_model("chat-default")

    assert model.args == ("test-model",)
    assert model.kwargs["provider"].kwargs["api_key"] == "sk-adapter"


def test_pydantic_ai_fallback_model_resolves_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)
    registry = build_registry(
        {"chat-default": ["primary/test-model", "backup/test-model"]},
        accounts=["primary", "backup"],
        credential="secret_ref:key",
        secret_resolver=constant_secret_resolver("sk-adapter"),
    )

    model = ClientFactory(registry).pydantic_ai_fallback_model("chat-default")

    assert len(model.args) == 2


def test_registry_property_exposes_candidates() -> None:
    factory = registered_factory()

    assert [r.account_id for r in factory.registry.candidates("chat-default")] == [
        "test-account"
    ]


def test_missing_extra_is_reported_on_first_use() -> None:
    with pytest.raises(MissingDependencyError) as caught:
        registered_factory().openai_client("chat-default")

    assert 'pip install "ai-registry[openai]"' in str(caught.value)


def test_from_data_builds_a_registry_and_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_openai_stub(monkeypatch)
    factory = ClientFactory.from_data(
        providers=[
            {
                "id": "test-provider",
                "name": "Test Provider",
                "sdk_type": "openai",
                "models": [{"id": "test-model", "type": "chat"}],
            }
        ],
        accounts=[
            {
                "id": "test-account",
                "provider_id": "test-provider",
                "credential": "secret_ref:key",
                "enabled_models": ["test-model"],
            }
        ],
        secret_resolver=constant_secret_resolver("sk-adapter"),
    )

    client = factory.openai_client("test-account/test-model")

    assert client.kwargs["api_key"] == "sk-adapter"


def test_from_files_builds_a_registry(tmp_path: Path) -> None:
    provider_path = tmp_path / "provider.yaml"
    provider_path.write_text(
        "id: openai\nname: OpenAI\nmodels:\n  - id: chat\n    type: chat\n",
        encoding="utf-8",
    )
    account_path = tmp_path / "accounts.yaml"
    account_path.write_text(
        "accounts:\n  - id: primary\n    provider_id: openai\n"
        "    enabled_models: [chat]\n",
        encoding="utf-8",
    )

    factory = ClientFactory.from_files([provider_path], [account_path])

    assert factory.registry.resolve("primary/chat").model.id == "chat"
```

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_factory.py -q`
Expected: FAIL with `ImportError: cannot import name 'ClientFactory' from 'ai_registry'`.

**Step 3: Write the minimal implementation**

Create `src/ai_registry/factory.py`:

```python
"""Facade that builds framework-native clients from a registry.

``ClientFactory`` bundles registry construction and adapter building so call
sites never thread a :class:`~ai_registry.registry.Registry` around. Adapter
modules are imported lazily on first use, so importing this module (or the
package) pulls in no optional SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_registry.registry import Registry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI, OpenAI
    from pydantic_ai.models import Model

__all__ = ["ClientFactory"]


class ClientFactory:
    """Build clients from a configured :class:`Registry` by reference.

    Construct directly with a registry, or use the ``from_*`` classmethods,
    which delegate to the matching :class:`Registry` builders and accept the
    same arguments::

        factory = ClientFactory.from_project(profile="prod")
        client = factory.openai_client("chat-default")
        model = factory.pydantic_ai_model("chat-default")

    The adapter extras are imported only when a method that needs them is first
    called, so the core stays dependency-light.
    """

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    @classmethod
    def from_data(cls, *args: Any, **kwargs: Any) -> ClientFactory:
        """Build a factory over :meth:`Registry.from_data`."""
        return cls(Registry.from_data(*args, **kwargs))

    @classmethod
    def from_files(cls, *args: Any, **kwargs: Any) -> ClientFactory:
        """Build a factory over :meth:`Registry.from_files`."""
        return cls(Registry.from_files(*args, **kwargs))

    @classmethod
    def from_project(cls, *args: Any, **kwargs: Any) -> ClientFactory:
        """Build a factory over :meth:`Registry.from_project`."""
        return cls(Registry.from_project(*args, **kwargs))

    @property
    def registry(self) -> Registry:
        """The underlying registry, for failover and introspection."""
        return self._registry

    def openai_client(self, reference: str, **overrides: Any) -> OpenAI:
        """Build a synchronous ``openai.OpenAI`` client for ``reference``."""
        from ai_registry.adapters.openai import create_client

        return create_client(self._registry.resolve(reference), **overrides)

    def openai_async_client(self, reference: str, **overrides: Any) -> AsyncOpenAI:
        """Build an ``openai.AsyncOpenAI`` client for ``reference``."""
        from ai_registry.adapters.openai import create_async_client

        return create_async_client(self._registry.resolve(reference), **overrides)

    def pydantic_ai_model(self, reference: str, **overrides: Any) -> Model:
        """Build a Pydantic AI ``Model`` for ``reference``."""
        from ai_registry.adapters.pydantic_ai import create_model

        return create_model(self._registry.resolve(reference), **overrides)

    def pydantic_ai_fallback_model(self, reference: str, **overrides: Any) -> Model:
        """Build a Pydantic AI ``FallbackModel`` over ``reference``'s candidates."""
        from ai_registry.adapters.pydantic_ai import create_fallback_model

        return create_fallback_model(self._registry.candidates(reference), **overrides)
```

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_factory.py -q`
Expected: PASS (9 tests).

**Step 5: Commit**

```bash
git add src/ai_registry/factory.py tests/test_factory.py
git commit -m "feat: add ClientFactory facade for registry-backed client building"
```

---

### Task 3: Re-export `ClientFactory` and pin the lazy-import guarantee

**Files:**
- Modify: `src/ai_registry/__init__.py`
- Modify: `tests/test_import.py`

**Step 1: Write the failing tests**

Append to `tests/test_import.py`:

```python
def test_package_exposes_client_factory() -> None:
    from ai_registry import ClientFactory

    assert ClientFactory is not None


def test_core_import_does_not_import_adapter_extras() -> None:
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import ai_registry, sys;"
            "assert 'ai_registry.adapters.openai' not in sys.modules;"
            "assert 'ai_registry.adapters.pydantic_ai' not in sys.modules",
        ],
        check=True,
    )
```

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_import.py -q`
Expected: FAIL (ImportError / assertion).

**Step 3: Implement the export**

In `src/ai_registry/__init__.py`, add after the `CatalogEntry` import (line 35):

```python
from ai_registry.factory import (
    ClientFactory as ClientFactory,
)
```

Add `"ClientFactory"` to `__all__` (after `"CatalogEntry"`).

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_import.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/ai_registry/__init__.py tests/test_import.py
git commit -m "feat: export ClientFactory from the package root"
```

---

### Task 4: Update documentation and changelog

**Files:**
- Modify: `src/ai_registry/adapters/__init__.py`
- Modify: `README.md`
- Modify: `docs/api-reference.md`
- Modify: `CHANGELOG.md`

**Step 1: Update `src/ai_registry/adapters/__init__.py` docstring**

Replace the code block (lines 6-13) with:

```python
Adapters live in submodules and are never imported by the core, so installing
``ai-registry`` alone still pulls in nothing but Pydantic and PyYAML. Import the
adapter you need directly::

    from ai_registry.adapters.openai import create_client
    from ai_registry.adapters.pydantic_ai import create_model

The functions take a :class:`~ai_registry.registry.Resolution`. For one-call
building from a reference, use :class:`~ai_registry.factory.ClientFactory`.
Each adapter resolves the credential exactly once, at client construction, and
never returns it.
```

**Step 2: Update `README.md` "Use the result" section**

Replace the code block with:

```python
from ai_registry import ClientFactory

factory = ClientFactory.from_project()

# An openai.OpenAI client, pointed at the resolved endpoint and key:
client = factory.openai_client("chat-default")

# A Pydantic AI model — a framework with no config-file registry of its own:
model = factory.pydantic_ai_model("chat-default")

# Registry routing becomes Pydantic AI request-time failover:
model = factory.pydantic_ai_fallback_model("chat-default")
```

Add after the block:

```python
# Or drive failover yourself — the registry stays reachable:
for resolution in factory.registry.candidates("chat-default"):
```

**Step 3: Update `docs/api-reference.md`**

In the `ai_registry.adapters.openai` section, remove the two `create_*_for`
signature lines. In the `ai_registry.adapters.pydantic_ai` section, remove the
two `create_*_for` lines and the sentence mentioning `create_fallback_model_for`.
Add a new section after the adapters section:

```markdown
### `ai_registry.ClientFactory`

```python
ClientFactory(registry)
ClientFactory.from_data(*args, **kwargs)
ClientFactory.from_files(*args, **kwargs)
ClientFactory.from_project(*args, **kwargs)
factory.registry -> Registry
factory.openai_client(reference, **overrides) -> openai.OpenAI
factory.openai_async_client(reference, **overrides) -> openai.AsyncOpenAI
factory.pydantic_ai_model(reference, **overrides) -> pydantic_ai.models.Model
factory.pydantic_ai_fallback_model(reference, **overrides) -> pydantic_ai.models.Model
```

The `from_*` classmethods delegate to the matching `Registry` builders and
accept the same arguments, so construction parameters are passed once. Build
methods resolve the reference and delegate to the adapter functions; the
adapter extras are imported lazily on first use.
```
```

**Step 4: Update `CHANGELOG.md` Unreleased entry**

Replace the adapter bullet with:

```markdown
- Optional adapters: `ai_registry.adapters.openai` (`create_client`,
  `create_async_client`, `client_kwargs`) and `ai_registry.adapters.pydantic_ai`
  (`create_model`, `create_fallback_model`). Install with the `openai` or
  `pydantic-ai` extras.
- `ClientFactory`: a core facade that builds a registry once (`from_project` /
  `from_files` / `from_data`) and builds framework clients from references
  (`openai_client`, `openai_async_client`, `pydantic_ai_model`,
  `pydantic_ai_fallback_model`). Adapter extras are imported lazily.
```

**Step 5: Verify and commit**

Run: `uv run pytest -q` then `uv run ruff check src tests` then `uv run mypy src`
Expected: all pass.

```bash
git add src/ai_registry/adapters/__init__.py README.md docs/api-reference.md CHANGELOG.md
git commit -m "docs: document ClientFactory facade and adapter API"
```

---

### Task 5: Final verification

Run the full gate:

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

Expected: all pass. Grep for stray references:

```bash
rg "create_.*_for|build_client|build_model" src README.md docs --glob '!docs/plans/**'
```

Expected: no matches outside `docs/plans/`.