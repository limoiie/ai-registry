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

from ai_registry.errors import MissingDependencyError
from ai_registry.factory import ClientFactory
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


def test_from_project_builds_a_registry_from_a_project_directory(
    tmp_path: Path,
) -> None:
    deployments_dir = tmp_path / ".ai-registry"
    deployments_dir.mkdir(exist_ok=True)
    (deployments_dir / "registry.yaml").write_text(
        "accounts:\n"
        "  - id: primary\n"
        "    provider_id: deepseek\n"
        "    credential: {env: DEEPSEEK_API_KEY}\n"
        "    enabled_models: [deepseek-v4-flash]\n"
        "aliases:\n"
        "  - id: chat-default\n"
        "    deployments:\n"
        "      - account_id: primary\n"
        "        model_id: deepseek-v4-flash\n",
        encoding="utf-8",
    )

    factory = ClientFactory.from_project(tmp_path)

    assert factory.registry.resolve("chat-default").model_id == "deepseek-v4-flash"


def test_pydantic_ai_model_forwards_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)

    model = registered_factory().pydantic_ai_model("chat-default", settings={})

    assert model.kwargs["settings"] == {}


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
    assert model.kwargs["api_key"] == "sk-adapter"


def test_langchain_missing_extra_is_reported_on_first_use() -> None:
    with pytest.raises(MissingDependencyError) as caught:
        registered_factory().langchain_chat_model("chat-default")

    assert 'pip install "ai-registry[langchain]"' in str(caught.value)
