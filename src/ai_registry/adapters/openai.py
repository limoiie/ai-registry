"""Adapter for the official OpenAI Python SDK.

Install with ``pip install "ai-registry[openai]"``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_registry.errors import MissingDependencyError, UnsupportedProviderError
from ai_registry.registry import Resolution
from ai_registry.schemas import SDKType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI, OpenAI

__all__ = ["client_kwargs", "create_async_client", "create_client"]


def client_kwargs(resolution: Resolution) -> dict[str, Any]:
    """Return the constructor arguments for an OpenAI SDK client.

    This resolves the credential, so treat the result as secret: it is intended
    to be splatted straight into a client constructor, not logged or stored.
    The OpenAI SDK is not imported, so this is useful for building any
    OpenAI-compatible client, including ones this package does not know about.
    """
    kwargs: dict[str, Any] = {}
    if resolution.endpoint is not None:
        kwargs["base_url"] = resolution.endpoint
    credential = resolution.resolve_credential()
    if credential is not None:
        kwargs["api_key"] = credential
    if resolution.account.timeout_seconds is not None:
        kwargs["timeout"] = resolution.account.timeout_seconds
    return kwargs


def create_client(resolution: Resolution, **overrides: Any) -> OpenAI:
    """Build a synchronous ``openai.OpenAI`` client for ``resolution``."""
    openai = _import_openai(resolution)
    return openai.OpenAI(**{**client_kwargs(resolution), **overrides})


def create_async_client(resolution: Resolution, **overrides: Any) -> AsyncOpenAI:
    """Build an ``openai.AsyncOpenAI`` client for ``resolution``."""
    openai = _import_openai(resolution)
    return openai.AsyncOpenAI(**{**client_kwargs(resolution), **overrides})


def _import_openai(resolution: Resolution) -> Any:
    if resolution.sdk_type is not SDKType.OPENAI:
        raise UnsupportedProviderError(
            f"provider '{resolution.provider.id}' resolves to sdk_type "
            f"'{resolution.sdk_type.value}'; use the matching adapter "
            "or set sdk_type: openai for an OpenAI-compatible endpoint"
        )
    try:
        import openai
    except ImportError as error:
        raise MissingDependencyError("openai", "openai") from error
    return openai
