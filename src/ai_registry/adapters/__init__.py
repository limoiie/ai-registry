"""Framework adapters that turn a :class:`~ai_registry.registry.Resolution` into
a native client.

Adapters live in submodules and are never imported by the core, so installing
``ai-registry`` alone still pulls in nothing but Pydantic and PyYAML. Import the
adapter you need directly::

    from ai_registry.adapters.openai import create_client_for
    from ai_registry.adapters.pydantic_ai import create_model_for

    client = create_client_for(registry, "chat-default")
    model = create_model_for(registry, "chat-default")

The ``create_*_for`` helpers resolve the reference with the registry and build
in one call. Each adapter resolves the credential exactly once, at client
construction, and never returns it.
"""

from __future__ import annotations

__all__ = ["openai", "pydantic_ai"]
