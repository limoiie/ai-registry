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
        """Build a factory over :meth:`Registry.from_data`.

        All parameters are keyword-only, mirroring :meth:`Registry.from_data`.
        """
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
