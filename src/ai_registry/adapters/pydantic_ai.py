"""Adapter for Pydantic AI.

Install with ``pip install "ai-registry[pydantic-ai]"``.

Pydantic AI has no configuration-file registry of its own: a model is either a
``'provider:model'`` string resolved against environment variables, or an
explicitly constructed model plus provider. This adapter supplies the second
form from registry configuration, so the alias stays the only name your
application code knows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_registry.errors import MissingDependencyError, UnsupportedProviderError
from ai_registry.registry import Registry, Resolution
from ai_registry.schemas import ModelType, SDKType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pydantic_ai.models import Model

__all__ = [
    "create_fallback_model",
    "create_fallback_model_for",
    "create_model",
    "create_model_for",
]


def create_model(resolution: Resolution, **overrides: Any) -> Model:
    """Build a Pydantic AI ``Model`` for ``resolution``.

    ``overrides`` are forwarded to the model constructor, so request-shaping
    options such as ``settings=`` remain available.
    """
    if resolution.model.type is not ModelType.CHAT:
        raise UnsupportedProviderError(
            f"model '{resolution.model.id}' is of type "
            f"'{resolution.model.type.value}'; Pydantic AI models are chat "
            "models, so resolve a chat alias instead"
        )
    credential = resolution.resolve_credential()
    sdk_type = resolution.sdk_type

    if sdk_type is SDKType.OPENAI:
        models = _import("pydantic_ai.models.openai")
        providers = _import("pydantic_ai.providers.openai")
        provider_kwargs: dict[str, Any] = {}
        if resolution.endpoint is not None:
            provider_kwargs["base_url"] = resolution.endpoint
        if credential is not None:
            provider_kwargs["api_key"] = credential
        return models.OpenAIChatModel(
            resolution.model.id,
            provider=providers.OpenAIProvider(**provider_kwargs),
            **overrides,
        )

    if sdk_type is SDKType.ANTHROPIC:
        models = _import("pydantic_ai.models.anthropic")
        providers = _import("pydantic_ai.providers.anthropic")
        anthropic_kwargs: dict[str, Any] = {}
        if credential is not None:
            anthropic_kwargs["api_key"] = credential
        if resolution.endpoint is not None:
            anthropic_kwargs["base_url"] = resolution.endpoint
        return models.AnthropicModel(
            resolution.model.id,
            provider=providers.AnthropicProvider(**anthropic_kwargs),
            **overrides,
        )

    raise UnsupportedProviderError(
        f"provider '{resolution.provider.id}' resolves to sdk_type "
        f"'{sdk_type.value}', which this adapter does not build; set "
        "sdk_type: openai for an OpenAI-compatible endpoint, or construct the "
        "Pydantic AI model yourself from the resolution"
    )


def create_fallback_model(resolutions: list[Resolution], **overrides: Any) -> Model:
    """Build a ``FallbackModel`` over ``resolutions``, best candidate first.

    Pair this with :meth:`ai_registry.Registry.candidates` to turn registry
    routing into Pydantic AI's request-time failover::

        model = create_fallback_model(registry.candidates("chat-default"))
    """
    if not resolutions:
        raise UnsupportedProviderError(
            "no resolutions supplied; an alias with no available deployment "
            "cannot produce a fallback model"
        )
    fallback = _import("pydantic_ai.models.fallback")
    built = [create_model(resolution, **overrides) for resolution in resolutions]
    if len(built) == 1:
        return built[0]
    return fallback.FallbackModel(*built)


def create_model_for(
    registry: Registry, reference: str, **overrides: Any
) -> Model:
    """Resolve ``reference`` with ``registry``, then build a Pydantic AI model.

    One import and one call::

        from ai_registry.adapters.pydantic_ai import create_model_for

        model = create_model_for(registry, "chat-default")
    """
    return create_model(registry.resolve(reference), **overrides)


def create_fallback_model_for(
    registry: Registry, reference: str, **overrides: Any
) -> Model:
    """Resolve every candidate for ``reference``, then build a ``FallbackModel``.

    Combines :meth:`ai_registry.Registry.candidates` routing with
    :func:`create_fallback_model`::

        from ai_registry.adapters.pydantic_ai import create_fallback_model_for

        model = create_fallback_model_for(registry, "chat-default")
    """
    return create_fallback_model(registry.candidates(reference), **overrides)


def _import(module: str) -> Any:
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as error:
        raise MissingDependencyError("pydantic-ai", "pydantic-ai") from error
