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


class ChatOpenAI(Recorder):
    pass


class OpenAIEmbeddings(Recorder):
    pass


class ChatAnthropic(Recorder):
    pass


class AnthropicEmbeddings(Recorder):
    pass


def install_langchain_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        "langchain_openai": (ChatOpenAI, OpenAIEmbeddings),
        "langchain_anthropic": (ChatAnthropic, AnthropicEmbeddings),
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
        langchain_adapter.create_embeddings(
            resolution(sdk_type="anthropic", model_type="embedding")
        )

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


def test_langchain_adapter_builds_anthropic_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    model = langchain_adapter.create_embeddings(
        resolution(sdk_type="anthropic", model_type="embedding")
    )

    assert isinstance(model, AnthropicEmbeddings)
    assert model.kwargs["api_key"] == "sk-adapter"


def test_langchain_adapter_overrides_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_langchain_stub(monkeypatch)

    model = langchain_adapter.create_chat_model(resolution(), max_tokens=7, timeout=1.0)

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
