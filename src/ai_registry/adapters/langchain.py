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
