"""Framework adapters that turn a :class:`~ai_registry.registry.Resolution` into
a native client.

Adapters live in submodules and are never imported by the core, so installing
``ai-registry`` alone still pulls in nothing but Pydantic and PyYAML. Import the
adapter you need directly::

    from ai_registry.adapters.openai import build_client
    from ai_registry.adapters.pydantic_ai import build_model

Each adapter resolves the credential exactly once, at client construction, and
never returns it.
"""

from __future__ import annotations

__all__ = ["openai", "pydantic_ai"]
