"""Adapter tests.

The optional extras are deliberately absent from the dev environment, so the
"missing dependency" paths are exercised for real and the "installed" paths run
against stub modules injected into ``sys.modules``. No network access and no
heavy SDK is required either way.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from ai_registry import MissingDependencyError, UnsupportedProviderError
from ai_registry.adapters import openai as openai_adapter
from ai_registry.adapters import pydantic_ai as pydantic_ai_adapter
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


class RecordingClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def install_openai_stub(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("openai")
    module.OpenAI = RecordingClient  # type: ignore[attr-defined]
    module.AsyncOpenAI = RecordingClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return module


def install_pydantic_ai_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "pydantic_ai",
        "pydantic_ai.models",
        "pydantic_ai.providers",
    ):
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


def test_client_kwargs_need_no_sdk_and_carry_endpoint_and_credential() -> None:
    kwargs = openai_adapter.client_kwargs(resolution(timeout_seconds=12.5))

    assert kwargs == {
        "base_url": "https://provider.test/v1",
        "api_key": "sk-adapter",
        "timeout": 12.5,
    }


def test_client_kwargs_omit_absent_values() -> None:
    registry = build_registry(
        {"chat-default": ["test-account/test-model"]},
        endpoint=None,
        credential=None,
    )

    assert openai_adapter.client_kwargs(registry.resolve("chat-default")) == {}


def test_openai_adapter_reports_the_missing_extra() -> None:
    with pytest.raises(MissingDependencyError) as caught:
        openai_adapter.build_client(resolution())

    assert 'pip install "ai-registry[openai]"' in str(caught.value)
    assert caught.value.extra == "openai"


def test_openai_adapter_builds_sync_and_async_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_openai_stub(monkeypatch)

    client = openai_adapter.build_client(resolution())
    assert client.kwargs["base_url"] == "https://provider.test/v1"
    assert client.kwargs["api_key"] == "sk-adapter"

    async_client = openai_adapter.build_async_client(resolution())
    assert async_client.kwargs["api_key"] == "sk-adapter"


def test_openai_adapter_overrides_win(monkeypatch: pytest.MonkeyPatch) -> None:
    install_openai_stub(monkeypatch)

    client = openai_adapter.build_client(resolution(), max_retries=7, timeout=1.0)

    assert client.kwargs["max_retries"] == 7
    assert client.kwargs["timeout"] == 1.0


def test_openai_adapter_refuses_a_non_openai_sdk_type() -> None:
    with pytest.raises(UnsupportedProviderError, match=r"anthropic"):
        openai_adapter.build_client(resolution(sdk_type="anthropic"))


def test_pydantic_ai_adapter_reports_the_missing_extra() -> None:
    with pytest.raises(MissingDependencyError) as caught:
        pydantic_ai_adapter.build_model(resolution())

    assert 'pip install "ai-registry[pydantic-ai]"' in str(caught.value)


def test_pydantic_ai_adapter_builds_an_openai_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)

    model = pydantic_ai_adapter.build_model(resolution())

    assert model.args == ("test-model",)
    provider = model.kwargs["provider"]
    assert provider.kwargs == {
        "base_url": "https://provider.test/v1",
        "api_key": "sk-adapter",
    }


def test_pydantic_ai_adapter_builds_an_anthropic_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)

    model = pydantic_ai_adapter.build_model(resolution(sdk_type="anthropic"))

    assert model.kwargs["provider"].kwargs["api_key"] == "sk-adapter"


def test_pydantic_ai_adapter_rejects_non_chat_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)

    with pytest.raises(UnsupportedProviderError, match=r"embedding"):
        pydantic_ai_adapter.build_model(resolution(model_type="embedding"))


def test_pydantic_ai_adapter_rejects_unsupported_sdk_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)

    with pytest.raises(UnsupportedProviderError, match=r"google"):
        pydantic_ai_adapter.build_model(resolution(sdk_type="google"))


def test_fallback_model_is_built_from_registry_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)
    registry = build_registry(
        {"chat-default": ["primary/test-model", "backup/test-model"]},
        accounts=["primary", "backup"],
        credential="secret_ref:key",
        secret_resolver=constant_secret_resolver("sk-adapter"),
    )

    model = pydantic_ai_adapter.build_fallback_model(
        registry.candidates("chat-default")
    )

    assert len(model.args) == 2


def test_single_candidate_needs_no_fallback_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_pydantic_ai_stub(monkeypatch)

    model = pydantic_ai_adapter.build_fallback_model([resolution()])

    assert model.args == ("test-model",)


def test_fallback_model_rejects_an_empty_candidate_list() -> None:
    with pytest.raises(UnsupportedProviderError, match=r"no resolutions"):
        pydantic_ai_adapter.build_fallback_model([])
